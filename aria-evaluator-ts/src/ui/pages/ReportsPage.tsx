// src/ui/pages/ReportsPage.tsx
import React, { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api.js';

interface ReportFile {
  filename: string;
  size: number;
  modifiedAt: string;
}

export function ReportsPage() {
  const [reports, setReports] = useState<ReportFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);

  useEffect(() => {
    apiFetch('/api/reports')
      .then((d: { reports: ReportFile[] }) => {
        // Only show HTML reports (visual); pair with JSON
        const html = (d.reports ?? []).filter((r) => r.filename.endsWith('.html'));
        setReports(html);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Reports</h2>
        <p className="text-slate-500 mt-1">{reports.length} evaluation report(s)</p>
      </div>

      <div className="grid md:grid-cols-4 gap-4">
        {/* ── Report List ── */}
        <div className="md:col-span-1 space-y-2">
          {loading ? (
            <div className="text-slate-400 text-sm">Loading…</div>
          ) : reports.length === 0 ? (
            <div className="card text-slate-400 text-sm">No reports yet. Run an evaluation to generate one.</div>
          ) : (
            reports.map((r) => {
              const url = `/reports/${r.filename}`;
              return (
                <div key={r.filename}
                  onClick={() => setSelectedUrl(url)}
                  className={`card cursor-pointer transition-all text-sm ${
                    selectedUrl === url ? 'ring-2 ring-[#0D2A66]' : 'hover:shadow-md'
                  }`}>
                  <p className="font-medium truncate">
                    📊 {r.filename.replace('report_', '').replace('.html', '')}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">{new Date(r.modifiedAt).toLocaleString()}</p>
                  <p className="text-xs text-slate-400">{(r.size / 1024).toFixed(1)} KB</p>
                  <a href={url} target="_blank" rel="noopener"
                    onClick={(e) => e.stopPropagation()}
                    className="text-xs text-blue-600 hover:underline mt-1 block">
                    Open in new tab ↗
                  </a>
                </div>
              );
            })
          )}
        </div>

        {/* ── Report Viewer ── */}
        <div className="md:col-span-3">
          {selectedUrl ? (
            <div className="card p-0 overflow-hidden h-[70vh]">
              <iframe
                src={selectedUrl}
                title="Report"
                className="w-full h-full border-0 rounded-xl"
              />
            </div>
          ) : (
            <div className="card flex items-center justify-center h-48 text-slate-400 text-sm">
              Select a report to preview
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
