// src/api/server.ts
// Express REST API + SSE for live run progress

import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import { createServer } from 'node:http';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';

import { scenariosRouter } from './routes/scenarios.js';
import { runsRouter } from './routes/runs.js';
import { transcriptsRouter } from './routes/transcripts.js';
import { reportsRouter } from './routes/reports.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env['API_PORT'] ?? '3001', 10);
const DIST_DIR = join(__dirname, '../../dist/ui');
const REPORTS_DIR = process.env['EVAL_REPORT_OUTPUT_DIR'] ?? './reports';
const TRANSCRIPTS_DIR = './transcripts';
const AUDIO_DIR = './transcripts/audio';
const PUBLIC_DIR = join(__dirname, '../../public');

export const app = express();

app.use(cors({ origin: '*' }));
app.use(express.json({ limit: '2mb' }));

// ── API routes ─────────────────────────────────────────────────────────────────
app.use('/api/scenarios', scenariosRouter);
app.use('/api/runs', runsRouter);
app.use('/api/transcripts', transcriptsRouter);
app.use('/api/reports', reportsRouter);

// ── Static file serving ────────────────────────────────────────────────────────
app.use('/reports',     express.static(REPORTS_DIR));
app.use('/transcripts', express.static(TRANSCRIPTS_DIR));
app.use('/audio',       express.static(AUDIO_DIR));
app.use(express.static(PUBLIC_DIR));
if (existsSync(DIST_DIR)) {
  app.use(express.static(DIST_DIR));
  app.get('*', (_req, res) => {
    res.sendFile(join(DIST_DIR, 'index.html'));
  });
}

// ── Health check ───────────────────────────────────────────────────────────────
app.get('/health', (_req, res) => {
  res.json({ ok: true, ts: new Date().toISOString() });
});

// ── Start ──────────────────────────────────────────────────────────────────────
if (process.env['NODE_ENV'] !== 'test') {
  const server = createServer(app);
  server.listen(PORT, () => {
    console.log(`\n🚀 ARIA Evaluator API running at http://localhost:${PORT}`);
    console.log(`   Health: http://localhost:${PORT}/health`);
    console.log(`   UI:     http://localhost:${PORT}`);
    console.log(`   CCP:    http://localhost:${PORT}/evaluator-ccp.html\n`);
  });
}
