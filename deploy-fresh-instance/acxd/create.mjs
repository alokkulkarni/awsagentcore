// Rebuilds templates/acxd (captured from today's workspace) in the NEW workspace, then builds and deploys every
// application to development and production and writes their alias codes (the Connect flow block needs the code,
// not the word "Production").
//
//   node create.mjs <result.json>
//   env: ACXD_API_KEY, ACXD_WORKSPACE_ID, ACXD_REGION   the new workspace
//        MORTGAGE_ENDPOINT_URL, DISPUTE_ACXD_URL         the new account's services the Data requests call
//        AWS_REGION, DISPUTE_KEY_SECRET                  where card_dispute_api_key's value lives in Secrets Manager
//
// Create-only and resumable: anything that already exists (same flowId, dataRequestId, name...) is reused, never
// changed. Progress is kept next to the result file, so a re-run carries on where it stopped.
//
// Flows and Data requests are named by you (flowId, dataRequestId), so references between them stay valid in the
// new workspace. Knowledge bases, guardrails and Live Sync scripts get new IDs: every reference to the old ones in
// flows and application settings is swapped for the new.
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  ListApplicationsCommand, CreateApplicationCommand, CreateApplicationBuildCommand, GetApplicationBuildCommand,
  CreateApplicationDeploymentCommand, GetApplicationDeploymentCommand, ListFlowsCommand, CreateFlowCommand,
  ListDataRequestsCommand, CreateDataRequestCommand, ListContextVariablesCommand, CreateContextVariableCommand,
  ListSlotTypesCommand, CreateSlotTypeCommand, ListKnowledgeBasesCommand, CreateKnowledgeBaseCommand,
  CreateKnowledgeBaseArticleCommand, PublishKnowledgeBaseCommand, ListGuardrailsCommand, CreateGuardrailCommand,
  ListLiveSyncScriptsCommand, CreateLiveSyncScriptCommand, CreateLiveSyncScriptBuildCommand,
  GetLiveSyncScriptBuildCommand, CreateLiveSyncScriptDeploymentCommand, ListModalitiesCommand, CreateModalityCommand,
  ListSecretsCommand, CreateSecretCommand,
} from 'amazon-connect-acxd-sdk';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';
import { all, client, createInput, log, sleep } from './lib.mjs';

const TEMPLATES = join(dirname(fileURLToPath(import.meta.url)), '..', 'templates', 'acxd');
const resultPath = process.argv[2];
if (!resultPath) throw new Error('usage: node create.mjs <result.json>');
const progressPath = `${resultPath}.progress.json`;
const progress = existsSync(progressPath) ? JSON.parse(readFileSync(progressPath, 'utf8')) : { ids: {}, apps: {} };
const keep = () => writeFileSync(progressPath, `${JSON.stringify(progress, null, 2)}\n`, { mode: 0o600 });
const read = (name) => JSON.parse(readFileSync(join(TEMPLATES, `${name}.json`), 'utf8'));
const acxd = client();

// Designer secrets and where their values come from. mortgage_api_key is the mortgage stack's own (its sync
// function writes it, after the acxd-access secret exists), so it's only checked here.
const SECRET_SOURCES = { card_dispute_api_key: process.env.DISPUTE_KEY_SECRET || 'aria-card-dispute/acxd-key' };
const SYNCED_BY_MORTGAGE_STACK = new Set(['mortgage_api_key']);

function swapIds(value) {
  let text = JSON.stringify(value);
  for (const [oldId, newId] of Object.entries(progress.ids)) text = text.split(oldId).join(newId);
  return JSON.parse(text);
}

function newEndpoint(url) {
  if (url.includes('/acxd/ops')) return process.env.DISPUTE_ACXD_URL;
  if (/execute-api\.[a-z0-9-]+\.amazonaws\.com\/.+\/ops$/.test(url)) return process.env.MORTGAGE_ENDPOINT_URL;
  return null;
}

