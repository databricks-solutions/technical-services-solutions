import { Typography } from '@databricks/design-system';
import { SqlBlock } from './SqlBlock';

/**
 * The project Genie agent as a tool for other agents: the managed MCP server of its Genie space, and the Python to
 * call it. The agent answers with the governed measures of the promoted views; the caller's rights apply.
 */
export function AgentToolSection({ base, spaceId }: { base: string; spaceId: string }) {
  const url = `${base}/api/2.0/mcp/genie/${spaceId}`;
  const code = [
    '# pip install --upgrade databricks-mcp databricks-sdk "mcp>=1.24,<2"',
    'from databricks_mcp import DatabricksMCPClient',
    'from databricks.sdk import WorkspaceClient',
    '',
    `mcp_client = DatabricksMCPClient(server_url="${url}", workspace_client=WorkspaceClient())`,
    'for tool in mcp_client.list_tools():',
    '    print(tool.name, tool.description)',
  ].join('\n');
  return (
    <section aria-label="Use it as an agent tool" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Typography.Title level={4} withoutMargins>
        Use it as an agent tool
      </Typography.Title>
      <Typography.Text color="secondary">
        Other agents (a custom agent, Agent Bricks, Genie Code or any MCP client) can ask this agent through the
        Databricks managed MCP server of its Genie space, and get answers from the governed measures. The caller needs
        access to the space and to its views. The managed MCP servers are a Public Preview: a workspace admin turns on
        Managed MCP Servers in the Previews page.
      </Typography.Text>
      <SqlBlock label="MCP server URL" sql={url} />
      <SqlBlock label="Python (runs as you, with your Databricks CLI profile)" sql={code} />
    </section>
  );
}
