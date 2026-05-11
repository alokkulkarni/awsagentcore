import { useEffect, useMemo, useRef, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Bot, Sparkles, Trash2, SendHorizonal, PlusCircle, MessageSquareText, Clock } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';

// "AVG_HANDLE_TIME" → "Avg Handle Time"
const METRIC_LABELS = {
  CONTACTS_HANDLED: 'Contacts Handled',
  CONTACTS_ABANDONED: 'Contacts Abandoned',
  AVG_HANDLE_TIME: 'Avg Handle Time',
  AVG_QUEUE_ANSWER_TIME: 'Avg Queue Answer Time',
  AVG_HOLD_TIME: 'Avg Hold Time',
  AVG_TALK_TIME: 'Avg Talk Time',
  AVG_INTERACTION_TIME: 'Avg Interaction Time',
  SERVICE_LEVEL: 'Service Level %',
  CONTACTS_QUEUED: 'Contacts Queued',
  CONTACTS_TRANSFERRED_OUT: 'Transferred Out',
  AGENT_OCCUPANCY: 'Agent Occupancy %',
};
function fmtMetricName(key) {
  return METRIC_LABELS[key] ?? key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Seconds → "2m 39s"
function fmtSeconds(v) {
  if (v == null || isNaN(v)) return '0s';
  const s = Math.round(v);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m === 0) return `${sec}s`;
  return `${m}m ${sec < 10 ? '0' + sec : sec}s`;
}

// "08:00" → "8am–9am", "14:00" → "2pm–3pm"; everything else unchanged
function fmtXLabel(label) {
  const m = String(label).match(/^(\d{1,2}):(\d{2})$/);
  if (m) {
    const h = parseInt(m[1], 10);
    const nextH = (h + 1) % 24;
    const fmt = (n) => {
      if (n === 0) return '12am';
      if (n === 12) return '12pm';
      return n < 12 ? `${n}am` : `${n - 12}pm`;
    };
    return `${fmt(h)}–${fmt(nextH)}`;
  }
  return label;
}

