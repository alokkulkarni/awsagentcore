import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Headphones, Search, Sparkles, RefreshCw, AlertCircle, Play, Pause,
  Info, ChevronDown, ChevronUp, Phone, MessageSquare, X, Radio, Bot,
  ArrowDownToLine, Clock, UserCheck, Wifi, WifiOff, Zap, Link2,
} from 'lucide-react';
import { getTranscript, getRecording, summarizeTranscript, getActiveCalls, getRecentBotContacts, getLiveBotContacts, getStreamsConfig } from '../services/api';
import { useConnectStreams } from '../hooks/useConnectStreams';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';

/* ─── helpers ──────────────────────────────────────────────────────────────── */

const POLL_MS = 20_000; // refresh active calls every 20 s

const sentimentStyles = {
  positive: 'bg-emerald-500/15 text-emerald-300',
  negative: 'bg-rose-500/15 text-rose-300',
  neutral: 'bg-slate-500/15 text-slate-300',
};

const queueColours = [
  'border-connect-500/40 bg-connect-500/10',
  'border-emerald-500/40 bg-emerald-500/10',
  'border-amber-500/40 bg-amber-500/10',
  'border-violet-500/40 bg-violet-500/10',
  'border-rose-500/40 bg-rose-500/10',
  'border-sky-500/40 bg-sky-500/10',
];

function fmtDuration(secs) {
  if (!secs) return '0:00';
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function highlight(text, keyword) {
  if (!keyword) return text;
  const safe = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return text.split(new RegExp(`(${safe})`, 'ig')).map((p, i) =>
    p.toLowerCase() === keyword.toLowerCase()
      ? <mark key={i} className="rounded bg-amber-400/30 px-1 text-amber-100">{p}</mark>
      : <span key={i}>{p}</span>
  );
}

/* ─── AudioPlayer ───────────────────────────────────────────────────────────── */
function AudioPlayer({ url }) {
  const ref = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [err, setErr] = useState(false);
  const fmt = (s) => `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, '0')}`;
  if (err) return (
    <div className="mt-3 rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-xs text-rose-300">
      Could not load recording. The presigned URL may have expired.
    </div>
  );
  return (
    <div className="mt-3 rounded-2xl border border-slate-700 bg-slate-950 p-3">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={ref} src={url} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)} onTimeUpdate={() => setCur(ref.current?.currentTime || 0)}
        onLoadedMetadata={() => setDur(ref.current?.duration || 0)} onError={() => setErr(true)}
        preload="metadata" className="hidden" />
      <div className="flex items-center gap-3">
        <button type="button" onClick={() => playing ? ref.current?.pause() : ref.current?.play().catch(() => setErr(true))}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-connect-500 text-white hover:bg-connect-700">
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <div className="flex flex-1 flex-col gap-1">
          <input type="range" min={0} max={dur || 1} step={0.5} value={cur}
            onChange={(e) => { if (ref.current) ref.current.currentTime = +e.target.value; setCur(+e.target.value); }}
            className="h-1.5 w-full cursor-pointer accent-connect-500" />
          <div className="flex justify-between text-xs text-slate-400"><span>{fmt(cur)}</span><span>{dur ? fmt(dur) : '--:--'}</span></div>
        </div>
      </div>
    </div>
  );
}

