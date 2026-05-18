import { LoaderCircle, SendHorizontal, Sparkles, Wifi, WifiOff } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import VoiceControl from './VoiceControl'

function makeId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function renderInline(text) {
  // Split on **bold**, *italic*, and `code` spans
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).filter(Boolean)
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index} className="font-semibold text-white">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return <em key={index} className="italic text-slate-300">{part.slice(1, -1)}</em>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={index} className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-xs text-cyan-300">
          {part.slice(1, -1)}
        </code>
      )
    }
    return <Fragment key={index}>{part}</Fragment>
  })
}

const TABLE_ROW_RE = /^\s*\|/
const TABLE_SEP_RE = /^\s*\|?\s*[-:]+(\s*\|\s*[-:]+)+\s*\|?\s*$/

function parseTableRow(row) {
  return row.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim())
}

function renderRichText(text) {
  const lines = text.split('\n')
  const blocks = []
  let bullets = []
  let numbered = []
  let tableRows = []

  const flushBullets = () => {
    if (!bullets.length) return
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="list-disc space-y-1.5 pl-5 text-sm leading-7 text-slate-200">
        {bullets.map((item, i) => <li key={i}>{renderInline(item)}</li>)}
      </ul>,
    )
    bullets = []
  }

  const flushNumbered = () => {
    if (!numbered.length) return
    blocks.push(
      <ol key={`ol-${blocks.length}`} className="list-decimal space-y-1.5 pl-5 text-sm leading-7 text-slate-200">
        {numbered.map((item, i) => <li key={i}>{renderInline(item)}</li>)}
      </ol>,
    )
    numbered = []
  }

  const flushTable = () => {
    if (!tableRows.length) return
    const meaningful = tableRows.filter((r) => !TABLE_SEP_RE.test(r))
    if (!meaningful.length) { tableRows = []; return }
    const [header, ...body] = meaningful
    const headers = parseTableRow(header)
    blocks.push(
      <div key={`tbl-${blocks.length}`} className="overflow-x-auto rounded-xl border border-slate-700">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 bg-slate-800/60">
              {headers.map((h, i) => (
                <th key={i} className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-cyan-300">
                  {renderInline(h)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, ri) => (
              <tr key={ri} className="border-b border-slate-800 last:border-0 even:bg-slate-900/40">
                {parseTableRow(row).map((cell, ci) => (
                  <td key={ci} className="px-4 py-2.5 text-slate-200">{renderInline(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    )
    tableRows = []
  }

  const flushAll = () => { flushBullets(); flushNumbered(); flushTable() }

  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd()
    const trimmed = line.trim()

    // Table rows
    if (TABLE_ROW_RE.test(trimmed) || (tableRows.length && TABLE_SEP_RE.test(trimmed))) {
      flushBullets(); flushNumbered()
      tableRows.push(trimmed)
      return
    }
    if (tableRows.length) flushTable()

    if (!trimmed) { flushAll(); return }

    // Horizontal rule
    if (/^---+$/.test(trimmed)) {
      flushAll()
      blocks.push(<hr key={`hr-${blocks.length}`} className="border-slate-700/60" />)
      return
    }

    // H3
    if (trimmed.startsWith('### ')) {
      flushAll()
      blocks.push(
        <h3 key={`h3-${blocks.length}`} className="text-sm font-semibold text-cyan-200">
          {renderInline(trimmed.slice(4))}
        </h3>,
      )
      return
    }

    // H2
    if (trimmed.startsWith('## ')) {
      flushAll()
      blocks.push(
        <h2 key={`h2-${blocks.length}`} className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300/80 pt-1">
          {renderInline(trimmed.slice(3))}
        </h2>,
      )
      return
    }

    // H1
    if (trimmed.startsWith('# ')) {
      flushAll()
      blocks.push(
        <h1 key={`h1-${blocks.length}`} className="text-base font-semibold text-white">
          {renderInline(trimmed.slice(2))}
        </h1>,
      )
      return
    }

    // Numbered list
    if (/^\d+\.\s+/.test(trimmed)) {
      flushBullets(); flushTable()
      numbered.push(trimmed.replace(/^\d+\.\s+/, ''))
      return
    }

    // Bullet list
    if (/^[-*]\s+/.test(trimmed)) {
      flushNumbered(); flushTable()
      bullets.push(trimmed.replace(/^[-*]\s+/, ''))
      return
    }

    // Paragraph
    flushAll()
    blocks.push(
      <p key={`p-${blocks.length}`} className="text-sm leading-7 text-slate-200">
        {renderInline(line)}
      </p>,
    )
  })

  flushAll()

  if (!blocks.length) return <p className="text-sm leading-7 text-slate-200">{text}</p>
  return <div className="space-y-2">{blocks}</div>
}

const TOOL_LABELS = {
  save_memory: 'Saving memory...',
  search_memories: 'Searching memories...',
  get_memories_by_topic: 'Retrieving topic insights...',
  link_ideas: 'Linking ideas...',
  get_related_ideas: 'Finding related ideas...',
  list_sessions: 'Loading past sessions...',
  get_session_insights: 'Pulling session insights...',
}

const STARTER_PROMPTS = [
  'Explore AI-native products for wealth management.',
  'Stress-test a go-to-market strategy for a B2B healthtech startup.',
  'Map second-order effects of quantum breakthroughs on cybersecurity.',
]

export default function ChatPanel({ session, onVoiceStateChange }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [thinking, setThinking] = useState(false)
  const [socketStatus, setSocketStatus] = useState('idle')
  const [toolState, setToolState] = useState({})
  const [lastAssistantMessage, setLastAssistantMessage] = useState('')
  const [error, setError] = useState('')
  const [safetyIndicator, setSafetyIndicator] = useState(null)
  const socketRef = useRef(null)
  const streamingMessageId = useRef(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)

  const storageKey = useMemo(
    () => (session?.id ? `brainstorm.chat.${session.id}` : null),
    [session?.id],
  )

  useEffect(() => {
    if (!storageKey) {
      setMessages([])
      setLastAssistantMessage('')
      return
    }
    const saved = window.localStorage.getItem(storageKey)
    if (!saved) {
      setMessages([])
      return
    }
    try {
      setMessages(JSON.parse(saved))
    } catch {
      setMessages([])
    }
  }, [storageKey])

  useEffect(() => {
    if (!storageKey) {
      return
    }
    window.localStorage.setItem(storageKey, JSON.stringify(messages.slice(-60)))
  }, [messages, storageKey])

  useEffect(() => {
    if (!session?.id) {
      setSocketStatus('idle')
      setThinking(false)
      setToolState({})
      setSafetyIndicator(null)
      streamingMessageId.current = null
      return undefined
    }

    let alive = true
    let retryCount = 0
    let retryTimer = null

    const connect = () => {
      if (!alive) return

      setError('')
      setSocketStatus('connecting')

      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const socket = new WebSocket(`${protocol}://${window.location.host}/ws/${session.id}`)
      socketRef.current = socket

      socket.onopen = () => {
        if (!alive) { socket.close(); return }
        setSocketStatus('open')
        retryCount = 0
      }

      socket.onclose = (evt) => {
        if (!alive) return
        socketRef.current = null
        // Clean close (user switched session) — don't retry
        if (evt.code === 1000) {
          setSocketStatus('closed')
          return
        }
        // Unexpected close — auto-reconnect with backoff
        const delay = Math.min(1000 * 2 ** retryCount, 16000)
        retryCount += 1
        setSocketStatus('connecting')
        retryTimer = window.setTimeout(connect, delay)
      }

      socket.onerror = () => {
        if (!alive) return
        setSocketStatus('error')
      }

      socket.onmessage = (event) => {
        if (!alive) return
        const data = JSON.parse(event.data)

        // Server keepalive ping — ignore silently
        if (data.type === 'ping') return

      if (data.type === 'token') {
        setThinking(false)
        setMessages((previous) => {
          const messageId = streamingMessageId.current || makeId()
          streamingMessageId.current = messageId
          const existingIndex = previous.findIndex((message) => message.id === messageId)
          if (existingIndex === -1) {
            return [
              ...previous,
              { id: messageId, role: 'assistant', content: data.content, createdAt: new Date().toISOString() },
            ]
          }
          const next = [...previous]
          next[existingIndex] = {
            ...next[existingIndex],
            content: `${next[existingIndex].content || ''}${data.content}`,
          }
          return next
        })
      }

      if (data.type === 'done') {
        setThinking(false)
        setMessages((previous) => {
          const messageId = streamingMessageId.current || makeId()
          const existingIndex = previous.findIndex((message) => message.id === messageId)
          if (existingIndex === -1) {
            return [
              ...previous,
              { id: messageId, role: 'assistant', content: data.content, createdAt: new Date().toISOString() },
            ]
          }
          const next = [...previous]
          next[existingIndex] = { ...next[existingIndex], content: data.content }
          return next
        })
        streamingMessageId.current = null
        setLastAssistantMessage(data.content)
        window.dispatchEvent(new CustomEvent('brainstorm-audit-refresh'))
      }

      if (data.type === 'tool') {
        setToolState((previous) => ({ ...previous, [data.name]: data }))
        if (data.status !== 'running') {
          window.setTimeout(() => {
            setToolState((previous) => {
              const next = { ...previous }
              delete next[data.name]
              return next
            })
          }, 1600)
        }
      }

      if (data.type === 'safety_blocked') {
        setThinking(false)
        streamingMessageId.current = null
        const blockedId = makeId()
        setMessages((previous) => [
          ...previous.filter((m) => m.content !== ''),
          {
            id: blockedId,
            role: 'assistant',
            content: data.reply || 'That request was blocked by the content safety filter.',
            blocked: true,
            category: data.category,
            createdAt: new Date().toISOString(),
          },
        ])
        window.dispatchEvent(new CustomEvent('brainstorm-audit-refresh'))
      }

      if (data.type === 'safety_analysis') {
        setSafetyIndicator({ drift: data.drift_score ?? 0, bias: data.bias_score ?? 0 })
        window.dispatchEvent(new CustomEvent('brainstorm-audit-refresh'))
      }

      if (data.type === 'memory_saved') {
        window.dispatchEvent(new CustomEvent('brainstorm-memory-saved', { detail: data.memory }))
      }

      if (data.type === 'error') {
        streamingMessageId.current = null
        setThinking(false)
        setError(data.content)
      }
      }
    }

    // Reset transient state for the new session before connecting
    setThinking(false)
    setToolState({})
    setSafetyIndicator(null)
    streamingMessageId.current = null

    connect()

    return () => {
      alive = false
      if (retryTimer) window.clearTimeout(retryTimer)
      const s = socketRef.current
      if (s) {
        s.onopen = null
        s.onclose = null
        s.onerror = null
        s.onmessage = null
        s.close(1000)
        socketRef.current = null
      }
    }
  }, [session?.id])

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = '0px'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`
    }
  }, [draft])

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, thinking, toolState])

  const sendMessage = (content = draft) => {
    const clean = content.trim()
    if (!clean || !session?.id) {
      return
    }
    const ws = socketRef.current
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      setError('Not connected. Select the session again to reconnect.')
      return
    }

    const userMessage = {
      id: makeId(),
      role: 'user',
      content: clean,
      createdAt: new Date().toISOString(),
    }
    const assistantId = makeId()
    streamingMessageId.current = assistantId

    setMessages((previous) => [
      ...previous,
      userMessage,
      { id: assistantId, role: 'assistant', content: '', createdAt: new Date().toISOString() },
    ])
    setThinking(true)
    setDraft('')
    setError('')

    const payload = JSON.stringify({ type: 'message', content: clean })
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(payload)
    } else {
      // Still connecting — send as soon as the socket opens
      ws.addEventListener('open', () => ws.send(payload), { once: true })
    }
  }

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendMessage()
      return
    }
    if (event.key === 'Enter' && event.ctrlKey) {
      event.preventDefault()
      sendMessage()
    }
  }

  const activeTools = Object.values(toolState)

  return (
    <section className="panel-surface flex min-h-[75vh] flex-col overflow-hidden">
      <div className="border-b border-slate-800 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.28em] text-cyan-300/80">Conversation</p>
            <h2 className="mt-1 text-lg font-semibold text-white">
              {session?.title || 'Select a session to start chatting'}
            </h2>
          </div>

          <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
            socketStatus === 'open'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
              : socketStatus === 'connecting'
                ? 'border-amber-500/30 bg-amber-500/10 text-amber-200'
                : 'border-slate-700 bg-slate-800 text-slate-300'
          }`}>
            {socketStatus === 'open'
              ? <Wifi size={14} />
              : socketStatus === 'connecting'
                ? <LoaderCircle size={14} className="animate-spin" />
                : <WifiOff size={14} />}
            {socketStatus === 'open' ? 'Live' : socketStatus === 'connecting' ? 'Reconnecting…' : 'Offline'}
          </div>

          {safetyIndicator ? (
            <div className="flex items-center gap-2 rounded-full border border-slate-700 bg-slate-800/80 px-3 py-1.5">
              <span className={`text-[10px] font-medium ${
                safetyIndicator.drift < 30 ? 'text-emerald-400' :
                safetyIndicator.drift < 60 ? 'text-amber-400' : 'text-rose-400'
              }`}>Drift {safetyIndicator.drift}</span>
              <span className="text-slate-600">·</span>
              <span className={`text-[10px] font-medium ${
                safetyIndicator.bias < 30 ? 'text-emerald-400' :
                safetyIndicator.bias < 60 ? 'text-amber-400' : 'text-rose-400'
              }`}>Bias {safetyIndicator.bias}</span>
            </div>
          ) : null}
        </div>

        <div className="mt-4">
          <VoiceControl onTranscript={sendMessage} lastAssistantMessage={lastAssistantMessage} onVoiceStateChange={onVoiceStateChange} />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-5">
        {!session?.id ? (
          <div className="flex h-full min-h-[420px] items-center justify-center">
            <div className="max-w-xl rounded-3xl border border-dashed border-slate-700 bg-slate-950/50 px-8 py-10 text-center">
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-cyan-400/20 bg-cyan-400/10 text-cyan-300">
                <Sparkles size={26} />
              </div>
              <h3 className="mt-5 text-2xl font-semibold text-white">Open a brainstorming lane</h3>
              <p className="mt-3 text-sm leading-7 text-slate-400">
                Create a session, choose a theme, then use chat or voice to unpack opportunities, risks, and strategic moves.
              </p>
            </div>
          </div>
        ) : (
          <>
            {!messages.length ? (
              <div className="rounded-3xl border border-slate-800 bg-slate-950/60 p-6">
                <p className="text-sm font-medium text-slate-200">Kick off with a prompt:</p>
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  {STARTER_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => sendMessage(prompt)}
                      className="rounded-2xl border border-slate-800 bg-slate-900/80 p-4 text-left text-sm text-slate-300 transition hover:border-cyan-400/30 hover:bg-slate-800"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="mt-4 space-y-4">
              {messages.map((message) => {
                const isUser = message.role === 'user'
                const isBlocked = message.blocked === true
                return (
                  <div key={message.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[90%] rounded-3xl border px-4 py-3 shadow-lg ${
                      isUser
                        ? 'border-slate-600 bg-slate-700 text-slate-100'
                        : isBlocked
                          ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
                          : 'border-slate-800 bg-slate-900 text-slate-100'
                    }`}>
                      {isBlocked ? (
                        <p className="text-sm leading-6">{message.content}</p>
                      ) : message.content ? (
                        renderRichText(message.content)
                      ) : thinking && !isUser ? (
                        <div className="flex items-center gap-2 text-sm text-slate-400">
                          <LoaderCircle size={16} className="animate-spin" />
                          Thinking...
                        </div>
                      ) : null}
                    </div>
                  </div>
                )
              })}
            </div>

            {activeTools.length ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {activeTools.map((tool) => (
                  <span
                    key={tool.name}
                    className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
                      tool.status === 'error'
                        ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
                        : tool.status === 'done'
                          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
                          : 'border-cyan-400/30 bg-cyan-400/10 text-cyan-100'
                    }`}
                  >
                    {tool.status === 'running' ? <LoaderCircle size={12} className="animate-spin" /> : null}
                    {TOOL_LABELS[tool.name] || tool.name}
                  </span>
                ))}
              </div>
            ) : null}

            {error ? <p className="mt-4 text-sm text-rose-300">{error}</p> : null}
            <div ref={scrollRef} />
          </>
        )}
      </div>

      <div className="border-t border-slate-800 px-5 py-4">
        <div className="rounded-3xl border border-slate-800 bg-slate-950/80 p-3">
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={session?.id ? 'Ask a strategic question, explore a domain, or challenge an assumption...' : 'Create a session first...'}
            disabled={!session?.id}
            rows={1}
            className="max-h-[180px] min-h-[56px] w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-500 disabled:cursor-not-allowed"
          />
          <div className="mt-3 flex items-center justify-between gap-3 border-t border-slate-800 pt-3">
            <p className="text-xs text-slate-500">Press Enter to send · Shift+Enter for a new line</p>
            <button
              type="button"
              onClick={() => sendMessage()}
              disabled={!session?.id || !draft.trim()}
              className="inline-flex items-center gap-2 rounded-2xl bg-cyan-400 px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              <SendHorizontal size={16} />
              Send
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
