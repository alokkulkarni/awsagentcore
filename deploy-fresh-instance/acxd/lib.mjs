// Shared by capture.mjs and create.mjs: the designer client, paging, and the read-only fields a Get returns that
// a Create refuses. The SDK authenticates with an API key only (x-api-key) and a workspace (x-workspace-id).
import { AgenticCXDesignerClient } from 'amazon-connect-acxd-sdk';

export function client() {
  const { ACXD_API_KEY: apiKey, ACXD_WORKSPACE_ID: workspaceId, ACXD_REGION: region } = process.env;
  if (!apiKey || !workspaceId || !region) {
    throw new Error('Set ACXD_API_KEY, ACXD_WORKSPACE_ID and ACXD_REGION (deploy.sh does, from what you paste).');
  }
  if (!apiKey.startsWith('acxd_')) throw new Error('That API key does not look like a designer key (acxd_...).');
  return new AgenticCXDesignerClient({ apiKey, workspaceId, region });
}

// Every List* call: { items, nextToken }.
export async function all(acxd, Command, input = {}) {
  const items = [];
  let nextToken;
  do {
    const page = await acxd.send(new Command({ ...input, ...(nextToken ? { nextToken } : {}) }));
    items.push(...(page.items ?? []));
    nextToken = page.nextToken;
  } while (nextToken);
  return items;
}

const READ_ONLY = new Set(['createdAt', 'updatedAt', 'updatedBy', 'saveId', 'creationStatus', 'apiKey', '$metadata',
  'deploymentAlias', 'deploymentStatus', 'status']);

// A Get result as a Create input: read-only fields gone, keys as the Create command names them.
export function createInput(obj, drop = []) {
  const out = {};
  for (const [k, v] of Object.entries(obj ?? {})) {
    if (!READ_ONLY.has(k) && !drop.includes(k) && v !== undefined) out[k] = v;
  }
  return out;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function log(kind, msg) {
  const colour = { ok: '\x1b[0;32m[ OK ]', info: '\x1b[0;36m[....]', warn: '\x1b[1;33m[WARN]', fail: '\x1b[0;31m[FAIL]' }[kind];
  console.log(`${colour} ${msg}\x1b[0m`);
}
