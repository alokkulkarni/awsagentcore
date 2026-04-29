// src/api/routes/runs.ts
// POST /api/runs — trigger a new evaluation run
// GET  /api/runs — list recent runs from DB
// GET  /api/runs/:id/events — SSE stream for live run progress
import { Router } from 'express';
import { randomUUID } from 'node:crypto';
import { resolve, join } from 'node:path';
import { existsSync } from 'node:fs';
import type { Response } from 'express';
import { prisma } from '../../db/client.js';
import { ScenarioRunner } from '../../conversation/runner.js';
import { ConnectChatAdapter } from '../../adapters/connect-chat.js';
import { ConnectWebRTCAdapter } from '../../adapters/connect-webrtc.js';
import { LLMJudge } from '../../judge/llm-judge.js';
import { ReportGenerator } from '../../report/generator.js';
import { loadScenariosFromFile } from '../../conversation/scenario-loader.js';
import type { Transcript } from '../../types/transcript.js';
import type { EvalResult } from '../../types/evaluation.js';
import type { RunnerEvent } from '../../conversation/runner.js';

export const runsRouter = Router();

// SSE clients: runId → list of Response objects
const sseClients = new Map<string, Response[]>();

function sseEmit(runId: string, event: string, data: unknown): void {
  const clients = sseClients.get(runId) ?? [];
  const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of clients) {
    try { res.write(payload); } catch { /* client disconnected */ }
  }
}