// ── Inline chart rendered from ```chart-json ... ``` blocks in assistant messages ──
function MetricsChart({ raw }) {
  const data = useMemo(() => {
    try { return JSON.parse(raw); } catch { return null; }
  }, [raw]);

  if (!data?.series?.length || !data?.data?.length) return null;

  const COLOURS = ['#10b981', '#2563eb', '#f59e0b', '#ef4444', '#8b5cf6'];

  // Split series: time-based (seconds) vs counts
  const timeSeries = data.series.filter(s => /time|duration|hold/i.test(s));
  const countSeries = data.series.filter(s => !/time|duration|hold/i.test(s));
  const hasTimeSeries = timeSeries.length > 0;

  return (
    <div className="mt-4 rounded-2xl border border-slate-700 bg-slate-800/60 p-4">
      {data.title && <p className="mb-3 text-sm font-semibold text-slate-200">{data.title}</p>}
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data.data} margin={{ top: 4, right: hasTimeSeries ? 52 : 8, left: 0, bottom: 36 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis
            dataKey="label"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            angle={-35}
            textAnchor="end"
            interval={0}
            tickFormatter={fmtXLabel}
          />
          {/* Left axis — contact counts */}
          <YAxis
            yAxisId="count"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            allowDecimals={false}
            width={32}
          />
          {/* Right axis — durations rendered as "Xm Ys" */}
          {hasTimeSeries && (
            <YAxis
              yAxisId="time"
              orientation="right"
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              tickFormatter={fmtSeconds}
              width={48}
              label={{ value: 'Handle time', angle: 90, position: 'insideRight', offset: 14, fill: '#64748b', fontSize: 10 }}
            />
          )}
          <Tooltip
            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
            labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
            itemStyle={{ color: '#94a3b8' }}
            labelFormatter={fmtXLabel}
            formatter={(value, name) =>
              /time|duration|hold/i.test(name) ? [fmtSeconds(value), name] : [value, name]
            }
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: '#94a3b8', paddingTop: 12 }}
            formatter={(value) => fmtMetricName(value)}
          />
          {countSeries.map((key, i) => (
            <Bar key={key} yAxisId="count" dataKey={key} name={fmtMetricName(key)} fill={COLOURS[i % COLOURS.length]} radius={[3, 3, 0, 0]} />
          ))}
          {timeSeries.map((key, i) => (
            <Bar key={key} yAxisId="time" dataKey={key} name={fmtMetricName(key)} fill={COLOURS[(countSeries.length + i) % COLOURS.length]} radius={[3, 3, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// Split assistant message into text parts and chart-json blocks
function AssistantMessage({ content }) {
  const parts = useMemo(() => {
    const segments = [];
    const re = /```chart-json\n([\s\S]*?)```/g;
    let last = 0;
    let match;
    while ((match = re.exec(content)) !== null) {
      if (match.index > last) segments.push({ type: 'md', text: content.slice(last, match.index) });
      segments.push({ type: 'chart', raw: match[1] });
      last = match.index + match[0].length;
    }
    if (last < content.length) segments.push({ type: 'md', text: content.slice(last) });
    return segments;
  }, [content]);

  return (
    <>
      {parts.map((part, i) =>
        part.type === 'chart'
          ? <MetricsChart key={i} raw={part.raw} />
          : (
            <div key={i} className="prose prose-chat prose-sm max-w-none text-inherit leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{part.text}</ReactMarkdown>
            </div>
          )
      )}
    </>
  );
}

const THINKING_STEPS = [
  { icon: '🔍', text: 'Analysing your query…' },
  { icon: '📡', text: 'Connecting to Amazon Connect…' },
  { icon: '📊', text: 'Fetching queue metrics…' },
  { icon: '👤', text: 'Querying agent states…' },
  { icon: '📞', text: 'Scanning contact records…' },
  { icon: '🧠', text: 'Processing with AI…' },
  { icon: '📝', text: 'Reviewing transcripts…' },
  { icon: '📈', text: 'Calculating historical metrics…' },
  { icon: '✨', text: 'Preparing your response…' },
];

function ThinkingIndicator() {
  const [stepIdx, setStepIdx] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    // Advance step every 2.2 s with a brief fade-out/in transition
    const timer = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setStepIdx((i) => (i + 1) % THINKING_STEPS.length);
        setVisible(true);
      }, 300);
    }, 2200);
    return () => clearInterval(timer);
  }, []);

  const step = THINKING_STEPS[stepIdx];

  return (
    <div className="inline-flex items-center gap-3 rounded-2xl border border-connect-500/30 bg-slate-900 px-4 py-3 text-sm shadow-[0_0_18px_rgba(99,102,241,0.12)] animate-pulse-border">
      {/* Animated ring around bot icon */}
      <span className="relative flex h-7 w-7 shrink-0 items-center justify-center">
        <span className="absolute inset-0 rounded-full border border-connect-500/40 animate-ping" />
        <Bot size={16} className="relative z-10 text-connect-400" />
      </span>

      {/* Cycling status text */}
      <span
        className="min-w-[200px] text-slate-300 transition-opacity duration-300"
        style={{ opacity: visible ? 1 : 0 }}
      >
        <span className="mr-1.5">{step.icon}</span>
        {step.text}
      </span>

      {/* Bouncing dots */}
      <span className="flex gap-1">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-connect-400 [animation-delay:-0.24s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-connect-400 [animation-delay:-0.12s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-connect-400" />
      </span>
    </div>
  );
}

const suggestedQueries = [
  'How many agents are busy right now?',
  'Who is my busiest agent today?',
  'Show me abandoned calls from the last hour',
  "Find calls mentioning 'escalation'",
  "What's the average handle time today?",
];

function SessionItem({ session, isActive, onLoad, onDelete }) {
  const [hovering, setHovering] = useState(false);
  const msgCount = session.messages?.length || 0;
  const relTime = formatDistanceToNow(new Date(session.updatedAt), { addSuffix: true });

  return (
    <div
      className={`group relative flex cursor-pointer flex-col gap-1 rounded-2xl border px-3 py-2.5 transition ${
        isActive
          ? 'border-connect-500/50 bg-connect-500/10 text-white'
          : 'border-slate-800 bg-slate-900/60 text-slate-300 hover:border-slate-700 hover:bg-slate-800/60'
      }`}
      onClick={() => onLoad(session.id)}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onLoad(session.id)}
    >
      <p className="truncate text-xs font-medium leading-snug">{session.title}</p>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">{relTime} · {msgCount} msg{msgCount !== 1 ? 's' : ''}</span>
        {(hovering || isActive) && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onDelete(session.id); }}
            className="rounded-lg p-0.5 text-slate-500 hover:bg-rose-500/15 hover:text-rose-400"
            title="Delete session"
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>
    </div>
  );
}

