import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Search,
  RefreshCw,
  AlertCircle,
  Mic,
  MessageSquare,
  Video,
  FileText,
  Ban,
  CalendarDays,
  Network,
  ChevronDown,
  ChevronUp,
  Phone,
  Hash,
  X,
  Layers,
  Filter,
  Tag,
  Gauge,
  Sparkles,
} from 'lucide-react';
import { searchContacts, getQueues, getAgentsForSearch, getContactMetrics } from '../services/api';
import ContactFlowGraph from './ContactFlowGraph';

const CHANNEL_OPTIONS = [
  { value: 'VOICE', label: 'Voice', icon: Mic },
  { value: 'CHAT', label: 'Chat', icon: MessageSquare },
  { value: 'TASK', label: 'Task', icon: Layers },
];

const METHOD_OPTIONS = [
  { value: 'INBOUND', label: 'Inbound' },
  { value: 'OUTBOUND', label: 'Outbound' },
  { value: 'TRANSFER', label: 'Transfer' },
  { value: 'QUEUE_TRANSFER', label: 'Queue Transfer' },
  { value: 'CALLBACK', label: 'Callback' },
  { value: 'API', label: 'API' },
];

const TIME_RANGE_OPTIONS = [
  { value: 'INITIATION_TIMESTAMP', label: 'Initiation time' },
  { value: 'CONNECTED_TO_AGENT_TIMESTAMP', label: 'Connected to agent' },
  { value: 'DISCONNECT_TIMESTAMP', label: 'Disconnect time' },
];

const STATUS_OPTIONS = ['All', 'CONNECTED', 'CONNECTING', 'INCOMING', 'MISSED', 'REJECTED', 'ENDED'];

function formatDuration(totalSeconds) {
  const seconds = Number(totalSeconds || 0);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${remainingSeconds}s`;
  return `${remainingSeconds}s`;
}

function AvailabilityBadge({ hasRecording, channel, status }) {
  const isEnded = status === 'ENDED';
  const isVoice = channel === 'VOICE';
  const isChat = channel === 'CHAT';

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {isVoice && isEnded && (
        hasRecording ? (
          <span title="Recording available" className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
            <Video size={9} /> Recording
          </span>
        ) : (
          <span title="No recording found" className="inline-flex items-center gap-1 rounded-full bg-slate-200/60 dark:bg-slate-700/60 px-2 py-0.5 text-[10px] font-medium text-slate-600 dark:text-slate-500">
            <Ban size={9} /> No recording
          </span>
        )
      )}
      {isEnded && (isVoice || isChat) && (
        <span
          title={isVoice ? 'Automated interaction log available (conversational AI transcript)' : 'Chat transcript available in S3'}
          className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400"
        >
          <FileText size={9} /> Transcript
        </span>
      )}
      {!isEnded && <span className="text-xs text-slate-600 dark:text-slate-500">Live / in progress</span>}
    </div>
  );
}

function ChannelBadge({ channel }) {
  const option = CHANNEL_OPTIONS.find((item) => item.value === channel);
  const Icon = option?.icon || Layers;
  const styles = {
    VOICE: 'bg-sky-500/15 text-sky-600 dark:text-sky-300 border-sky-500/30',
    CHAT: 'bg-violet-500/15 text-violet-600 dark:text-violet-300 border-violet-500/30',
    TASK: 'bg-amber-500/15 text-amber-600 dark:text-amber-300 border-amber-500/30',
  };

  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-medium ${styles[channel] || 'border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300'}`}>
      <Icon size={10} /> {option?.label || channel || '—'}
    </span>
  );
}

function MethodBadge({ method }) {
  const label = METHOD_OPTIONS.find((item) => item.value === method)?.label || method || '—';
  return (
    <span className="inline-flex items-center rounded-full border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 py-1 text-[11px] font-medium text-slate-700 dark:text-slate-300">
      {label}
    </span>
  );
}

