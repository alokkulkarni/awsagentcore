// src/ui/pages/RunsPage.tsx
import React, { useEffect, useState, useRef } from 'react';
import { apiFetch } from '../lib/api.js';
import { StatusBadge } from './Dashboard.js';
import type { Scenario } from '../../types/scenario.js';

interface Run {
  id: string;
  scenarioName: string;
  channel: string;
  status: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  errorMessage?: string;
  audioPath?: string;
  evalResult?: { overallScore: number; passed: boolean; summary: string } | null;
  turns?: Array<{ index: number; role: string; content: string }>;
}

// ── New Run Modal ─────────────────────────────────────────────────────────────
function NewRunModal({
  onClose,
  preselect,
  onStarted,
}: {
  onClose: () => void;
  preselect?: string;
  onStarted: (runId: string) => void;
}) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [search, setSearch] = useState(preselect ?? '');
  const [selected, setSelected] = useState<Scenario | null>(null);
  const [channel, setChannel] = useState<'chat' | 'voice'>('chat');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch('/api/scenarios')
      .then((d: { scenarios: Scenario[] }) => {
        const list = d.scenarios ?? [];
        setScenarios(list);
        // Pre-select if a scenario name was passed in
        if (preselect) {
          const match = list.find((s) => s.name === preselect);
          if (match) setSelected(match);
        }
      })
      .catch(() => {});
  }, [preselect]);

  const filtered = scenarios.filter(
    (s) =>
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      (s.goal ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  async function startRun() {
    if (!selected) return;
    setRunning(true);
    setError(null);
    const filePath = selected.filePath?.split('#')[0] ?? '';
    const indexInFile = parseInt(selected.filePath?.split('#')[1] ?? '0', 10);
    try {
      const data = await apiFetch('/api/runs', {
        method: 'POST',
        body: JSON.stringify({ scenarioFile: filePath, scenarioIndex: indexInFile, channel }),
      }) as { runId: string };
      onStarted(data.runId);
      onClose();
    } catch (err) {
      setError((err as Error).message);
      setRunning(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl mx-4 flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <h3 className="text-lg font-bold text-slate-900">New Evaluation Run</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl leading-none">✕</button>
        </div>

        {/* Search */}
        <div className="px-6 pt-4 pb-2">
          <input
            autoFocus
            type="text"
            placeholder="Search scenarios…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#0D2A66]"
          />
        </div>

        {/* Scenario list */}
        <div className="px-6 overflow-y-auto flex-1 py-2 space-y-1.5">
          {filtered.length === 0 ? (
            <p className="text-slate-400 text-sm py-4 text-center">No scenarios match.</p>
          ) : (
            filtered.map((s, i) => (
              <div
                key={i}
                onClick={() => { setSelected(s); setChannel(s.channel === 'voice' ? 'voice' : 'chat'); }}
                className={`rounded-lg px-3 py-2.5 cursor-pointer border transition-all text-sm ${
                  selected?.filePath === s.filePath
                    ? 'border-[#0D2A66] bg-blue-50'
                    : 'border-transparent hover:border-slate-200 hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-800">{s.name}</span>
                  <span className={s.channel === 'voice' ? 'badge-voice' : 'badge-chat'}>{s.channel}</span>
                </div>
                {s.goal && <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{s.goal}</p>}
              </div>
            ))
          )}
        </div>

        {/* Footer: channel + start */}
        <div className="px-6 py-4 border-t border-slate-100 space-y-3">
          {selected && (
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-500 font-medium">Channel:</span>
              {(['chat', 'voice'] as const).map((c) => (
                <button
                  key={c}
                  onClick={() => setChannel(c)}
                  className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                    channel === c
                      ? 'bg-[#0D2A66] text-white border-[#0D2A66]'
                      : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  {c === 'chat' ? '💬 Chat' : '🎤 Voice'}
                </button>
              ))}
            </div>
          )}

          {error && <p className="text-xs text-red-600">⚠ {error}</p>}

          <div className="flex gap-2">
            <button onClick={onClose} className="btn-secondary flex-1 text-sm">Cancel</button>
            <button
              disabled={!selected || running}
              onClick={startRun}
              className="btn-primary flex-1 text-sm disabled:opacity-40"
            >
              {running ? '⏳ Starting…' : '▶ Start Run'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── RunsPage ──────────────────────────────────────────────────────────────────
export function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);
  const [liveEvents, setLiveEvents] = useState<string[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [modalPreselect, setModalPreselect] = useState<string | undefined>(undefined);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    loadRuns();
    const interval = setInterval(loadRuns, 5000);
    return () => clearInterval(interval);
  }, []);

  function loadRuns() {
    apiFetch('/api/runs')
      .then((d: { runs: Run[] }) => setRuns(d.runs ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  function openNewRun(preselect?: string) {
    setModalPreselect(preselect);
    setShowModal(true);
  }

  function handleRunStarted(runId: string) {
    loadRuns();
    // Auto-select the new run and open SSE
    setTimeout(() => {
      apiFetch(`/api/runs/${runId}`)
        .then((d: { run: Run }) => { if (d.run) selectRun(d.run); })
        .catch(() => {});
    }, 500);
  }

  function selectRun(run: Run) {
    setSelected(run);
    setLiveEvents([]);
    if (esRef.current) { esRef.current.close(); esRef.current = null; }

    if (run.status === 'running' || run.status === 'evaluating' || run.status === 'pending') {
      const es = new EventSource(`/api/runs/${run.id}/events`);
      esRef.current = es;
      es.addEventListener('turn', (e) => {
        const t = JSON.parse(e.data);
        setLiveEvents((prev) => [...prev, `${t.role === 'customer' ? '👤' : '🤖'} ${t.content.slice(0, 120)}`]);
      });
      es.addEventListener('log', (e) => {
        const d = JSON.parse(e.data);
        setLiveEvents((prev) => [...prev, d.message]);
      });
      es.addEventListener('evaluating', () => {
        setLiveEvents((prev) => [...prev, '🔍 Running LLM evaluation…']);
      });
      es.addEventListener('complete', (e) => {
        const d = JSON.parse(e.data);
        setLiveEvents((prev) => [...prev, `✅ Score: ${d.overallScore}/10 — ${d.summary}`]);
        loadRuns();
        es.close();
      });
      es.addEventListener('failed', (e) => {
        const d = JSON.parse(e.data);
        setLiveEvents((prev) => [...prev, `❌ Failed: ${d.error}`]);
        loadRuns();
        es.close();
      });
    }
  }

  return (
    <>
      {showModal && (
        <NewRunModal
          preselect={modalPreselect}
          onClose={() => setShowModal(false)}
          onStarted={handleRunStarted}
        />
      )}

      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Evaluation Runs</h2>
            <p className="text-slate-500 mt-1">{runs.length} total runs</p>
          </div>
          <button onClick={() => openNewRun()} className="btn-primary">
            + New Run
          </button>
        </div>

        <div className="grid md:grid-cols-5 gap-4">
          {/* ── Run List ── */}
          <div className="md:col-span-2 space-y-2 max-h-[70vh] overflow-y-auto">
            {loading ? (
              <div className="text-slate-400 text-sm">Loading…</div>
            ) : runs.length === 0 ? (
              <div className="card text-center space-y-3 py-8">
                <p className="text-slate-400 text-sm">No runs yet.</p>
                <button onClick={() => openNewRun()} className="btn-primary text-sm">+ New Run</button>
              </div>
            ) : (
              runs.map((r) => (
                <div key={r.id} onClick={() => selectRun(r)}
                  className={`card cursor-pointer transition-all text-sm ${
                    selected?.id === r.id ? 'ring-2 ring-[#0D2A66]' : 'hover:shadow-md'
                  }`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-semibold truncate">{r.scenarioName}</p>
                      <p className="text-xs text-slate-400">{new Date(r.createdAt).toLocaleString()}</p>
                    </div>
                    <StatusBadge status={r.status} />
                  </div>
                  <div className="flex items-center justify-between mt-2">
                    <div className="flex items-center gap-2">
                      <span className={r.channel === 'voice' ? 'badge-voice' : 'badge-chat'}>{r.channel}</span>
                      {r.evalResult && (
                        <span className={r.evalResult.passed ? 'text-green-700 font-bold text-xs' : 'text-red-600 font-bold text-xs'}>
                          {r.evalResult.overallScore.toFixed(1)}/10
                        </span>
                      )}
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); openNewRun(r.scenarioName); }}
                      className="text-xs text-[#0D2A66] hover:underline font-medium"
                      title="Re-run this scenario"
                    >
                      ↩ Re-run
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* ── Run Detail ── */}
          <div className="md:col-span-3">
            {selected ? (
              <div className="card space-y-4">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-bold text-lg">{selected.scenarioName}</h3>
                    <p className="text-xs text-slate-400 font-mono">{selected.id}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={selected.status} />
                    <button
                      onClick={() => openNewRun(selected.scenarioName)}
                      className="btn-primary text-xs py-1 px-3"
                    >
                      ↩ Re-run
                    </button>
                  </div>
                </div>

                {selected.evalResult && (
                  <div className="bg-slate-50 rounded-lg p-4">
                    <p className="text-sm font-semibold text-slate-700 mb-1">
                      {selected.evalResult.passed ? '✅ PASS' : '❌ FAIL'} — {selected.evalResult.overallScore.toFixed(1)}/10
                    </p>
                    <p className="text-sm text-slate-600">{selected.evalResult.summary}</p>
                  </div>
                )}

                {selected.errorMessage && (
                  <div className="bg-red-50 text-red-700 rounded-lg p-3 text-sm">
                    ⚠ {selected.errorMessage}
                  </div>
                )}

                {liveEvents.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase mb-2">Live Output</p>
                    <div className="bg-slate-900 text-slate-100 rounded-lg p-3 text-xs font-mono max-h-52 overflow-y-auto space-y-1">
                      {liveEvents.map((e, i) => <div key={i}>{e}</div>)}
                      {(selected.status === 'running' || selected.status === 'evaluating') && (
                        <div className="animate-pulse text-slate-400">…</div>
                      )}
                    </div>
                  </div>
                )}

                {selected.turns && selected.turns.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase mb-2">Transcript</p>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {selected.turns.map((t) => (
                        <div key={t.index} className={`flex gap-2 ${t.role === 'customer' ? '' : 'flex-row-reverse'}`}>
                          <span className="text-lg flex-shrink-0">{t.role === 'customer' ? '👤' : '🤖'}</span>
                          <div className={`rounded-lg px-3 py-2 text-sm max-w-[80%] ${
                            t.role === 'customer' ? 'bg-blue-50 text-blue-900' : 'bg-slate-100 text-slate-800'
                          }`}>
                            {t.content}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {selected.audioPath && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase mb-2">🎙 Call Recording</p>
                    <audio
                      controls
                      className="w-full rounded-lg"
                      src={`/audio/${selected.audioPath}`}
                    >
                      Your browser does not support the audio element.
                    </audio>
                    <p className="text-xs text-slate-400 mt-1 font-mono">{selected.audioPath}</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="card flex flex-col items-center justify-center h-48 text-slate-400 text-sm gap-3">
                <p>Select a run to view details</p>
                <button onClick={() => openNewRun()} className="btn-primary text-sm">+ New Run</button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
