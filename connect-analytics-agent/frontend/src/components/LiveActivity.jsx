/**
 * LiveActivity — real-time contact centre activity dashboard.
 *
 * Polls three EventBridge-backed endpoints every 5 seconds:
 *   GET /live-contacts   → all active contacts, grouped by type + callbacks-by-queue
 *   GET /live-callbacks  → callbacks detail (waiting + scheduled, per queue)
 *   GET /live-outbound   → outbound calls with customer + agent info
 *
 * Sections:
 *   1. Summary KPI row
 *   2. Callbacks Waiting (queue breakdown table)
 *   3. Outbound Calls (per-agent, with masked customer number)
 *   4. Bot / IVR Contacts
 *   5. Inbound & Transfers
 *   6. Setup instructions when EventBridge is not yet configured
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity,
  ArrowDownLeft,
  ArrowUpRight,
  Bot,
  Calendar,
  Clock,
  Hash,
  Headphones,
  Network,
  Phone,
  PhoneCall,
  PhoneForwarded,
  PhoneIncoming,
  PhoneMissed,
  PhoneOff,
  PhoneOutgoing,
  RefreshCw,
  Terminal,
  User,
  Users,
  Wifi,
  WifiOff,
  Zap,
} from 'lucide-react';
import { getLiveContacts, getLiveCallbacks, getLiveOutbound } from '../services/api';
import ContactFlowGraph from './ContactFlowGraph';

// ── helpers ──────────────────────────────────────────────────────────────────

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
};

const fmtRelative = (iso) => {
  if (!iso) return '—';
  try {
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ${diff % 60}s ago`;
    return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m ago`;
  } catch {
    return '—';
  }
};

/** For a terminal contact, show when it ended (not how long it was started). */
const fmtContactTime = (contact) => {
  if (contact.contactTerminal && contact.contactEndedAt) {
    return `Ended ${fmtRelative(contact.contactEndedAt)}`;
  }
  return fmtRelative(contact.initiatedAt);
};

const channelIcon = (channel) => {
  switch ((channel || '').toUpperCase()) {
    case 'VOICE': return <Phone size={13} />;
    case 'CHAT':  return <Headphones size={13} />;
    case 'TASK':  return <Terminal size={13} />;
    default:      return <PhoneCall size={13} />;
  }
};

const stateColour = (state) => {
  switch ((state || '').toUpperCase()) {
    case 'INITIATED':            return 'bg-blue-500/15 text-blue-400';
    case 'QUEUED':               return 'bg-amber-500/15 text-amber-400';
    case 'CALLBACK_SCHEDULED':   return 'bg-purple-500/15 text-purple-400';
    case 'CONNECTED_TO_SYSTEM':  return 'bg-cyan-500/15 text-cyan-400';
    case 'CONNECTED_TO_AGENT':   return 'bg-emerald-500/15 text-emerald-400';
    case 'DISCONNECTED':
    case 'ENDED':                return 'bg-slate-500/15 text-slate-400';
    case 'MISSED':
    case 'ERROR':
    case 'REJECTED':             return 'bg-red-500/15 text-red-400';
    default:                     return 'bg-slate-500/15 text-slate-400';
  }
};

// ── sub-components ────────────────────────────────────────────────────────────

