// src/api/routes/transcripts.ts
import { Router } from 'express';
import { readdirSync, statSync, readFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

export const transcriptsRouter = Router();

const TRANSCRIPTS_DIR = resolve('./transcripts');

transcriptsRouter.get('/', (_req, res) => {
  try {
    if (!existsSync(TRANSCRIPTS_DIR)) return res.json({ transcripts: [] });
    const files = readdirSync(TRANSCRIPTS_DIR)
      .filter((f) => f.endsWith('.json'))
      .sort((a, b) => b.localeCompare(a))
      .map((f) => {
        const stat = statSync(join(TRANSCRIPTS_DIR, f));
        return { filename: f, size: stat.size, modifiedAt: stat.mtime.toISOString() };
      });
    res.json({ transcripts: files });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});

transcriptsRouter.get('/:filename', (req, res) => {
  const filename = req.params['filename']!;
  if (!filename.endsWith('.json') || filename.includes('/') || filename.includes('..')) {
    return res.status(400).json({ error: 'Invalid filename' });
  }
  const filePath = join(TRANSCRIPTS_DIR, filename);
  if (!existsSync(filePath)) return res.status(404).json({ error: 'Not found' });
  const content = JSON.parse(readFileSync(filePath, 'utf-8'));
  res.json(content);
});
