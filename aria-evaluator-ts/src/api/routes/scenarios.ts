// src/api/routes/scenarios.ts
import { Router } from 'express';
import { readdirSync, statSync, readFileSync, existsSync } from 'node:fs';
import { join, resolve, relative } from 'node:path';
import { prisma } from '../../db/client.js';
import {
  loadScenariosFromFile,
  loadScenariosFromDir,
} from '../../conversation/scenario-loader.js';

export const scenariosRouter = Router();

const SCENARIOS_DIR = resolve(
  process.env['SCENARIOS_DIR'] ?? join('..', 'aria-evaluator-v2', 'scenarios'),
);

// GET /api/scenarios — list all scenarios (from YAML files on disk)
scenariosRouter.get('/', async (_req, res) => {
  try {
    if (!existsSync(SCENARIOS_DIR)) {
      return res.json({ scenarios: [], dir: SCENARIOS_DIR, error: 'Directory not found' });
    }
    const scenarios = loadScenariosFromDir(SCENARIOS_DIR);
    res.json({ scenarios, total: scenarios.length, dir: SCENARIOS_DIR });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// GET /api/scenarios/files — list YAML files
scenariosRouter.get('/files', (_req, res) => {
  try {
    const files = walkYaml(SCENARIOS_DIR);
    res.json({ files, dir: SCENARIOS_DIR });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// GET /api/scenarios/file?path=banking/account_query.yaml — get raw YAML
scenariosRouter.get('/file', (req, res) => {
  const filePath = req.query['path'] as string;
  if (!filePath) return res.status(400).json({ error: 'path query param required' });
  const full = join(SCENARIOS_DIR, filePath);
  if (!full.startsWith(SCENARIOS_DIR)) return res.status(400).json({ error: 'Invalid path' });
  if (!existsSync(full)) return res.status(404).json({ error: 'File not found' });
  const content = readFileSync(full, 'utf-8');
  res.json({ path: filePath, content });
});

function walkYaml(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) =>
    d.isDirectory()
      ? walkYaml(join(dir, d.name))
      : (d.name.endsWith('.yaml') || d.name.endsWith('.yml'))
        ? [relative(SCENARIOS_DIR, join(dir, d.name))]
        : [],
  );
}