function AttributesBadge({ phoneNumber, customAttributes }) {
  const entries = Object.entries(customAttributes || {}).filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '');

  if (!phoneNumber && entries.length === 0) {
    return <span className="text-slate-600 dark:text-slate-500">—</span>;
  }

  return (
    <div className="group relative inline-flex max-w-xs flex-wrap gap-2">
      {phoneNumber && (
        <span className="inline-flex max-w-[12rem] items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-300">
          <Phone size={10} />
          <span className="truncate">{phoneNumber}</span>
        </span>
      )}
      {entries.length > 0 && (
        <>
          <span tabIndex={0} className="inline-flex items-center gap-1 rounded-full border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 py-1 text-[11px] font-medium text-slate-800 dark:text-slate-200 outline-none">
            <Tag size={10} /> Attrs {entries.length}
          </span>
          <div className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden min-w-[18rem] rounded-2xl border border-slate-300 dark:border-slate-700 bg-white/95 dark:bg-slate-950/95 p-3 text-xs text-slate-800 dark:text-slate-200 shadow-2xl group-hover:block group-focus-within:block">
            <p className="mb-2 font-medium text-slate-900 dark:text-white">Custom attributes</p>
            <div className="space-y-1.5">
              {phoneNumber && (
                <div className="flex items-start justify-between gap-3 border-b border-slate-200 dark:border-slate-800 pb-1.5 text-slate-700 dark:text-slate-300">
                  <span className="font-medium text-slate-500 dark:text-slate-400">CustomerEndpoint</span>
                  <span className="break-all text-right">{phoneNumber}</span>
                </div>
              )}
              {entries.map(([key, value]) => (
                <div key={key} className="flex items-start justify-between gap-3 border-b border-slate-200 dark:border-slate-800 pb-1.5 last:border-b-0 last:pb-0">
                  <span className="font-medium text-slate-500 dark:text-slate-400">{key}</span>
                  <span className="break-all text-right">{String(value)}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function LoadingRows() {
  return Array.from({ length: 5 }).map((_, index) => (
    <tr key={`loading-${index}`} className="animate-pulse">
      {Array.from({ length: 11 }).map((__, cellIndex) => (
        <td key={cellIndex} className="px-4 py-4">
          <div className="h-4 rounded bg-slate-100 dark:bg-slate-800" />
        </td>
      ))}
    </tr>
  ));
}

// ── Contact Lens metrics panel ────────────────────────────────────────────────
// The same conversation analytics the Contact Lens page shows in the Connect
// console: talk time split, non-talk time, interruptions, talk speed, sentiment.
function sentimentBadge(score) {
  if (score == null) return { label: '—', cls: 'bg-slate-500/10 text-slate-500' };
  const val = Number(score);
  if (val >= 1) return { label: `+${val}`, cls: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' };
  if (val <= -1) return { label: `${val}`, cls: 'bg-rose-500/15 text-rose-700 dark:text-rose-300' };
  return { label: `${val}`, cls: 'bg-slate-500/15 text-slate-600 dark:text-slate-300' };
}

function ContactLensMetricsPanel({ contactId, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    getContactMetrics(contactId)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e?.response?.data?.detail || e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [contactId]);

  const m = data?.metrics;
  const talkTotal = m?.talk_time_s?.total ?? 0;
  const nonTalk = m?.non_talk_time_s ?? 0;
  const convTotal = talkTotal + nonTalk;
  const agentPct = talkTotal > 0 ? Math.round(((m?.talk_time_s?.agent ?? 0) / talkTotal) * 100) : 0;
  const talkPct = convTotal > 0 ? Math.round((talkTotal / convTotal) * 100) : 0;
  const agentSent = sentimentBadge(m?.sentiment?.agent);
  const custSent = sentimentBadge(m?.sentiment?.customer);

  return (
    <div className="mt-4 rounded-3xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-900/70 p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-2">
          <Gauge size={14} className="text-connect-700 dark:text-connect-400" />
          Contact Lens metrics — <span className="font-mono text-slate-500 dark:text-slate-400">…{contactId.slice(-12)}</span>
          {data?.mock && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">mock data</span>}
        </p>
        <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"><X size={14} /></button>
      </div>

      {loading && <p className="py-4 text-sm text-slate-500 dark:text-slate-400">Loading Contact Lens analysis…</p>}
      {error && <p className="py-4 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
      {!loading && !error && data && !data.available && (
        <p className="py-4 text-sm text-slate-600 dark:text-slate-400">{data.message}</p>
      )}

      {!loading && !error && m && (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-4">
            <div>
              <div className="flex justify-between text-xs text-slate-600 dark:text-slate-400 mb-1">
                <span>Talk time vs non-talk time</span>
                <span className="tabular-nums">{formatDuration(talkTotal)} talk · {formatDuration(nonTalk)} non-talk</span>
              </div>
              <div className="flex h-3 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" title={`${talkPct}% of the conversation was talk time`}>
                <div className="bg-sky-500/80" style={{ width: `${talkPct}%` }} />
                <div className="bg-slate-400/60" style={{ width: `${100 - talkPct}%` }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between text-xs text-slate-600 dark:text-slate-400 mb-1">
                <span>Talk time split — agent vs customer</span>
                <span className="tabular-nums">
                  {formatDuration(m.talk_time_s?.agent ?? 0)} agent · {formatDuration(m.talk_time_s?.customer ?? 0)} customer
                </span>
              </div>
              <div className="flex h-3 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" title={`Agent spoke ${agentPct}% of talk time`}>
                <div className="bg-emerald-500/80" style={{ width: `${agentPct}%` }} />
                <div className="bg-indigo-500/70" style={{ width: `${100 - agentPct}%` }} />
              </div>
              <div className="mt-1 flex gap-3 text-[10px] text-slate-500 dark:text-slate-400">
                <span><span className="inline-block h-2 w-2 rounded-full bg-emerald-500/80 mr-1" />Agent {agentPct}%</span>
                <span><span className="inline-block h-2 w-2 rounded-full bg-indigo-500/70 mr-1" />Customer {100 - agentPct}%</span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 content-start">
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">Interruptions</p>
              <p className="mt-1 text-sm text-slate-800 dark:text-slate-200 tabular-nums">
                {m.interruptions?.agent ?? 0} by agent · {m.interruptions?.customer ?? 0} by customer
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">Talk speed (wpm)</p>
              <p className="mt-1 text-sm text-slate-800 dark:text-slate-200 tabular-nums">
                {m.talk_speed_wpm?.agent ?? '—'} agent · {m.talk_speed_wpm?.customer ?? '—'} customer
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">Sentiment (−5…+5)</p>
              <p className="mt-1 flex items-center gap-2 text-sm">
                <span className={`rounded-lg px-2 py-0.5 text-xs font-medium ${agentSent.cls}`}>agent {agentSent.label}</span>
                <span className={`rounded-lg px-2 py-0.5 text-xs font-medium ${custSent.cls}`}>customer {custSent.label}</span>
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">Conversation duration</p>
              <p className="mt-1 text-sm text-slate-800 dark:text-slate-200 tabular-nums">
                {formatDuration(m.total_duration_s ?? convTotal)}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ContactSearch({ onAskQuery, onSelectContact }) {
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [journeyContactId, setJourneyContactId] = useState(null);
  const [metricsContactId, setMetricsContactId] = useState(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [queues, setQueues] = useState([]);
  const [agents, setAgents] = useState([]);
  const [queuesLoading, setQueuesLoading] = useState(true);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [queuesError, setQueuesError] = useState(false);
  const [agentsError, setAgentsError] = useState(false);
  const [filters, setFilters] = useState({
    start: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString().slice(0, 16),
    end: new Date().toISOString().slice(0, 16),
    timeRangeType: 'INITIATION_TIMESTAMP',
    status: 'All',
    channels: [],
    initiationMethods: [],
    queueId: '',
    agentId: '',
    contactId: '',
    phoneNumber: '',
    minMinutes: '',
    maxMinutes: '',
    sortOrder: 'DESCENDING',
    customAttributes: [],
  });
  const [page, setPage] = useState(1);
  const pageSize = 10;

  useEffect(() => {
    let active = true;

    const loadOptions = async () => {
      setQueuesLoading(true);
      setAgentsLoading(true);

      const [queuesResult, agentsResult] = await Promise.allSettled([
        getQueues(),
        getAgentsForSearch(),
      ]);

      if (!active) return;

      if (queuesResult.status === 'fulfilled') {
        setQueues(queuesResult.value?.queues || []);
        setQueuesError(false);
      } else {
        setQueues([]);
        setQueuesError(true);
      }
      setQueuesLoading(false);

      if (agentsResult.status === 'fulfilled') {
        setAgents(agentsResult.value?.agents || []);
        setAgentsError(false);
      } else {
        setAgents([]);
        setAgentsError(true);
      }
      setAgentsLoading(false);
    };

    loadOptions();

    return () => {
      active = false;
    };
  }, []);

  const queueLabelById = useMemo(() => Object.fromEntries(queues.map((queue) => [queue.id, queue.name])), [queues]);
  const agentLabelById = useMemo(() => Object.fromEntries(agents.map((agent) => [agent.id, agent.name])), [agents]);

  const buildParams = useCallback((sourceFilters) => {
    const params = {
      start: sourceFilters.start ? new Date(sourceFilters.start).toISOString() : undefined,
      end: sourceFilters.end ? new Date(sourceFilters.end).toISOString() : undefined,
      time_range_type: sourceFilters.timeRangeType !== 'INITIATION_TIMESTAMP' ? sourceFilters.timeRangeType : undefined,
      contact_status: sourceFilters.status !== 'All' ? sourceFilters.status : undefined,
      channels: sourceFilters.channels.length ? sourceFilters.channels.join(',') : undefined,
      initiation_methods: sourceFilters.initiationMethods.length ? sourceFilters.initiationMethods.join(',') : undefined,
      queue_ids: sourceFilters.queueId || undefined,
      agent_ids: sourceFilters.agentId || undefined,
      contact_id: sourceFilters.contactId.trim() || undefined,
      phone_number: sourceFilters.phoneNumber.trim() || undefined,
      min_duration_seconds: sourceFilters.minMinutes ? Number(sourceFilters.minMinutes) * 60 : undefined,
      max_duration_seconds: sourceFilters.maxMinutes ? Number(sourceFilters.maxMinutes) * 60 : undefined,
      sort_order: sourceFilters.sortOrder === 'ASCENDING' ? 'ASCENDING' : undefined,
      searchable_attributes: sourceFilters.customAttributes.filter((attribute) => attribute.key && attribute.value).length
        ? JSON.stringify(sourceFilters.customAttributes.filter((attribute) => attribute.key && attribute.value).map((attribute) => ({ key: attribute.key, values: [attribute.value] })))
        : undefined,
      max_results: 100,
    };

    Object.keys(params).forEach((key) => params[key] === undefined && delete params[key]);
    return params;
  }, []);

  const runSearch = useCallback(async (sourceFilters = filters) => {
    setLoading(true);
    setError(null);
    setHasSearched(true);
    setPage(1);
    try {
      const data = await searchContacts(buildParams(sourceFilters));
      setContacts(data.contacts || []);
    } catch {
      setError('Could not search contacts. Check your AWS credentials and Connect instance ID.');
      setContacts([]);
    } finally {
      setLoading(false);
    }
  }, [buildParams, filters]);

  const applyQuickRange = useCallback((days) => {
    const now = new Date();
    const start = new Date(now);
    if (days === 0) {
      start.setHours(0, 0, 0, 0);
    } else {
      start.setDate(start.getDate() - days);
    }
    const nextFilters = {
      ...filters,
      start: start.toISOString().slice(0, 16),
      end: now.toISOString().slice(0, 16),
    };
    setFilters(nextFilters);
    runSearch(nextFilters);
  }, [filters, runSearch]);

  const toggleFilterValue = useCallback((key, value) => {
    setFilters((current) => ({
      ...current,
      [key]: current[key].includes(value)
        ? current[key].filter((item) => item !== value)
        : [...current[key], value],
    }));
  }, []);

  const activeFilterChips = useMemo(() => {
    const chips = [];

    if (filters.timeRangeType !== 'INITIATION_TIMESTAMP') {
      chips.push({
        key: 'timeRangeType',
        label: `Time range: ${TIME_RANGE_OPTIONS.find((item) => item.value === filters.timeRangeType)?.label || filters.timeRangeType}`,
        onRemove: () => setFilters((current) => ({ ...current, timeRangeType: 'INITIATION_TIMESTAMP' })),
      });
    }
    if (filters.status !== 'All') {
      chips.push({
        key: 'status',
        label: `Status: ${filters.status}`,
        onRemove: () => setFilters((current) => ({ ...current, status: 'All' })),
      });
    }
    filters.channels.forEach((channel) => chips.push({
      key: `channel-${channel}`,
      label: `Channel: ${CHANNEL_OPTIONS.find((item) => item.value === channel)?.label || channel}`,
      onRemove: () => setFilters((current) => ({ ...current, channels: current.channels.filter((item) => item !== channel) })),
    }));
    filters.initiationMethods.forEach((method) => chips.push({
      key: `method-${method}`,
      label: `Method: ${METHOD_OPTIONS.find((item) => item.value === method)?.label || method}`,
      onRemove: () => setFilters((current) => ({ ...current, initiationMethods: current.initiationMethods.filter((item) => item !== method) })),
    }));
    if (filters.queueId) {
      chips.push({
        key: 'queue',
        label: `Queue: ${queueLabelById[filters.queueId] || filters.queueId}`,
        onRemove: () => setFilters((current) => ({ ...current, queueId: '' })),
      });
    }
    if (filters.agentId) {
      chips.push({
        key: 'agent',
        label: `Agent: ${agentLabelById[filters.agentId] || filters.agentId}`,
        onRemove: () => setFilters((current) => ({ ...current, agentId: '' })),
      });
    }
    if (filters.phoneNumber.trim()) {
      chips.push({
        key: 'phone',
        label: `Phone: ${filters.phoneNumber.trim()}`,
        onRemove: () => setFilters((current) => ({ ...current, phoneNumber: '' })),
      });
    }
    if (filters.contactId.trim()) {
      chips.push({
        key: 'contactId',
        label: `Contact ID: ${filters.contactId.trim()}`,
        onRemove: () => setFilters((current) => ({ ...current, contactId: '' })),
      });
    }
    if (filters.minMinutes) {
      chips.push({
        key: 'minDuration',
        label: `Min duration: ${filters.minMinutes} min`,
        onRemove: () => setFilters((current) => ({ ...current, minMinutes: '' })),
      });
    }
    if (filters.maxMinutes) {
      chips.push({
        key: 'maxDuration',
        label: `Max duration: ${filters.maxMinutes} min`,
        onRemove: () => setFilters((current) => ({ ...current, maxMinutes: '' })),
      });
    }
    if (filters.sortOrder === 'ASCENDING') {
      chips.push({
        key: 'sortOrder',
        label: 'Sort: Oldest first',
        onRemove: () => setFilters((current) => ({ ...current, sortOrder: 'DESCENDING' })),
      });
    }
    filters.customAttributes.forEach((attribute, index) => {
      if (!attribute.key && !attribute.value) return;
      chips.push({
        key: `attribute-${index}`,
        label: `Attr: ${attribute.key || 'key'} = ${attribute.value || 'value'}`,
        onRemove: () => setFilters((current) => ({
          ...current,
          customAttributes: current.customAttributes.filter((_, itemIndex) => itemIndex !== index),
        })),
      });
    });

    return chips;
  }, [agentLabelById, filters, queueLabelById]);

  const paginated = useMemo(() => contacts.slice((page - 1) * pageSize, page * pageSize), [contacts, page]);
  const totalPages = Math.max(Math.ceil(contacts.length / pageSize), 1);
  const highlightKeyword = useMemo(() => {
    const firstAttribute = filters.customAttributes.find((attribute) => attribute.value?.trim());
    return firstAttribute?.value?.trim() || filters.phoneNumber.trim() || filters.contactId.trim() || '';
  }, [filters]);

  return (
    <section className="rounded-3xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-900/70 p-5 shadow-panel">
      <div className="flex items-center gap-3">
        <div className="rounded-2xl bg-connect-500/15 p-3 text-connect-700 dark:text-connect-400"><Search size={18} /></div>
        <div>
          <h3 className="text-xl font-semibold">Contact record search</h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Search CTRs with AWS Connect-native filters, then pivot into transcript, recording, or journey workflows.</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <CalendarDays size={14} className="text-slate-600 dark:text-slate-500" />
          {[
            { label: 'Today', days: 0 },
            { label: 'Last 7 days', days: 7 },
            { label: 'Last 30 days', days: 30 },
          ].map(({ label, days }) => (
            <button
              key={label}
              type="button"
              disabled={loading}
              onClick={() => applyQuickRange(days)}
              className="rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:border-connect-500 hover:text-connect-700 dark:hover:text-connect-400 disabled:opacity-40"
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5 space-y-4 rounded-3xl border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-950/50 p-4">
        <div className="grid gap-4 lg:grid-cols-4">
          <input
            type="datetime-local"
            value={filters.start}
            onChange={(event) => setFilters((current) => ({ ...current, start: event.target.value }))}
            className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
          />
          <input
            type="datetime-local"
            value={filters.end}
            onChange={(event) => setFilters((current) => ({ ...current, end: event.target.value }))}
            className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
          />
          <select
            value={filters.timeRangeType}
            onChange={(event) => setFilters((current) => ({ ...current, timeRangeType: event.target.value }))}
            className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
          >
            {TIME_RANGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <select
            value={filters.status}
            onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
            className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
          >
            {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </div>

        <div className="grid gap-4 lg:grid-cols-4">
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Channels</p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setFilters((current) => ({ ...current, channels: [] }))}
                className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition ${
                  filters.channels.length === 0
                    ? 'bg-connect-500 text-white'
                    : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-700 dark:text-slate-300 hover:border-connect-500'
                }`}
              >
                All
              </button>
              {CHANNEL_OPTIONS.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => toggleFilterValue('channels', value)}
                  className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition ${
                    filters.channels.includes(value)
                      ? 'bg-connect-500 text-white'
                      : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-700 dark:text-slate-300 hover:border-connect-500'
                  }`}
                >
                  <Icon size={11} />
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2 lg:col-span-2">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Initiation methods</p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setFilters((current) => ({ ...current, initiationMethods: [] }))}
                className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition ${
                  filters.initiationMethods.length === 0
                    ? 'bg-connect-500 text-white'
                    : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-700 dark:text-slate-300 hover:border-connect-500'
                }`}
              >
                All
              </button>
              {METHOD_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => toggleFilterValue('initiationMethods', value)}
                  className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition ${
                    filters.initiationMethods.includes(value)
                      ? 'bg-connect-500 text-white'
                      : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-700 dark:text-slate-300 hover:border-connect-500'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={() => runSearch()}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-connect-500 px-4 py-3 text-sm font-medium text-white hover:bg-connect-700 disabled:opacity-50"
          >
            {loading ? <RefreshCw size={16} className="animate-spin" /> : <Search size={16} />}
            {loading ? 'Searching…' : 'Search Contacts'}
          </button>
        </div>

        <button
          type="button"
          onClick={() => setAdvancedOpen((current) => !current)}
          className="inline-flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white"
        >
          <Filter size={15} />
          Advanced Filters
          {advancedOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>

        {advancedOpen && (
          <div className="grid gap-4 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 p-4 lg:grid-cols-2 xl:grid-cols-3">
            <select
              value={filters.queueId}
              onChange={(event) => setFilters((current) => ({ ...current, queueId: event.target.value }))}
              className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
            >
              <option value="">{queuesLoading ? 'Loading…' : queuesError ? 'Could not load options' : 'All Queues'}</option>
              {queues.map((queue) => <option key={queue.id} value={queue.id}>{queue.name}</option>)}
            </select>
            <select
              value={filters.agentId}
              onChange={(event) => setFilters((current) => ({ ...current, agentId: event.target.value }))}
              className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
            >
              <option value="">{agentsLoading ? 'Loading…' : agentsError ? 'Could not load options' : 'All Agents'}</option>
              {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
            <div className="relative">
              <Phone size={14} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-600 dark:text-slate-500" />
              <input
                type="text"
                placeholder="+447700900123"
                value={filters.phoneNumber}
                onChange={(event) => setFilters((current) => ({ ...current, phoneNumber: event.target.value }))}
                className="w-full rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 py-3 pl-11 pr-4 text-sm text-slate-900 dark:text-slate-100 outline-none"
              />
            </div>
            <div className="relative">
              <Hash size={14} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-600 dark:text-slate-500" />
              <input
                type="text"
                placeholder="Exact contact ID…"
                value={filters.contactId}
                onChange={(event) => setFilters((current) => ({ ...current, contactId: event.target.value }))}
                className="w-full rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 py-3 pl-11 pr-4 text-sm text-slate-900 dark:text-slate-100 outline-none"
              />
            </div>
            <input
              type="number"
              min="0"
              placeholder="Min duration (minutes)"
              value={filters.minMinutes}
              onChange={(event) => setFilters((current) => ({ ...current, minMinutes: event.target.value }))}
              className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
            />
            <input
              type="number"
              min="0"
              placeholder="Max duration (minutes)"
              value={filters.maxMinutes}
              onChange={(event) => setFilters((current) => ({ ...current, maxMinutes: event.target.value }))}
              className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
            />

            <div className="space-y-2 xl:col-span-1">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Sort order</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setFilters((current) => ({ ...current, sortOrder: 'DESCENDING' }))}
                  className={`rounded-xl px-3 py-2 text-xs font-medium ${filters.sortOrder === 'DESCENDING' ? 'bg-connect-500 text-white' : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-700 dark:text-slate-300'}`}
                >
                  Newest First
                </button>
                <button
                  type="button"
                  onClick={() => setFilters((current) => ({ ...current, sortOrder: 'ASCENDING' }))}
                  className={`rounded-xl px-3 py-2 text-xs font-medium ${filters.sortOrder === 'ASCENDING' ? 'bg-connect-500 text-white' : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-700 dark:text-slate-300'}`}
                >
                  Oldest First
                </button>
              </div>
            </div>

            <div className="space-y-3 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-950/70 p-4 lg:col-span-2 xl:col-span-3">
              <div>
                <p className="text-sm font-medium text-slate-900 dark:text-white">Custom Contact Attributes</p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Search by custom attributes set on the contact (e.g. customerName, authStatus)</p>
              </div>
              <div className="space-y-3">
                {filters.customAttributes.map((attribute, index) => (
                  <div key={`attribute-row-${index}`} className="grid gap-3 md:grid-cols-[1fr,1fr,auto]">
                    <input
                      type="text"
                      placeholder="Attribute key"
                      value={attribute.key}
                      onChange={(event) => setFilters((current) => ({
                        ...current,
                        customAttributes: current.customAttributes.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value } : item),
                      }))}
                      className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
                    />
                    <input
                      type="text"
                      placeholder="Attribute value"
                      value={attribute.value}
                      onChange={(event) => setFilters((current) => ({
                        ...current,
                        customAttributes: current.customAttributes.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item),
                      }))}
                      className="rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-sm text-slate-900 dark:text-slate-100 outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setFilters((current) => ({
                        ...current,
                        customAttributes: current.customAttributes.filter((_, itemIndex) => itemIndex !== index),
                      }))}
                      className="inline-flex items-center justify-center rounded-2xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-4 py-3 text-slate-700 dark:text-slate-300 hover:border-rose-500 hover:text-rose-600 dark:hover:text-rose-300"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setFilters((current) => ({ ...current, customAttributes: [...current.customAttributes, { key: '', value: '' }] }))}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:border-connect-500 hover:text-connect-700 dark:hover:text-connect-400"
              >
                <Tag size={12} /> Add attribute
              </button>
            </div>
          </div>
        )}
      </div>

      {activeFilterChips.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {activeFilterChips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              onClick={chip.onRemove}
              className="inline-flex items-center gap-2 rounded-full border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:border-connect-500 hover:text-slate-900 dark:hover:text-white"
            >
              {chip.label}
              <X size={12} />
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="mt-4 flex items-center gap-3 rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-600 dark:text-rose-300">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {!hasSearched ? (
        <div className="mt-10 flex flex-col items-center gap-3 py-10 text-slate-500 dark:text-slate-400">
          <Search size={32} className="opacity-30" />
          <p className="text-sm">Set your filters and click <strong className="text-slate-800 dark:text-slate-200">Search Contacts</strong> to load CTRs.</p>
        </div>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-3xl border border-slate-200 dark:border-slate-800">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800 text-sm">
            <thead className="bg-white/80 dark:bg-slate-950/80 text-slate-500 dark:text-slate-400">
              <tr>
                {['Contact ID', 'Date/Time', 'Agent', 'Queue', 'Channel', 'Method', 'Duration', 'Status', 'Attrs', 'Availability', 'Actions'].map((label) => (
                  <th key={label} className="px-4 py-3 text-left font-medium">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800 bg-white/70 dark:bg-slate-900/70">
              {loading ? (
                <LoadingRows />
              ) : paginated.length === 0 ? (
                <tr>
                  <td colSpan={11} className="px-4 py-10 text-center text-slate-500 dark:text-slate-400">No contacts found for the selected filters.</td>
                </tr>
              ) : paginated.map((contact) => (
                <tr key={contact.contactId} className="hover:bg-slate-100 dark:hover:bg-slate-800/70">
                  <td className="px-4 py-4 font-medium text-slate-900 dark:text-white">{contact.contactId}</td>
                  <td className="px-4 py-4 text-slate-700 dark:text-slate-300">{contact.dateTime ? new Date(contact.dateTime).toLocaleString() : '—'}</td>
                  <td className="px-4 py-4 text-slate-700 dark:text-slate-300">{contact.agent}</td>
                  <td className="px-4 py-4 text-slate-700 dark:text-slate-300">{contact.queue}</td>
                  <td className="px-4 py-4"><ChannelBadge channel={contact.channel} /></td>
                  <td className="px-4 py-4"><MethodBadge method={contact.initiationMethod} /></td>
                  <td className="px-4 py-4 text-slate-700 dark:text-slate-300">{formatDuration(contact.duration)}</td>
                  <td className="px-4 py-4 text-slate-700 dark:text-slate-300">{contact.status}</td>
                  <td className="px-4 py-4"><AttributesBadge phoneNumber={contact.phoneNumber} customAttributes={contact.customAttributes} /></td>
                  <td className="px-4 py-4">
                    <AvailabilityBadge hasRecording={contact.hasRecording} channel={contact.channel} status={contact.status} />
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setMetricsContactId(metricsContactId === contact.contactId ? null : contact.contactId)}
                        className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs transition ${
                          metricsContactId === contact.contactId
                            ? 'bg-connect-700 text-white'
                            : 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 hover:bg-slate-200 dark:hover:bg-slate-700'
                        }`}
                      >
                        <Gauge size={11} />
                        {metricsContactId === contact.contactId ? 'Hide Detail' : 'View Detail'}
                      </button>
                      <button
                        type="button"
                        onClick={() => onAskQuery(
                          `Analyse contact ${contact.contactId} (queue: ${contact.queue || 'unknown'}, agent: ${contact.agent || 'unknown'}, `
                          + `channel: ${contact.channel || 'unknown'}, status: ${contact.status || 'unknown'}). `
                          + 'Summarise what happened on this contact and anything a supervisor should follow up on.'
                        )}
                        className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-500/15 px-3 py-2 text-xs text-indigo-600 dark:text-indigo-300 hover:bg-indigo-500/25"
                      >
                        <Sparkles size={11} />
                        Ask AI
                      </button>
                      <button type="button" onClick={() => onSelectContact(contact, highlightKeyword)} className="rounded-xl bg-connect-500 px-3 py-2 text-xs text-white hover:bg-connect-700">Get Transcript</button>
                      {contact.hasRecording && contact.channel === 'VOICE' && (
                        <button type="button" onClick={() => onSelectContact(contact, highlightKeyword)} className="rounded-xl bg-emerald-700 px-3 py-2 text-xs text-white hover:bg-emerald-600">Play Recording</button>
                      )}
                      <button
                        type="button"
                        onClick={() => setJourneyContactId(journeyContactId === contact.contactId ? null : contact.contactId)}
                        className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition ${
                          journeyContactId === contact.contactId
                            ? 'bg-indigo-600 text-white'
                            : 'bg-indigo-500/15 text-indigo-600 dark:text-indigo-300 hover:bg-indigo-500/25'
                        }`}
                      >
                        <Network size={11} />
                        {journeyContactId === contact.contactId ? 'Hide Journey' : 'View Journey'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {metricsContactId && (
        <ContactLensMetricsPanel
          contactId={metricsContactId}
          onClose={() => setMetricsContactId(null)}
        />
      )}

      {journeyContactId && (
        <div className="mt-4">
          <ContactFlowGraph
            contactId={journeyContactId}
            onClose={() => setJourneyContactId(null)}
          />
        </div>
      )}

      {hasSearched && contacts.length > 0 && !loading && (
        <div className="mt-4 flex items-center justify-between text-sm text-slate-500 dark:text-slate-400">
          <p>{contacts.length} result(s)</p>
          <div className="flex items-center gap-3">
            <button type="button" disabled={page === 1} onClick={() => setPage((current) => Math.max(current - 1, 1))} className="rounded-xl border border-slate-300 dark:border-slate-700 px-3 py-2 text-slate-900 dark:text-slate-100 disabled:opacity-40">Previous</button>
            <span>Page {page} of {totalPages}</span>
            <button type="button" disabled={page === totalPages} onClick={() => setPage((current) => Math.min(current + 1, totalPages))} className="rounded-xl border border-slate-300 dark:border-slate-700 px-3 py-2 text-slate-900 dark:text-slate-100 disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </section>
  );
}
