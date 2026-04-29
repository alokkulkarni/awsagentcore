#!/usr/bin/env node
// src/cli/run.ts — ARIA Evaluator CLI
// Same UX as aria-evaluator-v2 run_evaluation.py

import 'dotenv/config';
import { parseArgs } from 'node:util';
import { readdirSync, existsSync, readFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { ScenarioRunner } from '../conversation/runner.js';
import { ConnectChatAdapter } from '../adapters/connect-chat.js';
import { ConnectWebRTCAdapter } from '../adapters/connect-webrtc.js';
import { LLMJudge } from '../judge/llm-judge.js';
import { ReportGenerator } from '../report/generator.js';
import {
  loadScenariosFromDir,
  loadScenariosFromFile,
  filterScenarios,
} from '../conversation/scenario-loader.js';
import type { Transcript } from '../types/transcript.js';
import type { EvalResult } from '../types/evaluation.js';

// ── Banner ─────────────────────────────────────────────────────────────────────
console.log(`
🚀 ARIA Evaluator TS  starting at ${new Date().toISOString()}

  How to run:
    All scenarios (chat):  npx tsx src/cli/run.ts
    All scenarios (voice): npx tsx src/cli/run.ts --channel voice
    One scenario:          npx tsx src/cli/run.ts --scenario banking/account_query
    Voice scenario:        npx tsx src/cli/run.ts --scenario banking/account_query --channel voice
    Re-evaluate saved:     npx tsx src/cli/run.ts --transcript transcripts/foo.json
    Conversation only:     npx tsx src/cli/run.ts --conversation-only
`);

// ── Parse args ─────────────────────────────────────────────────────────────────
const { values: args } = parseArgs({
  options: {
    scenario:          { type: 'string', short: 's' },
    channel:           { type: 'string', short: 'c', default: 'chat' },
    transcript:        { type: 'string', short: 't' },
    'conversation-only': { type: 'boolean', default: false },
    'no-eval':         { type: 'boolean', default: false },
    'scenarios-dir':   { type: 'string', default: '../aria-evaluator/scenarios' },
    headless:          { type: 'boolean', default: true },
  },
  strict: false,
});

const channel = (args['channel'] as string).toLowerCase() === 'voice' ? 'voice' : 'chat';
const conversationOnly = args['conversation-only'] as boolean;
const noEval = args['no-eval'] as boolean;
const scenariosDir = resolve(args['scenarios-dir'] as string);

// ── Validate env ───────────────────────────────────────────────────────────────
// AWS credentials can come from env vars OR the shared ~/.aws/credentials file.
const hasAwsCreds = (process.env['AWS_ACCESS_KEY_ID'] && process.env['AWS_SECRET_ACCESS_KEY'])
  || process.env['AWS_PROFILE']
  || process.env['AWS_ROLE_ARN']
  || existsSync(join(process.env['HOME'] ?? '', '.aws', 'credentials'));

const REQUIRED_ALWAYS = ['CONNECT_INSTANCE_ID'];
const REQUIRED_CHAT   = ['CONNECT_CONTACT_FLOW'];
const REQUIRED_VOICE  = ['CONNECT_WEBRTC_FLOW_ID'];

const missing: string[] = [];
for (const k of REQUIRED_ALWAYS) { if (!process.env[k]) missing.push(k); }
if (channel === 'chat') {
  for (const k of REQUIRED_CHAT) {
    if (!process.env[k] && !process.env['CONNECT_CONTACT_FLOW_NAME']) missing.push(k);
  }
}
if (channel === 'voice') {
  for (const k of REQUIRED_VOICE) { if (!process.env[k]) missing.push(k); }
}
if (!hasAwsCreds) missing.push('AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (or ~/.aws/credentials)');

if (missing.length) {
  console.error(`  ✗ Missing environment variables: ${missing.join(', ')}`);
  console.error('    Copy .env.example to .env and fill in the values.');
  process.exit(1);
}

// ── Re-evaluate saved transcript ───────────────────────────────────────────────
if (args['transcript']) {
  const transcriptPath = resolve(args['transcript'] as string);
  if (!existsSync(transcriptPath)) {
    console.error(`  ✗ Transcript not found: ${transcriptPath}`);
    process.exit(1);
  }
  const transcript: Transcript = JSON.parse(readFileSync(transcriptPath, 'utf-8'));
  console.log(`  ℹ  Re-evaluating: ${transcript.scenarioName}`);

  const judge = new LLMJudge();
  const result = await judge.evaluate(transcript, 'Evaluate transcript quality');
  const reporter = new ReportGenerator();
  reporter.generate({
    runId: transcript.id,
    generatedAt: new Date().toISOString(),
    transcripts: [transcript],
    results: [result],
  });
  process.exit(0);
}

// ── Discover scenarios ─────────────────────────────────────────────────────────
let scenarioFiles: string[] = [];

if (args['scenario']) {
  const scenarioArg = args['scenario'] as string;
  const candidate = join(scenariosDir, scenarioArg);
  const withYaml = candidate.endsWith('.yaml') ? candidate : `${candidate}.yaml`;
  if (existsSync(withYaml)) {
    scenarioFiles = [withYaml];
  } else if (existsSync(candidate)) {
    // directory
    scenarioFiles = readdirSync(candidate)
      .filter((f) => f.endsWith('.yaml'))
      .map((f) => join(candidate, f));
  } else {
    console.error(`  ✗ Scenario not found: ${scenarioArg}`);
    process.exit(1);
  }
} else {
  // All scenarios
  const walk = (dir: string): string[] => {
    if (!existsSync(dir)) return [];
    return readdirSync(dir, { withFileTypes: true }).flatMap((d) =>
      d.isDirectory() ? walk(join(dir, d.name)) : d.name.endsWith('.yaml') ? [join(dir, d.name)] : [],
    );
  };
  scenarioFiles = walk(scenariosDir);
}

if (scenarioFiles.length === 0) {
  console.error(`  ✗ No scenario files found in: ${scenariosDir}`);
  process.exit(1);
}

console.log(`📂 Running ${scenarioFiles.length} scenario file(s) on channel: ${channel}\n`);

// ── Run scenarios ──────────────────────────────────────────────────────────────
const runner = new ScenarioRunner();
const allTranscripts: Transcript[] = [];
const allResults: EvalResult[] = [];
const judge = conversationOnly || noEval ? null : new LLMJudge();
const runId = randomUUID();

for (const file of scenarioFiles) {
  console.log(`\n── ${file} ──`);

  let scenarios;
  try {
    scenarios = loadScenariosFromFile(file);
  } catch (err) {
    console.error(`  ✗ Failed to load ${file}: ${(err as Error).message}`);
    continue;
  }

  // Filter to requested channel
  const filtered = filterScenarios(scenarios, undefined, channel as 'chat' | 'voice');
  if (filtered.length === 0) {
    console.log(`  ℹ  No ${channel} scenarios in this file`);
    continue;
  }

  for (const scenario of filtered) {
    const adapter = channel === 'voice'
      ? new ConnectWebRTCAdapter({
          instanceId: process.env['CONNECT_INSTANCE_ID']!,
          contactFlowId: process.env['CONNECT_WEBRTC_FLOW_ID']!,
          region: process.env['AWS_REGION'] ?? process.env['CONNECT_REGION'] ?? 'eu-west-2',
        })
      : new ConnectChatAdapter({
          instanceId: process.env['CONNECT_INSTANCE_ID']!,
        contactFlowIdOrName: process.env['CONNECT_CONTACT_FLOW'] ?? process.env['CONNECT_CONTACT_FLOW_NAME']!,
          region: process.env['AWS_REGION'] ?? 'eu-west-2',
        });

    const transcript = await runner.run(scenario, adapter);
    allTranscripts.push(transcript);

    if (judge && !transcript.error) {
      const result = await judge.evaluate(transcript, scenario.goal ?? scenario.name, scenario);
      allResults.push(result);
    }
  }
}

// ── Report ─────────────────────────────────────────────────────────────────────
if (allTranscripts.length === 0) {
  console.log('\n⚠  No transcripts collected.');
  process.exit(1);
}

if (allResults.length > 0) {
  const reporter = new ReportGenerator();
  reporter.generate({
    runId,
    generatedAt: new Date().toISOString(),
    transcripts: allTranscripts,
    results: allResults,
  });

  const passCount = allResults.filter((r) => r.passed).length;
  const avgScore = allResults.reduce((a, b) => a + b.overallScore, 0) / allResults.length;
  console.log(`\n✅ Done. ${passCount}/${allResults.length} passed. Average score: ${avgScore.toFixed(1)}/10`);
} else {
  console.log(`\n✅ Done. ${allTranscripts.length} transcript(s) saved (no evaluation run).`);
}
