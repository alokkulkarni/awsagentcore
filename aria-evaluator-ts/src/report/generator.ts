// src/report/generator.ts
// Generates HTML and JSON evaluation reports.

import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Transcript } from '../types/transcript.js';
import type { EvalResult } from '../types/evaluation.js';
import { ALL_DIMENSIONS_BY_ID } from '../judge/dimensions.js';

export interface ReportData {
  runId: string;
  generatedAt: string;
  transcripts: Transcript[];
  results: EvalResult[];
}

export class ReportGenerator {
  constructor(private readonly reportsDir: string = './reports') {}

  generate(data: ReportData): { htmlPath: string; jsonPath: string } {
    mkdirSync(this.reportsDir, { recursive: true });
    const ts = data.generatedAt.replace(/[:.]/g, '-').slice(0, 19);
    const baseName = `report_${ts}`;

    const jsonPath = join(this.reportsDir, `${baseName}.json`);
    writeFileSync(jsonPath, JSON.stringify(data, null, 2));

    const htmlPath = join(this.reportsDir, `${baseName}.html`);
    writeFileSync(htmlPath, this.renderHtml(data));

    console.log(`\n  📊 Report saved:`);
    console.log(`     JSON: ${jsonPath}`);
    console.log(`     HTML: ${htmlPath}`);

    return { htmlPath, jsonPath };
  }

