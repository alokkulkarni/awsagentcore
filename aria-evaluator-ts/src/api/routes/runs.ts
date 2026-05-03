// src/api/routes/runs.ts
// Runs the CLI in a child process and streams live terminal output via SSE.
import { Router } from 'express';
import type { Response } from 'express';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { basename, join, resolve } from 'node:path';
import yaml from 'js-yaml';

import { prisma } from '../../db/client.js';
import { loadScenariosFromFile } from '../../conversation/scenario-loader.js';
import type { Scenario } from '../../types/scenario.js';
import type { Transcript } from '../../types/transcript.js';
import type { EvalResult, DimensionScore } from '../../types/evaluation.js';
import { getEffectiveSettings, getRuntimeSettingsEnv } from '../runtime-settings.js';

export const runsRouter = Router();

const PROJECT_ROOT = resolve(process.cwd());
const SCENARIOS_DIR = resolve(
  process.env['SCENARIOS_DIR'] ?? join('..', 'aria-evaluator-v2', 'scenarios'),
);
const TMP_RUN_DIR = resolve(join(PROJECT_ROOT, '.tmp', 'portal-runs'));
const TRANSCRIPTS_DIR = resolve(join(PROJECT_ROOT, 'transcripts'));
const REPORTS_DIR = resolve(process.env['EVAL_REPORT_OUTPUT_DIR'] ?? join(PROJECT_ROOT, 'reports'));
const RUN_LOGS_DIR = resolve(join(REPORTS_DIR, 'run-logs'));
const RUN_HARD_TIMEOUT_MS = Number.parseInt(process.env['RUN_HARD_TIMEOUT_MS'] ?? '3600000', 10);
const RUN_DONE_GRACE_MS = Number.parseInt(process.env['RUN_DONE_GRACE_MS'] ?? '12000', 10);
const MAX_PERSISTED_LOG_LINES = Number.parseInt(process.env['MAX_PERSISTED_LOG_LINES'] ?? '3000', 10);

mkdirSync(TMP_RUN_DIR, { recursive: true });
mkdirSync(RUN_LOGS_DIR, { recursive: true });

// SSE clients: runId → list of Response objects
const sseClients = new Map<string, Response[]>();

interface RunRequestBody {
  scenarioFile?: string;
  scenarioIndex?: number;
  scenarioFiles?: string[];
  scenarioRefs?: string[];
  channel?: 'chat' | 'voice';
  provider?: 'connect' | 'lex' | 'azure' | 'strands' | 'copilot' | 'custom';
}

interface AggregatedReportJson {
  runId: string;
  generatedAt: string;
  transcripts: Transcript[];
  results: EvalResult[];
}

function sseEmit(runId: string, event: string, data: unknown): void {
  const clients = sseClients.get(runId) ?? [];
  const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of clients) {
    try { res.write(payload); } catch { /* disconnected */ }
  }
}

function sanitizeRelativePath(input: string): string | null {
  if (!input || input.includes('..') || input.startsWith('/')) return null;
  return input.replace(/\\/g, '/');
}

function sanitizeScenarioRef(input: string): string | null {
  if (!input) return null;
  const [rawPath, rawIndex] = input.split('#');
  if (!rawPath || rawIndex == null) return null;
  const filePath = sanitizeRelativePath(rawPath);
  if (!filePath) return null;
  const idx = Number.parseInt(rawIndex, 10);
  if (!Number.isFinite(idx) || idx < 0) return null;
  return `${filePath}#${idx}`;
}

function runLogPath(runId: string): string {
  return resolve(join(RUN_LOGS_DIR, `run-${runId}.log`));
}

function appendRunLogLine(runId: string, line: string): void {
  try {
    appendFileSync(runLogPath(runId), `${line}\n`, 'utf-8');
  } catch {
    // best-effort persistence
  }
}

