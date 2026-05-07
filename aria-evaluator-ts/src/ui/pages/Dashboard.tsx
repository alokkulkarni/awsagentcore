// src/ui/pages/Dashboard.tsx
import React, { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api.js';

interface Run {
  id: string;
  scenarioName: string;
  channel: string;
  status: string;
  createdAt: string;
  evalResult?: { overallScore: number; passed: boolean; scenarioType?: string } | null;
}

interface Props {
  onNavigate: (page: 'scenarios' | 'runs' | 'transcripts' | 'reports') => void;
}

export function Dashboard({ onNavigate }: Props) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch('/api/runs')
      .then((d: { runs: Run[] }) => setRuns(d.runs ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const total = runs.length;
  const passed = runs.filter((r) => r.evalResult?.passed === true).length;
  const failed = runs.filter((r) => r.evalResult?.passed === false).length;

  // Exclude security-only runs from the quality average so adversarial tests
  // don't drag down the headline score.
  const qualityRuns = runs.filter((r) => r.evalResult && r.evalResult.scenarioType !== 'security');
  const avgScore =
    qualityRuns.length > 0
      ? (qualityRuns.reduce((a, b) => a + (b.evalResult?.overallScore ?? 0), 0) / qualityRuns.length).toFixed(1)
      : '—';

  const recent = runs.slice(0, 8);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Dashboard</h2>
        <p className="text-slate-500 mt-1">Agent quality evaluation overview</p>
      </div>

      {/* ── Summary Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Avg Score" value={String(avgScore)} sub="/10" color="blue" />
        <StatCard label="Total Runs" value={String(total)} color="slate" />
        <StatCard label="Passed" value={String(passed)} color="green" />
        <StatCard label="Failed" value={String(failed)} color="red" />
      </div>

      {/* ── Recent Runs ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-slate-900">Recent Runs</h3>
          <button onClick={() => onNavigate('runs')} className="text-sm text-blue-600 hover:underline">
            View all →
          </button>
        </div>

        {loading ? (
          <div className="text-slate-400 text-sm py-8 text-center">Loading…</div>
        ) : recent.length === 0 ? (
          <div className="text-slate-400 text-sm py-8 text-center">
            No runs yet.{' '}
            <button onClick={() => onNavigate('scenarios')} className="text-blue-600 hover:underline">
              Start one →
            </button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500 uppercase tracking-wide border-b border-slate-100">
                <th className="pb-2 font-medium">Scenario</th>
                <th className="pb-2 font-medium">Channel</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium">Score</th>
                <th className="pb-2 font-medium">Date</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((r) => (
                <tr key={r.id} className="border-b border-slate-50 last:border-0">
                  <td className="py-2.5 font-medium text-slate-800">{r.scenarioName}</td>
                  <td className="py-2.5">
                    <span className={r.channel === 'voice' ? 'badge-voice' : 'badge-chat'}>
                      {r.channel}
                    </span>
                  </td>
                  <td className="py-2.5">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="py-2.5">
                    {r.evalResult ? (
                      <div className="flex items-center gap-1.5">
                        {r.evalResult.scenarioType === 'security' && (
                          <span title="Security test" className="text-xs bg-purple-100 text-purple-700 rounded px-1.5 py-0.5 font-semibold">🛡 Security</span>
                        )}
                        <span className={r.evalResult.passed ? 'text-green-700 font-semibold' : 'text-red-600 font-semibold'}>
                          {r.evalResult.overallScore.toFixed(1)}/10
                        </span>
                      </div>
                    ) : '—'}
                  </td>
                  <td className="py-2.5 text-slate-400">{new Date(r.createdAt).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Quick Actions ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: '📋 Browse Scenarios', page: 'scenarios' as const },
          { label: '▶️ Start a Run', page: 'scenarios' as const },
          { label: '💬 View Transcripts', page: 'transcripts' as const },
          { label: '📊 View Reports', page: 'reports' as const },
        ].map((a) => (
          <button key={a.page} onClick={() => onNavigate(a.page)}
            className="card text-center text-sm font-medium text-slate-700 hover:bg-slate-50 hover:shadow transition-shadow cursor-pointer">
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color: string }) {
  const colors: Record<string, string> = {
    blue: 'text-blue-700', green: 'text-green-700', red: 'text-red-600', slate: 'text-slate-800',
  };
  return (
    <div className="card">
      <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${colors[color] ?? 'text-slate-800'}`}>
        {value}{sub && <span className="text-base font-normal text-slate-400">{sub}</span>}
      </p>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: 'badge-pass', failed: 'badge-fail',
    running: 'badge-running', evaluating: 'badge-running', pending: 'badge-pending',
  };
  return <span className={map[status] ?? 'badge-pending'}>{status}</span>;
}
