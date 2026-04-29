// src/api/routes/reports.ts
import { Router } from 'express';
import { readdirSync, statSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

export const reportsRouter = Router();

const REPORTS_DIR = resolve(process.env['EVAL_REPORT_OUTPUT_DIR'] ?? './reports');

reportsRouter.get('/', (_req, res) => {
  try {
    if (!existsSync(REPORTS_DIR)) return res.json({ reports: [] });
    const files = readdirSync(REPORTS_DIR)
      .filter((f) => f.endsWith('.html') || f.endsWith('.json'))
      .sort((a, b) => b.localeCompare(a))
      .map((f) => {
        const stat = statSync(join(REPORTS_DIR, f));
        return { filename: f, size: stat.size, modifiedAt: stat.mtime.toISOString() };
      });
    res.json({ reports: files });
  } catch (err) {
    res.status(500).json({ error: (err as Error).message });
  }
});
