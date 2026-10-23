// Run once against TODAY's workspace (it only reads): writes everything the designer holds to templates/acxd, so
// create.mjs can rebuild it in the new workspace. Secrets are listed by name only; their values never leave AWS
// (create.mjs fills them from Secrets Manager in the new account).
//
//   ACXD_API_KEY=... ACXD_WORKSPACE_ID=... ACXD_REGION=eu-west-2 node capture.mjs
//   (./deploy.sh capture-acxd asks for these and runs it)
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  ListApplicationsCommand, GetApplicationCommand, ListFlowsCommand, GetFlowCommand, ListDataRequestsCommand,
  ListContextVariablesCommand, ListSlotTypesCommand, ListKnowledgeBasesCommand, ListKnowledgeBaseArticlesCommand,
  ListGuardrailsCommand, ListLiveSyncScriptsCommand, GetLiveSyncScriptCommand, ListModalitiesCommand, ListSecretsCommand,
} from 'amazon-connect-acxd-sdk';
import { all, client, log } from './lib.mjs';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'templates', 'acxd');
const acxd = client();
const save = (name, data) => writeFileSync(join(OUT, `${name}.json`), `${JSON.stringify(data, null, 2)}\n`);
mkdirSync(OUT, { recursive: true });

const applications = [];
for (const summary of await all(acxd, ListApplicationsCommand)) {
  applications.push(await acxd.send(new GetApplicationCommand({ applicationIdentifier: summary.applicationId })));
}
const flows = [];
for (const summary of await all(acxd, ListFlowsCommand)) {
  flows.push(await acxd.send(new GetFlowCommand({ flowIdentifier: summary.flowId })));
}
const knowledgeBases = [];
for (const kb of await all(acxd, ListKnowledgeBasesCommand)) {
  const articles = kb.type === 'articles'
    ? await all(acxd, ListKnowledgeBaseArticlesCommand, { knowledgeBaseId: kb.knowledgeBaseId }) : [];
  if (kb.type !== 'articles') log('warn', `Knowledge base ${kb.name} holds documents; create.mjs makes it empty (re-upload them).`);
  knowledgeBases.push({ ...kb, articles });
}
const liveSyncScripts = [];
for (const summary of await all(acxd, ListLiveSyncScriptsCommand)) {
  liveSyncScripts.push(await acxd.send(new GetLiveSyncScriptCommand({ liveSyncScriptIdentifier: summary.liveSyncScriptId })));
}
const dataRequests = await all(acxd, ListDataRequestsCommand);
const contextVariables = await all(acxd, ListContextVariablesCommand);
const slotTypes = await all(acxd, ListSlotTypesCommand);
const guardrails = await all(acxd, ListGuardrailsCommand);
const modalities = await all(acxd, ListModalitiesCommand);
const secrets = (await all(acxd, ListSecretsCommand)).map(({ name, description, isSensitive }) => ({ name, description, isSensitive }));

// The webhook addresses the Data requests call today: create.mjs swaps each for the new account's service.
const endpoints = [...new Set(dataRequests.flatMap((d) => [d.webhook?.url, d.webhook?.environments?.production?.url,
  d.webhook?.environments?.development?.url]).filter(Boolean))];

const strip = (o) => JSON.parse(JSON.stringify(o, (k, v) => (k === '$metadata' ? undefined : v)));
save('applications', strip(applications));
save('flows', strip(flows));
save('data-requests', strip(dataRequests));
save('context-variables', strip(contextVariables));
save('slot-types', strip(slotTypes));
save('knowledge-bases', strip(knowledgeBases));
save('guardrails', strip(guardrails));
save('live-sync-scripts', strip(liveSyncScripts));
save('modalities', strip(modalities));
save('secrets', secrets);
save('index', {
  capturedAt: new Date().toISOString(), workspaceId: process.env.ACXD_WORKSPACE_ID, region: process.env.ACXD_REGION,
  applications: Object.fromEntries(applications.map((a) => [a.name, a.applicationId])),
  counts: { applications: applications.length, flows: flows.length, dataRequests: dataRequests.length,
    contextVariables: contextVariables.length, slotTypes: slotTypes.length, knowledgeBases: knowledgeBases.length,
    guardrails: guardrails.length, liveSyncScripts: liveSyncScripts.length, modalities: modalities.length, secrets: secrets.length },
  endpoints,
});
log('ok', `Captured ${applications.length} applications (${applications.map((a) => a.name).join(', ')}), ${flows.length} flows, `
  + `${dataRequests.length} data requests, ${knowledgeBases.length} knowledge bases, ${secrets.length} secret names → ${OUT}`);
log('info', `Data requests call: ${endpoints.join(', ') || '(none)'}`);