export default function ChatInterface({ chat, prefilledMessage, onPrefillConsumed }) {
  const [draft, setDraft] = useState('');
  const listRef = useRef(null);

  useEffect(() => {
    if (!prefilledMessage) return;
    setDraft(prefilledMessage);
    onPrefillConsumed?.();
  }, [prefilledMessage, onPrefillConsumed]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [chat.messages, chat.isLoading]);

  const emptyState = useMemo(() => chat.messages.length === 0, [chat.messages.length]);

  const submit = async () => {
    if (!draft.trim() || chat.isLoading) return;
    const next = draft;
    setDraft('');
    await chat.sendMessage(next);
  };

  // Sessions sorted newest first, exclude current empty new session if it has no messages
  const historySessions = useMemo(() =>
    (chat.allSessions || []).filter((s) => s.messages?.length > 0),
  [chat.allSessions]);

  return (
    <section className="grid gap-5 rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-panel lg:grid-cols-[1fr_280px]">

      {/* ── Main chat area ── */}
      <div className="flex min-h-[70vh] flex-col rounded-3xl border border-slate-800 bg-slate-950/60">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <div>
            <h3 className="text-lg font-semibold">Analytics chat</h3>
            <p className="truncate text-xs text-slate-500">Session {chat.sessionId}</p>
          </div>
          <button
            type="button"
            onClick={chat.clearChat}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            <PlusCircle size={14} />
            New chat
          </button>
        </div>

        <div ref={listRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {emptyState && (
            <div className="rounded-3xl border border-dashed border-slate-700 bg-slate-900/70 p-6 text-center">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-connect-500/15 text-connect-500">
                <Sparkles size={24} />
              </div>
              <h4 className="mt-4 text-lg font-semibold">Start with a suggested query</h4>
              <p className="mt-2 text-sm text-slate-400">Ask about queue health, agents, transcripts, or call search results.</p>
              <div className="mt-5 flex flex-wrap justify-center gap-3">
                {suggestedQueries.map((query) => (
                  <button
                    key={query}
                    type="button"
                    onClick={() => setDraft(query)}
                    className="rounded-full border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-200 hover:border-connect-500 hover:text-white"
                  >
                    {query}
                  </button>
                ))}
              </div>
            </div>
          )}

          {chat.messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-3xl rounded-3xl px-4 py-3 ${message.role === 'user' ? 'bg-connect-500 text-white' : 'border border-slate-800 bg-slate-900 text-slate-100'}`}>
                {message.role === 'assistant' && (
                  <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-connect-400">
                    <Bot size={14} />
                    Assistant
                  </div>
                )}
                <div className="prose prose-chat prose-sm max-w-none text-inherit leading-relaxed">
                  {message.role === 'assistant'
                    ? <AssistantMessage content={message.content} />
                    : <p>{message.content}</p>}
                </div>
                <p className={`mt-3 text-xs ${message.role === 'user' ? 'text-blue-100/80' : 'text-slate-500'}`}>
                  {formatDistanceToNow(new Date(message.timestamp), { addSuffix: true })}
                </p>
              </div>
            </div>
          ))}

          {chat.isLoading && (
            <div className="flex justify-start px-1">
              <ThinkingIndicator />
            </div>
          )}
        </div>

        <div className="border-t border-slate-800 p-4">
          <div className="rounded-3xl border border-slate-700 bg-slate-900 px-4 py-3 shadow-inner">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
              }}
              rows={3}
              maxLength={4000}
              placeholder="Ask about queues, agents, transcripts, or recordings..."
              className="w-full resize-none border-none bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
            />
            <div className="mt-3 flex items-center justify-between">
              <p className="text-xs text-slate-500">Enter to send · Shift+Enter for newline</p>
              <button
                type="button"
                onClick={submit}
                disabled={chat.isLoading}
                className="inline-flex items-center gap-2 rounded-2xl bg-connect-500 px-4 py-2 text-sm font-medium text-white hover:bg-connect-700 disabled:cursor-not-allowed disabled:bg-slate-700"
              >
                <SendHorizonal size={16} />
                Send
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── Right sidebar: session history + suggestions ── */}
      <aside className="flex flex-col gap-5">

        {/* Session history */}
        <div className="flex flex-1 flex-col rounded-3xl border border-slate-800 bg-slate-950/60 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Clock size={15} className="text-connect-400" />
              Session history
            </div>
            <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">
              {historySessions.length}
            </span>
          </div>

          {historySessions.length === 0 ? (
            <div className="mt-4 flex flex-col items-center gap-2 py-6 text-center text-xs text-slate-500">
              <MessageSquareText size={22} className="text-slate-700" />
              No saved sessions yet. Start chatting to create one.
            </div>
          ) : (
            <div className="mt-3 flex max-h-[400px] flex-col gap-2 overflow-y-auto pr-1">
              {historySessions.map((session) => (
                <SessionItem
                  key={session.id}
                  session={session}
                  isActive={session.id === chat.sessionId}
                  onLoad={chat.loadSession}
                  onDelete={chat.deleteSession}
                />
              ))}
            </div>
          )}
        </div>

        {/* Suggested prompts */}
        <div className="rounded-3xl border border-slate-800 bg-slate-950/60 p-4">
          <h3 className="text-sm font-semibold">Suggested prompts</h3>
          <div className="mt-3 space-y-2">
            {suggestedQueries.slice(0, 4).map((query) => (
              <button
                key={query}
                type="button"
                onClick={() => setDraft(query)}
                className="w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-left text-xs text-slate-300 hover:border-connect-500"
              >
                {query}
              </button>
            ))}
          </div>
        </div>

      </aside>
    </section>
  );
}