/* ─── TranscriptPanel (reused in modal and standalone) ─────────────────────── */
function TranscriptPanel({ contact, highlightKeyword, onClose }) {
  const [segments, setSegments] = useState(contact?.transcript || []);
  const [channel, setChannel] = useState(contact?.channel || null);
  const [transcriptSource, setTranscriptSource] = useState(null);
  const [tMsg, setTMsg] = useState(null);
  const [tErr, setTErr] = useState(null);
  const [tStatus, setTStatus] = useState(null);          // PROCESSING | ACTIVE_NO_REALTIME | NOT_FOUND | null
  const [retryAfter, setRetryAfter] = useState(null);    // seconds until next auto-retry
  const [countdown, setCountdown] = useState(null);      // live countdown display
  const [loadingT, setLoadingT] = useState(false);
  const [recUrl, setRecUrl] = useState(null);
  const [recMsg, setRecMsg] = useState(null);
  const [loadingR, setLoadingR] = useState(false);
  const [showPlayer, setShowPlayer] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [summary, setSummary] = useState(null);
  const [summErr, setSummErr] = useState(null);
  const [summOpen, setSummOpen] = useState(true);
  const [manualId, setManualId] = useState(contact?.contactId || '');

  const retryTimerRef = useRef(null);
  const countdownRef  = useRef(null);
  const cid = contact?.contactId;

  const clearRetry = () => {
    clearTimeout(retryTimerRef.current);
    clearInterval(countdownRef.current);
    setCountdown(null);
  };

  const fetchT = useCallback(async (id, silent = false) => {
    if (!id) return;
    if (!silent) { setLoadingT(true); setTErr(null); setSegments([]); setTMsg(null); setTranscriptSource(null); setTStatus(null); }
    clearRetry();
    try {
      const d = await getTranscript(id);
      setSegments(d.segments || []);
      if (d.channel) setChannel(d.channel);
      if (d.source) setTranscriptSource(d.source);
      if (d.message) setTMsg(d.message);
      setTStatus(d.status || null);

      // Auto-retry when Contact Lens is still processing the contact
      if (d.processing && d.retry_after_seconds > 0 && (d.segments || []).length === 0) {
        const delay = d.retry_after_seconds * 1000;
        let rem = d.retry_after_seconds;
        setRetryAfter(rem);
        setCountdown(rem);
        countdownRef.current = setInterval(() => {
          rem -= 1;
          setCountdown(rem);
          if (rem <= 0) clearInterval(countdownRef.current);
        }, 1000);
        retryTimerRef.current = setTimeout(() => fetchT(id, true), delay);
      }
    } catch { setTErr('Could not load transcript.'); }
    finally { setLoadingT(false); }
  }, []);

  useEffect(() => {
    if (cid && !contact?.transcript) fetchT(cid);
    else { setSegments(contact?.transcript || []); setTMsg(null); setTErr(null); setTranscriptSource(null); setTStatus(null); }
    setManualId(cid || '');
    setRecUrl(null); setRecMsg(null); setShowPlayer(false); setSummary(null); setSummErr(null);
    return () => clearRetry();
  }, [cid]);

  const isVoice = channel ? channel === 'VOICE' : (contact?.channel !== 'CHAT');
  const isEscalated = contact?.escalatedFromBot && transcriptSource === 'automated_interaction_log';
  const isBotOnlyCompleted = transcriptSource === 'automated_interaction_log' && !contact?.escalatedFromBot;

  const handleRec = async () => {
    if (showPlayer && recUrl) { setShowPlayer(false); return; }
    if (recUrl) { setShowPlayer(true); return; }
    const id = manualId || cid;
    if (!id) return;
    setLoadingR(true); setRecMsg(null);
    try {
      const d = await getRecording(id);
      if (d.url) { setRecUrl(d.url); setShowPlayer(true); }
      else setRecMsg(d.message || 'No recording available.');
    } catch { setRecMsg('Could not fetch recording.'); }
    finally { setLoadingR(false); }
  };

  const handleSumm = async () => {
    const id = manualId || cid;
    if (!id) return;
    setSummarizing(true); setSummErr(null); setSummary(null); setSummOpen(true);
    try {
      const d = await summarizeTranscript(id);
      setSummary(d.summary || 'No summary available.');
    } catch { setSummErr('Could not generate summary.'); }
    finally { setSummarizing(false); }
  };

  return (
    <div className="flex flex-col gap-5 h-full">
      {/* Header row */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-connect-500/15 p-2.5 text-connect-400">
            {isVoice ? <Phone size={16} /> : <MessageSquare size={16} />}
          </div>
          <div>
            <p className="text-xs text-slate-400">Contact</p>
            <h4 className="font-semibold text-sm text-white">{contact?.contactId || '—'}</h4>
          </div>
        </div>
        {onClose && (
          <button type="button" onClick={onClose}
            className="rounded-xl border border-slate-700 p-2 text-slate-400 hover:border-slate-500 hover:text-slate-200">
            <X size={16} />
          </button>
        )}
      </div>

      {/* Meta pills */}
      <div className="flex flex-wrap gap-2 text-xs">
        {contact?.queue && <span className="rounded-full border border-slate-700 bg-slate-800 px-3 py-1 text-slate-300">{contact.queue}</span>}
        {contact?.agent && <span className="rounded-full border border-slate-700 bg-slate-800 px-3 py-1 text-slate-300">{contact.agent}</span>}
        {contact?.status && <span className="rounded-full border border-slate-700 bg-slate-800 px-3 py-1 text-slate-300">{contact.status}</span>}
        {contact?.duration != null && <span className="rounded-full border border-slate-700 bg-slate-800 px-3 py-1 text-slate-300">{fmtDuration(contact.duration)}</span>}
        {channel && <span className={`rounded-full border px-3 py-1 ${isVoice ? 'border-connect-500/30 text-connect-300' : 'border-emerald-500/30 text-emerald-300'}`}>{channel}</span>}
        {isEscalated && (
          <span className="flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-amber-300">
            <Bot size={10} />Escalated from Bot
          </span>
        )}
        {isBotOnlyCompleted && (
          <span className="flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1 text-violet-300">
            <Bot size={10} />Bot handled
          </span>
        )}
      </div>

      {/* Manual ID input */}
      {!contact?.contactId && (
        <div className="flex gap-2">
          <div className="flex flex-1 items-center gap-2 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
            <Search size={14} className="text-slate-400" />
            <input value={manualId} onChange={(e) => setManualId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fetchT(manualId)}
              placeholder="Enter Contact ID…" className="flex-1 bg-transparent outline-none text-slate-100" />
          </div>
          <button type="button" onClick={() => fetchT(manualId)} disabled={loadingT}
            className="rounded-xl bg-connect-500 px-4 py-2 text-sm font-medium text-white hover:bg-connect-700 disabled:opacity-50">
            {loadingT ? <RefreshCw size={14} className="animate-spin" /> : <Search size={14} />}
          </button>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        {isVoice && (
          <button type="button" onClick={handleRec} disabled={loadingR}
            className="inline-flex items-center gap-2 rounded-xl bg-connect-500 px-4 py-2 text-sm font-medium text-white hover:bg-connect-700 disabled:opacity-50">
            {loadingR ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
            {showPlayer ? 'Hide Player' : 'Play Recording'}
          </button>
        )}
        <button type="button" onClick={handleSumm} disabled={summarizing}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-950 px-4 py-2 text-sm text-slate-100 hover:border-connect-500 disabled:opacity-50">
          {summarizing ? <RefreshCw size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {summarizing ? 'Summarizing…' : 'Summarize'}
        </button>
      </div>

      {showPlayer && recUrl && <AudioPlayer url={recUrl} />}
      {recMsg && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          <Info size={13} className="mt-0.5 shrink-0" />{recMsg}
        </div>
      )}

      {/* AI Summary */}
      {(summarizing || summary || summErr) && (
        <div className="rounded-2xl border border-connect-500/30 bg-connect-500/10">
          <button type="button" onClick={() => setSummOpen(v => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-connect-300">
            <span className="flex items-center gap-2"><Sparkles size={14} />AI Summary</span>
            {summOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {summOpen && (
            <div className="border-t border-connect-500/20 px-4 py-4">
              {summarizing && <div className="flex items-center gap-2 text-sm text-slate-400"><RefreshCw size={13} className="animate-spin" />Generating…</div>}
              {summErr && <div className="flex items-start gap-2 text-sm text-rose-300"><AlertCircle size={13} className="mt-0.5 shrink-0" />{summErr}</div>}
              {summary && <div className="prose prose-invert prose-sm max-w-none text-slate-200"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{summary}</ReactMarkdown></div>}
            </div>
          )}
        </div>
      )}

      {/* Transcript */}
      <div className="flex-1 overflow-y-auto">
        {tErr && <div className="mb-3 flex items-center gap-2 rounded-xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-300"><AlertCircle size={14} />{tErr}</div>}

        {/* Processing banner — Contact Lens still generating, auto-retry scheduled */}
        {!tErr && tStatus === 'PROCESSING' && segments.length === 0 && (
          <div className="mb-3 rounded-xl border border-sky-500/25 bg-sky-500/10 px-4 py-4">
            <div className="flex items-center gap-2 text-sm text-sky-300">
              <RefreshCw size={14} className="animate-spin shrink-0" />
              <span className="font-medium">Generating transcript…</span>
            </div>
            {tMsg && <p className="mt-2 text-xs text-sky-300/70">{tMsg}</p>}
            {countdown !== null && countdown > 0 && (
              <div className="mt-3 flex items-center gap-2">
                <div className="h-1.5 flex-1 rounded-full bg-sky-500/20 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-sky-500 transition-all duration-1000"
                    style={{ width: `${Math.max(0, (1 - countdown / (retryAfter || 30)) * 100)}%` }}
                  />
                </div>
                <span className="text-xs text-sky-400 tabular-nums shrink-0">
                  Retry in {countdown}s
                </span>
                <button
                  onClick={() => fetchT(cid || manualId)}
                  className="rounded-lg border border-sky-500/30 px-2.5 py-1 text-xs text-sky-300 hover:bg-sky-500/20 transition-colors"
                >
                  Retry now
                </button>
              </div>
            )}
          </div>
        )}

        {/* Generic info message (NOT_FOUND, ACTIVE_NO_REALTIME, or plain messages) */}
        {!tErr && tStatus !== 'PROCESSING' && tMsg && segments.length === 0 && (
          <div className={`mb-3 flex items-start gap-2 rounded-xl border px-4 py-3 text-sm ${
            tStatus === 'NOT_FOUND'
              ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
              : 'border-slate-700 bg-slate-800/50 text-slate-400'
          }`}>
            <Info size={14} className="mt-0.5 shrink-0" />
            <div>
              <p>{tMsg}</p>
              <button
                onClick={() => fetchT(cid || manualId)}
                className="mt-2 rounded-lg border border-current/30 px-2.5 py-1 text-xs opacity-70 hover:opacity-100 transition-opacity"
              >
                Try again
              </button>
            </div>
          </div>
        )}

        {loadingT ? (
          <div className="flex items-center justify-center gap-3 py-12 text-sm text-slate-400"><RefreshCw size={16} className="animate-spin" />Loading transcript…</div>
        ) : segments.length === 0 ? (
          !tMsg && !tErr && <p className="py-8 text-center text-sm text-slate-400">No transcript segments. Select a contact above.</p>
        ) : (
          <div className="space-y-3">
            {/* Bot interaction header for automated_interaction_log transcripts */}
            {transcriptSource === 'automated_interaction_log' && (
              <div className="flex items-center gap-2 rounded-xl border border-violet-500/25 bg-violet-500/10 px-4 py-2.5 text-xs text-violet-300">
                <Bot size={13} className="shrink-0" />
                <span>Conversational AI bot interaction (automated interaction log)</span>
              </div>
            )}
            {segments.map((seg, i) => {
              const timeLabel = seg.time || (seg.start_offset_millis != null
                ? new Date(seg.start_offset_millis).toISOString().slice(11, 19) : '');
              const sentiment = (seg.sentiment || 'NEUTRAL').toLowerCase();
              const isAgent = seg.speaker === 'AGENT';
              return (
                <div key={i} className={`rounded-2xl border p-4 ${isAgent ? 'border-connect-500/25 bg-connect-500/10' : 'border-slate-800 bg-slate-900'}`}>
                  <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-widest text-slate-400">
                    <span>{seg.speaker}</span>
                    {timeLabel && <span>{timeLabel}</span>}
                    <span className={`rounded-full px-2.5 py-0.5 ${sentimentStyles[sentiment] || sentimentStyles.neutral}`}>{sentiment}</span>
                  </div>
                  <p className="mt-2 text-sm leading-7 text-slate-100">{highlight(seg.text, highlightKeyword)}</p>
                </div>
              );
            })}
            {/* Escalation event divider */}
            {isEscalated && (
              <div className="relative flex items-center gap-3 py-2">
                <div className="h-px flex-1 bg-amber-500/30" />
                <div className="flex shrink-0 items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs text-amber-300">
                  <ArrowDownToLine size={11} />
                  Escalated to {contact.queueName || contact.queue || 'agent queue'}
                  {contact.enqueuedAt && (
                    <span className="ml-1 text-amber-400/70">· {new Date(contact.enqueuedAt).toLocaleTimeString()}</span>
                  )}
                </div>
                <div className="h-px flex-1 bg-amber-500/30" />
              </div>
            )}
            {/* Agent handling footer for escalated calls */}
            {isEscalated && (
              <div className="flex items-center gap-2 rounded-xl border border-connect-500/25 bg-connect-500/10 px-4 py-2.5 text-xs text-connect-300">
                <UserCheck size={13} className="shrink-0" />
                {contact.connectedToAgentAt
                  ? <>Agent connected at {new Date(contact.connectedToAgentAt).toLocaleTimeString()}</>
                  : 'Waiting for agent…'}
                {contact.agent && <span className="ml-auto text-slate-400">{contact.agent}</span>}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── CallTile ─────────────────────────────────────────────────────────────── */
function CallTile({ call, colourClass, onClick }) {
  const [elapsed, setElapsed] = useState(call.duration || 0);
  useEffect(() => {
    const t = setInterval(() => setElapsed(s => s + 1), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <button type="button" onClick={() => onClick(call)}
      className={`group relative rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-lg cursor-pointer ${colourClass}`}>
      {/* Live badge */}
      <span className="absolute top-3 right-3 flex items-center gap-1.5 rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-medium text-rose-300">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400" />LIVE
      </span>
      <div className="flex items-center gap-2 text-xs text-slate-400 mb-2">
        {call.channel === 'CHAT' ? <MessageSquare size={13} /> : <Phone size={13} />}
        <span className="uppercase">{call.channel || 'VOICE'}</span>
        {call.escalatedFromBot && (
          <span className="flex items-center gap-1 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-300">
            <Bot size={9} />🤖→👤
          </span>
        )}
      </div>
      <p className="font-semibold text-sm text-slate-100 truncate pr-10">{call.agent || 'Unknown agent'}</p>
      <p className="text-xs text-slate-400 mt-0.5 truncate">{call.contactId}</p>
      <p className="mt-3 font-mono text-lg font-semibold text-white">{fmtDuration(elapsed)}</p>
      <p className="mt-1 text-xs text-slate-400 truncate">{call.queue || call.queueName}</p>
      {call.escalatedFromBot && call.connectedToAgentAt && (
        <p className="mt-1 flex items-center gap-1 text-[10px] text-amber-300/70">
          <Clock size={9} />Agent connected {new Date(call.connectedToAgentAt).toLocaleTimeString()}
        </p>
      )}
    </button>
  );
}

/* ─── Modal ─────────────────────────────────────────────────────────────────── */
function Modal({ call, onClose, highlightKeyword }) {
  useEffect(() => {
    const handler = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-950/80 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 flex h-[90vh] w-full max-w-3xl flex-col rounded-3xl border border-slate-700 bg-slate-900 p-6 shadow-2xl overflow-hidden">
        <TranscriptPanel contact={call} highlightKeyword={highlightKeyword} onClose={onClose} />
      </div>
    </div>
  );
}

/* ─── BotContactRow ─────────────────────────────────────────────────────────── */
function BotContactRow({ c, onClick }) {
  return (
    <button type="button" onClick={() => onClick(c)}
      className="flex w-full items-start gap-3 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3 text-left hover:border-slate-600 transition">
      <div className={`mt-0.5 rounded-xl p-2 ${c.escalatedToAgent ? 'bg-amber-500/15 text-amber-300' : 'bg-violet-500/15 text-violet-300'}`}>
        <Bot size={14} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <span className="font-mono text-slate-300 truncate">{c.contactId}</span>
          {c.escalatedToAgent && (
            <span className="flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-amber-300">
              <ArrowDownToLine size={9} />Escalated → {c.queueName}
            </span>
          )}
          {!c.escalatedToAgent && (
            <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-violet-300">Bot only</span>
          )}
          {c.inProgress && <span className="flex items-center gap-1 text-rose-300"><span className="h-1 w-1 animate-pulse rounded-full bg-rose-400" />in progress</span>}
        </div>
        <div className="flex flex-wrap gap-3 text-[11px] text-slate-400">
          <span><Clock size={10} className="inline mr-1" />{new Date(c.initiatedAt).toLocaleString()}</span>
          {c.enqueuedAt && <span>Enqueued {new Date(c.enqueuedAt).toLocaleTimeString()}</span>}
          {c.connectedToAgentAt && <span className="text-connect-300">Agent {new Date(c.connectedToAgentAt).toLocaleTimeString()}</span>}
        </div>
      </div>
    </button>
  );
}

/* ─── Main component ─────────────────────────────────────────────────────────── */
export default function TranscriptViewer({ contact, highlightKeyword, onContactClose }) {
  const [activeCalls, setActiveCalls] = useState([]);
  const [loadingCalls, setLoadingCalls] = useState(true);
  const [selectedCall, setSelectedCall] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  // EventBridge live bot contacts (from SQS pipeline)
  const [ebContacts, setEbContacts] = useState([]);
  const [ebActive, setEbActive] = useState(false);
  // Recent completed bot contacts (REST API fallback)
  const [botContacts, setBotContacts] = useState([]);
  const [botTotal, setBotTotal] = useState(0);
  const [loadingBot, setLoadingBot] = useState(true);
  const [botOpen, setBotOpen] = useState(true);
  const [botApiNote, setBotApiNote] = useState(null);
  // Integrations panel open/close
  const [integrOpen, setIntegrOpen] = useState(true);
  // Config
  const [streamsConfig, setStreamsConfig] = useState(null);

  // Connect Streams SDK hook
  const streams = useConnectStreams();
  // Hidden CCP container (invisible 1×1 iframe wrapper)
  const ccpRef = useRef(null);

  // Attach the Streams hook container ref when CCP panel mounts
  useEffect(() => {
    if (ccpRef.current) {
      streams.containerRef.current = ccpRef.current;
    }
  });

  // Fetch server-side config (for EventBridge / instance alias status)
  useEffect(() => {
    getStreamsConfig().then(setStreamsConfig).catch(() => {});
  }, []);

  // Queue → stable colour index map (merge agent calls + escalated Streams contacts)
  const queueColourMap = useMemo(() => {
    const map = {};
    let idx = 0;
    activeCalls.forEach(c => {
      const q = c.queue || 'Unknown';
      if (!(q in map)) map[q] = idx++ % queueColours.length;
    });
    return map;
  }, [activeCalls]);

  const byQueue = useMemo(() => {
    const map = {};
    activeCalls.forEach(c => {
      const q = c.queue || 'Unknown';
      if (!map[q]) map[q] = [];
      map[q].push(c);
    });
    return map;
  }, [activeCalls]);

  // Streams contacts that are NOT already in activeCalls (dedup by contactId)
  const activeCallIds = useMemo(() => new Set(activeCalls.map(c => c.contactId)), [activeCalls]);
  const streamsExtra = useMemo(() =>
    streams.contacts.filter(c => !activeCallIds.has(c.contactId)),
    [streams.contacts, activeCallIds]
  );
  // Bot-only contacts from Streams (in IVR, not yet an agent contact)
  const streamsBotContacts = useMemo(() =>
    streams.contacts.filter(c => c.isBot && !activeCallIds.has(c.contactId)),
    [streams.contacts, activeCallIds]
  );

  const fetchCalls = useCallback(async () => {
    try {
      const data = await getActiveCalls();
      setActiveCalls(data.calls || []);
      setLastRefresh(new Date());
    } catch {
      setActiveCalls([]);
    } finally {
      setLoadingCalls(false);
    }
  }, []);

  const fetchEbContacts = useCallback(async () => {
    try {
      const data = await getLiveBotContacts();
      setEbContacts(data.contacts || []);
      setEbActive(data.listener_active || false);
    } catch {
      setEbContacts([]);
    }
  }, []);

  const fetchBotContacts = useCallback(async () => {
    setLoadingBot(true);
    try {
      const data = await getRecentBotContacts(2);
      setBotContacts(data.contacts || []);
      setBotTotal(data.total || 0);
      if (data.api_limitation_note) setBotApiNote(data.api_limitation_note);
    } catch {
      setBotContacts([]);
    } finally {
      setLoadingBot(false);
    }
  }, []);

  useEffect(() => {
    fetchCalls();
    const t = setInterval(fetchCalls, POLL_MS);
    return () => clearInterval(t);
  }, [fetchCalls]);

  useEffect(() => {
    fetchEbContacts();
    const t = setInterval(fetchEbContacts, 5_000); // poll EventBridge contacts every 5 s
    return () => clearInterval(t);
  }, [fetchEbContacts]);

  useEffect(() => {
    fetchBotContacts();
    const t = setInterval(fetchBotContacts, 60_000);
    return () => clearInterval(t);
  }, [fetchBotContacts]);

  const isFromContact = selectedCall && contact?.contactId && selectedCall.contactId === contact.contactId;

  useEffect(() => {
    if (contact?.contactId) setSelectedCall(contact);
  }, [contact]);

  const handleModalClose = () => {
    setSelectedCall(null);
    if (isFromContact && onContactClose) onContactClose();
  };

  const queues = Object.keys(byQueue);
  const escalatedCount = botContacts.filter(c => c.escalatedToAgent).length;
  // Total live bot contacts visible across both Streams and EventBridge
  const liveBotCount = streamsBotContacts.length + ebContacts.filter(c => !c.escalatedToAgent).length;

  return (
    <>
      {/* ── Connect Streams + EventBridge integration panel ── */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-panel">
        <button type="button" className="flex w-full items-center justify-between" onClick={() => setIntegrOpen(v => !v)}>
          <div className="flex items-center gap-2">
            <Zap size={18} className="text-amber-400" />
            <h3 className="text-lg font-semibold">Live Bot Tracking</h3>
            {streams.connected && (
              <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-xs text-emerald-300">
                <Wifi size={10} />Streams connected
              </span>
            )}
            {ebActive && (
              <span className="flex items-center gap-1 rounded-full bg-sky-500/15 px-2.5 py-0.5 text-xs text-sky-300">
                <Zap size={10} />EventBridge active
              </span>
            )}
            {liveBotCount > 0 && (
              <span className="flex items-center gap-1 rounded-full bg-violet-500/15 px-2.5 py-0.5 text-xs text-violet-300">
                <Bot size={10} />{liveBotCount} bot{liveBotCount !== 1 ? 's' : ''} live
              </span>
            )}
          </div>
          {integrOpen ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
        </button>

        {integrOpen && (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {/* ── Connect Streams card ── */}
            <div className="rounded-2xl border border-slate-700 bg-slate-950/60 p-4">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className={`rounded-xl p-2 ${streams.connected ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-700/50 text-slate-400'}`}>
                    {streams.connected ? <Wifi size={15} /> : <WifiOff size={15} />}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-100">Connect Streams SDK</p>
                    <p className="text-xs text-slate-400">Browser real-time contact events</p>
                  </div>
                </div>
                {streams.connected ? (
                  <button type="button" onClick={streams.disconnect}
                    className="rounded-xl border border-slate-600 px-3 py-1.5 text-xs text-slate-300 hover:border-rose-500 hover:text-rose-300">
                    Disconnect
                  </button>
                ) : (
                  <button type="button" onClick={streams.connect} disabled={streams.connecting || !streams.ccpAvailable}
                    className="rounded-xl bg-connect-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-connect-700 disabled:opacity-50">
                    {streams.connecting ? 'Connecting…' : 'Connect to CCP'}
                  </button>
                )}
              </div>

              {streams.error && (
                <div className="mt-3 flex items-start gap-2 rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                  <AlertCircle size={12} className="mt-0.5 shrink-0" />{streams.error}
                </div>
              )}

              {!streams.ccpAvailable && (
                <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/8 px-3 py-2 text-xs text-amber-300">
                  <p className="font-medium">Setup required:</p>
                  <ol className="mt-1 list-decimal list-inside space-y-1 text-amber-300/80">
                    <li>Set <code className="font-mono">CONNECT_ALIAS</code> env var (your instance alias)</li>
                    <li>In Connect console → Application integrations → Approved origins, add <code className="font-mono">http://localhost:5274</code></li>
                    <li>Rebuild the container: <code className="font-mono">./deploy.sh local</code></li>
                  </ol>
                </div>
              )}

              {streams.connected && (
                <div className="mt-3 space-y-2">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Agent state</span>
                    <span className="text-slate-200">{streams.agentState || '—'}</span>
                  </div>
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Contacts visible</span>
                    <span className="text-slate-200">{streams.contacts.length}</span>
                  </div>
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Bot/IVR contacts</span>
                    <span className={streamsBotContacts.length > 0 ? 'text-violet-300' : 'text-slate-200'}>
                      {streamsBotContacts.length}
                    </span>
                  </div>
                </div>
              )}

              {/* Hidden CCP iframe container — Connect Streams mounts the CCP here */}
              <div ref={ccpRef} style={{ width: 1, height: 1, overflow: 'hidden', position: 'absolute', left: -9999 }} aria-hidden="true" />
            </div>

            {/* ── EventBridge + SQS card ── */}
            <div className="rounded-2xl border border-slate-700 bg-slate-950/60 p-4">
              <div className="flex items-center gap-2 mb-3">
                <div className={`rounded-xl p-2 ${ebActive ? 'bg-sky-500/15 text-sky-300' : 'bg-slate-700/50 text-slate-400'}`}>
                  <Zap size={15} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-100">EventBridge Pipeline</p>
                  <p className="text-xs text-slate-400">Server-side contact event stream via SQS</p>
                </div>
              </div>

              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">SQS listener</span>
                  <span className={ebActive ? 'text-emerald-300' : 'text-amber-300'}>
                    {ebActive ? '✓ Running' : '○ Not started'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Queue configured</span>
                  <span className={streamsConfig?.bot_events_queue_configured ? 'text-emerald-300' : 'text-amber-300'}>
                    {streamsConfig?.bot_events_queue_configured ? '✓ Yes' : '○ Not set'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Live bot contacts</span>
                  <span className={ebContacts.length > 0 ? 'text-violet-300 font-medium' : 'text-slate-300'}>
                    {ebContacts.length}
                  </span>
                </div>
              </div>

              {!ebActive && (
                <div className="mt-3 rounded-xl border border-sky-500/20 bg-sky-500/8 px-3 py-2 text-xs text-sky-300">
                  <p className="font-medium">Setup required:</p>
                  <ol className="mt-1 list-decimal list-inside space-y-1 text-sky-300/80">
                    <li>Deploy the EventBridge rule + SQS queue:</li>
                    <li><code className="font-mono">./deploy.sh setup-eventbridge</code></li>
                    <li>Set <code className="font-mono">BOT_EVENTS_QUEUE_URL</code> env var</li>
                    <li>Restart agent container</li>
                  </ol>
                </div>
              )}

              {ebContacts.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  {ebContacts.slice(0, 3).map(c => (
                    <button key={c.contactId} type="button" onClick={() => setSelectedCall(c)}
                      className="flex w-full items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2 text-left hover:border-violet-500/30 transition">
                      <Bot size={11} className="shrink-0 text-violet-300" />
                      <span className="font-mono text-[10px] text-slate-300 truncate flex-1">{c.contactId}</span>
                      <span className={`rounded-full px-1.5 py-0.5 text-[9px] ${c.escalatedToAgent ? 'bg-amber-500/15 text-amber-300' : 'bg-violet-500/15 text-violet-300'}`}>
                        {c.contactState}
                      </span>
                    </button>
                  ))}
                  {ebContacts.length > 3 && (
                    <p className="text-[10px] text-center text-slate-400">+{ebContacts.length - 3} more below</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Bot contacts from Streams SDK (live, not yet agent-connected) ── */}
        {streams.connected && streamsBotContacts.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 flex items-center gap-2 text-xs font-medium text-violet-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400" />
              {streamsBotContacts.length} bot contact{streamsBotContacts.length !== 1 ? 's' : ''} in IVR (live via Streams)
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {streamsBotContacts.map((c) => (
                <button key={c.contactId} type="button" onClick={() => setSelectedCall(c)}
                  className="relative rounded-2xl border border-violet-500/30 bg-violet-500/8 p-4 text-left hover:-translate-y-0.5 hover:shadow-lg transition">
                  <span className="absolute top-3 right-3 flex items-center gap-1 rounded-full bg-violet-500/20 px-2 py-0.5 text-[10px] text-violet-300">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400" />BOT
                  </span>
                  <div className="flex items-center gap-1.5 text-xs text-slate-400 mb-2">
                    <Bot size={12} className="text-violet-400" />
                    <span className="uppercase">{c.channel}</span>
                    <span>· {c.state}</span>
                  </div>
                  <p className="font-mono text-xs text-slate-300 truncate pr-12">{c.contactId}</p>
                  <p className="mt-2 text-xs text-slate-400">Handling by conversational AI bot</p>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* ── Live Active Calls (agent-connected) ── */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-panel">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h3 className="text-xl font-semibold flex items-center gap-2">
              <Radio size={20} className="text-rose-400" />
              Live Active Calls
            </h3>
            <p className="mt-1 text-sm text-slate-400">
              {activeCalls.length} agent call{activeCalls.length !== 1 ? 's' : ''} across {queues.length} queue{queues.length !== 1 ? 's' : ''}
              {lastRefresh && ` · refreshed ${Math.round((Date.now() - lastRefresh) / 1000)}s ago`}
            </p>
          </div>
          <div className="flex gap-3">
            <button type="button" onClick={fetchCalls}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-100 hover:border-connect-500">
              <RefreshCw size={16} className={loadingCalls ? 'animate-spin' : ''} />Refresh
            </button>
            <button type="button" onClick={() => setSelectedCall({})}
              className="inline-flex items-center gap-2 rounded-2xl bg-connect-500 px-4 py-3 text-sm font-medium text-white hover:bg-connect-700">
              <Search size={16} />Lookup Contact ID
            </button>
          </div>
        </div>

        <div className="mt-6">
          {loadingCalls ? (
            <div className="flex items-center justify-center gap-3 py-16 text-sm text-slate-400">
              <RefreshCw size={18} className="animate-spin" />Loading active calls…
            </div>
          ) : activeCalls.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-400">
              <Headphones size={36} className="opacity-30" />
              <p className="text-sm">No agent calls right now</p>
              {!streams.connected && <p className="text-xs text-slate-500">Connect to CCP above to also see bot-only calls</p>}
            </div>
          ) : (
            <div className="space-y-6">
              {queues.map((queue) => (
                <div key={queue}>
                  <div className="mb-3 flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${queueColours[queueColourMap[queue]]?.split(' ')[1]?.replace('bg-', 'bg-') || 'bg-connect-400'}`} />
                    <h4 className="text-sm font-semibold text-slate-300">{queue}</h4>
                    <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
                      {byQueue[queue].length} call{byQueue[queue].length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {byQueue[queue].map((call) => (
                      <CallTile
                        key={call.contactId}
                        call={call}
                        colourClass={queueColours[queueColourMap[queue]]}
                        onClick={setSelectedCall}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* ── Recent Completed Bot Contacts ── */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-panel">
        <div className="flex w-full items-center justify-between">
          <div
            role="button" tabIndex={0}
            className="flex flex-1 cursor-pointer items-center gap-2"
            onClick={() => setBotOpen(v => !v)}
            onKeyDown={(e) => e.key === 'Enter' && setBotOpen(v => !v)}
          >
            <Bot size={20} className="text-violet-400" />
            <h3 className="text-xl font-semibold">Recent Bot Contacts</h3>
            <span className="rounded-full bg-violet-500/15 px-2.5 py-0.5 text-xs text-violet-300">last 2 h · completed</span>
            {!loadingBot && botTotal > 0 && (
              <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-xs text-slate-300">{botTotal} total</span>
            )}
            {!loadingBot && escalatedCount > 0 && (
              <span className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-xs text-amber-300">
                {escalatedCount} escalated
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-slate-400">
            <button type="button" onClick={() => fetchBotContacts()}
              className="rounded-xl border border-slate-700 p-1.5 hover:border-slate-500">
              <RefreshCw size={13} className={loadingBot ? 'animate-spin' : ''} />
            </button>
            <span
              role="button" tabIndex={0} className="cursor-pointer"
              onClick={() => setBotOpen(v => !v)}
              onKeyDown={(e) => e.key === 'Enter' && setBotOpen(v => !v)}
            >
              {botOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </span>
          </div>
        </div>

        {botOpen && (
          <div className="mt-4 space-y-3">
            {loadingBot ? (
              <div className="flex items-center justify-center gap-3 py-10 text-sm text-slate-400">
                <RefreshCw size={16} className="animate-spin" />Loading bot contacts…
              </div>
            ) : botContacts.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 py-10 text-slate-400">
                <Bot size={28} className="opacity-30" />
                <p className="text-sm">No completed bot contacts in the last 2 hours</p>
              </div>
            ) : (
              <div className="space-y-2">
                {botContacts.map((c) => (
                  <BotContactRow key={c.contactId} c={c} onClick={setSelectedCall} />
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* ── Modal ── */}
      {selectedCall && (
        <Modal call={selectedCall} highlightKeyword={highlightKeyword} onClose={handleModalClose} />
      )}
    </>
  );
}
