import { getExecutionContext, getWarehouseId, isInUserContext } from '@databricks/appkit';
import type { RunAsUser } from '../sql/runner';
import { parseOneChat } from './onechat';
import type { OneChatAnswer } from './onechat';

/** Genie One answers stream; a longer one is cut here. */
const MAX_STREAM_BYTES = 4 * 1024 * 1024;

export interface GenieAnswer {
  text: string;
  sql: string | null;
}

/** Genie calls, always as the calling user (OBO). Needs the dashboards.genie app scope. */
export interface GenieDeps {
  createSpace(view: string, title: string, description: string): Promise<string>;
  trashSpace(spaceId: string): Promise<void>;
  ask(spaceId: string, question: string): Promise<GenieAnswer>;
  /** Genie One (OneChat): not bound to a space, so it can read other data and workspace knowledge. */
  askOne(question: string): Promise<OneChatAnswer>;
}

function client() {
  if (!isInUserContext()) throw new Error('Genie calls must run as the calling user (OBO), never as the app');
  return getExecutionContext().client.toLegacyWorkspaceClient();
}

export function genieDeps(runAsUser: RunAsUser): GenieDeps {
  return {
    createSpace: (view, title, description) =>
      runAsUser(async () => {
        // The SDK has no create-space method yet; this is the REST call it would make.
        const res = (await client().apiClient.request({
          path: '/api/2.0/genie/spaces',
          method: 'POST',
          headers: new Headers(),
          raw: false,
          payload: {
            warehouse_id: await getWarehouseId(),
            title,
            description,
            serialized_space: JSON.stringify({ version: 2, data_sources: { tables: [{ identifier: view }] } }),
          },
        })) as { space_id?: string };
        if (!res.space_id) throw new Error('Genie did not return a space id.');
        return res.space_id;
      }),
    trashSpace: (spaceId) =>
      runAsUser(async () => {
        await client().genie.trashSpace({ space_id: spaceId });
      }),
    ask: (spaceId, question) =>
      runAsUser(async () => {
        const waiter = await client().genie.startConversation({ space_id: spaceId, content: question });
        const message = await waiter.wait();
        const attachments = message.attachments ?? [];
        return {
          text: attachments
            .map((a) => a.text?.content ?? '')
            .filter(Boolean)
            .join('\n\n'),
          sql: attachments.find((a) => a.query?.query)?.query?.query ?? null,
        };
      }),
    askOne: (question) =>
      runAsUser(async () => {
        // No SDK method yet. The endpoint streams OpenAI Responses style SSE events.
        const res = (await client().apiClient.request({
          path: '/api/2.0/data-rooms/tools/onechat/responses',
          method: 'POST',
          headers: new Headers({ Accept: 'text/event-stream' }),
          raw: true,
          payload: {
            input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: question }] }],
            enable_viz: false,
            source: 'semantics-builder',
          },
        })) as { contents?: AsyncIterable<Uint8Array> };
        if (!res.contents) throw new Error('Genie One returned no answer.');
        const chunks: Buffer[] = [];
        let size = 0;
        for await (const chunk of res.contents) {
          chunks.push(Buffer.from(chunk));
          size += chunk.length;
          if (size > MAX_STREAM_BYTES) break;
        }
        return parseOneChat(Buffer.concat(chunks).toString('utf8'));
      }),
  };
}