async function secrets() {
  const have = new Set((await all(acxd, ListSecretsCommand)).map((s) => s.name));
  const sm = new SecretsManagerClient({ region: process.env.AWS_REGION });
  for (const secret of read('secrets')) {
    if (have.has(secret.name)) continue;
    if (SYNCED_BY_MORTGAGE_STACK.has(secret.name)) {
      throw new Error(`${secret.name} isn't in the workspace yet: run the step that stores the designer access secret `
        + '(the mortgage stack\'s sync function writes it), then this one again.');
    }
    const source = SECRET_SOURCES[secret.name];
    if (!source) { log('warn', `Secret ${secret.name}: no source known; add it in the designer (Resources → Secrets).`); continue; }
    const { SecretString } = await sm.send(new GetSecretValueCommand({ SecretId: source }));
    await acxd.send(new CreateSecretCommand({ name: secret.name, secretValue: SecretString, isSensitive: true,
      description: secret.description || `From Secrets Manager ${source} (deploy-fresh-instance)` }));
    log('ok', `Secret ${secret.name} (from ${source})`);
  }
}

async function simple(label, items, listCommand, idKey, Command, drop = []) {
  const have = new Set((await all(acxd, listCommand)).map((x) => x[idKey]));
  for (const item of items) {
    if (have.has(item[idKey])) continue;
    await acxd.send(new Command(createInput(item, drop)));
    log('ok', `${label} ${item[idKey]}`);
  }
}

async function dataRequests() {
  const have = new Set((await all(acxd, ListDataRequestsCommand)).map((d) => d.dataRequestId));
  const swaps = Object.fromEntries((read('index').endpoints || []).map((u) => [u, newEndpoint(u)]));
  for (const [oldUrl, url] of Object.entries(swaps)) {
    if (!url) throw new Error(`No new address for ${oldUrl} (expected …/acxd/ops or the mortgage …/ops).`);
    log('info', `${oldUrl} → ${url}`);
  }
  for (const request of read('data-requests')) {
    if (have.has(request.dataRequestId)) continue;
    let text = JSON.stringify(createInput(request));
    for (const [oldUrl, url] of Object.entries(swaps)) text = text.split(oldUrl).join(url);
    await acxd.send(new CreateDataRequestCommand(JSON.parse(text)));
    log('ok', `Data request ${request.dataRequestId}`);
  }
}

async function byName(label, items, idKey, listCommand, create) {
  const have = Object.fromEntries((await all(acxd, listCommand)).map((x) => [x.name, x[idKey]]));
  for (const item of items) {
    if (progress.ids[item[idKey]]) continue;
    progress.ids[item[idKey]] = have[item.name] || (await create(item))[idKey];
    keep();
    log('ok', `${label} ${item.name}: ${progress.ids[item[idKey]]}`);
  }
}

async function waitFor(what, get, done) {
  for (let i = 0; i < 120; i += 1) {
    const got = await get();
    const state = JSON.stringify(got.status ?? got.deploymentStatus ?? '').toLowerCase();
    if (/fail|error/.test(state)) throw new Error(`${what} failed: ${state}`);
    if (done(got)) return got;
    if (i % 3 === 0) log('info', `Waiting for ${what} (${state || 'pending'})...`);
    await sleep(5000);
  }
  throw new Error(`Gave up waiting for ${what}. Run this step again to carry on.`);
}
const finished = (s) => /succe|complete|ready|built|deployed|active|live/.test(JSON.stringify(s ?? '').toLowerCase());

async function knowledgeBases() {
  await byName('Knowledge base', read('knowledge-bases'), 'knowledgeBaseId', ListKnowledgeBasesCommand, async (kb) => {
    const made = await acxd.send(new CreateKnowledgeBaseCommand(createInput(kb, ['knowledgeBaseId', 'articles'])));
    for (const article of kb.articles || []) {
      await acxd.send(new CreateKnowledgeBaseArticleCommand({ ...createInput(article, ['articleId', 'knowledgeBaseId']),
        knowledgeBaseId: made.knowledgeBaseId }));
    }
    if (kb.articles?.length) await acxd.send(new PublishKnowledgeBaseCommand({ knowledgeBaseId: made.knowledgeBaseId }));
    return made;
  });
}