function KpiCard({ label, value, icon: Icon, colour = 'text-connect-400', sub }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">{label}</span>
        <Icon size={16} className={colour} />
      </div>
      <p className={`mt-2 text-3xl font-bold ${colour}`}>{value ?? '—'}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function StateBadge({ state }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${stateColour(state)}`}>
      {state || '—'}
    </span>
  );
}

function EndpointPill({ ep, label }) {
  if (!ep || !ep.display) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-slate-800 px-2 py-0.5 text-xs font-mono text-slate-300" title={`${label}: ${ep.address || ep.display}`}>
      <Phone size={10} className="text-slate-500" />
      {ep.display}
    </span>
  );
}

// UUID pattern — 8-4-4-4-12 hex chars
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Returns true if the string looks like a raw UUID rather than a human-readable name */
const isRawId = (s) => !s || UUID_RE.test(s.trim());

function ContactRow({ contact, onJourneyClick, journeyActive }) {
  const ce = contact.customerEndpoint || {};
  const se = contact.systemEndpoint   || {};

  // Queue name: prefer human-readable name; fall back to last 8 chars of ID while lookup pending
  const rawQueue = contact.queueName && contact.queueName !== '—' ? contact.queueName : null;
  const queueLabel = rawQueue && !isRawId(rawQueue)
    ? rawQueue
    : (contact.queueId ? `…${contact.queueId.slice(-8)}` : '—');
  const queuePending = !rawQueue || isRawId(rawQueue);  // still resolving

  // Agent name: prefer human-readable name; fall back to last 8 chars of ARN segment
  const rawAgent = contact.agentName || '';
  const agentLabel = rawAgent && !isRawId(rawAgent)
    ? rawAgent
    : (contact.agentArn ? `…${contact.agentArn.split('/').pop().slice(-8)}` : '');
  const agentPending = !rawAgent || isRawId(rawAgent);

  const isEnded = !!contact.contactTerminal;

  return (
    <tr className={`border-t border-slate-800/60 transition ${isEnded ? 'opacity-40' : 'hover:bg-slate-800/30'}`}>
      <td className="px-3 py-2 font-mono text-xs text-slate-400">
        <span>{contact.contactId?.slice(-8)}</span>
        {isEnded && (
          <span className="ml-1.5 rounded-full bg-slate-700 px-1.5 py-0.5 text-[9px] text-slate-400 uppercase tracking-wide">ended</span>
        )}
      </td>
      <td className="px-3 py-2">
        <span className="inline-flex items-center gap-1 text-xs text-slate-300">
          {channelIcon(contact.channel)} {contact.channel}
        </span>
      </td>
      <td className="px-3 py-2"><StateBadge state={contact.contactState} /></td>
      <td className="px-3 py-2 text-xs">
        {contact.escalatedToAgent
          ? (
            <span className={`flex items-center gap-1 ${agentPending ? 'text-emerald-300/60' : 'text-emerald-300'}`}>
              <User size={10} />
              {agentLabel}
              {agentPending && <span className="text-[9px] text-emerald-300/40">(resolving…)</span>}
            </span>
          )
          : (
            <span className={`flex items-center gap-0.5 ${queuePending ? 'text-slate-400' : 'text-slate-300'}`}>
              {queueLabel}
              {queuePending && contact.queueId && (
                <span className="text-[9px] text-slate-500">(resolving…)</span>
              )}
            </span>
          )
        }
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-col gap-0.5">
          {ce.display && <EndpointPill ep={ce} label="Customer" />}
          {se.display && se.display !== ce.display && (
            <span className="text-[10px] text-slate-500 font-mono">via {se.display}</span>
          )}
        </div>
      </td>
      <td className={`px-3 py-2 text-xs ${isEnded ? 'text-slate-500' : 'text-slate-400'}`}>
        {fmtContactTime(contact)}
      </td>
      <td className="px-3 py-2">
        <button
          type="button"
          onClick={() => onJourneyClick(contact.contactId)}
          className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[10px] font-medium transition ${
            journeyActive
              ? 'bg-indigo-600 text-white'
              : 'bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20'
          }`}
          title="View flow journey for this contact"
        >
          <Network size={9} />
          Journey
        </button>
      </td>
    </tr>
  );
}

function OutboundRow({ contact }) {
  const ce = contact.customerEndpoint || {};
  const se = contact.systemEndpoint   || {};
  const agentName = contact.outboundAgentName || contact.agentName || contact.outboundAgentArn?.split('/').pop() || '—';
  return (
    <tr className="border-t border-slate-800/60 hover:bg-slate-800/30 transition">
      <td className="px-3 py-2 font-mono text-xs text-slate-400">{contact.contactId?.slice(-8)}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-1.5 text-xs text-slate-200">
          <User size={12} className="text-slate-400" />
          {agentName}
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-col gap-0.5">
          {ce.display
            ? <EndpointPill ep={ce} label="Dialling" />
            : <span className="text-xs text-slate-500">—</span>}
          {se.display && (
            <span className="text-[10px] text-slate-500 font-mono">from {se.display}</span>
          )}
        </div>
      </td>
      <td className="px-3 py-2"><StateBadge state={contact.contactState} /></td>
      <td className="px-3 py-2 text-xs text-slate-400">
        {contact.initiationMethod === 'EXTERNAL_OUTBOUND' ? (
          <span className="text-[10px] bg-orange-500/10 text-orange-400 rounded px-1.5 py-0.5">Campaign</span>
        ) : (
          <span className="text-[10px] bg-slate-700 text-slate-300 rounded px-1.5 py-0.5">Agent</span>
        )}
      </td>
      <td className="px-3 py-2 text-xs text-slate-400">{fmtContactTime(contact)}</td>
    </tr>
  );
}

