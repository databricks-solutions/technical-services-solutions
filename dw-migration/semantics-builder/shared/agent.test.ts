import { describe, expect, it } from 'vitest';
import { accessBody, accessCommand, accessRequest } from './agent';

describe('access to the Genie agent', () => {
  it('gives CAN RUN once to each principal, in a stable order', () => {
    const body = JSON.parse(
      accessRequest([
        { kind: 'user', name: 'b@x.com' },
        { kind: 'group', name: 'Finance' },
        { kind: 'user', name: 'B@x.com' },
      ])
    ) as { access_control_list: unknown[] };
    expect(body.access_control_list).toEqual([
      { group_name: 'Finance', permission_level: 'CAN_RUN' },
      { user_name: 'B@x.com', permission_level: 'CAN_RUN' },
    ]);
  });

  it('makes one CLI command, and stops names that could break out of its quotes', () => {
    expect(accessCommand('sp1', [{ kind: 'group', name: 'Finance analysts' }])).toBe(
      `databricks permissions update genie sp1 --json '{"access_control_list":[{"group_name":"Finance analysts","permission_level":"CAN_RUN"}]}'`
    );
    expect(accessBody.safeParse({ principals: [{ kind: 'group', name: "x'; rm -rf ~" }] }).success).toBe(false);
    expect(accessBody.safeParse({ principals: [{ kind: 'user', name: 'dana' }] }).success).toBe(false);
  });
});