async function liveSyncScripts() {
  await byName('Live Sync script', read('live-sync-scripts'), 'liveSyncScriptId', ListLiveSyncScriptsCommand, async (s) => {
    const made = await acxd.send(new CreateLiveSyncScriptCommand(createInput(s, ['liveSyncScriptId'])));
    const build = await acxd.send(new CreateLiveSyncScriptBuildCommand({ liveSyncScriptIdentifier: made.liveSyncScriptId }));
    await waitFor(`script ${s.name} to build`, () => acxd.send(new GetLiveSyncScriptBuildCommand({
      liveSyncScriptIdentifier: made.liveSyncScriptId, buildIdentifier: build.buildId })), (b) => finished(b.status));
    for (const environment of ['development', 'production']) {
      await acxd.send(new CreateLiveSyncScriptDeploymentCommand({ liveSyncScriptIdentifier: made.liveSyncScriptId,
        buildIdentifier: build.buildId, environment }));
    }
    return made;
  });
}

async function flows() {
  const have = new Set((await all(acxd, ListFlowsCommand)).map((f) => f.flowId));
  let todo = read('flows').filter((f) => !have.has(f.flowId));
  // A flow may redirect to one not made yet: keep going round while each pass makes progress.
  while (todo.length) {
    const failed = [];
    for (const flow of todo) {
      try {
        await acxd.send(new CreateFlowCommand(swapIds(createInput(flow))));
        log('ok', `Flow ${flow.flowId}`);
      } catch (err) {
        failed.push({ flow, err });
      }
    }
    if (failed.length === todo.length) {
      for (const { flow, err } of failed) log('fail', `Flow ${flow.flowId}: ${err.message}`);
      throw new Error('Some flows could not be made (above). Fix the cause and run this step again.');
    }
    todo = failed.map((f) => f.flow);
  }
}

async function applications() {
  const have = Object.fromEntries((await all(acxd, ListApplicationsCommand)).map((a) => [a.name, a.applicationId]));
  for (const app of read('applications')) {
    const done = progress.apps[app.name] || {};
    done.applicationId ||= have[app.name]
      || (await acxd.send(new CreateApplicationCommand(swapIds(createInput(app, ['applicationId']))))).applicationId;
    progress.apps[app.name] = done; keep();
    log('ok', `Application ${app.name}: ${done.applicationId}`);
    if (!done.buildId) {
      const build = await acxd.send(new CreateApplicationBuildCommand({ applicationIdentifier: done.applicationId,
        description: 'deploy-fresh-instance' }));
      await waitFor(`${app.name} to build`, () => acxd.send(new GetApplicationBuildCommand({
        applicationIdentifier: done.applicationId, buildIdentifier: build.buildId })), (b) => finished(b.status));
      done.buildId = build.buildId; keep();
    }
    done.aliases ||= {};
    for (const environment of ['development', 'production']) {
      if (done.aliases[environment]) continue;
      const made = await acxd.send(new CreateApplicationDeploymentCommand({ applicationIdentifier: done.applicationId,
        buildIdentifier: done.buildId, environment, description: 'deploy-fresh-instance' }));
      const live = await waitFor(`${app.name} → ${environment}`, () => acxd.send(new GetApplicationDeploymentCommand({
        applicationIdentifier: done.applicationId, deploymentIdentifier: made.deploymentId })),
      (d) => d.deploymentAlias && finished(d.deploymentStatus || 'deployed'));
      done.aliases[environment] = live.deploymentAlias; keep();
      log('ok', `${app.name} deployed to ${environment}: alias ${live.deploymentAlias}`);
    }
  }
}

await secrets();
await simple('Context variable', read('context-variables'), ListContextVariablesCommand, 'name', CreateContextVariableCommand, ['type', 'metadata']);
await simple('Slot type', read('slot-types'), ListSlotTypesCommand, 'slotTypeId', CreateSlotTypeCommand);
await simple('Modality', read('modalities'), ListModalitiesCommand, 'modalityId', CreateModalityCommand);
await dataRequests();
await byName('Guardrail', read('guardrails'), 'guardrailId', ListGuardrailsCommand, (g) => acxd.send(new CreateGuardrailCommand(
  { ...createInput(g, ['guardrailId']), rules: (g.rules || []).map((r) => createInput(r, ['id'])) })));
await knowledgeBases();
await liveSyncScripts();
await flows();
await applications();

writeFileSync(resultPath, `${JSON.stringify({ workspaceId: process.env.ACXD_WORKSPACE_ID, applications: progress.apps }, null, 2)}\n`);
log('ok', `Designer apps ready: ${Object.entries(progress.apps).map(([n, a]) => `${n} (${a.aliases?.production})`).join(', ')}`);