function CallbackRow({ contact }) {
  const ce = contact.customerEndpoint || {};
  return (
    <tr className="border-t border-slate-800/60 hover:bg-slate-800/30 transition">
      <td className="px-3 py-2 font-mono text-xs text-slate-400">{contact.contactId?.slice(-8)}</td>
      <td className="px-3 py-2 text-xs text-slate-300">{contact.queueName || '—'}</td>
      <td className="px-3 py-2">
        {ce.display
          ? <EndpointPill ep={ce} label="Customer" />
          : <span className="text-xs text-slate-500">—</span>}
      </td>
      <td className="px-3 py-2">
        {contact.callbackScheduled ? (
          <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium bg-purple-500/15 text-purple-400">
            <Calendar size={10} /> Scheduled
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium bg-amber-500/15 text-amber-400">
            <Clock size={10} /> Waiting
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-xs text-slate-400">{fmtRelative(contact.initiatedAt)}</td>
    </tr>
  );
}

function SectionHeader({ icon: Icon, title, count, colour = 'text-slate-300' }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon size={16} className={colour} />
      <h3 className={`text-sm font-semibold ${colour}`}>{title}</h3>
      {count !== undefined && (
        <span className="ml-1 rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-300">{count}</span>
      )}
    </div>
  );
}

function TableWrapper({ children, cols }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-800/50">
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 text-xs font-medium text-slate-400">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function EmptyRow({ cols, message }) {
  return (
    <tr>
      <td colSpan={cols} className="px-3 py-6 text-center text-xs text-slate-500">{message}</td>
    </tr>
  );
}

// ── Callbacks-by-queue breakdown ──────────────────────────────────────────────
function CallbacksByQueue({ byQueue }) {
  const entries = Object.entries(byQueue || {});
  if (!entries.length) return (
    <p className="text-xs text-slate-500 py-2">No callbacks in any queue right now.</p>
  );
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-800/50">
          <tr>
            {['Queue', 'Waiting for Agent', 'Scheduled (not yet fired)', 'Total'].map((c) => (
              <th key={c} className="px-3 py-2 text-xs font-medium text-slate-400">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map(([q, counts]) => (
            <tr key={q} className="border-t border-slate-800/60 hover:bg-slate-800/30 transition">
              <td className="px-3 py-2 text-xs font-medium text-slate-200">{q}</td>
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-1 text-xs text-amber-400">
                  <Clock size={11} /> {counts.waiting}
                </span>
              </td>
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-1 text-xs text-purple-400">
                  <Calendar size={11} /> {counts.scheduled}
                </span>
              </td>
              <td className="px-3 py-2 text-xs font-semibold text-slate-300">
                {(counts.waiting || 0) + (counts.scheduled || 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Setup banner ──────────────────────────────────────────────────────────────
function SetupBanner() {
  return (
    <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-center">
      <WifiOff size={36} className="mx-auto mb-3 text-slate-600" />
      <h3 className="text-sm font-semibold text-slate-300 mb-1">EventBridge listener not active</h3>
      <p className="text-xs text-slate-500 max-w-md mx-auto mb-4">
        Live activity requires an EventBridge rule forwarding Amazon Connect Contact Events to SQS.
        Run the one-time setup below, then set <code className="bg-slate-800 px-1 rounded">BOT_EVENTS_QUEUE_URL</code> and restart.
      </p>
      <div className="inline-flex flex-col items-start gap-1 rounded-xl bg-slate-950 px-4 py-3 font-mono text-xs text-emerald-400 text-left">
        <span className="text-slate-500"># one-time setup</span>
        <span>./deploy.sh setup-eventbridge</span>
        <span className="text-slate-500 mt-1"># then export + restart</span>
        <span>export BOT_EVENTS_QUEUE_URL=&lt;queue-url-from-above&gt;</span>
        <span>./deploy.sh local</span>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function LiveActivity({ darkMode }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [journeyContactId, setJourneyContactId] = useState(null);
  const timerRef = useRef(null);

  const toggleJourney = useCallback((contactId) => {
    setJourneyContactId((prev) => (prev === contactId ? null : contactId));
  }, []);

  const fetchAll = useCallback(async () => {
    try {
      const [contacts] = await Promise.all([getLiveContacts()]);
      setData(contacts);
      setLastRefresh(new Date());
      setError(null);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load live activity');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    timerRef.current = setInterval(fetchAll, 5000);
    return () => clearInterval(timerRef.current);
  }, [fetchAll]);

  const card = `rounded-2xl border p-5 ${darkMode ? 'border-slate-800 bg-slate-900/70' : 'border-slate-200 bg-white/85'}`;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <RefreshCw size={22} className="animate-spin text-connect-500 mr-3" />
        <span className="text-slate-400 text-sm">Loading live activity…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`${card} text-center py-10`}>
        <p className="text-sm text-red-400 mb-2">{error}</p>
        <button onClick={fetchAll} className="text-xs text-slate-400 underline">Retry</button>
      </div>
    );
  }

  const listenerActive = data?.listener_active;
  const summary        = data?.summary || {};
  const inbound        = data?.inbound || [];
  const outbound       = data?.outbound || [];
  const callbacks      = data?.callbacks || [];
  const botContacts    = data?.bot_contacts || [];
  const transfers      = data?.transfers || [];
  const cbByQueue      = data?.callbacks_by_queue || {};

  const waiting   = callbacks.filter(c => !c.callbackScheduled);
  const scheduled = callbacks.filter(c =>  c.callbackScheduled);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className={`${card} flex items-center justify-between`}>
        <div className="flex items-center gap-3">
          <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${listenerActive ? 'bg-emerald-500/15' : 'bg-slate-700/40'}`}>
            {listenerActive ? <Wifi size={20} className="text-emerald-400" /> : <WifiOff size={20} className="text-slate-500" />}
          </div>
          <div>
            <h2 className="text-base font-semibold">Live Contact Centre Activity</h2>
            <p className="text-xs text-slate-400">
              {listenerActive
                ? `EventBridge listener active · refreshes every 5s`
                : 'EventBridge listener not configured'}
              {lastRefresh && (
                <span className="ml-2 text-slate-500">· last updated {fmtTime(lastRefresh.toISOString())}</span>
              )}
            </p>
          </div>
        </div>
        <button
          onClick={fetchAll}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-slate-300 hover:bg-slate-700 transition"
        >
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {!listenerActive && <SetupBanner />}

      {listenerActive && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
            <KpiCard label="Total Active"          value={summary.total}               icon={Activity}       colour="text-connect-400" />
            <KpiCard label="Inbound"               value={summary.inbound}             icon={PhoneIncoming}  colour="text-blue-400" />
            <KpiCard label="Outbound"              value={summary.outbound}            icon={PhoneOutgoing}  colour="text-orange-400" />
            <KpiCard label="Callbacks Waiting"     value={summary.callbacks_waiting}   icon={PhoneForwarded} colour="text-amber-400" />
            <KpiCard label="Callbacks Scheduled"   value={summary.callbacks_scheduled} icon={Calendar}       colour="text-purple-400" />
            <KpiCard label="Bot / IVR"             value={summary.bot_handling}        icon={Bot}            colour="text-cyan-400" />
            <KpiCard label="With Agent"            value={summary.agent_connected}     icon={Headphones}     colour="text-emerald-400" />
            <KpiCard label="Transfers"             value={summary.transfers}           icon={PhoneMissed}    colour="text-slate-400" />
          </div>

          {/* Channel breakdown */}
          <div className="grid grid-cols-3 gap-3">
            <KpiCard label="Voice" value={summary.voice} icon={Phone}     colour="text-blue-300" />
            <KpiCard label="Chat"  value={summary.chat}  icon={Headphones} colour="text-violet-300" />
            <KpiCard label="Task"  value={summary.task}  icon={Terminal}   colour="text-slate-300" />
          </div>

          {/* Callbacks section */}
          <div className={card}>
            <SectionHeader icon={PhoneForwarded} title="Callbacks" count={callbacks.length} colour="text-amber-400" />
            <p className="text-xs text-slate-500 mb-4">
              <span className="text-amber-400 font-medium">{waiting.length} waiting</span> for an agent ·{' '}
              <span className="text-purple-400 font-medium">{scheduled.length} scheduled</span> (not yet fired)
            </p>

            <div className="mb-4">
              <p className="text-xs font-medium text-slate-400 mb-2 uppercase tracking-wide">By Queue</p>
              <CallbacksByQueue byQueue={cbByQueue} />
            </div>

            {callbacks.length > 0 && (
              <>
                <p className="text-xs font-medium text-slate-400 mb-2 uppercase tracking-wide">All Callback Contacts</p>
                <TableWrapper cols={['Contact ID', 'Queue', 'Customer Number', 'Status', 'Started']}>
                  {callbacks.map(c => <CallbackRow key={c.contactId} contact={c} />)}
                </TableWrapper>
              </>
            )}
          </div>

          {/* Outbound calls */}
          <div className={card}>
            <SectionHeader icon={PhoneOutgoing} title="Outbound Calls" count={outbound.length} colour="text-orange-400" />
            {outbound.length === 0 ? (
              <p className="text-xs text-slate-500">No active outbound calls.</p>
            ) : (
              <TableWrapper cols={['Contact ID', 'Agent', 'Customer / System Number', 'State', 'Type', 'Started']}>
                {outbound.map(c => <OutboundRow key={c.contactId} contact={c} />)}
              </TableWrapper>
            )}
          </div>

          {/* Bot / IVR */}
          <div className={card}>
            <SectionHeader icon={Bot} title="Bot / IVR Handling" count={botContacts.filter(c => !c.contactTerminal).length} colour="text-cyan-400" />
            {botContacts.filter(c => !c.contactTerminal).length === 0 ? (
              <p className="text-xs text-slate-500">No contacts currently in IVR or bot handling.</p>
            ) : (
              <TableWrapper cols={['Contact ID', 'Channel', 'State', 'Queue', 'Customer', 'Started', 'Journey']}>
                {botContacts.map(c => (
                  <ContactRow
                    key={c.contactId}
                    contact={c}
                    onJourneyClick={toggleJourney}
                    journeyActive={journeyContactId === c.contactId}
                  />
                ))}
              </TableWrapper>
            )}
          </div>

          {/* Inbound & transfers */}
          <div className={card}>
            <SectionHeader
              icon={PhoneIncoming}
              title="Inbound Contacts"
              count={[...inbound, ...transfers].filter(c => !c.contactTerminal).length}
              colour="text-blue-400"
            />
            <TableWrapper cols={['Contact ID', 'Channel', 'State', 'Queue / Agent', 'Customer', 'Time', 'Journey']}>
              {[...inbound, ...transfers].length === 0 && (
                <EmptyRow cols={7} message="No inbound contacts right now." />
              )}
              {[...inbound, ...transfers].map(c => (
                <ContactRow
                  key={c.contactId}
                  contact={c}
                  onJourneyClick={toggleJourney}
                  journeyActive={journeyContactId === c.contactId}
                />
              ))}
            </TableWrapper>
          </div>

          {/* Live journey panel — shown below tables when a contact is selected */}
          {journeyContactId && (
            <ContactFlowGraph
              contactId={journeyContactId}
              live={!([...inbound, ...transfers, ...botContacts].find(c => c.contactId === journeyContactId)?.contactTerminal)}
              onClose={() => setJourneyContactId(null)}
            />
          )}
        </>
      )}
    </div>
  );
}
