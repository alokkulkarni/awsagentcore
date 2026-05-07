// src/ui/pages/ScenariosPage.tsx
import React, { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../lib/api.js';
import type { Scenario } from '../../types/scenario.js';
import { ScenarioBuilderModal } from './ScenarioBuilderModal.js';

interface ScenarioFile {
  filename: string;
  scenarios: Scenario[];
}

interface RunDetail {
  status: string;
  errorMessage?: string | null;
  evalResult?: { overallScore: number } | null;
}

type Provider = 'connect' | 'lex' | 'azure' | 'strands' | 'copilot' | 'custom';

function supportedChannels(provider: Provider): Array<'chat' | 'voice'> {
  if (provider === 'connect' || provider === 'custom') return ['chat', 'voice'];
  return ['chat'];
}

export function ScenariosPage() {
  const [files, setFiles] = useState<string[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Scenario | null>(null);
  const [channelFilter, setChannelFilter] = useState<'all' | 'chat' | 'voice'>('all');
  const [provider, setProvider] = useState<Provider>('connect');
  const [runState, setRunState] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [runId, setRunId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<string[]>([]);
  const [builder, setBuilder] = useState<{ mode: 'create' | 'edit'; scenario?: Scenario } | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    Promise.all([
      apiFetch('/api/scenarios'),
      apiFetch('/api/settings').catch(() => ({ settings: {} })),
    ])
      .then(([scenariosData, settingsData]) => {
        const d = scenariosData as { scenarios: Scenario[] };
        const s = settingsData as { settings?: Record<string, string> };
        setScenarios(d.scenarios ?? []);
        const unique = [...new Set((d.scenarios ?? []).map((sc: Scenario) => sc.filePath?.split('#')[0] ?? ''))];
        setFiles(unique.filter(Boolean));
        const defaultProvider = (s.settings?.['EVAL_PROVIDER_DEFAULT'] ?? 'connect').toLowerCase();
        if (defaultProvider === 'connect' || defaultProvider === 'lex' || defaultProvider === 'azure' || defaultProvider === 'strands' || defaultProvider === 'copilot' || defaultProvider === 'custom') {
          setProvider(defaultProvider);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    return () => {
      if (esRef.current) esRef.current.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const filtered = scenarios.filter(
    (s) => channelFilter === 'all' || s.channel === channelFilter || s.channel === 'both',
  );

  function cleanup() {
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  // Core helper: starts one run and resolves/rejects when it finishes.
  // appendEvent is called for every log/status line so callers can prefix them.
  function runOneChannel(
    scenario: Scenario,
    channel: 'chat' | 'voice',
    appendEvent: (line: string) => void,
  ): Promise<void> {
    const filePath = scenario.filePath?.split('#')[0] ?? '';
    const indexInFile = parseInt(scenario.filePath?.split('#')[1] ?? '0', 10);

    return apiFetch('/api/runs', {
      method: 'POST',
      body: JSON.stringify({ scenarioFile: filePath, scenarioIndex: indexInFile, channel, provider }),
    }).then((raw) => {
      const data = raw as { runId: string };
      setRunId(data.runId);

      return new Promise<void>((resolve, reject) => {
        const es = new EventSource(`/api/runs/${data.runId}/events`);
        esRef.current = es;

        const finish = (scoreLine?: string) => {
          cleanup();
          if (scoreLine) appendEvent(scoreLine);
          resolve();
        };
        const fail = (msg: string) => {
          cleanup();
          reject(new Error(msg));
        };

        pollRef.current = setInterval(async () => {
          try {
            const d = await apiFetch(`/api/runs/${data.runId}`) as { run: RunDetail };
            if (d.run?.status === 'completed') {
              const score = typeof d.run?.evalResult?.overallScore === 'number'
                ? ` — Score: ${d.run.evalResult.overallScore}/10` : '';
              finish(`✅ Complete${score}`);
            } else if (d.run?.status === 'failed') {
              fail(d.run?.errorMessage ?? 'Run failed');
            }
          } catch { /* ignore transient */ }
        }, 3000);

        es.addEventListener('log', (e) => {
          appendEvent((JSON.parse(e.data) as { message: string }).message);
        });
        es.addEventListener('complete', (e) => {
          const d = JSON.parse(e.data) as { overallScore?: number };
          const score = typeof d.overallScore === 'number' ? ` — Score: ${d.overallScore}/10` : '';
          finish(`✅ Complete${score}`);
        });
        es.addEventListener('failed', (e) => {
          fail((JSON.parse(e.data) as { error: string }).error);
        });
      });
    });
  }

  async function startRun(scenario: Scenario, channel: 'chat' | 'voice') {
    cleanup();
    setRunState('running');
    setLiveEvents([]);
    setRunError(null);
    try {
      await runOneChannel(scenario, channel, (line) => setLiveEvents((p) => [...p, line]));
      setRunState('done');
    } catch (err) {
      setRunError((err as Error).message);
      setRunState('error');
    }
  }

  async function startBothRun(scenario: Scenario) {
    cleanup();
    setRunState('running');
    setLiveEvents(['── 💬 Chat ──']);
    setRunError(null);
    try {
      await runOneChannel(scenario, 'chat', (line) => setLiveEvents((p) => [...p, line]));
      setLiveEvents((p) => [...p, '', '── 🎤 Voice ──']);
      await runOneChannel(scenario, 'voice', (line) => setLiveEvents((p) => [...p, line]));
      setRunState('done');
    } catch (err) {
      setRunError((err as Error).message);
      setRunState('error');
    }
  }

  async function reloadScenarios() {
    try {
      const data = await apiFetch('/api/scenarios') as { scenarios: Scenario[] };
      setScenarios(data.scenarios ?? []);
      const unique = [...new Set((data.scenarios ?? []).map((sc: Scenario) => sc.filePath?.split('#')[0] ?? ''))];
      setFiles(unique.filter(Boolean));
    } catch { /* ignore */ }
  }

  return (
    <>
    {builder && (
      <ScenarioBuilderModal
        mode={builder.mode}
        scenario={builder.scenario}
        existingFiles={files}
        onClose={() => setBuilder(null)}
        onSaved={() => { void reloadScenarios(); }}
      />
    )}
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Scenarios</h2>
          <p className="text-slate-500 mt-1">{filtered.length} scenario(s) available</p>
        </div>
        <div className="flex gap-2 items-center">
          <button
            onClick={() => setBuilder({ mode: 'create' })}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold bg-[#0D2A66] text-white hover:bg-blue-900 transition-colors">
            ✨ New Scenario
          </button>
          <div className="flex gap-1">
            {(['connect', 'lex', 'azure', 'strands', 'copilot', 'custom'] as const).map((p) => (
              <button key={p} onClick={() => setProvider(p)}
                className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                  provider === p
                    ? 'bg-[#0D2A66] text-white border-[#0D2A66]'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}>
                {p}
              </button>
            ))}
          </div>
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
                  <span className={
                    s.channel === 'voice' ? 'badge-voice' :
                    s.channel === 'both' ? 'badge-both' : 'badge-chat'
                  }>
                    {s.channel === 'both' ? '🔀 both' : s.channel}
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
                    ['Timeout', `${selected.default_timeout_seconds ?? 120}s`],
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
                  disabled={runState === 'running' || !supportedChannels(provider).includes('chat')}
                  onClick={() => startRun(selected, 'chat')}
                  className="btn-primary flex-1 disabled:opacity-50">
                  {runState === 'running' ? '⏳ Running…' : '💬 Chat'}
                </button>
                <button
                  disabled={runState === 'running' || !supportedChannels(provider).includes('voice')}
                  onClick={() => startRun(selected, 'voice')}
                  className="btn-secondary flex-1 disabled:opacity-50">
                  🎤 Voice
                </button>
                {supportedChannels(provider).includes('voice') && (
                  <button
                    disabled={runState === 'running'}
                    onClick={() => void startBothRun(selected)}
                    title="Run on Chat then Voice sequentially"
                    className="px-3 py-2 text-sm font-medium border-2 border-purple-300 text-purple-700 bg-purple-50 rounded-lg hover:bg-purple-100 disabled:opacity-50 transition-colors flex-1">
                    {runState === 'running' ? '⏳ Running…' : '🔀 Both'}
                  </button>
                )}
                <button
                  onClick={() => setBuilder({ mode: 'edit', scenario: selected })}
                  className="px-3 py-2 text-sm border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 transition-colors"
                  title="Edit this scenario">
                  ✏️ Edit
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
    </>
  );
}
