// src/api/routes/scenarios.ts
import { Router } from 'express';
import { readdirSync, statSync, readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, resolve, relative, dirname } from 'node:path';
import yaml from 'js-yaml';
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

// GET /api/scenarios/folders — list subdirectory names for the file location picker
scenariosRouter.get('/folders', (_req, res) => {
  try {
    if (!existsSync(SCENARIOS_DIR)) return res.json({ folders: [] });
    const folders = readdirSync(SCENARIOS_DIR, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name)
      .sort();
    res.json({ folders });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

// POST /api/scenarios/file — create a new YAML file (or append a doc to an existing one)
scenariosRouter.post('/file', (req, res) => {
  const { path: filePath, content, append } = req.body as {
    path: string; content: string; append?: boolean;
  };
  if (!filePath || !content) return res.status(400).json({ error: 'path and content required' });

  const full = join(SCENARIOS_DIR, filePath);
  if (!full.startsWith(SCENARIOS_DIR + '/')) return res.status(400).json({ error: 'Invalid path' });

  // Validate YAML before touching disk
  try {
    const parsed = (yaml.loadAll(content) as Array<Record<string, unknown>>).filter(Boolean);
    if (!parsed.length || !parsed[0]?.['name']) {
      return res.status(400).json({ error: 'Invalid YAML: scenario must have a name field' });
    }
  } catch (e) {
    return res.status(400).json({ error: `Invalid YAML: ${(e as Error).message}` });
  }

  try {
    mkdirSync(dirname(full), { recursive: true });
    if (existsSync(full)) {
      if (!append) {
        return res.status(409).json({
          error: 'File already exists. Set append=true to add this scenario to it, or choose a different filename.',
        });
      }
      const existing = readFileSync(full, 'utf-8').trimEnd();
      writeFileSync(full, `${existing}\n---\n${content.trimEnd()}\n`, 'utf-8');
    } else {
      writeFileSync(full, content.trimEnd() + '\n', 'utf-8');
    }
    res.json({ ok: true, path: filePath });
  } catch (e) {
    res.status(500).json({ error: (e as Error).message });
  }
});

// POST /api/scenarios/update-doc — replace one document in a multi-doc YAML file
// Body: { filePath: 'banking/account_query.yaml', docIndex: 2, docContent: '<yaml string>' }
scenariosRouter.post('/update-doc', (req, res) => {
  const { filePath, docIndex, docContent } = req.body as {
    filePath: string; docIndex: number; docContent: string;
  };
  if (!filePath || docIndex == null || !docContent) {
    return res.status(400).json({ error: 'filePath, docIndex and docContent required' });
  }

  const full = join(SCENARIOS_DIR, filePath);
  if (!full.startsWith(SCENARIOS_DIR + '/')) return res.status(400).json({ error: 'Invalid path' });
  if (!existsSync(full)) return res.status(404).json({ error: 'File not found' });

  // Validate new doc YAML
  try {
    const parsed = (yaml.loadAll(docContent) as Array<Record<string, unknown>>).filter(Boolean);
    if (!parsed.length || !parsed[0]?.['name']) {
      return res.status(400).json({ error: 'Invalid YAML: scenario must have a name field' });
    }
  } catch (e) {
    return res.status(400).json({ error: `Invalid YAML: ${(e as Error).message}` });
  }

  try {
    const raw = readFileSync(full, 'utf-8');
    const { preamble, docs } = splitMultiDoc(raw);
    if (docIndex < 0 || docIndex >= docs.length) {
      return res.status(400).json({ error: `docIndex ${docIndex} out of range (file has ${docs.length} docs)` });
    }
    docs[docIndex] = docContent.trimEnd();
    writeFileSync(full, joinMultiDoc(preamble, docs), 'utf-8');
    res.json({ ok: true, filePath, docIndex });
  } catch (e) {
    res.status(500).json({ error: (e as Error).message });
  }
});

/** Split a multi-document YAML file into preamble + docs array */
function splitMultiDoc(content: string): { preamble: string; docs: string[] } {
  const parts = content.split(/^---$/m).map((p) => p.trim()).filter(Boolean);
  // If the first part is all comments (starts with #) treat it as preamble
  if (parts[0] && /^#/.test(parts[0])) {
    return { preamble: parts[0], docs: parts.slice(1) };
  }
  return { preamble: '', docs: parts };
}

function joinMultiDoc(preamble: string, docs: string[]): string {
  const sections = preamble ? [preamble] : [];
  for (const doc of docs) sections.push('---\n' + doc);
  return sections.join('\n') + '\n';
}
