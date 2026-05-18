import { Brain, ClipboardList, Database, Sparkles, Volume2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import AuditLog from './components/AuditLog'
import ChatPanel from './components/ChatPanel'
import MemoryBrowser from './components/MemoryBrowser'
import SessionManager from './components/SessionManager'

function getVoiceBadge(voiceState) {
  if (!voiceState.supported) {
    return { label: 'Voice unavailable', tone: 'bg-slate-800 text-slate-400 border-slate-700' }
  }
  if (voiceState.listening) {
    return { label: 'Listening', tone: 'bg-rose-500/10 text-rose-300 border-rose-500/30' }
  }
  if (voiceState.speaking) {
    return { label: 'Speaking', tone: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30' }
  }
  if (!voiceState.ttsEnabled) {
    return { label: 'Voice muted', tone: 'bg-slate-800 text-slate-300 border-slate-700' }
  }
  return { label: 'Voice ready', tone: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' }
}

export default function App() {
  const preferredSessionId = useMemo(() => new URLSearchParams(window.location.search).get('session'), [])
  const [currentSession, setCurrentSession] = useState(null)
  const [rightTab, setRightTab] = useState('memories')
  const [voiceState, setVoiceState] = useState({
    supported: true,
    listening: false,
    speaking: false,
    ttsEnabled: true,
  })

  useEffect(() => {
    if (!currentSession?.id) {
      return
    }
    const url = new URL(window.location.href)
    url.searchParams.set('session', currentSession.id)
    window.history.replaceState({}, '', url)
  }, [currentSession?.id])

  const voiceBadge = getVoiceBadge(voiceState)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center justify-between gap-4 px-4 py-4 lg:px-6">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-cyan-400/20 bg-cyan-400/10 text-cyan-300 shadow-lg shadow-cyan-500/10">
              <Brain size={22} />
            </div>
            <div>
              <p className="flex items-center gap-2 text-[11px] uppercase tracking-[0.35em] text-cyan-300/80">
                <Sparkles size={14} />
                Brainstorm Studio
              </p>
              <h1 className="text-xl font-semibold text-white">Brainstorm</h1>
              <p className="text-sm text-slate-400">
                {currentSession?.title || 'Create or select a session to start exploring ideas.'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${voiceBadge.tone}`}>
              <Volume2 size={14} />
              {voiceBadge.label}
            </div>
            {currentSession?.topics?.length ? (
              <div className="hidden max-w-xl flex-wrap gap-2 lg:flex">
                {currentSession.topics.slice(0, 5).map((topic) => (
                  <span key={topic} className="chip">
                    {topic}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-[1800px] grid-cols-1 gap-4 px-4 py-4 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)_340px] lg:px-6">
        <SessionManager
          currentSessionId={currentSession?.id}
          preferredSessionId={preferredSessionId}
          onSessionSelect={setCurrentSession}
        />

        <ChatPanel session={currentSession} onVoiceStateChange={setVoiceState} />

        <div className="flex flex-col gap-0">
          <div className="flex rounded-t-2xl border border-b-0 border-slate-800 bg-slate-900 overflow-hidden">
            <button
              type="button"
              onClick={() => setRightTab('memories')}
              className={`flex flex-1 items-center justify-center gap-2 px-3 py-2.5 text-xs font-medium transition ${
                rightTab === 'memories'
                  ? 'bg-slate-800 text-cyan-300'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Database size={13} />
              Memories
            </button>
            <button
              type="button"
              onClick={() => setRightTab('audit')}
              className={`flex flex-1 items-center justify-center gap-2 px-3 py-2.5 text-xs font-medium transition ${
                rightTab === 'audit'
                  ? 'bg-slate-800 text-cyan-300'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <ClipboardList size={13} />
              Audit
            </button>
          </div>
          {rightTab === 'memories' ? (
            <MemoryBrowser session={currentSession} />
          ) : (
            <AuditLog session={currentSession} />
          )}
        </div>
      </main>
    </div>
  )
}