function readRunLogLines(runId: string): string[] {
  const p = runLogPath(runId);
  if (!existsSync(p)) return [];
  const text = readFileSync(p, 'utf-8');
  const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
  if (MAX_PERSISTED_LOG_LINES > 0 && lines.length > MAX_PERSISTED_LOG_LINES) {
    return lines.slice(lines.length - MAX_PERSISTED_LOG_LINES);
  }
  return lines;
}

function scenarioCompatibleWithChannel(s: Scenario, channel: 'chat' | 'voice'): boolean {
  return s.channel === channel || (channel === 'voice' && s.channel === 'chat');
}

function makeRunLabel(scenarios: Scenario[], files: string[]): string {
  if (scenarios.length === 1) return scenarios[0]!.name;
  if (files.length === 1) return `${scenarios.length} scenarios (${files[0]})`;
  return `${scenarios.length} scenarios (${files.length} files)`;
}

function normalizeProvider(raw?: string): 'connect' | 'lex' | 'azure' | 'strands' | 'copilot' | 'custom' {
  const candidate = (raw ?? '').toLowerCase();
  if (candidate === 'connect' || candidate === 'lex' || candidate === 'azure' || candidate === 'strands' || candidate === 'copilot' || candidate === 'custom') {
    return candidate;
  }
  return 'connect';
}

function findRecentFiles(dir: string, extensions: string[], startMs: number): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => extensions.some((ext) => f.endsWith(ext)))
    .map((f) => ({ path: resolve(join(dir, f)), mtimeMs: statSync(join(dir, f)).mtimeMs }))
    .filter((f) => f.mtimeMs >= startMs - 2_000)
    .sort((a, b) => a.mtimeMs - b.mtimeMs)
    .map((f) => f.path);
}

function parsePathFromLog(line: string, kind: 'transcript' | 'reportJson' | 'reportHtml'): string | null {
  const transcriptMatch = line.match(/transcript saved\s*→\s*(.+\.json)\s*$/i);
  if (kind === 'transcript' && transcriptMatch?.[1]) return resolve(join(PROJECT_ROOT, transcriptMatch[1].trim()));

  const jsonMatch = line.match(/^\s*JSON:\s*(.+\.json)\s*$/);
  if (kind === 'reportJson' && jsonMatch?.[1]) return resolve(join(PROJECT_ROOT, jsonMatch[1].trim()));

  const htmlMatch = line.match(/^\s*HTML:\s*(.+\.html)\s*$/);
  if (kind === 'reportHtml' && htmlMatch?.[1]) return resolve(join(PROJECT_ROOT, htmlMatch[1].trim()));

  return null;
}

function aggregateDimensionScores(results: EvalResult[]): Record<string, DimensionScore> {
  const buckets = new Map<string, { total: number; count: number; reasons: string[]; evidence: string[] }>();
  for (const r of results) {
    for (const [dimId, dim] of Object.entries(r.dimensionScores)) {
      const b = buckets.get(dimId) ?? { total: 0, count: 0, reasons: [], evidence: [] };
      b.total += dim.score;
      b.count += 1;
      if (dim.justification) b.reasons.push(dim.justification);
      if (dim.evidence) b.evidence.push(dim.evidence);
      buckets.set(dimId, b);
    }
  }

  const aggregated: Record<string, DimensionScore> = {};
  for (const [dimId, b] of buckets.entries()) {
    aggregated[dimId] = {
      score: Math.round((b.total / Math.max(1, b.count)) * 10) / 10,
      justification: b.reasons.slice(0, 3).join(' | '),
      evidence: b.evidence.slice(0, 3).join('\n'),
    };
  }
  return aggregated;
}

async function isRunDeleted(runId: string): Promise<boolean> {
  const row = await prisma.run.findUnique({ where: { id: runId }, select: { status: true } });
  return row?.status === 'deleted';
}