  private renderHtml(data: ReportData): string {
    const { transcripts, results } = data;
    const providers = Array.from(
      new Set(transcripts.map((t) => t.provider ?? 'unknown')),
    );

    const overallAvg =
      results.length > 0
        ? results.reduce((a, b) => a + b.overallScore, 0) / results.length
        : 0;

    const passCount = results.filter((r) => r.passed).length;
    const failCount = results.length - passCount;

    const scenarioRows = results
      .map((r) => {
        const t = transcripts.find((t) => t.id === r.runId);
        const channel = t?.channel ?? 'unknown';
        const provider = t?.provider ?? 'unknown';
        const turns = t?.turns.length ?? 0;
        const statusIcon = r.passed ? '✅' : '❌';
        return `
        <tr>
          <td>${r.scenarioName}</td>
          <td>${provider}</td>
          <td>${channel}</td>
          <td>${turns}</td>
          <td class="${r.passed ? 'pass' : 'fail'}">${statusIcon} ${r.overallScore.toFixed(1)}/10</td>
          <td>${r.summary}</td>
        </tr>`;
      })
      .join('');

    const dimTable = this.renderDimensionTable(results);
    const transcriptCards = this.renderTranscriptCards(transcripts);

    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>ARIA Evaluation Report — ${data.generatedAt.slice(0, 10)}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f5f7fa; color: #2d3748; }
    .header { background: #0D2A66; color: white; padding: 24px 32px; }
    .header h1 { font-size: 24px; }
    .header p  { opacity: .8; margin-top: 4px; font-size: 14px; }
    .container { max-width: 1200px; margin: 0 auto; padding: 24px 32px; }
    .summary-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }
    .card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    .card .label { font-size: 12px; color: #718096; text-transform: uppercase; letter-spacing: .05em; }
    .card .value { font-size: 32px; font-weight: 700; margin-top: 8px; }
    .card.pass .value { color: #38a169; }
    .card.fail .value { color: #e53e3e; }
    .card.score .value { color: #0D2A66; }
    section { background: white; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
               padding: 24px; margin-bottom: 24px; }
    h2 { font-size: 18px; margin-bottom: 16px; color: #1a202c; }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 12px; font-weight: 600; color: #718096;
         text-transform: uppercase; padding: 8px 12px; border-bottom: 2px solid #e2e8f0; }
    td { padding: 10px 12px; border-bottom: 1px solid #edf2f7; font-size: 14px; }
    tr:last-child td { border-bottom: none; }
    .pass { color: #38a169; font-weight: 600; }
    .fail { color: #e53e3e; font-weight: 600; }
    .transcript-card { background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 6px;
                        padding: 16px; margin-bottom: 12px; }
    .transcript-card h3 { font-size: 14px; margin-bottom: 12px; color: #2d3748; }
    .turn { display: flex; gap: 10px; margin-bottom: 8px; }
    .turn .role { font-size: 11px; font-weight: 700; width: 70px; flex-shrink: 0;
                   padding-top: 2px; }
    .turn.customer .role { color: #0D2A66; }
    .turn.agent .role { color: #718096; }
    .turn .text { font-size: 13px; line-height: 1.5; }
    .score-bar { background: #e2e8f0; border-radius: 4px; height: 8px; margin-top: 4px; }
    .score-bar-fill { height: 8px; border-radius: 4px; }
    .fill-pass { background: #38a169; }
    .fill-fail { background: #e53e3e; }
    .score-pass { font-weight: 700; color: #38a169; }
    .score-fail { font-weight: 700; color: #e53e3e; }
    .dim-table { width: 100%; border-collapse: collapse; }
    .dim-category { width: 160px; color: #718096; font-size: 13px; font-weight: 600; padding: 12px; border-bottom: 1px solid #edf2f7; vertical-align: top; }
    .dim-description { padding: 12px; border-bottom: 1px solid #edf2f7; }
    .dim-score { width: 100px; padding: 12px; border-bottom: 1px solid #edf2f7; vertical-align: top; }
    .dim-details { margin-top: 6px; }
    .dim-summary { font-size: 12px; color: #4a6fa5; cursor: pointer; user-select: none; display: inline-block; }
    .dim-summary:hover { text-decoration: underline; }
    .dim-detail-body { margin-top: 8px; padding: 10px 12px; background: #f7fafc; border-left: 3px solid #cbd5e0; border-radius: 0 4px 4px 0; font-size: 13px; }
    .reasoning-block ul { margin: 4px 0 8px 16px; padding: 0; }
    .reasoning-block li { margin-bottom: 4px; line-height: 1.5; color: #2d3748; }
    .evidence-block { margin-top: 8px; }
    .evidence-label { display: block; font-size: 11px; font-weight: 700; color: #718096; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 4px; }
    .evidence-quote { background: #fff; border: 1px solid #e2e8f0; border-radius: 4px; padding: 6px 10px; font-family: 'SF Mono', Consolas, monospace; font-size: 12px; color: #4a5568; margin-bottom: 4px; white-space: pre-wrap; word-break: break-word; }
  </style>
</head>
<body>
<div class="header">
  <h1>ARIA Evaluation Report</h1>
  <p>Generated ${data.generatedAt} · Run ID: ${data.runId} · Provider(s): ${providers.join(', ')}</p>
</div>
<div class="container">

  <div class="summary-cards">
    <div class="card score">
      <div class="label">Overall Score</div>
      <div class="value">${overallAvg.toFixed(1)}</div>
    </div>
    <div class="card">
      <div class="label">Scenarios Run</div>
      <div class="value">${results.length}</div>
    </div>
    <div class="card pass">
      <div class="label">Passed</div>
      <div class="value">${passCount}</div>
    </div>
    <div class="card fail">
      <div class="label">Failed</div>
      <div class="value">${failCount}</div>
    </div>
  </div>

  <section>
    <h2>Scenario Results</h2>
    <table>
      <thead><tr><th>Scenario</th><th>Provider</th><th>Channel</th><th>Turns</th><th>Score</th><th>Summary</th></tr></thead>
      <tbody>${scenarioRows}</tbody>
    </table>
  </section>

  <section>
    <h2>Dimension Scores</h2>
    ${dimTable}
  </section>

  <section>
    <h2>Conversation Transcripts</h2>
    ${transcriptCards}
  </section>

</div>
</body>
</html>`;
  }

  private renderDimensionTable(results: EvalResult[]): string {
    if (results.length === 0) return '<p>No results.</p>';

    const allDimIds = new Set<string>();
    for (const r of results) {
      for (const id of Object.keys(r.dimensionScores)) allDimIds.add(id);
    }

    const rows = Array.from(allDimIds)
      .map((dimId) => {
        const dim = ALL_DIMENSIONS_BY_ID[dimId];
        const dimScores = results.flatMap((r) =>
          r.dimensionScores[dimId] ? [r.dimensionScores[dimId]!] : [],
        );
        const numericScores = dimScores.map((d) => d.score);
        const avg = numericScores.length > 0 ? numericScores.reduce((a, b) => a + b, 0) / numericScores.length : 0;
        const pct = (avg / 10) * 100;
        const passing = avg >= 6;  // default passing threshold
        const scoreClass = passing ? 'score-pass' : 'score-fail';

        // Build justification blocks (one per result)
        const detailBlocks = dimScores
          .map((ds, i) => {
            const justLines = ds.justification
              ? ds.justification.split(' | ').map((line) =>
                  `<li>${escapeHtml(line)}</li>`,
                ).join('')
              : '';
            const evidenceLines = ds.evidence
              ? ds.evidence.split('\n').map((line) =>
                  `<div class="evidence-quote">${escapeHtml(line)}</div>`,
                ).join('')
              : '';
            const resultLabel = results.length > 1 ? `<strong>Scenario ${i + 1}:</strong> ` : '';
            return `
              ${justLines ? `<div class="reasoning-block">${resultLabel}<ul>${justLines}</ul></div>` : ''}
              ${evidenceLines ? `<div class="evidence-block"><span class="evidence-label">📎 Evidence</span>${evidenceLines}</div>` : ''}`;
          })
          .join('');

        return `
        <tr class="dim-row">
          <td class="dim-category">${dim?.category ?? 'Other'}</td>
          <td class="dim-description">
            <div>${dim?.description ?? dimId}</div>
            <details class="dim-details">
              <summary class="dim-summary">Why this score?</summary>
              <div class="dim-detail-body">${detailBlocks || '<p>No detail available.</p>'}</div>
            </details>
          </td>
          <td class="dim-score">
            <div class="${scoreClass}">${avg.toFixed(1)}/10</div>
            <div class="score-bar"><div class="score-bar-fill ${passing ? 'fill-pass' : 'fill-fail'}" style="width:${pct}%"></div></div>
          </td>
        </tr>`;
      })
      .join('');

    return `<table class="dim-table">
      <thead><tr><th>Category</th><th>Dimension</th><th>Score</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  private renderTranscriptCards(transcripts: Transcript[]): string {
    return transcripts
      .map((t) => {
        const turns = t.turns
          .map(
            (turn) => `
          <div class="turn ${turn.role}">
            <div class="role">${turn.role === 'customer' ? '👤 You' : '🤖 Agent'}</div>
            <div class="text">${escapeHtml(turn.content)}</div>
          </div>`,
          )
          .join('');

        return `
        <div class="transcript-card">
          <h3>📋 ${escapeHtml(t.scenarioName)} <small style="color:#718096">[${t.provider ?? 'unknown'} · ${t.channel}]</small></h3>
          ${turns}
          ${t.error ? `<p style="color:#e53e3e;margin-top:8px">⚠ Error: ${escapeHtml(t.error)}</p>` : ''}
        </div>`;
      })
      .join('');
  }
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
