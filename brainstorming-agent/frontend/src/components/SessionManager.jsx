import { CalendarDays, Lightbulb, Plus, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

function formatDate(value) {
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export default function SessionManager({ currentSessionId, preferredSessionId, onSessionSelect }) {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [title, setTitle] = useState('')
  const [topicInput, setTopicInput] = useState('')
  const [topics, setTopics] = useState([])
  const [saving, setSaving] = useState(false)

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === currentSessionId) || null,
    [currentSessionId, sessions],
  )

  const loadSessions = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/sessions')
      if (!response.ok) {
        throw new Error('Unable to load sessions')
      }
      const data = await response.json()
      setSessions(data)

      const selected =
        data.find((session) => session.id === currentSessionId) ||
        data.find((session) => session.id === preferredSessionId) ||
        data[0]

      if (selected && selected.id !== currentSessionId) {
        onSessionSelect(selected)
      }
    } catch (fetchError) {
      setError(fetchError.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSessions()
  }, [])

  const addTopic = () => {
    const cleanTopic = topicInput.trim()
    if (!cleanTopic || topics.includes(cleanTopic)) {
      setTopicInput('')
      return
    }
    setTopics((previous) => [...previous, cleanTopic])
    setTopicInput('')
  }

  const handleTopicKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      addTopic()
    }
  }

  const createSession = async () => {
    if (!title.trim()) {
      return
    }

    setSaving(true)
    setError('')
    try {
      const response = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), topics }),
      })

      if (!response.ok) {
        throw new Error('Unable to create session')
      }

      const session = await response.json()
      const nextSessions = [session, ...sessions]
      setSessions(nextSessions)
      onSessionSelect(session)
      setShowModal(false)
      setTitle('')
      setTopics([])
      setTopicInput('')
    } catch (createError) {
      setError(createError.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <aside className="panel-surface flex min-h-[320px] flex-col overflow-hidden">
      <div className="border-b border-slate-800 px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.28em] text-cyan-300/80">Sessions</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Strategic threads</h2>
          </div>
          <button
            type="button"
            onClick={() => setShowModal(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-cyan-400/30 bg-cyan-400/10 px-3 py-2 text-sm font-medium text-cyan-200 transition hover:bg-cyan-400/20"
          >
            <Plus size={16} />
            New Session
          </button>
        </div>

        <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
          <p className="text-xs text-slate-400">Current focus</p>
          <p className="mt-1 text-sm font-medium text-slate-100">
            {activeSession?.title || 'No session selected'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {activeSession?.topics?.length ? (
              activeSession.topics.map((topic) => (
                <span key={topic} className="chip">
                  {topic}
                </span>
              ))
            ) : (
              <span className="text-xs text-slate-500">Create a session to organise themes and memories.</span>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {loading ? (
          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-5 text-sm text-slate-400">
            Loading sessions...
          </div>
        ) : null}

        {!loading && !sessions.length ? (
          <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/40 px-4 py-6 text-center text-sm text-slate-400">
            No brainstorming sessions yet.
          </div>
        ) : null}

        <div className="space-y-2">
          {sessions.map((session) => {
            const active = session.id === currentSessionId
            return (
              <button
                key={session.id}
                type="button"
                onClick={() => onSessionSelect(session)}
                className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                  active
                    ? 'border-cyan-400/40 bg-cyan-400/10 text-white shadow-lg shadow-cyan-500/5'
                    : 'border-slate-800 bg-slate-900/60 text-slate-300 hover:border-slate-700 hover:bg-slate-800/70'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{session.title}</p>
                    <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                      <CalendarDays size={12} />
                      {formatDate(session.updated_at)}
                    </div>
                  </div>
                  <span className="rounded-full bg-slate-800 px-2 py-1 text-[10px] font-semibold text-slate-300">
                    {session.memory_count || 0}
                  </span>
                </div>

                {session.topics?.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {session.topics.slice(0, 4).map((topic) => (
                      <span key={topic} className="chip">
                        {topic}
                      </span>
                    ))}
                  </div>
                ) : null}
              </button>
            )
          })}
        </div>
      </div>

      {error ? <p className="border-t border-slate-800 px-4 py-3 text-sm text-rose-300">{error}</p> : null}

      {showModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-3xl border border-slate-800 bg-slate-900 p-5 shadow-2xl shadow-slate-950/50">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.28em] text-cyan-300/80">New Session</p>
                <h3 className="mt-1 text-lg font-semibold text-white">Start Brainstorming</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="rounded-full border border-slate-700 p-2 text-slate-400 transition hover:text-slate-200"
              >
                <X size={16} />
              </button>
            </div>

            <label className="mt-5 block text-sm text-slate-300">
              Session title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="AI x fintech wedge exploration"
                className="mt-2 w-full rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-cyan-400/60"
              />
            </label>

            <label className="mt-4 block text-sm text-slate-300">
              Topics
              <div className="mt-2 rounded-2xl border border-slate-700 bg-slate-950/80 px-3 py-3">
                <div className="flex flex-wrap gap-2">
                  {topics.map((topic) => (
                    <span key={topic} className="inline-flex items-center gap-1 rounded-full bg-indigo-500/15 px-2.5 py-1 text-xs font-medium text-indigo-200">
                      <Lightbulb size={12} />
                      {topic}
                      <button type="button" onClick={() => setTopics((previous) => previous.filter((item) => item !== topic))}>
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                </div>
                <input
                  value={topicInput}
                  onChange={(event) => setTopicInput(event.target.value)}
                  onKeyDown={handleTopicKeyDown}
                  onBlur={addTopic}
                  placeholder="Type a topic and press Enter"
                  className="mt-3 w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
                />
              </div>
            </label>

            <button
              type="button"
              onClick={createSession}
              disabled={saving || !title.trim()}
              className="mt-5 inline-flex w-full items-center justify-center rounded-2xl bg-cyan-400 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {saving ? 'Creating...' : 'Start Brainstorming'}
            </button>
          </div>
        </div>
      ) : null}
    </aside>
  )
}
