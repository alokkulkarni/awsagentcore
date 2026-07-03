/**
 * RealtimeCommandCenter — enterprise supervisor dashboard.
 *
 * Single-screen view designed for large monitoring screens and supervisors who
 * need full situational awareness of the contact centre in real time.
 *
 * Layout:
 *   • Alert banners  — proactive anomaly alerts (auto-generated)
 *   • KPI row 1      — Connect Metrics API (agents, queue depth, wait time)
 *   • KPI row 2      — EventBridge live summary (active contacts breakdown)
 *   • Main grid      — Left: live contacts table | Right: agent roster OR contact detail panel
 *   • Bottom strip   — Callbacks by queue + outbound calls (collapsible)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Bot,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  ExternalLink,
  Headphones,
  Info,
  Maximize2,
  MessageSquare,
  Minimize2,
  Phone,
  PhoneCall,
  PhoneForwarded,
  PhoneIncoming,
  PhoneOutgoing,
  RefreshCw,
  Search,
  ShieldAlert,
  LogOut,
  Sparkles,
  Terminal,
  User,
  Users,
  Wifi,
  WifiOff,
  X,
  Zap,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import TeamsPanel from './TeamsPanel';
import { getTeamsProvider, PRESENCE_STYLE } from '../services/teams';
import {
  getAgentStates,
  getLiveContacts,
  getMetrics,
  getTranscript,
  getContactSentiment,
  queryAgent,
  summarizeTranscript,
  forceLogoutAgent,
} from '../services/api';
import SupervisorBargePanel from './SupervisorBargePanel';
import LiveQueueMetricsChart from './LiveQueueMetricsChart';
import { AbandonedTodayPanel, CallbacksTodayPanel } from './TodayStatsPanels';
import TransferBadge from './TransferBadge';

// ── constants ──────────────────────────────────────────────────────────────────
const LIVE_POLL_MS      = 5_000;
const METRICS_POLL_MS   = 15_000;
const AGENT_POLL_MS     = 30_000;
const SENTIMENT_POLL_MS = 6_000;   // sentiment refreshes every 6 s while calls are live
const AI_SESSION_ID     = 'supervisor-detail-panel';
const UUID_RE           = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isRawId           = (s) => !s || UUID_RE.test(s?.trim());

// ── helpers ────────────────────────────────────────────────────────────────────

function fmtTime(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch { return iso; }
}

function elapsedSeconds(iso) {
  if (!iso) return 0;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
}

function fmtDuration(secs) {
  const s = Math.floor(secs);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${(m % 60).toString().padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${(s % 60).toString().padStart(2, '0')}s`;
  return `${s}s`;
}

function fmtContactTime(contact) {
  if (contact.contactTerminal && contact.contactEndedAt) {
    const ago = elapsedSeconds(contact.contactEndedAt);
    return `Ended ${fmtDuration(ago)} ago`;
  }
  return fmtDuration(elapsedSeconds(contact.initiatedAt));
}

// ── small shared components ────────────────────────────────────────────────────

function ChannelIcon({ channel }) {
  switch ((channel || '').toUpperCase()) {
    case 'VOICE': return <Phone size={11} />;
    case 'CHAT':  return <Headphones size={11} />;
    case 'TASK':  return <Terminal size={11} />;
    default:      return <PhoneCall size={11} />;
  }
}

function StateBadge({ state }) {
  const colours = {
    INITIATED:           'bg-blue-500/20 text-blue-700 dark:text-blue-300',
    QUEUED:              'bg-amber-500/20 text-amber-700 dark:text-amber-300',
    CALLBACK_SCHEDULED:  'bg-purple-500/20 text-purple-700 dark:text-purple-300',
    CONNECTED_TO_SYSTEM: 'bg-cyan-500/20 text-cyan-700 dark:text-cyan-300',
    CONNECTED_TO_AGENT:  'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300',
    DISCONNECTED:        'bg-slate-500/15 text-slate-500 dark:text-slate-400',
    ENDED:               'bg-slate-500/15 text-slate-500 dark:text-slate-400',
    MISSED:              'bg-red-500/20 text-red-700 dark:text-red-400',
    ERROR:               'bg-red-500/20 text-red-700 dark:text-red-400',
  };
  const cls = colours[(state || '').toUpperCase()] || 'bg-slate-500/15 text-slate-500 dark:text-slate-400';
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${cls}`}>
      {state || '—'}
    </span>
  );
}

function AgentStateBadge({ status }) {
  const styles = {
    Available:          'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
    'On Call':          'bg-sky-500/15 text-sky-700 dark:text-sky-300',
    'After Contact Work': 'bg-orange-500/15 text-orange-700 dark:text-orange-300',
    'Non-Productive':   'bg-amber-500/15 text-amber-700 dark:text-amber-300',
    Offline:            'bg-slate-500/15 text-slate-500 dark:text-slate-400',
    Error:              'bg-rose-500/15 text-rose-700 dark:text-rose-300',
  };
  const cls = styles[status] || 'bg-slate-500/15 text-slate-500 dark:text-slate-400';
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[9px] font-semibold ${cls}`}>
      {status || '—'}
    </span>
  );
}

// ── Sentiment badge ─────────────────────────────────────────────────────────────
function SentimentBadge({ sentiment, compact = false }) {
  if (!sentiment) return null;
  const { overall, score, customer } = sentiment;
  const label = customer?.overall || overall || 'NEUTRAL';

  const cfg = {
    POSITIVE: { icon: '↑', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20', dot: 'bg-emerald-400' },
    NEGATIVE: { icon: '↓', cls: 'bg-rose-500/15    text-rose-300    border-rose-500/20',    dot: 'bg-rose-400'    },
    MIXED:    { icon: '⟷', cls: 'bg-amber-500/15   text-amber-300   border-amber-500/20',   dot: 'bg-amber-400'   },
    NEUTRAL:  { icon: '–', cls: 'bg-slate-600/40   text-slate-500 dark:text-slate-400   border-slate-300 dark:border-slate-600/30',   dot: 'bg-slate-500'   },
  };
  const { icon, cls, dot } = cfg[label] || cfg.NEUTRAL;

  if (compact) {
    return (
      <span title={`Customer: ${label} (${score > 0 ? '+' : ''}${score})`}
        className={`inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${cls}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        {icon}
      </span>
    );
  }

  const pct = customer?.counts
    ? Math.round((customer.counts.POSITIVE / Math.max(1, customer.total_turns)) * 100)
    : null;

  return (
    <div className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 ${cls}`}>
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      <span className="text-[10px] font-semibold">{label}</span>
      {pct !== null && <span className="text-[9px] opacity-70">{pct}%↑</span>}
    </div>
  );
}

function KpiCard({ label, value, icon: Icon, colour, sub, warn, critical }) {  const border = critical
    ? 'border-rose-500/40 bg-rose-500/10'
    : warn
    ? 'border-amber-500/40 bg-amber-500/10'
    : 'border-slate-300 dark:border-slate-700/60 bg-slate-200/50 dark:bg-slate-800/50';
  return (
    <div className={`rounded-xl border p-3 ${border}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">{label}</span>
        {Icon && <Icon size={13} className={colour || 'text-slate-600 dark:text-slate-500'} />}
      </div>
      <p className={`text-2xl font-bold tabular-nums ${colour || 'text-slate-900 dark:text-slate-100'}`}>{value ?? '—'}</p>
      {sub && <p className="mt-0.5 text-[10px] text-slate-600 dark:text-slate-500">{sub}</p>}
    </div>
  );
}

function SectionBar({ icon: Icon, title, count, colour = 'text-slate-500 dark:text-slate-400', expanded, onToggle }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center gap-2 py-1.5 text-left hover:opacity-80 transition"
    >
      <Icon size={13} className={colour} />
      <span className={`text-xs font-semibold ${colour}`}>{title}</span>
      {count !== undefined && (
        <span className="rounded-full bg-slate-200 dark:bg-slate-700 px-2 py-0.5 text-[10px] text-slate-700 dark:text-slate-300">{count}</span>
      )}
      <span className="ml-auto text-slate-600 dark:text-slate-500">
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </span>
    </button>
  );
}

function EmptyRow({ cols, text }) {
  return (
    <tr>
      <td colSpan={cols} className="px-3 py-3 text-center text-[11px] text-slate-600 dark:text-slate-500">{text}</td>
    </tr>
  );
}

// ── Alert banner strip ─────────────────────────────────────────────────────────

function AlertBanners({ alerts, onDismiss, onViewContact, onQueryAI }) {
  const [open, setOpen] = useState(false);
  if (!alerts.length) return null;

  const critical = alerts.filter((a) => a.severity === 'critical').length;
  const warnings = alerts.length - critical;
  const dotColour = critical > 0 ? 'bg-rose-500' : 'bg-amber-500';

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={`w-full flex items-center gap-3 rounded-xl border px-4 py-2.5 text-left transition ${
          critical > 0
            ? 'border-rose-300 bg-rose-50 hover:bg-rose-100 dark:border-rose-500/50 dark:bg-rose-950/60 dark:hover:bg-rose-950'
            : 'border-amber-300 bg-amber-50 hover:bg-amber-100 dark:border-amber-500/40 dark:bg-amber-950/60 dark:hover:bg-amber-950'
        }`}
      >
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${dotColour}`} />
          <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dotColour}`} />
        </span>
        {critical > 0
          ? <ShieldAlert size={15} className="shrink-0 text-rose-600 dark:text-rose-400" />
          : <AlertTriangle size={15} className="shrink-0 text-amber-600 dark:text-amber-400" />}
        <span className={`flex-1 min-w-0 truncate text-xs font-semibold ${critical > 0 ? 'text-rose-800 dark:text-rose-200' : 'text-amber-800 dark:text-amber-200'}`}>
          {alerts.length} active alert{alerts.length !== 1 ? 's' : ''}
          <span className="ml-2 font-normal text-slate-500 dark:text-slate-400">
            {critical > 0 && `${critical} critical`}
            {critical > 0 && warnings > 0 && ' · '}
            {warnings > 0 && `${warnings} warning${warnings !== 1 ? 's' : ''}`}
          </span>
        </span>
        <span className="shrink-0 text-[10px] text-slate-500 dark:text-slate-400">{open ? 'Hide' : 'Review'}</span>
        {open
          ? <ChevronUp size={14} className="shrink-0 text-slate-500 dark:text-slate-400" />
          : <ChevronDown size={14} className="shrink-0 text-slate-500 dark:text-slate-400" />}
      </button>

      {open && (
        <div className="mt-2 flex max-h-[45vh] flex-col gap-2 overflow-y-auto pr-1">
          {alerts.map((alert) => (
            <AlertBanner
              key={alert.id}
              alert={alert}
              onDismiss={() => onDismiss(alert.id)}
              onViewContact={alert.contactId ? () => onViewContact(alert.contactId, alert.contactMeta) : null}
              onQueryAI={() => onQueryAI(alert.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AlertBanner({ alert, onDismiss, onViewContact, onQueryAI }) {
  const isCritical = alert.severity === 'critical';
  const bg    = isCritical ? 'bg-rose-50 dark:bg-rose-950/80 border-rose-300 dark:border-rose-500/50' : 'bg-amber-50 dark:bg-amber-950/80 border-amber-300 dark:border-amber-500/40';
  const icon  = isCritical ? <ShieldAlert size={15} className="text-rose-600 dark:text-rose-400 shrink-0" /> : <AlertTriangle size={15} className="text-amber-600 dark:text-amber-400 shrink-0" />;
  const pulse = isCritical ? 'animate-pulse' : '';
  return (
    <div className={`rounded-xl border px-4 py-2.5 flex items-start gap-3 ${bg} ${pulse}`}>
      <span className="mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <p className={`text-xs font-semibold ${isCritical ? 'text-rose-800 dark:text-rose-200' : 'text-amber-800 dark:text-amber-200'}`}>{alert.title}</p>
        <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">{alert.message}</p>
        {alert.aiQuerying && (
          <p className="mt-1 flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400">
            <RefreshCw size={10} className="animate-spin" /> AI analysing…
          </p>
        )}
        {alert.aiResponse && (
          <div className="mt-2 rounded-lg bg-white/60 dark:bg-slate-900/60 border border-slate-300 dark:border-slate-700/50 px-3 py-2">
            <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1 flex items-center gap-1">
              <Sparkles size={9} /> AI Recommendation
            </p>
            <p className="text-[11px] text-slate-800 dark:text-slate-200 leading-relaxed">{alert.aiResponse}</p>
          </div>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {onViewContact && (
          <button
            type="button"
            onClick={onViewContact}
            className="text-[10px] rounded-lg bg-slate-100 dark:bg-slate-800 px-2 py-1 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
          >
            View Call
          </button>
        )}
        {!alert.aiResponse && !alert.aiQuerying && (
          <button
            type="button"
            onClick={onQueryAI}
            className="text-[10px] rounded-lg bg-slate-100 dark:bg-slate-800 px-2 py-1 text-connect-700 dark:text-connect-400 hover:bg-slate-200 dark:hover:bg-slate-700 transition flex items-center gap-1"
          >
            <Sparkles size={9} /> Ask AI
          </button>
        )}
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-lg p-1 text-slate-600 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition"
        >
          <X size={12} />
        </button>
      </div>
    </div>
  );
}

// ── Contact row in the live table ─────────────────────────────────────────────

function LiveContactRow({ contact, selected, onClick, sentiment }) {
  const isEnded = !!contact.contactTerminal;
  const rawQueue = contact.queueName && !isRawId(contact.queueName) ? contact.queueName : null;
  const queueLabel = rawQueue || (contact.queueId ? `…${contact.queueId.slice(-8)}` : '—');
  const rawAgent = contact.agentName || '';
  const agentLabel = rawAgent && !isRawId(rawAgent) ? rawAgent : (contact.agentArn ? `…${contact.agentArn.split('/').pop().slice(-8)}` : '');

  const age = elapsedSeconds(contact.initiatedAt);
  const isLong = age > 900;
  const isMedium = age > 480 && age <= 900;

  return (
    <tr
      onClick={isEnded ? undefined : onClick}
      className={`border-t border-slate-200 dark:border-slate-800/50 text-xs transition ${
        isEnded     ? 'opacity-30 cursor-default' :
        selected    ? 'bg-connect-500/15 cursor-pointer' :
        isLong      ? 'bg-rose-500/5 hover:bg-rose-500/10 cursor-pointer' :
        isMedium    ? 'bg-amber-500/5 hover:bg-amber-500/10 cursor-pointer' :
        'hover:bg-slate-100 dark:hover:bg-slate-800/40 cursor-pointer'
      }`}
    >
      <td className="px-2 py-1.5">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-mono text-slate-500 dark:text-slate-400">…{contact.contactId?.slice(-8)}</span>
          {contact.isBot && !contact.escalatedToAgent && (
            <span className="rounded-full bg-cyan-500/15 px-1.5 py-0.5 text-[9px] font-medium text-cyan-400">BOT</span>
          )}
          {contact.escalatedToAgent && (
            <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-medium text-emerald-400">AGENT</span>
          )}
          {isLong && <span className="rounded-full bg-rose-500/15 px-1.5 py-0.5 text-[9px] font-medium text-rose-400">LONG</span>}
          {sentiment && <SentimentBadge sentiment={sentiment} compact />}
        </div>
      </td>
      <td className="px-2 py-1.5">
        <span className="inline-flex items-center gap-1 text-slate-700 dark:text-slate-300">
          <ChannelIcon channel={contact.channel} /> {contact.channel}
        </span>
      </td>
      <td className="px-2 py-1.5"><StateBadge state={contact.contactState} /></td>
      <td className="px-2 py-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {contact.escalatedToAgent
            ? <span className="text-emerald-600 dark:text-emerald-300">{agentLabel || '—'}</span>
            : <span className="text-slate-700 dark:text-slate-300">{queueLabel}</span>}
          <TransferBadge contact={contact} />
        </div>
      </td>
      <td className={`px-2 py-1.5 tabular-nums font-mono ${isLong ? 'text-rose-600 dark:text-rose-400' : isMedium ? 'text-amber-600 dark:text-amber-400' : 'text-slate-500 dark:text-slate-400'}`}>
        {fmtContactTime(contact)}
      </td>
    </tr>
  );
}

// ── Contact detail panel ───────────────────────────────────────────────────────

// ── Compact transcript pane ────────────────────────────────────────────────────
function TranscriptPane({ segments, status, loading, isLive, clEnabled, clSegCount, qcSegCount, sentiment }) {
  const bottomRef = useRef(null);

  // Auto-scroll to newest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [segments?.length]);

  const ROLE_STYLE = {
    AGENT:    { tag: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/20', text: 'text-slate-800 dark:text-slate-200' },
    BOT:      { tag: 'bg-violet-500/20  text-violet-300  border-violet-500/20',  text: 'text-slate-900 dark:text-slate-100' },
    CUSTOMER: { tag: 'bg-slate-200/60 dark:bg-slate-700/60   text-slate-500 dark:text-slate-400   border-slate-300 dark:border-slate-600/30',   text: 'text-slate-700 dark:text-slate-300' },
    SYSTEM:   { tag: 'bg-cyan-500/15    text-cyan-300    border-cyan-500/20',    text: 'text-slate-500 dark:text-slate-400' },
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header row */}
      <div className="flex items-center justify-between shrink-0 mb-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500">Transcript</p>
          {isLive && clEnabled && (
            <span className="flex items-center gap-0.5 text-[9px] text-emerald-600 dark:text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              LIVE
            </span>
          )}
          {qcSegCount > 0 && clSegCount > 0 && (
            <span className="text-[9px] text-slate-600 font-mono">AI+Human</span>
          )}
          {sentiment && <SentimentBadge sentiment={sentiment} />}
        </div>
        {loading && <RefreshCw size={9} className="animate-spin text-slate-600 shrink-0" />}
      </div>

      {/* Status notices */}
      {!loading && !segments?.length && status === 'ACTIVE_CL_STARTING' && (
        <div className="flex items-center gap-1.5 text-[10px] text-emerald-600/80 dark:text-emerald-400/80 py-1">
          <RefreshCw size={9} className="animate-spin shrink-0" />
          CL real-time initialising — retrying…
        </div>
      )}
      {!loading && !segments?.length && status === 'ACTIVE_NO_REALTIME' && (
        <div className="text-[10px] text-amber-600/80 dark:text-amber-400/80 py-1">
          Real-time transcript not enabled on this flow.
        </div>
      )}
      {!loading && !segments?.length && status === 'PROCESSING' && (
        <div className="flex items-center gap-1.5 text-[10px] text-blue-600/80 dark:text-blue-400/80 py-1">
          <RefreshCw size={9} className="animate-spin shrink-0" />
          Post-call analysis processing (2–5 min)…
        </div>
      )}
      {!loading && !segments?.length && (!status || status === 'NOT_FOUND') && (
        <div className="text-[10px] text-slate-600 py-1">No transcript yet.</div>
      )}

      {/* Transcript rows */}
      {segments?.length > 0 && (
        <div className="flex-1 min-h-0 overflow-y-auto">
          {segments.map((seg, i) => {
            const rawRole   = (seg.participantRole || seg.role || seg.speaker || '').toUpperCase();
            const isAiAgent = seg.display_name === 'AI Agent' || rawRole === 'BOT';
            const roleKey   = isAiAgent ? 'BOT' : rawRole === 'AGENT' ? 'AGENT' : rawRole === 'SYSTEM' ? 'SYSTEM' : 'CUSTOMER';
            const label     = seg.display_name
              || (roleKey === 'BOT' ? 'AI Agent' : roleKey === 'AGENT' ? 'Agent' : roleKey === 'SYSTEM' ? 'System' : 'Customer');
            const text      = seg.content || seg.transcript || seg.text || '';
            const style     = ROLE_STYLE[roleKey] || ROLE_STYLE.CUSTOMER;
            if (!text) return null;
            return (
              <div
                key={i}
                className="flex gap-1.5 items-start py-1 border-b border-slate-200 dark:border-slate-800/40 last:border-0 group"
              >
                <span
                  className={`shrink-0 rounded border px-1 py-0.5 text-[8px] font-semibold font-mono uppercase leading-none mt-0.5 ${style.tag}`}
                  style={{ minWidth: 48, textAlign: 'center' }}
                >
                  {label}
                </span>
                <span className={`text-[11px] leading-snug break-words ${style.text}`}>{text}</span>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}

// ── Contact detail panel ────────────────────────────────────────────────────────
function ContactDetailPanel({ contact, onClose, onAskAssistant, connectAlias }) {
  const [transcript, setTranscript]       = useState(null);
  const [tStatus, setTStatus]             = useState(null);
  const [tLoading, setTLoading]           = useState(false);
  const [clEnabled, setClEnabled]         = useState(false);
  const [clSegCount, setClSegCount]       = useState(0);
  const [qcSegCount, setQcSegCount]       = useState(0);
  const [sentimentSummary, setSentiment]  = useState(null);
  const tPollRef = useRef(null);

  const fetchTranscript = useCallback((contactId, silent = false) => {
    if (!silent) setTLoading(true);
    getTranscript(contactId)
      .then((d) => {
        if (d.cl_realtime_enabled !== undefined) setClEnabled(d.cl_realtime_enabled);
        if (d.cl_segments_count   !== undefined) setClSegCount(d.cl_segments_count);
        if (d.qc_segments_count   !== undefined) setQcSegCount(d.qc_segments_count);
        if (d.sentiment_summary)                  setSentiment(d.sentiment_summary);

        const segs = d.segments || d.turns || [];
        if (segs.length > 0) {
          setTranscript(segs);
          setTStatus('OK');
        } else if (d.status === 'PROCESSING') {
          setTStatus('PROCESSING');
        } else if (d.status === 'ACTIVE_CL_STARTING') {
          setTStatus('ACTIVE_CL_STARTING');
        } else if (d.status === 'ACTIVE_NO_REALTIME') {
          setTStatus('ACTIVE_NO_REALTIME');
        } else if (d.status === 'NOT_FOUND') {
          setTStatus('NOT_FOUND');
        } else {
          setTStatus('NOT_FOUND');
        }
      })
      .catch(() => setTStatus('NOT_FOUND'))
      .finally(() => { if (!silent) setTLoading(false); });
  }, []);

  // Continuous 4-second poll while contact is live
  useEffect(() => {
    if (tPollRef.current) { clearInterval(tPollRef.current); tPollRef.current = null; }
    if (contact.contactTerminal) return;
    tPollRef.current = setInterval(() => fetchTranscript(contact.contactId, true), 4_000);
    return () => { if (tPollRef.current) { clearInterval(tPollRef.current); tPollRef.current = null; } };
  }, [contact.contactId, contact.contactTerminal, fetchTranscript]);

  // Re-fetch on state change (bot→agent) — keep existing transcript visible while fetching
  const prevStateRef = useRef(null);
  useEffect(() => {
    const newState = contact.contactState;
    if (prevStateRef.current && prevStateRef.current !== newState) {
      fetchTranscript(contact.contactId, true);  // silent = keep showing existing data
    }
    prevStateRef.current = newState;
  }, [contact.contactState, contact.contactId, fetchTranscript]);

  const [summary, setSummary]         = useState(null);
  const [sumLoading, setSumLoading]   = useState(false);
  const [aiAdvice, setAiAdvice]       = useState(null);
  const [aiLoading, setAiLoading]     = useState(false);
  const [elapsed, setElapsed]         = useState(0);

  // Live duration counter
  useEffect(() => {
    const tick = () => setElapsed(elapsedSeconds(contact.initiatedAt));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [contact.initiatedAt]);

  // Fetch transcript on mount / contactId change
  useEffect(() => {
    setTranscript(null);
    setTStatus(null);
    setSummary(null);
    setAiAdvice(null);
    setClEnabled(false);
    setClSegCount(0);
    setQcSegCount(0);
    fetchTranscript(contact.contactId);
  }, [contact.contactId, fetchTranscript]);

  const fetchSummary = async () => {
    setSumLoading(true);
    try {
      const d = await summarizeTranscript(contact.contactId);
      setSummary(d.summary || d.text || JSON.stringify(d));
    } catch {
      setSummary('Summary not available for this contact.');
    } finally {
      setSumLoading(false);
    }
  };

  // "Suggest Intervention" also opens the monitor/barge panel and brings it
  // into view — the advice and the action belong together.
  const [interventionSignal, setInterventionSignal] = useState(0);
  const bargeRef = useRef(null);

  const suggestIntervention = async () => {
    setInterventionSignal((n) => n + 1);
    requestAnimationFrame(() => bargeRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    setAiLoading(true);
    const rawQueue = contact.queueName && !isRawId(contact.queueName) ? contact.queueName : 'unknown queue';
    const rawAgent = contact.agentName && !isRawId(contact.agentName) ? contact.agentName : 'an agent';
    const chan  = (contact.channel || 'voice').toLowerCase();
    const dur   = fmtDuration(elapsed);
    // Include up to 8 most recent turns from the FULL merged transcript (bot + human)
    const transcriptSnippet = transcript?.length
      ? transcript.slice(-8).map((s) => {
          const role = s.display_name || s.participantRole || s.role || s.speaker || 'unknown';
          const text = s.content || s.transcript || s.text || '';
          return `${role}: ${text}`.trim();
        }).join('\n')
      : 'No transcript available yet';
    const prompt =
      `SUPERVISOR BRIEFING REQUEST — Contact …${contact.contactId?.slice(-8)}\n` +
      `Channel: ${chan} | Duration: ${dur} | Queue: ${rawQueue} | Agent: ${rawAgent}\n` +
      `State: ${contact.contactState || 'unknown'}\n` +
      `Transcript source: ${qcSegCount > 0 && clSegCount > 0 ? 'AI agent + human agent (merged)' : qcSegCount > 0 ? 'AI agent (bot phase)' : clSegCount > 0 ? 'human agent (CL real-time)' : 'unavailable'}\n\n` +
      `Recent conversation:\n${transcriptSnippet}\n\n` +
      `Should the supervisor intervene? What is the recommended action, and what context does the supervisor need before barging in or monitoring?`;

    try {
      const resp = await queryAgent(prompt, AI_SESSION_ID);
      setAiAdvice(resp.response);
    } catch {
      setAiAdvice('Could not reach AI agent. Please try again.');
    } finally {
      setAiLoading(false);
    }
  };

  const rawQueue = contact.queueName && !isRawId(contact.queueName) ? contact.queueName : (contact.queueId ? `…${contact.queueId.slice(-8)}` : '—');
  const rawAgent = contact.agentName && !isRawId(contact.agentName) ? contact.agentName : (contact.agentArn ? `…${contact.agentArn.split('/').pop().slice(-8)}` : '—');
  const isLive   = !contact.contactTerminal;
  const isLong   = elapsed > 900;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Panel header */}
      <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-2.5 mb-2.5 shrink-0">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-600 dark:text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 transition"
          >
            <ArrowLeft size={14} />
          </button>
          <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">Contact Detail</span>
          {isLive && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[9px] font-semibold text-emerald-700 dark:text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400 animate-pulse" />
              LIVE
            </span>
          )}
        </div>
        <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-600 dark:text-slate-500 hover:text-rose-600 dark:hover:text-rose-400 transition">
          <X size={13} />
        </button>
      </div>

      {/* Two-row body: top scrolls, transcript pinned at bottom */}
      <div className="flex-1 min-h-0 flex flex-col gap-0 overflow-hidden">

        {/* ── TOP: metadata + actions + AI content (scrollable) ──────────────── */}
        <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-0.5 pb-2">

          {/* Contact metadata */}
          <div className="rounded-xl bg-slate-200/50 dark:bg-slate-800/50 border border-slate-300 dark:border-slate-700/50 p-2.5">
            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[10px]">
              <div>
                <p className="text-slate-600 dark:text-slate-500 mb-0.5">Contact ID</p>
                <p className="font-mono text-slate-700 dark:text-slate-300">…{contact.contactId?.slice(-14)}</p>
              </div>
              <div>
                <p className="text-slate-600 dark:text-slate-500 mb-0.5">Channel</p>
                <span className="inline-flex items-center gap-1 text-slate-800 dark:text-slate-200">
                  <ChannelIcon channel={contact.channel} />
                  {contact.channel || '—'}
                </span>
              </div>
              <div>
                <p className="text-slate-600 dark:text-slate-500 mb-0.5">State</p>
                <StateBadge state={contact.contactState} />
              </div>
              <div>
                <p className="text-slate-600 dark:text-slate-500 mb-0.5">Duration</p>
                <p className={`font-mono font-bold tabular-nums ${isLong ? 'text-rose-600 dark:text-rose-400' : 'text-slate-800 dark:text-slate-200'}`}>
                  {fmtDuration(elapsed)}
                  {isLong && <span className="ml-1 text-[9px] text-rose-600 dark:text-rose-500">LONG</span>}
                </p>
              </div>
              <div>
                <p className="text-slate-600 dark:text-slate-500 mb-0.5">Queue</p>
                <p className="text-slate-800 dark:text-slate-200">{rawQueue}</p>
              </div>
              <div>
                <p className="text-slate-600 dark:text-slate-500 mb-0.5">Agent</p>
                <p className="text-emerald-600 dark:text-emerald-300">{rawAgent}</p>
              </div>
              <div>
                <p className="text-slate-600 dark:text-slate-500 mb-0.5">Started</p>
                <p className="text-slate-500 dark:text-slate-400">{fmtTime(contact.initiatedAt)}</p>
              </div>
              {contact.customerEndpoint?.display && (
                <div>
                  <p className="text-slate-600 dark:text-slate-500 mb-0.5">Customer</p>
                  <p className="font-mono text-slate-500 dark:text-slate-400">{contact.customerEndpoint.display}</p>
                </div>
              )}
              {contact.contactType === 'transfer' && (
                <div>
                  <p className="text-slate-600 dark:text-slate-500 mb-0.5">Transfer</p>
                  <TransferBadge contact={contact} />
                </div>
              )}
            </div>
          </div>

          {/* Supervisor actions */}
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500 mb-1.5">Supervisor Actions</p>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={suggestIntervention}
                disabled={aiLoading}
                className="inline-flex items-center gap-1.5 rounded-xl bg-connect-500 px-2.5 py-1.5 text-[11px] font-medium text-white hover:bg-connect-700 disabled:opacity-50 transition"
              >
                {aiLoading ? <RefreshCw size={10} className="animate-spin" /> : <Sparkles size={10} />}
                {aiLoading ? 'Analysing…' : 'Suggest Intervention'}
              </button>
              {!summary && (
                <button
                  type="button"
                  onClick={fetchSummary}
                  disabled={sumLoading}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-2.5 py-1.5 text-[11px] text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-50 transition"
                >
                  {sumLoading ? <RefreshCw size={10} className="animate-spin" /> : <Zap size={10} />}
                  {sumLoading ? 'Summarising…' : 'AI Summary'}
                </button>
              )}
              {onAskAssistant && (
                <button
                  type="button"
                  onClick={() => onAskAssistant(`Tell me everything about contact ${contact.contactId?.slice(-8)}: its current state, how long it has been active, and what I should do as a supervisor.`)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-2.5 py-1.5 text-[11px] text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
                >
                  <Headphones size={10} />
                  Ask AI Agent
                </button>
              )}
              {connectAlias && (
                <a
                  href={`https://${connectAlias}.my.connect.aws/ccp-v2/`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-2.5 py-1.5 text-[11px] text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
                >
                  <ExternalLink size={10} />
                  Open CCP
                </a>
              )}
            </div>
          </div>

          {/* AI intervention briefing + AI summary side by side when both present */}
          {(aiAdvice || summary) && (
            <div className={`flex gap-2 ${aiAdvice && summary ? 'flex-row' : 'flex-col'}`}>
              {aiAdvice && (
                <div className={`rounded-xl border border-connect-500/30 bg-connect-500/10 p-2.5 ${summary ? 'flex-1 min-w-0' : ''}`}>
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-connect-700 dark:text-connect-400 mb-1 flex items-center gap-1">
                    <Sparkles size={9} /> Supervisor Briefing
                  </p>
                  <div className="text-[10px] text-slate-800 dark:text-slate-200 leading-relaxed prose prose-xs dark:prose-invert max-w-none">
                    <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{aiAdvice}</ReactMarkdown>
                  </div>
                </div>
              )}
              {summary && (
                <div className={`rounded-xl border border-slate-300 dark:border-slate-700/50 bg-slate-200/50 dark:bg-slate-800/50 p-2.5 ${aiAdvice ? 'flex-1 min-w-0' : ''}`}>
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500 mb-1">AI Summary</p>
                  <div className="text-[10px] text-slate-700 dark:text-slate-300 leading-relaxed prose prose-xs dark:prose-invert max-w-none">
                    <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{summary}</ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Supervisor monitor / barge-in panel */}
          <div ref={bargeRef}>
            <SupervisorBargePanel contact={contact} openSignal={interventionSignal} />
          </div>
        </div>

        {/* ── BOTTOM: Transcript — always visible, never pushed off screen ─────── */}
        <div className="shrink-0 border-t border-slate-200 dark:border-slate-800 pt-2" style={{ height: '220px' }}>
          <TranscriptPane
            segments={transcript}
            status={tStatus}
            loading={tLoading}
            isLive={isLive}
            clEnabled={clEnabled}
            clSegCount={clSegCount}
            qcSegCount={qcSegCount}
            sentiment={sentimentSummary}
          />
        </div>
      </div>
    </div>
  );
}

// ── Agent roster panel ─────────────────────────────────────────────────────────

const BLOCKED_STATUSES = new Set(['On Call', 'After Contact Work']);

function ForceLogoutBtn({ agent, onSuccess }) {
  const [state, setState] = useState('idle'); // idle | confirm | loading | done | blocked | error
  const [msg, setMsg] = useState('');

  const isBlocked = BLOCKED_STATUSES.has(agent.status) || agent.hasActiveContact;

  const handleClick = (e) => {
    e.stopPropagation();
    if (isBlocked) {
      setState('blocked');
      setMsg(
        agent.status === 'After Contact Work'
          ? 'In ACW — contact not yet closed'
          : `Active contact: ${agent.contactId || 'in progress'}`,
      );
      return;
    }
    setState('confirm');
  };

  const handleConfirm = async (e) => {
    e.stopPropagation();
    setState('loading');
    try {
      const result = await forceLogoutAgent(agent.agentId, 'Supervisor force-logout');
      if (result.blocked) {
        setState('blocked');
        setMsg(result.reason || 'Blocked: active contact');
      } else {
        setState('done');
        setMsg('Forced offline');
        onSuccess(agent.agentId);
      }
    } catch (err) {
      setState('error');
      setMsg(err?.response?.data?.detail || 'Request failed');
    }
  };

  const dismiss = (e) => { e.stopPropagation(); setState('idle'); setMsg(''); };

  if (state === 'done') return (
    <span className="flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400">
      <CheckCircle2 size={10} /> {msg}
      <button type="button" onClick={dismiss} className="text-slate-600 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">✕</button>
    </span>
  );

  if (state === 'blocked' || state === 'error') return (
    <span className="flex items-center gap-1 text-[10px] text-rose-600 dark:text-rose-400 max-w-[120px]" title={msg}>
      <ShieldAlert size={10} className="shrink-0" />
      <span className="truncate">{msg}</span>
      <button type="button" onClick={dismiss} className="shrink-0 text-slate-600 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">✕</button>
    </span>
  );

  if (state === 'confirm') return (
    <span className="flex items-center gap-1 text-[10px]" onClick={(e) => e.stopPropagation()}>
      <span className="text-amber-600 dark:text-amber-300">Sure?</span>
      <button type="button" onClick={handleConfirm} className="rounded bg-rose-600/80 px-1.5 py-0.5 text-white hover:bg-rose-600">Yes</button>
      <button type="button" onClick={dismiss} className="rounded bg-slate-200 dark:bg-slate-700 px-1.5 py-0.5 text-slate-800 dark:text-slate-200 hover:bg-slate-300 dark:hover:bg-slate-600">No</button>
    </span>
  );

  if (state === 'loading') return (
    <span className="flex items-center gap-1 text-[10px] text-slate-500 dark:text-slate-400">
      <RefreshCw size={10} className="animate-spin" /> Forcing…
    </span>
  );

  return (
    <button
      type="button"
      onClick={handleClick}
      title={isBlocked ? 'Cannot force logout — agent has active contact' : 'Force agent to Offline'}
      className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-colors
        ${isBlocked
          ? 'cursor-not-allowed text-slate-600 border border-slate-200 dark:border-slate-800'
          : 'border border-rose-700/50 text-rose-600 dark:text-rose-400 hover:bg-rose-500/10 hover:border-rose-500'
        }`}
    >
      <LogOut size={10} />
      {isBlocked ? 'Blocked' : 'Force out'}
    </button>
  );
}

function AgentRoster({ agentRows, loading, onForceLogout, onTeamsChat }) {
  const statOrder = { Available: 0, 'On Call': 1, 'After Contact Work': 2, 'Non-Productive': 3, Offline: 4, Error: 5 };
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  useEffect(() => { setRows(agentRows || []); }, [agentRows]);

  const sorted = [...rows].sort((a, b) =>
    (statOrder[a.status] ?? 9) - (statOrder[b.status] ?? 9) || (a.name || '').localeCompare(b.name || ''),
  );
  const avail  = sorted.filter((r) => r.status === 'Available').length;
  const onCall = sorted.filter((r) => r.status === 'On Call').length;
  const acw    = sorted.filter((r) => r.status === 'After Contact Work').length;
  const errored = sorted.filter((r) => r.status === 'Error').length;

  const query = search.trim().toLowerCase();
  const filtered = query ? sorted.filter((r) => (r.name || '').toLowerCase().includes(query)) : sorted;
  // Collapsed: a preview of the first few agents; expanded: everything + search
  const visible = open ? filtered : sorted.slice(0, 5);

  // Teams presence per agent (mock: coherent with roster status; real mode
  // needs the agent→M365 mapping that lands in Teams Phase 2). Throttled.
  const [presence, setPresence] = useState({});
  const presenceFetchedAt = useRef(0);
  useEffect(() => {
    if (!rows.length || Date.now() - presenceFetchedAt.current < 15_000) return;
    presenceFetchedAt.current = Date.now();
    let cancelled = false;
    (async () => {
      try {
        const provider = await getTeamsProvider();
        const map = await provider.getPresence(rows.map((r) => ({
          key: r.agentId,
          hint: r.status,
          email: (r.username || '').includes('@') ? r.username : null,
        })));
        if (!cancelled) setPresence(map);
      } catch { /* presence is decorative — never break the roster */ }
    })();
    return () => { cancelled = true; };
  }, [rows]);

  const handleSuccess = (agentId) => {
    setRows((prev) => prev.map((r) => r.agentId === agentId ? { ...r, status: 'Offline', hasActiveContact: false, contactId: '' } : r));
    if (onForceLogout) onForceLogout(agentId);
  };

  const renderAgentRow = (agent) => {
    const pKey = presence[agent.agentId];
    const pStyle = pKey ? PRESENCE_STYLE[pKey] : null;
    return (
      <div key={agent.agentId || agent.name} className="flex items-center justify-between py-1.5 border-b border-slate-200 dark:border-slate-800/50 text-[11px]">
        <div className="min-w-0 flex-1 mr-2">
          <p className="text-slate-800 dark:text-slate-200 font-medium truncate flex items-center gap-1.5">
            {pStyle && (
              <span
                title={`Teams: ${pStyle.label}`}
                className="inline-block h-2 w-2 rounded-full shrink-0"
                style={{ background: pStyle.colour }}
              />
            )}
            {agent.name || '—'}
          </p>
          {agent.currentQueue && <p className="text-slate-600 dark:text-slate-500 truncate">{agent.currentQueue}</p>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {pStyle && onTeamsChat && (
            <button
              type="button"
              onClick={() => onTeamsChat({
                name: agent.name,
                email: (agent.username || '').includes('@') ? agent.username : null,
              })}
              title={`Chat with ${agent.name} in Teams`}
              className="rounded p-1 text-indigo-500 hover:bg-indigo-500/10 transition"
            >
              <MessageSquare size={11} />
            </button>
          )}
          <AgentStateBadge status={agent.status} />
          {agent.status !== 'Offline' && (
            <ForceLogoutBtn agent={agent} onSuccess={handleSuccess} />
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* Title + quick numbers stay visible; the full list lives in a drawer */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center justify-between mb-2 shrink-0 w-full text-left group"
      >
        <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">
          Agent Roster
          <span className="ml-2 rounded-full bg-slate-200 dark:bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:text-slate-400">{sorted.length}</span>
        </p>
        <span className="flex items-center gap-1.5">
          {loading && <RefreshCw size={11} className="animate-spin text-slate-600 dark:text-slate-500" />}
          <span className="text-[10px] text-slate-500 dark:text-slate-400 opacity-0 group-hover:opacity-100 transition">{open ? 'Hide' : 'Show all'}</span>
          {open
            ? <ChevronUp size={13} className="text-slate-500 dark:text-slate-400" />
            : <ChevronDown size={13} className="text-slate-500 dark:text-slate-400" />}
        </span>
      </button>
      <div className="flex flex-wrap gap-2 mb-3 shrink-0">
        <span className="rounded-lg bg-emerald-500/15 px-2 py-1 text-[10px] font-medium text-emerald-400">{avail} available</span>
        <span className="rounded-lg bg-sky-500/15 px-2 py-1 text-[10px] font-medium text-sky-400">{onCall} on call</span>
        <span className="rounded-lg bg-orange-500/15 px-2 py-1 text-[10px] font-medium text-orange-400">{acw} ACW</span>
        <span className={`rounded-lg px-2 py-1 text-[10px] font-medium ${errored > 0
          ? 'bg-rose-500/15 text-rose-500 dark:text-rose-400'
          : 'bg-slate-500/10 text-slate-500'}`}>
          {errored} error
        </span>
      </div>
      {open && (
        <div className="relative mb-2 shrink-0">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 dark:text-slate-400 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search agent by name…"
            className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 pl-7 pr-7 py-1.5 text-[11px] text-slate-800 dark:text-slate-200 placeholder:text-slate-500 dark:placeholder:text-slate-500 focus:outline-none focus:border-connect-500"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            >
              <X size={11} />
            </button>
          )}
        </div>
      )}
      <div className={`flex-1 overflow-y-auto ${open ? 'max-h-[420px]' : ''}`}>
        {sorted.length === 0 && (
          <p className="text-[11px] text-slate-600 dark:text-slate-500 py-3">No agent data available.</p>
        )}
        {open && sorted.length > 0 && visible.length === 0 && (
          <p className="text-[11px] text-slate-600 dark:text-slate-500 py-3">No agents match “{search.trim()}”.</p>
        )}
        {visible.map(renderAgentRow)}
        {!open && sorted.length > 5 && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="w-full py-1.5 text-[10px] text-connect-700 dark:text-connect-400 hover:text-connect-500 text-left"
          >
            + {sorted.length - 5} more agents…
          </button>
        )}
      </div>
    </div>
  );
}

// ── Queue summary panel ────────────────────────────────────────────────────────

function QueueSummary({ cbByQueue }) {
  const entries = Object.entries(cbByQueue || {});
  if (!entries.length) return (
    <p className="text-[11px] text-slate-600 dark:text-slate-500 py-2">No queue callback data.</p>
  );
  return (
    <div className="space-y-1">
      {entries.map(([q, counts]) => (
        <div key={q} className="flex items-center justify-between text-[11px] py-1 border-b border-slate-200 dark:border-slate-800/50">
          <span className="text-slate-700 dark:text-slate-300 font-medium">{q}</span>
          <div className="flex items-center gap-2">
            {counts.waiting > 0 && (
              <span className="text-amber-600 dark:text-amber-400">{counts.waiting} waiting</span>
            )}
            {counts.scheduled > 0 && (
              <span className="text-purple-600 dark:text-purple-400">{counts.scheduled} sched.</span>
            )}
            {counts.waiting === 0 && counts.scheduled === 0 && (
              <span className="text-emerald-600 dark:text-emerald-400 flex items-center gap-1"><CheckCircle2 size={10} />Clear</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Setup banner (polling fallback mode — non-blocking) ────────────────────────

function PollingModeBanner() {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-2.5 mb-3">
      <Wifi size={13} className="text-amber-600 dark:text-amber-400 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-[11px] font-semibold text-amber-600 dark:text-amber-300">Direct-poll mode (5 s refresh)</p>
        <p className="text-[10px] text-slate-600 dark:text-slate-500 mt-0.5">
          EventBridge not configured — showing contacts via Connect API polling.
          For full real-time tracking run{' '}
          <code className="font-mono text-emerald-600 dark:text-emerald-400">./deploy.sh setup-eventbridge</code>.
        </p>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function RealtimeCommandCenter({
  alerts = [],
  onDismissAlert,
  onQueryAlertAI,
  onAskAssistant,
  connectConfig,
}) {
  const [metrics, setMetrics]         = useState({});
  const [liveData, setLiveData]       = useState(null);
  const [agentRows, setAgentRows]     = useState([]);
  const [agentLoading, setAgentLoading] = useState(false);
  const [liveLoading, setLiveLoading] = useState(true);
  const [now, setNow]                 = useState(new Date());
  const [lastRefresh, setLastRefresh] = useState(null);
  const [selectedContact, setSelectedContact] = useState(null);
  const [sentimentMap, setSentimentMap] = useState({});
  const [teamsOpen, setTeamsOpen] = useState(false);
  const [teamsUnread, setTeamsUnread] = useState(0);
  const [teamsChatTarget, setTeamsChatTarget] = useState(null);

  // Roster chat button: open the in-dashboard Teams panel on that agent's
  // 1:1 thread (sign-in happens in-panel first when needed) — never a new tab.
  const handleTeamsChat = useCallback((target) => {
    setTeamsChatTarget({ ...target, requestId: Date.now() });
    setTeamsOpen(true);
  }, []);

  // Keep the detail panel in sync — when the live contact list refreshes (every 5s)
  // find the currently selected contact in the fresh data and update its metadata
  // (agent name, queue name, state etc. all change as the call progresses).
  const selectedContactRef = useRef(null);
  selectedContactRef.current = selectedContact;
  useEffect(() => {
    const current = selectedContactRef.current;
    if (!current) return;
    const allContacts = [
      ...(liveData?.inbound       || []),
      ...(liveData?.bot_contacts  || []),
      ...(liveData?.transfers     || []),
      ...(liveData?.outbound      || []),
      ...(liveData?.callbacks     || []),
    ];
    const fresh = allContacts.find((c) => c.contactId === current.contactId);
    if (fresh) setSelectedContact(fresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveData]); // re-run whenever live contact data arrives

  // ── Sentiment polling (every 6 s, only for active contacts) ──────────────────
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      if (cancelled) return;
      const allContacts = [
        ...(liveData?.inbound       || []),
        ...(liveData?.bot_contacts  || []),
        ...(liveData?.transfers     || []),
        ...(liveData?.outbound      || []),
        ...(liveData?.callbacks     || []),
      ];
      // Contact Lens sentiment only exists once an agent is connected, and each
      // check costs a DescribeContact + S3 probe — cap the fan-out so 100+
      // concurrent contacts can't throttle AWS (TooManyRequestsException).
      const eligible = allContacts.filter((c) => !c.contactTerminal && c.contactId && c.escalatedToAgent);
      const selId = selectedContactRef.current?.contactId;
      const active = [
        ...eligible.filter((c) => c.contactId === selId),
        ...eligible.filter((c) => c.contactId !== selId),
      ].slice(0, 30);
      if (!active.length) return;
      const results = await Promise.all(
        active.map((c) => getContactSentiment(c.contactId).catch(() => null))
      );
      if (cancelled) return;
      setSentimentMap((prev) => {
        const next = { ...prev };
        results.forEach((r, i) => {
          if (r?.sentiment_summary) next[active[i].contactId] = r.sentiment_summary;
        });
        return next;
      });
    };
    poll();
    const timer = setInterval(poll, SENTIMENT_POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [liveData]);

  // Sections expand/collapse
  // Contact sections start collapsed — at production volume the lists are
  // long, so the user opens only what they need.
  const [showCallbacks, setShowCallbacks] = useState(false);
  const [showOutbound, setShowOutbound]   = useState(false);
  const [showInbound, setShowInbound]     = useState(false);
  const [showBot, setShowBot]             = useState(false);
  const [showTransfers, setShowTransfers] = useState(false);

  const liveTimerRef    = useRef(null);
  const metricsTimerRef = useRef(null);
  const agentTimerRef   = useRef(null);
  const clockTimerRef   = useRef(null);

  const connectAlias = connectConfig?.connect_alias || null;

  // Live clock
  useEffect(() => {
    clockTimerRef.current = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(clockTimerRef.current);
  }, []);

  // Poll live contacts
  const fetchLive = useCallback(async () => {
    try {
      const d = await getLiveContacts();
      setLiveData(d);
      setLastRefresh(new Date());
    } catch {
      // retain last data
    } finally {
      setLiveLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLive();
    liveTimerRef.current = setInterval(fetchLive, LIVE_POLL_MS);
    return () => clearInterval(liveTimerRef.current);
  }, [fetchLive]);

  // Poll metrics
  const fetchMetrics = useCallback(async () => {
    try {
      const d = await getMetrics();
      setMetrics(d.metrics || {});
    } catch {}
  }, []);

  useEffect(() => {
    fetchMetrics();
    metricsTimerRef.current = setInterval(fetchMetrics, METRICS_POLL_MS);
    return () => clearInterval(metricsTimerRef.current);
  }, [fetchMetrics]);

  // Poll agent states
  const fetchAgents = useCallback(async () => {
    setAgentLoading(true);
    try {
      const d = await getAgentStates();
      setAgentRows(d.agents || []);
    } catch {}
    finally { setAgentLoading(false); }
  }, []);

  useEffect(() => {
    fetchAgents();
    agentTimerRef.current = setInterval(fetchAgents, AGENT_POLL_MS);
    return () => clearInterval(agentTimerRef.current);
  }, [fetchAgents]);

  // Derived live data
  const listenerActive = liveData?.listener_active;
  const pollingMode    = liveData?.polling_mode;
  const summary        = liveData?.summary || {};
  const inbound        = liveData?.inbound  || [];
  const outbound       = liveData?.outbound || [];
  const callbacks      = liveData?.callbacks || [];
  const botContacts    = liveData?.bot_contacts || [];
  const transfers      = liveData?.transfers || [];
  const cbByQueue      = liveData?.callbacks_by_queue || {};

  // KPI thresholds
  const queueCount  = +(metrics.contacts_in_queue ?? 0);
  const agentsAvail = +(metrics.agents_available  ?? 0);

  const handleContactClick = useCallback((contact) => {
    setSelectedContact((prev) => prev?.contactId === contact.contactId ? null : contact);
  }, []);

  const handleAlertViewContact = useCallback((contactId, meta) => {
    // Prefer the live copy of the contact; the alert's snapshot can be stale
    const found = [...inbound, ...botContacts, ...transfers, ...outbound, ...callbacks]
      .find((c) => c.contactId === contactId);
    if (found || meta) setSelectedContact(found || meta);
  }, [inbound, botContacts, transfers, outbound, callbacks]);

  return (
    <div className="flex flex-col gap-4 h-full">

      {/* ── Header bar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className={`flex h-8 w-8 items-center justify-center rounded-xl ${
            listenerActive ? 'bg-emerald-500/15' : pollingMode ? 'bg-amber-500/15' : 'bg-slate-200 dark:bg-slate-700'
          }`}>
            {listenerActive
              ? <Wifi size={15} className="text-emerald-600 dark:text-emerald-400" />
              : pollingMode
              ? <Wifi size={15} className="text-amber-600 dark:text-amber-400" />
              : <WifiOff size={15} className="text-slate-600 dark:text-slate-500" />}
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-800 dark:text-slate-200">Real-Time Command Centre</p>
            <p className="text-[10px] text-slate-600 dark:text-slate-500">
              {listenerActive
                ? 'EventBridge live · 5s refresh'
                : pollingMode
                ? '⚠ Direct-poll mode — EventBridge not configured (see logs)'
                : 'Connecting…'}
              {lastRefresh && ` · last at ${fmtTime(lastRefresh.toISOString())}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {alerts.length > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-xl bg-rose-500/15 px-3 py-1.5 text-xs font-medium text-rose-300">
              <ShieldAlert size={12} />
              {alerts.length} alert{alerts.length !== 1 ? 's' : ''}
            </span>
          )}
          <div className="text-right">
            <p className="text-lg font-semibold tabular-nums text-slate-900 dark:text-slate-100">
              {now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </p>
            <p className="text-[10px] text-slate-600 dark:text-slate-500">
              {now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setTeamsOpen(true)}
            title="Microsoft Teams — chat and agent presence"
            className="relative rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-2 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition flex items-center gap-1.5"
          >
            <MessageSquare size={12} className="text-indigo-500" /> Teams
            {teamsUnread > 0 && (
              <span className="absolute -top-1.5 -right-1.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-indigo-600 px-1 text-[9px] font-semibold text-white">
                {teamsUnread}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={fetchLive}
            className="rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-2 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition flex items-center gap-1.5"
          >
            <RefreshCw size={12} className={liveLoading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      {/* ── Alert banners ────────────────────────────────────────────────────── */}
      {alerts.length > 0 && (
        <AlertBanners
          alerts={alerts}
          onDismiss={onDismissAlert}
          onViewContact={handleAlertViewContact}
          onQueryAI={onQueryAlertAI}
        />
      )}

      {!listenerActive && !liveLoading && pollingMode && <PollingModeBanner />}

      <>
        {/* ── KPI strip 1: Connect Metrics ─────────────────────────────────── */}
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 shrink-0">
            <KpiCard label="Online"       value={metrics.agents_online}     icon={Users}        colour="text-slate-700 dark:text-slate-300" />
            <KpiCard label="Available"    value={metrics.agents_available}  icon={CheckCircle2} colour="text-emerald-600 dark:text-emerald-400"
              warn={agentsAvail <= 2} critical={agentsAvail === 0} />
            <KpiCard label="On Call"      value={metrics.agents_on_call}    icon={Phone}        colour="text-sky-600 dark:text-sky-400" />
            <KpiCard label="ACW"          value={metrics.agents_in_acw}     icon={Clock}        colour="text-orange-600 dark:text-orange-400" />
            <KpiCard label="In Queue"     value={metrics.contacts_in_queue} icon={PhoneIncoming} colour="text-amber-600 dark:text-amber-400"
              warn={queueCount > 5} critical={queueCount > 10} />
            <KpiCard label="Oldest Wait"  value={metrics.oldest_contact_age || '—'} icon={Activity} colour="text-slate-700 dark:text-slate-300" sub="hh:mm:ss" />
          </div>

          {/* ── KPI strip 2: EventBridge Live ─────────────────────────────────── */}
          <div className="grid grid-cols-4 gap-2 sm:grid-cols-8 shrink-0">
            <KpiCard label="Total Active" value={summary.total}               icon={PhoneCall}     colour="text-connect-700 dark:text-connect-400" />
            <KpiCard label="Inbound"      value={summary.inbound}             icon={PhoneIncoming} colour="text-blue-600 dark:text-blue-400" />
            <KpiCard label="Bot / IVR"    value={summary.bot_handling}        icon={Bot}           colour="text-cyan-600 dark:text-cyan-400" />
            <KpiCard label="With Agent"   value={summary.agent_connected}     icon={Headphones}    colour="text-emerald-600 dark:text-emerald-400" />
            <KpiCard
              label="Transfers"
              value={summary.transfers}
              icon={PhoneForwarded}
              colour="text-violet-600 dark:text-violet-400"
              sub={summary.transfers ? `${summary.transfers_internal || 0} int · ${summary.transfers_external || 0} ext` : undefined}
            />
            <KpiCard label="Callbacks ⌚" value={summary.callbacks_waiting}  icon={PhoneForwarded} colour="text-amber-600 dark:text-amber-400" />
            <KpiCard label="Outbound"     value={summary.outbound}            icon={PhoneOutgoing} colour="text-orange-600 dark:text-orange-400" />
            <KpiCard label="Voice"        value={summary.voice}               icon={Phone}         colour="text-blue-600 dark:text-blue-300" />
          </div>

          {/* ── Main grid: contacts table + right panel ───────────────────────── */}
          <div className="flex gap-4 flex-1 min-h-0">

            {/* LEFT: Live contacts table */}
            <div className="flex-1 overflow-y-auto rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 p-4 space-y-3">

              {/* Inbound & Transfers */}
              <div>
                <SectionBar
                  icon={PhoneIncoming}
                  title="Inbound & Transfers"
                  count={inbound.length + transfers.length}
                  colour="text-blue-600 dark:text-blue-400"
                  expanded={showInbound}
                  onToggle={() => setShowInbound((v) => !v)}
                />
                {showInbound && (
                  <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800/60">
                    <table className="w-full text-left">
                      <thead className="bg-slate-100 dark:bg-slate-800/50">
                        <tr>
                          {['Contact', 'Channel', 'State', 'Queue / Agent', 'Duration'].map((c) => (
                            <th key={c} className="px-2 py-1.5 text-[10px] font-medium text-slate-500 dark:text-slate-400">{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {[...inbound, ...transfers].length === 0 && <EmptyRow cols={5} text="No active inbound contacts" />}
                        {[...inbound, ...transfers].map((c) => (
                          <LiveContactRow
                            key={c.contactId}
                            contact={c}
                            selected={selectedContact?.contactId === c.contactId}
                            onClick={() => handleContactClick(c)}
                            sentiment={sentimentMap[c.contactId]}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Bot / IVR */}
              <div>
                <SectionBar
                  icon={Bot}
                  title="Bot / IVR"
                  count={botContacts.length}
                  colour="text-cyan-600 dark:text-cyan-400"
                  expanded={showBot}
                  onToggle={() => setShowBot((v) => !v)}
                />
                {showBot && (
                  <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800/60">
                    <table className="w-full text-left">
                      <thead className="bg-slate-100 dark:bg-slate-800/50">
                        <tr>
                          {['Contact', 'Channel', 'State', 'Queue / Agent', 'Duration'].map((c) => (
                            <th key={c} className="px-2 py-1.5 text-[10px] font-medium text-slate-500 dark:text-slate-400">{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {botContacts.length === 0 && <EmptyRow cols={5} text="No bot / IVR contacts active" />}
                        {botContacts.map((c) => (
                          <LiveContactRow
                            key={c.contactId}
                            contact={c}
                            selected={selectedContact?.contactId === c.contactId}
                            onClick={() => handleContactClick(c)}
                            sentiment={sentimentMap[c.contactId]}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Outbound */}
              {outbound.length > 0 && (
                <div>
                  <SectionBar
                    icon={PhoneOutgoing}
                    title="Outbound"
                    count={outbound.length}
                    colour="text-orange-600 dark:text-orange-400"
                    expanded={showOutbound}
                    onToggle={() => setShowOutbound((v) => !v)}
                  />
                  {showOutbound && (
                    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800/60">
                      <table className="w-full text-left">
                        <thead className="bg-slate-100 dark:bg-slate-800/50">
                          <tr>
                            {['Contact', 'Channel', 'State', 'Agent', 'Duration'].map((c) => (
                              <th key={c} className="px-2 py-1.5 text-[10px] font-medium text-slate-500 dark:text-slate-400">{c}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {outbound.map((c) => (
                            <LiveContactRow
                              key={c.contactId}
                              contact={c}
                              selected={selectedContact?.contactId === c.contactId}
                              onClick={() => handleContactClick(c)}
                              sentiment={sentimentMap[c.contactId]}
                            />
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* Callbacks */}
              {callbacks.length > 0 && (
                <div>
                  <SectionBar
                    icon={PhoneForwarded}
                    title="Callbacks"
                    count={callbacks.length}
                    colour="text-amber-600 dark:text-amber-400"
                    expanded={showCallbacks}
                    onToggle={() => setShowCallbacks((v) => !v)}
                  />
                  {showCallbacks && (
                    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800/60">
                      <table className="w-full text-left">
                        <thead className="bg-slate-100 dark:bg-slate-800/50">
                          <tr>
                            {/* LiveContactRow renders 5 cells — keep headers aligned with it */}
                            {['Contact', 'Channel', 'State', 'Queue / Agent', 'Duration'].map((c) => (
                              <th key={c} className="px-2 py-1.5 text-[10px] font-medium text-slate-500 dark:text-slate-400">{c}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {callbacks.map((c) => (
                            <LiveContactRow
                              key={c.contactId}
                              contact={c}
                              selected={selectedContact?.contactId === c.contactId}
                              onClick={() => handleContactClick(c)}
                              sentiment={sentimentMap[c.contactId]}
                            />
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* ── Live Queue Metrics Chart ─────────────────────────────────── */}
              <LiveQueueMetricsChart />

              {/* ── Today-so-far stats (abandonment timing + callbacks) ──────── */}
              <div className="grid gap-4 xl:grid-cols-2">
                <AbandonedTodayPanel />
                <CallbacksTodayPanel />
                {Object.keys(cbByQueue).length > 0 && (
                  <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 p-4">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500 mb-2 flex items-center gap-1.5">
                      <PhoneCall size={10} /> Callbacks by Queue
                    </p>
                    <div className="max-h-64 overflow-y-auto pr-1">
                      <QueueSummary cbByQueue={cbByQueue} />
                    </div>
                  </div>
                )}
              </div>

            </div>

            {/* RIGHT: Agent roster */}
            <div className="w-80 shrink-0 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 p-4 overflow-hidden flex flex-col">
              <AgentRoster agentRows={agentRows} loading={agentLoading} onTeamsChat={handleTeamsChat} />
            </div>
          </div>
        </>

      {/* ── Microsoft Teams slide-over (always mounted for the unread badge) ── */}
      <TeamsPanel
        open={teamsOpen}
        onClose={() => setTeamsOpen(false)}
        onUnreadChange={setTeamsUnread}
        chatTarget={teamsChatTarget}
      />

      {/* ── Contact detail slide-over ─────────────────────────────────────────
          Opened by View Call on an alert or clicking a contact row. A fixed
          overlay: visible instantly wherever the page is scrolled, instead of
          swapping content into the right rail below the fold. */}
      {selectedContact && (
        <div className="fixed inset-0 z-[60] flex justify-end" onClick={() => setSelectedContact(null)}>
          <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px]" />
          <div
            className="relative h-full w-[420px] max-w-[92vw] bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 shadow-2xl p-4 flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <ContactDetailPanel
              contact={selectedContact}
              onClose={() => setSelectedContact(null)}
              onAskAssistant={onAskAssistant}
              connectAlias={connectAlias}
            />
          </div>
        </div>
      )}
    </div>
  );
}
