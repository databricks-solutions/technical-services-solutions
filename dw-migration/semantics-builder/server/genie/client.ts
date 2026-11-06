import { getExecutionContext, getWarehouseId, isInUserContext } from '@databricks/appkit';
import type { RunAsUser } from '../sql/runner';

export interface GenieAnswer {
  text: string;
  sql: string | null;
}

/** Genie calls, always as the calling user (OBO). Needs the dashboards.genie app scope. */
export interface GenieDeps {
  createSpace(view: string, title: string, description: string): Promise<string>;
  trashSpace(spaceId: string): Promise<void>;
  ask(spaceId: string, question: string): Promise<GenieAnswer>;
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
  };
}