// GET /api/runs
runsRouter.get('/', async (_req, res) => {
  try {
    const runs = await prisma.run.findMany({
      where: { NOT: { status: 'deleted' } },
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
    const run = await prisma.run.findFirst({
      where: { id: req.params['id']!, NOT: { status: 'deleted' } },
      include: { turns: { orderBy: { index: 'asc' } }, evalResult: true, report: true },
    });
    if (!run) return res.status(404).json({ error: 'Not found' });
    res.json({ run });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// GET /api/runs/:id/logs
runsRouter.get('/:id/logs', async (req, res) => {
  try {
    const run = await prisma.run.findFirst({
      where: { id: req.params['id']!, NOT: { status: 'deleted' } },
      select: { id: true },
    });
    if (!run) return res.status(404).json({ error: 'Not found' });
    res.json({ logs: readRunLogLines(run.id) });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// DELETE /api/runs/:id — soft delete
runsRouter.delete('/:id', async (req, res) => {
  try {
    const updated = await prisma.run.updateMany({
      where: { id: req.params['id']! },
      data: { status: 'deleted' },
    });
    if (updated.count === 0) return res.status(404).json({ error: 'Not found' });
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// GET /api/runs/:id/events — SSE
runsRouter.get('/:id/events', async (req, res) => {
  const runId = req.params['id']!;
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

  // Include SSE id field so the browser sends Last-Event-ID on auto-reconnect
  // and we can resume from the right position instead of replaying everything.
  const sendEvent = (event: string, data: unknown, id?: number): void => {
    if (id !== undefined) res.write(`id: ${id}\n`);
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  };

  // On reconnect the browser sends Last-Event-ID; skip lines already delivered.
  const lastIdHeader = req.headers['last-event-id'];
  const lastIdStr = Array.isArray(lastIdHeader) ? lastIdHeader[0] : lastIdHeader;
  const startFrom = lastIdStr ? Number.parseInt(lastIdStr, 10) + 1 : 0;

  // Replay stored log lines (from startFrom to catch reconnects up without duplication).
  const logLines = readRunLogLines(runId);
  for (let i = startFrom; i < logLines.length; i++) {
    sendEvent('log', { message: logLines[i] }, i);
  }

  // If the run already finished, synthesise the terminal event and close.
  const run = await prisma.run.findUnique({
    where: { id: runId },
    include: { evalResult: true, report: true },
  });
  if (run && run.status !== 'running' && run.status !== 'pending') {
    if (run.status === 'completed') {
      sendEvent('complete', {
        runId,
        overallScore: run.evalResult?.overallScore ?? null,
        passed: run.evalResult?.passed ?? null,
        summary: run.evalResult?.summary ?? 'Run completed',
        reportJsonPath: run.report?.jsonPath ?? null,
        reportHtmlPath: run.report?.htmlPath ?? null,
      });
    } else if (run.status === 'failed') {
      sendEvent('failed', { error: run.errorMessage ?? 'Run failed' });
    }
    res.end();
    return;
  }

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
  const {
    scenarioFile,
    scenarioIndex,
    scenarioFiles = [],
    scenarioRefs = [],
    channel = 'chat',
    provider: requestedProvider,
  } = req.body as RunRequestBody;
  const settings = getEffectiveSettings();
  const provider = normalizeProvider(requestedProvider ?? settings['EVAL_PROVIDER_DEFAULT'] ?? 'connect');

  const normalizedRefs = (scenarioRefs ?? [])
    .map((r) => sanitizeScenarioRef(r))
    .filter((r): r is string => !!r);

  const normalizedFiles = (scenarioFiles ?? [])
    .map((f) => sanitizeRelativePath(f))
    .filter((f): f is string => !!f);

  const selectedScenarios: Scenario[] = [];
  let selectedFiles: string[] = [];

  if (normalizedRefs.length > 0) {
    const uniqueRefs = [...new Set(normalizedRefs)];
    selectedFiles = [...new Set(uniqueRefs.map((ref) => ref.split('#')[0]!))];
    const docsByFile = new Map<string, Scenario[]>();

    for (const relFile of selectedFiles) {
      const fullPath = join(SCENARIOS_DIR, relFile);
      if (!fullPath.startsWith(SCENARIOS_DIR) || !existsSync(fullPath)) {
        return res.status(404).json({ error: `Scenario file not found: ${relFile}` });
      }
      docsByFile.set(relFile, loadScenariosFromFile(fullPath, SCENARIOS_DIR));
    }

    for (const ref of uniqueRefs) {
      const [relFile, rawIndex] = ref.split('#');
      const idx = Number.parseInt(rawIndex ?? '', 10);
      const docs = docsByFile.get(relFile ?? '');
      const picked = docs?.[idx];
      if (!picked) return res.status(400).json({ error: `Scenario ref out of range: ${ref}` });
      if (scenarioCompatibleWithChannel(picked, channel)) {
        selectedScenarios.push({ ...picked, channel });
      }
    }
  } else {
    selectedFiles = normalizedFiles.length > 0
      ? [...new Set(normalizedFiles)]
      : (() => {
          const single = sanitizeRelativePath(scenarioFile ?? '');
          return single ? [single] : [];
        })();

    if (selectedFiles.length === 0) {
      return res.status(400).json({ error: 'scenarioFile, scenarioFiles[] or scenarioRefs[] is required' });
    }

    for (const relFile of selectedFiles) {
      const fullPath = join(SCENARIOS_DIR, relFile);
      if (!fullPath.startsWith(SCENARIOS_DIR) || !existsSync(fullPath)) {
        return res.status(404).json({ error: `Scenario file not found: ${relFile}` });
      }

      const docs = loadScenariosFromFile(fullPath, SCENARIOS_DIR);
      if (docs.length === 0) continue;

      if (selectedFiles.length === 1 && scenarioIndex != null) {
        const picked = docs[scenarioIndex];
        if (!picked) return res.status(400).json({ error: 'Scenario index out of range' });
        if (scenarioCompatibleWithChannel(picked, channel)) {
          selectedScenarios.push({ ...picked, channel });
        }
        continue;
      }

      for (const s of docs) {
        if (scenarioCompatibleWithChannel(s, channel)) {
          selectedScenarios.push({ ...s, channel });
        }
      }
    }
  }

  if (selectedScenarios.length === 0) {
    return res.status(400).json({ error: `No scenarios match channel "${channel}" in selected file(s)` });
  }

  const runId = randomUUID();
  const runLabel = makeRunLabel(selectedScenarios, selectedFiles);
  const tmpScenarioFilename = `run-${runId}.yaml`;
  const tmpScenarioPath = join(TMP_RUN_DIR, tmpScenarioFilename);
  const yamlContent = selectedScenarios
    .map((s) => {
      const { filePath: _filePath, ...doc } = s;
      return yaml.dump(doc, { lineWidth: -1 }).trim();
    })
    .join('\n---\n');
  writeFileSync(tmpScenarioPath, yamlContent + '\n', 'utf-8');

  await prisma.run.create({
    data: {
      id: runId,
      scenarioName: `[${provider}] ${runLabel}`,
      channel,
      status: 'pending',
    },
  });

  res.status(202).json({ runId, scenarioName: runLabel });

  setImmediate(async () => {
    const startedAt = new Date();
    const startedAtMs = startedAt.getTime();
    const persistedRunLogPath = runLogPath(runId);
    const transcriptPaths = new Set<string>();
    let reportJsonPath: string | null = null;
    let reportHtmlPath: string | null = null;
    let stderrTail = '';

    const flushBufferedLines = (
      chunk: Buffer,
      carry: { value: string },
      onLine: (line: string) => void,
    ): void => {
      carry.value += chunk.toString('utf-8');
      const lines = carry.value.split(/\r?\n/);
      carry.value = lines.pop() ?? '';
      for (const line of lines) onLine(line);
    };

    try {
      writeFileSync(
        persistedRunLogPath,
        `=== Run ${runId} started at ${startedAt.toISOString()} [provider=${provider} channel=${channel}] ===\n`,
        'utf-8',
      );
      await prisma.run.updateMany({
        where: { id: runId, NOT: { status: 'deleted' } },
        data: { status: 'running', startedAt },
      });
      sseEmit(runId, 'start', {
        runId,
        provider,
        channel,
        scenarioFiles: selectedFiles,
        scenarioCount: selectedScenarios.length,
      });

      const args = [
        'run',
        `cli:${provider}`,
        '--',
        '--scenario',
        basename(tmpScenarioPath),
        '--scenarios-dir',
        TMP_RUN_DIR,
        '--channel',
        channel,
      ];
      // detached=true makes npm the leader of a new process group so we can
      // kill the entire group (npm + sh + node grandchild) in one shot.
      const child = spawn('npm', args, {
        cwd: PROJECT_ROOT,
        env: { ...process.env, ...getRuntimeSettingsEnv() },
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: true,
      });

      // Kill the whole process group; fall back to direct kill if unavailable.
      const killProcessGroup = (sig: NodeJS.Signals): void => {
        try {
          if (child.pid != null) process.kill(-child.pid, sig);
        } catch {
          if (child.exitCode == null && !child.killed) child.kill(sig);
        }
      };

      // Capture resolveExit so the done-grace timer can force-resolve if the
      // child's pipes stay open after SIGTERM (grandchild lingering handles).
      let forceResolveExit: ((v: { code: number | null; signal: NodeJS.Signals | null }) => void) | null = null;

      let sawDoneBanner = false;
      let doneGraceTimer: ReturnType<typeof setTimeout> | null = null;
      const hardTimeout = setTimeout(() => {
        if (child.exitCode == null && !child.killed) {
          sseEmit(runId, 'log', {
            message: `⚠ Run exceeded ${Math.round(RUN_HARD_TIMEOUT_MS / 1000)}s. Stopping process.`,
          });
          killProcessGroup('SIGTERM');
          // Force-resolve after 5s so the hard-timeout path always completes.
          setTimeout(() => { forceResolveExit?.({ code: null, signal: 'SIGTERM' }); }, 5_000);
        }
      }, RUN_HARD_TIMEOUT_MS);

      const outCarry = { value: '' };
      const errCarry = { value: '' };
      const onLogLine = (line: string): void => {
        const trimmed = line.trimEnd();
        if (!trimmed) return;
        appendRunLogLine(runId, trimmed);
        sseEmit(runId, 'log', { message: trimmed });
        if (trimmed.includes('Done.')) {
          sawDoneBanner = true;
          if (doneGraceTimer) clearTimeout(doneGraceTimer);
          doneGraceTimer = setTimeout(() => {
            if (child.exitCode == null && !child.killed) {
              sseEmit(runId, 'log', {
                message: 'ℹ Run completed output detected. Closing lingering process handles…',
              });
              killProcessGroup('SIGTERM');
            }
            // Force-resolve 5s after SIGTERM regardless of whether the pipes
            // close — grandchild processes may keep them open indefinitely.
            setTimeout(() => { forceResolveExit?.({ code: null, signal: 'SIGTERM' }); }, 5_000);
          }, RUN_DONE_GRACE_MS);
        }
        const transcript = parsePathFromLog(trimmed, 'transcript');
        if (transcript) transcriptPaths.add(transcript);
        const json = parsePathFromLog(trimmed, 'reportJson');
        if (json) reportJsonPath = json;
        const html = parsePathFromLog(trimmed, 'reportHtml');
        if (html) reportHtmlPath = html;
      };
      const onErrLine = (line: string): void => {
        const trimmed = line.trimEnd();
        if (!trimmed) return;
        appendRunLogLine(runId, trimmed);
        stderrTail = `${stderrTail}\n${trimmed}`.slice(-8_000);
        sseEmit(runId, 'log', { message: trimmed });
      };

      child.stdout.on('data', (chunk: Buffer) => flushBufferedLines(chunk, outCarry, onLogLine));
      child.stderr.on('data', (chunk: Buffer) => flushBufferedLines(chunk, errCarry, onErrLine));

      const exitInfo = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolveExit) => {
        forceResolveExit = (v) => { forceResolveExit = null; resolveExit(v); };
        child.on('close', (code, signal) => resolveExit({ code, signal: signal as NodeJS.Signals | null }));
        child.on('error', () => resolveExit({ code: 1, signal: null }));
      });
      clearTimeout(hardTimeout);
      if (doneGraceTimer) clearTimeout(doneGraceTimer);
      const exitCode = sawDoneBanner ? 0 : (exitInfo.code ?? 1);

      if (outCarry.value.trim()) onLogLine(outCarry.value.trim());
      if (errCarry.value.trim()) onErrLine(errCarry.value.trim());

      if (transcriptPaths.size === 0) {
        for (const p of findRecentFiles(TRANSCRIPTS_DIR, ['.json'], startedAtMs)) {
          transcriptPaths.add(p);
        }
      }
      if (!reportJsonPath || !existsSync(reportJsonPath)) {
        const recentReports = findRecentFiles(REPORTS_DIR, ['.json'], startedAtMs);
        if (recentReports.length > 0) reportJsonPath = recentReports.at(-1)!;
      }
      if (!reportHtmlPath || !existsSync(reportHtmlPath)) {
        const recentHtml = findRecentFiles(REPORTS_DIR, ['.html'], startedAtMs);
        if (recentHtml.length > 0) reportHtmlPath = recentHtml.at(-1)!;
      }

      const transcripts: Transcript[] = [];
      for (const p of transcriptPaths) {
        try {
          const parsed = JSON.parse(readFileSync(p, 'utf-8')) as Transcript;
          transcripts.push(parsed);
        } catch {
          // ignore malformed transcript
        }
      }
      transcripts.sort((a, b) => a.startedAt.localeCompare(b.startedAt));

      let mergedTurnIndex = 0;
      const multiScenario = transcripts.length > 1;
      for (const t of transcripts) {
        if (multiScenario) {
          await prisma.turn.create({
            data: {
              runId,
              index: mergedTurnIndex++,
              role: 'agent',
              content: `=== ${t.scenarioName} ===`,
              timestampMs: BigInt(Date.now()),
            },
          });
        }
        for (const turn of t.turns) {
          await prisma.turn.create({
            data: {
              runId,
              index: mergedTurnIndex++,
              role: turn.role,
              content: turn.content,
              durationMs: turn.durationMs,
              timestampMs: BigInt(turn.timestampMs),
            },
          });
        }
      }

      const audioPath = transcripts.map((t) => t.audioPath).find((p): p is string => !!p);
      if (audioPath) {
        await prisma.run.updateMany({
          where: { id: runId, NOT: { status: 'deleted' } },
          data: { audioPath },
        });
      }

      let finalStatus: 'completed' | 'failed' = exitCode === 0 ? 'completed' : 'failed';
      let finalError: string | null = null;
      if (exitCode !== 0) {
        finalError = stderrTail.trim() || (
          exitInfo.signal
            ? `CLI process exited via signal ${exitInfo.signal}`
            : `CLI process exited with code ${exitCode}`
        );
      }

      if (reportJsonPath && existsSync(reportJsonPath)) {
        try {
          const report = JSON.parse(readFileSync(reportJsonPath, 'utf-8')) as AggregatedReportJson;
          const passCount = report.results.filter((r) => r.passed).length;

          // Quality-only results drive the headline score so security refusals
          // (which always score 0 on quality dims) don't drag down the average.
          const qualityResults = report.results.filter((r) => r.scenarioType !== 'security');
          const securityResults = report.results.filter((r) => r.scenarioType === 'security');
          const scoringResults = qualityResults.length > 0 ? qualityResults : report.results;
          const avg =
            scoringResults.length > 0
              ? scoringResults.reduce((sum, r) => sum + r.overallScore, 0) / scoringResults.length
              : 0;

          const runScenarioType =
            qualityResults.length > 0 && securityResults.length > 0
              ? 'mixed'
              : securityResults.length > 0
                ? 'security'
                : 'quality';

          const summary =
            report.results.length > 0
              ? `${passCount}/${report.results.length} passed. Quality score: ${avg.toFixed(1)}/10` +
                (securityResults.length > 0
                  ? ` (${securityResults.length} security test${securityResults.length > 1 ? 's' : ''} excluded from quality average)`
                  : '')
              : 'No evaluation results generated.';

          await prisma.evalResult.upsert({
            where: { runId },
            update: {
              overallScore: Math.round(avg * 10) / 10,
              passed: report.results.length > 0 ? passCount === report.results.length : finalStatus === 'completed',
              dimensionScores: JSON.stringify(aggregateDimensionScores(qualityResults.length > 0 ? qualityResults : report.results)),
              summary,
              judgeModel: report.results[0]?.judgeModel ?? 'unknown',
              scenarioType: runScenarioType,
            },
            create: {
              runId,
              overallScore: Math.round(avg * 10) / 10,
              passed: report.results.length > 0 ? passCount === report.results.length : finalStatus === 'completed',
              dimensionScores: JSON.stringify(aggregateDimensionScores(qualityResults.length > 0 ? qualityResults : report.results)),
              summary,
              judgeModel: report.results[0]?.judgeModel ?? 'unknown',
              scenarioType: runScenarioType,
            },
          });
        } catch (err) {
          sseEmit(runId, 'log', { message: `⚠ Unable to parse report JSON: ${(err as Error).message}` });
        }
      }

      if (reportJsonPath && reportHtmlPath && existsSync(reportJsonPath) && existsSync(reportHtmlPath)) {
        await prisma.report.upsert({
          where: { runId },
          update: { jsonPath: reportJsonPath, htmlPath: reportHtmlPath },
          create: { runId, jsonPath: reportJsonPath, htmlPath: reportHtmlPath },
        });
      }

      if (!(await isRunDeleted(runId))) {
        await prisma.run.update({
          where: { id: runId },
          data: {
            status: finalStatus,
            completedAt: new Date(),
            errorMessage: finalError,
          },
        });
      }

      if (finalStatus === 'failed') {
        appendRunLogLine(runId, `=== Run failed: ${finalError ?? 'Run failed'} ===`);
        sseEmit(runId, 'failed', { error: finalError ?? 'Run failed' });
      } else {
        const evalResult = await prisma.evalResult.findUnique({ where: { runId } });
        appendRunLogLine(runId, `=== Run completed: ${evalResult?.summary ?? 'Run completed'} ===`);
        sseEmit(runId, 'complete', {
          runId,
          overallScore: evalResult?.overallScore ?? null,
          passed: evalResult?.passed ?? null,
          summary: evalResult?.summary ?? 'Run completed',
          reportJsonPath,
          reportHtmlPath,
        });
      }
    } catch (err) {
      const msg = (err as Error).message;
      appendRunLogLine(runId, `=== Run failed: ${msg} ===`);
      await prisma.run.updateMany({
        where: { id: runId, NOT: { status: 'deleted' } },
        data: { status: 'failed', completedAt: new Date(), errorMessage: msg },
      }).catch(() => {});
      sseEmit(runId, 'failed', { error: msg });
    } finally {
      try { unlinkSync(tmpScenarioPath); } catch { /* ignore */ }
    }
  });
});
