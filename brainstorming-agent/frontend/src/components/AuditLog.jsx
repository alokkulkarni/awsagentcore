import { ChevronDown, ChevronRight, RefreshCw, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

const API = import.meta.env.VITE_API_URL || ''

const EVENT_CONFIG = {
  user_message: {
    label: 'User',
    bar: 'bg-slate-600',
    badge: 'border-slate-600 bg-slate-700 text-slate-200',
  },
  assistant_response: {
    label: 'Assistant',
    bar: 'bg-cyan-600',
    badge: 'border-cyan-600/40 bg-cyan-500/10 text-cyan-200',
  },
  tool_call: {
    label: 'Tool Call',
    bar: 'bg-violet-600',
    badge: 'border-violet-500/40 bg-violet-500/10 text-violet-200',
  },
  tool_result: {
    label: 'Tool Result',
    bar: 'bg-emerald-600',
    badge: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  },
  safety_analysis: {
    label: 'Safety Analysis',
    bar: 'bg-amber-500',
    badge: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  },
  content_blocked: {
    label: 'Blocked',
    bar: 'bg-rose-600',
    badge: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
  },
  error: {
    label: 'Error',
    bar: 'bg-rose-600',
    badge: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
  },
}

function formatTime(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

function tryParseJson(str) {
  if (!str) return null
  try {
    return JSON.parse(str)
  } catch {
    return null
  }
}

function JsonBlock({ value }) {
  const parsed = tryParseJson(value)
  if (!parsed) {
    return <pre className="whitespace-pre-wrap break-words text-xs text-slate-300">{value}</pre>
  }
  return (
    <pre className="whitespace-pre-wrap break-words text-xs text-slate-300">
      {JSON.stringify(parsed, null, 2)}
    </pre>
  )
}

function ScoreMeter({ label, score, lowGood = true }) {
  const pct = Math.min(Math.max(score, 0), 100)
  const color =
    lowGood
      ? pct < 30 ? 'bg-emerald-500' : pct < 60 ? 'bg-amber-400' : 'bg-rose-500'
      : pct > 70 ? 'bg-emerald-500' : pct > 40 ? 'bg-amber-400' : 'bg-rose-500'
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 flex-shrink-0 text-[10px] text-slate-400">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-slate-700">
        <div className={`h-1.5 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`w-8 text-right text-[10px] font-semibold ${
        lowGood
          ? pct < 30 ? 'text-emerald-400' : pct < 60 ? 'text-amber-400' : 'text-rose-400'
          : pct > 70 ? 'text-emerald-400' : pct > 40 ? 'text-amber-400' : 'text-rose-400'
      }`}>{pct}</span>
    </div>
  )
}

function SafetyDetail({ data }) {
  if (!data) return null
  const {
    drift_score = 0, bias_score = 0, overconfidence_score = 0, balance_score = 0,
    markers = [], cognitive_biases = [], new_topics = [],
  } = data
  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Drift</p>
        <ScoreMeter label="Topic drift" score={drift_score} lowGood />
        {new_topics.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {new_topics.map((t) => (
              <span key={t} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">{t}</span>
            ))}
          </div>
        )}
      </div>
      <div className="space-y-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Bias</p>
        <ScoreMeter label="Overall bias" score={bias_score} lowGood />
        <ScoreMeter label="Overconfidence" score={overconfidence_score} lowGood />
        <ScoreMeter label="Balance" score={balance_score} lowGood={false} />
        {markers.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {markers.map((m) => (
              <span key={m} className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[10px] text-amber-300">{m}</span>
            ))}
          </div>
        )}
        {cognitive_biases.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {cognitive_biases.map((b) => (
              <span key={b} className="rounded bg-rose-900/40 px-1.5 py-0.5 text-[10px] text-rose-300">
                {b.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

const CATEGORY_LABELS = {
  weapons: 'Weapons / Explosives',
  self_harm: 'Self-harm',
  illegal_drugs: 'Illegal Drug Synthesis',
  hate_speech: 'Hate Speech',
  csam: 'Child Safety (CSAM)',
  cybercrime: 'Cybercrime',
  prompt_injection: 'Prompt Injection',
}

function BlockedDetail({ entry }) {
  const detail = tryParseJson(entry.tool_output) || {}
  const trigger = tryParseJson(entry.tool_input) || {}
  const isOutputBlock = trigger.source === 'agent_output'
  const category = entry.tool_name || detail.category || 'unknown'
  const categoryLabel = CATEGORY_LABELS[category] || category.replace(/_/g, ' ')

  return (
    <div className="space-y-3">
      {/* Source + category */}
      <div className="flex flex-wrap gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
          isOutputBlock
            ? 'bg-orange-900/40 text-orange-300'
            : 'bg-rose-900/40 text-rose-300'
        }`}>
          {isOutputBlock ? 'Agent output blocked' : 'User input blocked'}
        </span>
        <span className="rounded-full bg-rose-800/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-rose-200">
          {categoryLabel}
        </span>
      </div>

      {/* Original blocked text */}
      <div>
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          {isOutputBlock ? 'Agent output (suppressed)' : 'Original message'}
        </p>
        <div className="rounded-lg border border-rose-500/20 bg-rose-950/30 p-2.5">
          <p className="text-xs leading-5 text-rose-200 break-words">{entry.content}</p>
        </div>
      </div>

      {/* What triggered it */}
      {trigger.matched_text ? (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Matched pattern</p>
          <div className="rounded-lg border border-amber-500/20 bg-amber-950/30 p-2.5">
            <code className="text-xs text-amber-300 break-all">{trigger.matched_text}</code>
          </div>
        </div>
      ) : null}

      {/* Reason */}
      {detail.reason ? (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Reason</p>
          <p className="text-xs text-slate-300">{detail.reason}</p>
        </div>
      ) : null}

      {/* Reply sent to user */}
      {detail.reply ? (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Reply sent to user</p>
          <div className="rounded-lg border border-slate-700 bg-slate-900 p-2.5">
            <p className="text-xs italic leading-5 text-slate-400">{detail.reply}</p>
          </div>
        </div>
      ) : null}

      {/* Rule regex */}
      {trigger.rule_pattern ? (
        <details className="group">
          <summary className="cursor-pointer text-[10px] text-slate-500 hover:text-slate-300 transition list-none flex items-center gap-1">
            <ChevronRight size={10} className="group-open:rotate-90 transition-transform" />
            Detection rule (regex)
          </summary>
          <div className="mt-1 rounded-lg border border-slate-700 bg-slate-950 p-2">
            <code className="text-[10px] text-slate-500 break-all">{trigger.rule_pattern}</code>
          </div>
        </details>
      ) : null}
    </div>
  )
}

function AuditEntry({ entry }) {
  const [expanded, setExpanded] = useState(false)
  const config = EVENT_CONFIG[entry.event_type] || {
    label: entry.event_type,
    bar: 'bg-slate-500',
    badge: 'border-slate-600 bg-slate-700 text-slate-300',
  }

  const safetyData = entry.event_type === 'safety_analysis' ? tryParseJson(entry.tool_output) : null
  const isSafety = entry.event_type === 'safety_analysis'
  const isBlocked = entry.event_type === 'content_blocked'

  const hasDetail =
    isSafety ||
    isBlocked ||
    (entry.event_type === 'tool_call' && entry.tool_input) ||
    (entry.event_type === 'tool_result' && entry.tool_output) ||
    (entry.event_type === 'assistant_response' && entry.content) ||
    (entry.event_type === 'error' && entry.content)

  const blockTrigger = isBlocked ? (tryParseJson(entry.tool_input) || {}) : null
  const blockDetail = isBlocked ? (tryParseJson(entry.tool_output) || {}) : null

  const previewText =
    isSafety
      ? entry.content
      : isBlocked
        ? `${blockTrigger?.source === 'agent_output' ? 'Agent output' : 'User input'} blocked — ${
            CATEGORY_LABELS[entry.tool_name] || entry.tool_name || 'unknown category'
          }: ${blockDetail?.reason || entry.content?.slice(0, 60) || ''}`
        : entry.event_type === 'user_message'
          ? entry.content
          : entry.event_type === 'assistant_response'
            ? entry.content?.slice(0, 120) + (entry.content?.length > 120 ? '…' : '')
            : entry.event_type === 'tool_call'
              ? `${entry.tool_name}()`
              : entry.event_type === 'tool_result'
                ? `${entry.tool_name} → ${entry.tool_output?.slice(0, 80) || ''}`
                : entry.content?.slice(0, 100) || ''

  return (
    <div className="group flex gap-3">
      <div className="relative flex flex-col items-center">
        <div className={`mt-1 h-3 w-3 flex-shrink-0 rounded-full ${config.bar}`} />
        <div className="flex-1 w-px bg-slate-800 group-last:hidden" />
      </div>

      <div className="mb-3 min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${config.badge}`}>
            {isBlocked ? <ShieldAlert size={10} className="inline mr-0.5" /> : isSafety ? <ShieldCheck size={10} className="inline mr-0.5" /> : null}
            {config.label}
          </span>
          {entry.tool_name && !isSafety && !isBlocked ? (
            <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
              {entry.tool_name}
            </span>
          ) : null}
          {isSafety && safetyData ? (
            <>
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                safetyData.drift_score < 30 ? 'bg-emerald-900/40 text-emerald-300' :
                safetyData.drift_score < 60 ? 'bg-amber-900/40 text-amber-300' : 'bg-rose-900/40 text-rose-300'
              }`}>
                Drift {safetyData.drift_score}
              </span>
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                safetyData.bias_score < 30 ? 'bg-emerald-900/40 text-emerald-300' :
                safetyData.bias_score < 60 ? 'bg-amber-900/40 text-amber-300' : 'bg-rose-900/40 text-rose-300'
              }`}>
                Bias {safetyData.bias_score}
              </span>
            </>
          ) : null}
          {entry.latency_ms > 0 && !isSafety ? (
            <span className="text-[10px] text-slate-500">{entry.latency_ms}ms</span>
          ) : null}
          <span className="ml-auto text-[10px] text-slate-600">{formatTime(entry.created_at)}</span>
        </div>

        <p className={`mt-1 text-xs leading-5 break-words ${isBlocked ? 'text-rose-300' : 'text-slate-400'}`}>
          {previewText}
        </p>

        {hasDetail ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1 flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 transition"
          >
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {expanded ? 'Hide detail' : 'Show detail'}
          </button>
        ) : null}

        {expanded && hasDetail ? (
          <div className="mt-2 rounded-lg border border-slate-700 bg-slate-900 p-3">
            {isSafety && safetyData ? (
              <SafetyDetail data={safetyData} />
            ) : isBlocked ? (
              <BlockedDetail entry={entry} />
            ) : entry.event_type === 'tool_call' && entry.tool_input ? (
              <>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Input</p>
                <JsonBlock value={entry.tool_input} />
              </>
            ) : entry.event_type === 'tool_result' && entry.tool_output ? (
              <>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Output</p>
                <JsonBlock value={entry.tool_output} />
              </>
            ) : (entry.event_type === 'assistant_response' || entry.event_type === 'error') && entry.content ? (
              <pre className="whitespace-pre-wrap break-words text-xs text-slate-300">{entry.content}</pre>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default function AuditLog({ session }) {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const scrollRef = useRef(null)

  const fetchLog = useCallback(async () => {
    if (!session?.id) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API}/sessions/${session.id}/audit?limit=500`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setEntries(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [session?.id])

  useEffect(() => {
    fetchLog()
  }, [fetchLog])

  // Refresh after each new assistant message
  useEffect(() => {
    const handler = () => setTimeout(fetchLog, 400)
    window.addEventListener('brainstorm-audit-refresh', handler)
    return () => window.removeEventListener('brainstorm-audit-refresh', handler)
  }, [fetchLog])

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries.length])

  return (
    <section className="panel-surface flex flex-col overflow-hidden" style={{ maxHeight: '80vh' }}>
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.28em] text-cyan-300/70">Session Audit</p>
          <h2 className="mt-0.5 text-sm font-semibold text-white">
            {entries.length ? `${entries.length} events` : 'No events yet'}
          </h2>
        </div>
        <button
          type="button"
          onClick={fetchLog}
          disabled={loading || !session?.id}
          className="rounded-xl border border-slate-700 bg-slate-800 p-2 text-slate-400 transition hover:text-white disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {!session?.id ? (
          <p className="text-center text-xs text-slate-500 pt-8">Select a session to view its audit log.</p>
        ) : error ? (
          <p className="text-xs text-rose-400">{error}</p>
        ) : !entries.length ? (
          <p className="text-center text-xs text-slate-500 pt-8">No audit events recorded yet.</p>
        ) : (
          entries.map((entry) => <AuditEntry key={entry.id} entry={entry} />)
        )}
        <div ref={scrollRef} />
      </div>
    </section>
  )
}