// GET /api/runs
runsRouter.get('/', async (_req, res) => {
  try {
    const runs = await prisma.run.findMany({
      orderBy: { createdAt: 'desc' },
      take: 100,
      include: { evalResult: true },
    });
    res.json({ runs });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// GET /api/runs/:id
runsRouter.get('/:id', async (req, res) => {
  try {
    const run = await prisma.run.findUnique({
      where: { id: req.params['id']! },
      include: { turns: { orderBy: { index: 'asc' } }, evalResult: true, report: true },
    });
    if (!run) return res.status(404).json({ error: 'Not found' });
    res.json({ run });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// GET /api/runs/:id/events — SSE
runsRouter.get('/:id/events', (req, res) => {
  const runId = req.params['id']!;
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

  const clients = sseClients.get(runId) ?? [];
  clients.push(res);
  sseClients.set(runId, clients);

  req.on('close', () => {
    const remaining = (sseClients.get(runId) ?? []).filter((c) => c !== res);
    if (remaining.length > 0) sseClients.set(runId, remaining);
    else sseClients.delete(runId);
  });
});

// POST /api/runs
runsRouter.post('/', async (req, res) => {
  const { scenarioFile, scenarioIndex, channel = 'chat', evaluateOnly = false } = req.body as {
    scenarioFile?: string;
    scenarioIndex?: number;
    channel?: 'chat' | 'voice';
    evaluateOnly?: boolean;
  };

  if (!scenarioFile) return res.status(400).json({ error: 'scenarioFile required' });

  const SCENARIOS_DIR = resolve(
    process.env['SCENARIOS_DIR'] ?? join('..', 'aria-evaluator-v2', 'scenarios'),
  );
  const fullPath = join(SCENARIOS_DIR, scenarioFile);
  if (!existsSync(fullPath)) return res.status(404).json({ error: 'Scenario file not found' });

  const runId = randomUUID();
  const scenarios = loadScenariosFromFile(fullPath, SCENARIOS_DIR);
  if (scenarios.length === 0) {
    return res.status(400).json({ error: `No scenarios found in ${scenarioFile}` });
  }

  // scenarioIndex is the raw document index within the YAML file.
  // The YAML channel field is a default; the request channel overrides it.
  const rawScenario = scenarios[scenarioIndex ?? 0];
  if (!rawScenario) return res.status(400).json({ error: 'Scenario index out of range' });
  // Override channel with the caller's explicit choice
  const scenario = { ...rawScenario, channel: channel as 'chat' | 'voice' };

  // Create DB run record
  const dbRun = await prisma.run.create({
    data: {
      id: runId,
      scenarioName: scenario.name,
      channel,
      status: 'pending',
    },
  });

  // Respond immediately with run ID
  res.status(202).json({ runId, scenarioName: scenario.name });

  // Run in background (fire-and-forget)
  setImmediate(async () => {
    try {
      await prisma.run.update({ where: { id: runId }, data: { status: 'running', startedAt: new Date() } });
      sseEmit(runId, 'start', { runId, scenarioName: scenario.name, channel });

      const runner = new ScenarioRunner({
        onProgress: (event: RunnerEvent) => {
          if (event.type === 'turn') {
            sseEmit(runId, 'turn', event.turn);
          } else if (event.type === 'log') {
            sseEmit(runId, 'log', { message: event.message });
          } else if (event.type === 'error') {
            sseEmit(runId, 'error', { message: event.error });
          }
        },
      });

      const adapter = channel === 'voice'
        ? new ConnectWebRTCAdapter({
            instanceId: process.env['CONNECT_INSTANCE_ID']!,
            contactFlowId: process.env['CONNECT_WEBRTC_FLOW_ID'] ?? '',
            region: process.env['AWS_REGION'] ?? process.env['CONNECT_REGION'] ?? 'eu-west-2',
          })
        : new ConnectChatAdapter({
            instanceId: process.env['CONNECT_INSTANCE_ID']!,
            contactFlowIdOrName:
              process.env['CONNECT_CONTACT_FLOW'] ??
              process.env['CONNECT_CONTACT_FLOW_NAME'] ??
              'conversation bot flow',
            region: process.env['AWS_REGION'] ?? process.env['CONNECT_REGION'] ?? 'eu-west-2',
          });

      const transcript: Transcript = await runner.run(scenario, adapter, runId);

      // Persist turns to DB
      for (const t of transcript.turns) {
        await prisma.turn.create({
          data: {
            runId,
            index: t.index,
            role: t.role,
            content: t.content,
            durationMs: t.durationMs,
            timestampMs: BigInt(t.timestampMs),
          },
        });
      }

      // Store audio path if voice run captured one
      if (transcript.audioPath) {
        await prisma.run.update({
          where: { id: runId },
          data: { audioPath: transcript.audioPath },
        });
      }

      if (transcript.error) {
        await prisma.run.update({
          where: { id: runId },
          data: { status: 'failed', completedAt: new Date(), errorMessage: transcript.error },
        });
        sseEmit(runId, 'failed', { error: transcript.error });
        return;
      }

      await prisma.run.update({
        where: { id: runId },
        data: { status: 'evaluating', completedAt: new Date() },
      });
      sseEmit(runId, 'evaluating', { message: 'Running LLM judge…' });

      const judge = new LLMJudge();
      const result: EvalResult = await judge.evaluate(transcript, scenario.goal ?? scenario.name);

      await prisma.evalResult.create({
        data: {
          runId,
          overallScore: result.overallScore,
          passed: result.passed,
          dimensionScores: JSON.stringify(result.dimensionScores),
          summary: result.summary,
          judgeModel: result.judgeModel,
        },
      });

      const reporter = new ReportGenerator();
      const { htmlPath, jsonPath } = reporter.generate({
        runId,
        generatedAt: new Date().toISOString(),
        transcripts: [transcript],
        results: [result],
      });

      await prisma.report.create({ data: { runId, htmlPath, jsonPath } });
      await prisma.run.update({ where: { id: runId }, data: { status: 'completed' } });

      sseEmit(runId, 'complete', {
        runId,
        overallScore: result.overallScore,
        passed: result.passed,
        summary: result.summary,
        htmlPath,
        jsonPath,
      });
    } catch (err) {
      const msg = (err as Error).message;
      await prisma.run.update({
        where: { id: runId },
        data: { status: 'failed', errorMessage: msg },
      }).catch(() => {});
      sseEmit(runId, 'failed', { error: msg });
    }
  });
});
