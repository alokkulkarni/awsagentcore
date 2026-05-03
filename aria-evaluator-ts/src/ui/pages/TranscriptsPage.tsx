// src/ui/pages/TranscriptsPage.tsx
import React, { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api.js';
import type { Transcript } from '../../types/transcript.js';

interface TranscriptFile {
  filename: string;
  size: number;
  modifiedAt: string;
}

export function TranscriptsPage({ initialFilename }: { initialFilename?: string }) {
  const [files, setFiles] = useState<TranscriptFile[]>([]);
  const [selected, setSelected] = useState<Transcript | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoLoadedInitial, setAutoLoadedInitial] = useState(false);

  useEffect(() => {
    apiFetch('/api/transcripts')
      .then((d: { transcripts: TranscriptFile[] }) => setFiles(d.transcripts ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function loadTranscript(filename: string) {
    const t = await apiFetch(`/api/transcripts/${filename}`) as Transcript;
    setSelected(t);
  }

  useEffect(() => {
    if (loading || autoLoadedInitial) return;
    if (!initialFilename) {
      setAutoLoadedInitial(true);
      return;
    }
    const exists = files.some((f) => f.filename === initialFilename);
    if (!exists) {
      setAutoLoadedInitial(true);
      return;
    }
    void loadTranscript(initialFilename)
      .catch(() => {})
      .finally(() => setAutoLoadedInitial(true));
  }, [loading, autoLoadedInitial, initialFilename, files]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Transcripts</h2>
        <p className="text-slate-500 mt-1">{files.length} saved transcript(s)</p>
      </div>

      <div className="grid md:grid-cols-5 gap-4">
        {/* ── File List ── */}
        <div className="md:col-span-2 space-y-2 max-h-[70vh] overflow-y-auto">
          {loading ? (
            <div className="text-slate-400 text-sm">Loading…</div>
          ) : files.length === 0 ? (
            <div className="card text-slate-400 text-sm">No transcripts yet.</div>
          ) : (
            files.map((f) => (
              <div key={f.filename} onClick={() => loadTranscript(f.filename)}
                className={`card cursor-pointer transition-all text-sm ${
                  selected?.id && f.filename.includes(selected.id.slice(0, 8))
                    ? 'ring-2 ring-[#0D2A66]' : 'hover:shadow-md'
                }`}>
                <p className="font-medium truncate">{f.filename.replace('.json', '').replace(/_/g, ' ')}</p>
                <p className="text-xs text-slate-400 mt-0.5">{new Date(f.modifiedAt).toLocaleString()}</p>
              </div>
            ))
          )}
        </div>

        {/* ── Transcript Viewer ── */}
        <div className="md:col-span-3">
          {selected ? (
            <div className="card space-y-4">
              <div>
                <h3 className="font-bold text-lg">{selected.scenarioName}</h3>
                <div className="flex gap-2 mt-1">
                  <span className={selected.channel === 'voice' ? 'badge-voice' : 'badge-chat'}>
                    {selected.channel}
                  </span>
                  <span className="text-xs text-slate-400">{selected.startedAt?.slice(0, 16).replace('T', ' ')}</span>
                  {selected.error && <span className="badge-fail">error</span>}
                </div>
              </div>

              {selected.error && (
                <div className="bg-red-50 text-red-700 rounded p-3 text-sm">⚠ {selected.error}</div>
              )}

              <div className="space-y-3 max-h-[55vh] overflow-y-auto">
                {selected.turns.map((t) => (
                  <div key={t.index} className={`flex gap-3 ${t.role === 'agent' ? 'flex-row-reverse' : ''}`}>
                    <div className="text-xl flex-shrink-0">{t.role === 'customer' ? '👤' : '🤖'}</div>
                    <div className={`rounded-xl px-4 py-3 text-sm max-w-[78%] leading-relaxed ${
                      t.role === 'customer'
                        ? 'bg-[#0D2A66] text-white'
                        : 'bg-slate-100 text-slate-900'
                    }`}>
                      {t.content}
                      {t.durationMs && (
                        <p className="text-xs mt-1.5 opacity-60">{(t.durationMs / 1000).toFixed(1)}s response</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="card flex items-center justify-center h-48 text-slate-400 text-sm">
              Select a transcript to view
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
