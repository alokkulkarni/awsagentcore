// src/ui/pages/ScenariosPage.tsx
import React, { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api.js';
import type { Scenario } from '../../types/scenario.js';

interface ScenarioFile {
  filename: string;
  scenarios: Scenario[];
}

export function ScenariosPage() {
  const [files, setFiles] = useState<string[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Scenario | null>(null);
  const [channelFilter, setChannelFilter] = useState<'all' | 'chat' | 'voice'>('all');
  const [runState, setRunState] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [runId, setRunId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<string[]>([]);

  useEffect(() => {
    apiFetch('/api/scenarios')
      .then((d: { scenarios: Scenario[] }) => {
        setScenarios(d.scenarios ?? []);
        const unique = [...new Set((d.scenarios ?? []).map((s: Scenario) => s.filePath?.split('#')[0] ?? ''))];
        setFiles(unique.filter(Boolean));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = scenarios.filter(
    (s) => channelFilter === 'all' || s.channel === channelFilter,
  );

  async function startRun(scenario: Scenario, channel: 'chat' | 'voice') {
    setRunState('running');
    setLiveEvents([]);
    setRunError(null);
    const filePath = scenario.filePath?.split('#')[0] ?? '';
    const indexInFile = parseInt(scenario.filePath?.split('#')[1] ?? '0', 10);
    try {
      const data = await apiFetch('/api/runs', {
        method: 'POST',
        body: JSON.stringify({ scenarioFile: filePath, scenarioIndex: indexInFile, channel }),
      }) as { runId: string };
      setRunId(data.runId);

      const es = new EventSource(`/api/runs/${data.runId}/events`);
      es.addEventListener('turn', (e) => {
        const t = JSON.parse(e.data);
        setLiveEvents((prev) => [...prev, `${t.role === 'customer' ? '👤' : '🤖'} ${t.content}`]);
      });
      es.addEventListener('complete', (e) => {
        const d = JSON.parse(e.data);
        setLiveEvents((prev) => [...prev, `✅ Complete — Score: ${d.overallScore}/10`]);
        setRunState('done');
        es.close();
      });
      es.addEventListener('failed', (e) => {
        const d = JSON.parse(e.data);
        setRunError(d.error);
        setRunState('error');
        es.close();
      });
    } catch (err) {
      setRunError((err as Error).message);
      setRunState('error');
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Scenarios</h2>
          <p className="text-slate-500 mt-1">{filtered.length} scenario(s) available</p>
        </div>
        <div className="flex gap-2">
          {(['all', 'chat', 'voice'] as const).map((c) => (
            <button key={c} onClick={() => setChannelFilter(c)}
              className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                channelFilter === c
                  ? 'bg-[#0D2A66] text-white border-[#0D2A66]'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}>
              {c === 'all' ? 'All' : c === 'chat' ? '💬 Chat' : '🎤 Voice'}
            </button>
          ))}
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {/* ── Scenario List ── */}
        <div className="space-y-2">
          {loading ? (
            <div className="text-slate-400 text-sm">Loading scenarios…</div>
          ) : filtered.length === 0 ? (
            <div className="text-slate-400 text-sm">No scenarios found.</div>
          ) : (
            filtered.map((s, i) => (
              <div key={i}
                onClick={() => setSelected(s)}
                className={`card cursor-pointer transition-all ${
                  selected === s ? 'ring-2 ring-[#0D2A66]' : 'hover:shadow-md'
                }`}>
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-semibold text-slate-900">{s.name}</p>
                    <p className="text-xs text-slate-400 mt-0.5">{s.filePath?.split('#')[0]}</p>
                  </div>
                  <span className={s.channel === 'voice' ? 'badge-voice' : 'badge-chat'}>
                    {s.channel}
                  </span>
                </div>
                {s.goal && <p className="text-sm text-slate-500 mt-2 line-clamp-2">{s.goal}</p>}
              </div>
            ))
          )}
        </div>

        {/* ── Scenario Detail + Run ── */}
        <div>
          {selected ? (
            <div className="card space-y-4 sticky top-6">
              <h3 className="font-bold text-lg text-slate-900">{selected.name}</h3>
              {selected.description && <p className="text-sm text-slate-600">{selected.description}</p>}
              <table className="text-sm w-full">
                <tbody>
                  {[
                    ['Channel', selected.channel],
                    ['Authenticated', selected.authenticated ? 'Yes' : 'No'],
                    ['Max turns', selected.max_turns ?? '—'],
                    ['Timeout', `${selected.default_timeout_seconds ?? 40}s`],
                  ].map(([k, v]) => (
                    <tr key={k} className="border-b border-slate-50">
                      <td className="py-1.5 text-slate-500 font-medium w-1/3">{k}</td>
                      <td className="py-1.5 text-slate-800">{String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {selected.goal && (
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase mb-1">Goal</p>
                  <p className="text-sm text-slate-700 bg-slate-50 rounded p-2">{selected.goal}</p>
                </div>
              )}
              {selected.customer_persona && (
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase mb-1">Persona</p>
                  <p className="text-sm text-slate-700 bg-slate-50 rounded p-2">{selected.customer_persona}</p>
                </div>
              )}

              <div className="flex gap-2">
                <button
                  disabled={runState === 'running'}
                  onClick={() => startRun(selected, 'chat')}
                  className="btn-primary flex-1 disabled:opacity-50">
                  {runState === 'running' ? '⏳ Running…' : '💬 Run Chat'}
                </button>
                <button
                  disabled={runState === 'running'}
                  onClick={() => startRun(selected, 'voice')}
                  className="btn-secondary flex-1 disabled:opacity-50">
                  🎤 Run Voice
                </button>
              </div>

              {/* Live output */}
              {liveEvents.length > 0 && (
                <div className="bg-slate-900 text-slate-100 rounded-lg p-3 text-xs font-mono max-h-48 overflow-y-auto space-y-1">
                  {liveEvents.map((e, i) => <div key={i}>{e}</div>)}
                  {runState === 'running' && <div className="animate-pulse text-slate-400">…</div>}
                </div>
              )}
              {runError && <p className="text-sm text-red-600">⚠ {runError}</p>}
            </div>
          ) : (
            <div className="card flex items-center justify-center h-48 text-slate-400 text-sm">
              Select a scenario to view details and run
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
