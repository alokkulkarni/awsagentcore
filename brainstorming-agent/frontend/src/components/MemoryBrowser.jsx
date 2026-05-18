import { BookOpenText, Link2, RefreshCcw, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import TopicCloud from './TopicCloud'

function snippet(text) {
  if (text.length <= 180) {
    return text
  }
  return `${text.slice(0, 177)}...`
}

async function fetchJson(url) {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error('Request failed')
  }
  return response.json()
}

export default function MemoryBrowser({ session }) {
  const [memories, setMemories] = useState([])
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [activeTopic, setActiveTopic] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [linksByMemory, setLinksByMemory] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadMemories = async () => {
    if (!session?.id) {
      setMemories([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await fetchJson(`/api/sessions/${session.id}/memories`)
      setMemories(data)
    } catch (fetchError) {
      setError(fetchError.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setActiveTopic(null)
    setExpandedId(null)
    setLinksByMemory({})
    loadMemories()
  }, [session?.id])

  useEffect(() => {
    const handler = (event) => {
      const memory = event.detail
      if (!memory?.id || memory.session_id !== session?.id) {
        return
      }
      setMemories((previous) => [memory, ...previous.filter((item) => item.id !== memory.id)])
    }

    window.addEventListener('brainstorm-memory-saved', handler)
    return () => window.removeEventListener('brainstorm-memory-saved', handler)
  }, [session?.id])

  useEffect(() => {
    if (!search.trim()) {
      setSearchResults([])
      return undefined
    }

    const timeoutId = window.setTimeout(async () => {
      try {
        const data = await fetchJson(`/api/memories/search?q=${encodeURIComponent(search.trim())}`)
        setSearchResults(data)
      } catch {
        setSearchResults([])
      }
    }, 250)

    return () => window.clearTimeout(timeoutId)
  }, [search])

  const allTopics = useMemo(() => {
    const sourceTopics = new Set(session?.topics || [])
    memories.forEach((memory) => {
      ;(memory.topics || []).forEach((topic) => sourceTopics.add(topic))
    })
    return Array.from(sourceTopics)
  }, [memories, session?.topics])

  const visibleMemories = useMemo(() => {
    const source = search.trim() ? searchResults : memories
    if (!activeTopic) {
      return source
    }
    return source.filter((memory) => (memory.topics || []).includes(activeTopic))
  }, [activeTopic, memories, search, searchResults])

  const toggleExpanded = async (memoryId) => {
    setExpandedId((previous) => (previous === memoryId ? null : memoryId))
    if (linksByMemory[memoryId]) {
      return
    }
    try {
      const links = await fetchJson(`/api/memories/${memoryId}/links`)
      setLinksByMemory((previous) => ({ ...previous, [memoryId]: links }))
    } catch {
      setLinksByMemory((previous) => ({ ...previous, [memoryId]: [] }))
    }
  }

  return (
    <aside className="panel-surface flex min-h-[320px] flex-col overflow-hidden">
      <div className="border-b border-slate-800 px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.28em] text-indigo-300/80">Memory Browser</p>
            <h2 className="mt-1 text-lg font-semibold text-white">Saved insights</h2>
          </div>
          <button
            type="button"
            onClick={loadMemories}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300 transition hover:bg-slate-700 hover:text-white"
          >
            <RefreshCcw size={14} />
            Refresh
          </button>
        </div>

        <div className="mt-4 flex items-center gap-2 rounded-2xl border border-slate-800 bg-slate-950/80 px-3 py-3">
          <Search size={16} className="text-slate-500" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search memories, themes, tags..."
            className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
          />
        </div>
      </div>

      <div className="space-y-5 overflow-y-auto px-4 py-4">
        <section>
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-200">
            <BookOpenText size={16} className="text-cyan-300" />
            Recent Memories
          </div>
          {!session?.id ? (
            <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/40 px-4 py-5 text-sm text-slate-500">
              Select a session to browse its insights.
            </div>
          ) : null}
          {loading ? <p className="text-sm text-slate-500">Loading memories...</p> : null}
          {error ? <p className="text-sm text-rose-300">{error}</p> : null}

          <div className="space-y-3">
            {visibleMemories.slice(0, search.trim() ? 20 : 10).map((memory) => {
              const expanded = expandedId === memory.id
              const links = linksByMemory[memory.id] || []
              return (
                <button
                  key={memory.id}
                  type="button"
                  onClick={() => toggleExpanded(memory.id)}
                  className="w-full rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-left transition hover:border-slate-700 hover:bg-slate-900"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-white">{memory.title}</p>
                      <p className="mt-2 text-sm leading-6 text-slate-300">{expanded ? memory.content : snippet(memory.content)}</p>
                    </div>
                    <span className="inline-flex items-center gap-1 rounded-full bg-slate-800 px-2 py-1 text-[11px] font-medium text-slate-300">
                      <Link2 size={12} />
                      {memory.linked_count || links.length || 0}
                    </span>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    {(memory.topics || []).map((topic) => (
                      <span key={topic} className="chip">
                        {topic}
                      </span>
                    ))}
                  </div>

                  {expanded ? (
                    <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/80 p-3">
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Related ideas</p>
                      <div className="mt-3 space-y-2">
                        {links.length ? (
                          links.map((link) => (
                            <div key={link.id} className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-sm text-slate-300">
                              <p className="font-medium text-slate-100">{link.related_title}</p>
                              <p className="mt-1 text-xs uppercase tracking-[0.2em] text-indigo-300">{link.relationship}</p>
                            </div>
                          ))
                        ) : (
                          <p className="text-sm text-slate-500">No linked ideas yet.</p>
                        )}
                      </div>
                    </div>
                  ) : null}
                </button>
              )
            })}
            {!loading && session?.id && !visibleMemories.length ? (
              <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/40 px-4 py-5 text-sm text-slate-500">
                No memories match the current filter.
              </div>
            ) : null}
          </div>
        </section>

        <section>
          <p className="mb-3 text-sm font-medium text-slate-200">Topics</p>
          <TopicCloud topics={allTopics} activeTopic={activeTopic} onSelect={setActiveTopic} />
        </section>
      </div>
    </aside>
  )
}
