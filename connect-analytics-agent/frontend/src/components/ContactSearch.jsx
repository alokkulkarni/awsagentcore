import { useCallback, useMemo, useState } from 'react';
import { Search, RefreshCw, AlertCircle, Mic, MessageSquare, Video, FileText, Ban, CalendarDays, Network } from 'lucide-react';
import { searchContacts } from '../services/api';
import ContactFlowGraph from './ContactFlowGraph';

function AvailabilityBadge({ hasRecording, channel, status }) {
  const isEnded = status === 'ENDED';
  const isVoice = channel === 'VOICE';
  const isChat = channel === 'CHAT';

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {/* Channel badge */}
      {isVoice && (
        <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-medium text-sky-400">
          <Mic size={9} /> Voice
        </span>
      )}
      {isChat && (
        <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] font-medium text-violet-400">
          <MessageSquare size={9} /> Chat
        </span>
      )}
      {/* Recording badge — voice only */}
      {isVoice && isEnded && (
        hasRecording
          ? (
            <span title="Recording available" className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
              <Video size={9} /> Recording
            </span>
          )
          : (
            <span title="No recording found" className="inline-flex items-center gap-1 rounded-full bg-slate-700/60 px-2 py-0.5 text-[10px] font-medium text-slate-500">
              <Ban size={9} /> No recording
            </span>
          )
      )}
      {/* Transcript badge */}
      {isEnded && (isVoice || isChat) && (
        <span
          title={isVoice ? "Automated interaction log available (conversational AI transcript)" : "Chat transcript available in S3"}
          className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-400"
        >
          <FileText size={9} /> Transcript
        </span>
      )}
    </div>
  );
}

export default function ContactSearch({ onAskQuery, onSelectContact }) {
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [journeyContactId, setJourneyContactId] = useState(null); // currently expanded journey
  const [filters, setFilters] = useState({
    start: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString().slice(0, 16),
    end: new Date().toISOString().slice(0, 16),
    status: 'All',
    minMinutes: '',
    maxMinutes: '',
    keyword: '',
  });
  const [page, setPage] = useState(1);
  const pageSize = 10;

  const applyQuickRange = useCallback((days) => {
    const now = new Date();
    const start = new Date(now);
    if (days === 0) {
      // Today: midnight → now
      start.setHours(0, 0, 0, 0);
    } else {
      start.setDate(start.getDate() - days);
    }
    const newFilters = {
      ...filters,
      start: start.toISOString().slice(0, 16),
      end: now.toISOString().slice(0, 16),
    };
    setFilters(newFilters);
    // Auto-search immediately
    setLoading(true);
    setError(null);
    setHasSearched(true);
    setPage(1);
    const params = {
      start: start.toISOString(),
      end: now.toISOString(),
      contact_status: newFilters.status !== 'All' ? newFilters.status : undefined,
      min_duration_seconds: newFilters.minMinutes ? Number(newFilters.minMinutes) * 60 : undefined,
      max_duration_seconds: newFilters.maxMinutes ? Number(newFilters.maxMinutes) * 60 : undefined,
      max_results: 100,
    };
    searchContacts(params)
      .then((data) => {
        const all = data.contacts || [];
        const kw = newFilters.keyword.toLowerCase();
        setContacts(kw ? all.filter((c) => [c.contactId, c.agent, c.queue, c.status].some((v) => String(v || '').toLowerCase().includes(kw))) : all);
      })
      .catch(() => setError('Could not search contacts. Check your AWS credentials and Connect instance ID.'))
      .finally(() => setLoading(false));
  }, [filters]);

  const doSearch = useCallback(async () => {
    setLoading(true);
    setError(null);
    setHasSearched(true);
    setPage(1);
    try {
      const params = {
        start: filters.start ? new Date(filters.start).toISOString() : undefined,
        end: filters.end ? new Date(filters.end).toISOString() : undefined,
        contact_status: filters.status !== 'All' ? filters.status : undefined,
        min_duration_seconds: filters.minMinutes ? Number(filters.minMinutes) * 60 : undefined,
        max_duration_seconds: filters.maxMinutes ? Number(filters.maxMinutes) * 60 : undefined,
        max_results: 100,
      };
      const data = await searchContacts(params);
      const all = data.contacts || [];
      const kw = filters.keyword.toLowerCase();
      const filtered = kw ? all.filter((c) => [c.contactId, c.agent, c.queue, c.status].some((v) => String(v || '').toLowerCase().includes(kw))) : all;
      setContacts(filtered);
    } catch {
      setError('Could not search contacts. Check your AWS credentials and Connect instance ID.');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  const paginated = useMemo(() => contacts.slice((page - 1) * pageSize, page * pageSize), [contacts, page]);
  const totalPages = Math.max(Math.ceil(contacts.length / pageSize), 1);

  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-panel">
      <div className="flex items-center gap-3">
        <div className="rounded-2xl bg-connect-500/15 p-3 text-connect-400"><Search size={18} /></div>
        <div>
          <h3 className="text-xl font-semibold">Contact record search</h3>
          <p className="mt-1 text-sm text-slate-400">Search CTRs and pivot into transcript or recording workflows.</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <CalendarDays size={14} className="text-slate-500" />
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
              className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-connect-500 hover:text-connect-300 disabled:opacity-40"
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-4">
        <input type="datetime-local" value={filters.start} onChange={(e) => setFilters((f) => ({ ...f, start: e.target.value }))} className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none" />
        <input type="datetime-local" value={filters.end} onChange={(e) => setFilters((f) => ({ ...f, end: e.target.value }))} className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none" />
        <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))} className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none">
          {['All', 'CONNECTED', 'ENDED', 'MISSED', 'REJECTED'].map((s) => <option key={s}>{s}</option>)}
        </select>
        <input type="text" placeholder="Keyword filter (agent, queue, ID)" value={filters.keyword} onChange={(e) => setFilters((f) => ({ ...f, keyword: e.target.value }))} className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none" />
        <input type="number" min="0" placeholder="Min duration (minutes)" value={filters.minMinutes} onChange={(e) => setFilters((f) => ({ ...f, minMinutes: e.target.value }))} className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none" />
        <input type="number" min="0" placeholder="Max duration (minutes)" value={filters.maxMinutes} onChange={(e) => setFilters((f) => ({ ...f, maxMinutes: e.target.value }))} className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none" />
        <button type="button" onClick={doSearch} disabled={loading} className="col-span-2 inline-flex items-center justify-center gap-2 rounded-2xl bg-connect-500 px-4 py-3 text-sm font-medium text-white hover:bg-connect-700 disabled:opacity-50">
          {loading ? <RefreshCw size={16} className="animate-spin" /> : <Search size={16} />}
          {loading ? 'Searching…' : 'Search Contacts'}
        </button>
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-3 rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {!hasSearched ? (
        <div className="mt-10 flex flex-col items-center gap-3 py-10 text-slate-400">
          <Search size={32} className="opacity-30" />
          <p className="text-sm">Set your filters and click <strong className="text-slate-200">Search Contacts</strong> to load CTRs.</p>
        </div>
      ) : (
      <div className="mt-6 overflow-hidden rounded-3xl border border-slate-800">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-950/80 text-slate-400">
            <tr>
              {['Contact ID', 'Date/Time', 'Agent', 'Queue', 'Duration', 'Status', 'Availability', 'Actions'].map((label) => <th key={label} className="px-4 py-3 text-left font-medium">{label}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900/70">
            {paginated.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-400">No contacts found for the selected filters.</td></tr>
            ) : paginated.map((contact) => (
              <tr key={contact.contactId} className="hover:bg-slate-800/70">
                <td className="px-4 py-4 font-medium text-white">{contact.contactId}</td>
                <td className="px-4 py-4 text-slate-300">{contact.dateTime ? new Date(contact.dateTime).toLocaleString() : '—'}</td>
                <td className="px-4 py-4 text-slate-300">{contact.agent}</td>
                <td className="px-4 py-4 text-slate-300">{contact.queue}</td>
                <td className="px-4 py-4 text-slate-300">{Math.round((contact.duration || 0) / 60)} min</td>
                <td className="px-4 py-4 text-slate-300">{contact.status}</td>
                <td className="px-4 py-4">
                  <AvailabilityBadge hasRecording={contact.hasRecording} channel={contact.channel} status={contact.status} />
                </td>
                <td className="px-4 py-4">
                   <div className="flex flex-wrap gap-2">
                     <button type="button" onClick={() => onAskQuery(`Show me details for contact ${contact.contactId}.`)} className="rounded-xl bg-slate-800 px-3 py-2 text-xs text-slate-100 hover:bg-slate-700">View Detail</button>
                     <button type="button" onClick={() => onSelectContact(contact, filters.keyword)} className="rounded-xl bg-connect-500 px-3 py-2 text-xs text-white hover:bg-connect-700">Get Transcript</button>
                     {contact.hasRecording && contact.channel === 'VOICE' && (
                       <button type="button" onClick={() => onSelectContact(contact, filters.keyword)} className="rounded-xl bg-emerald-700 px-3 py-2 text-xs text-white hover:bg-emerald-600">Play Recording</button>
                     )}
                     <button
                       type="button"
                       onClick={() => setJourneyContactId(journeyContactId === contact.contactId ? null : contact.contactId)}
                       className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition ${
                         journeyContactId === contact.contactId
                           ? 'bg-indigo-600 text-white'
                           : 'bg-indigo-500/15 text-indigo-300 hover:bg-indigo-500/25'
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

      {/* Inline journey panel — expands below table when a contact is selected */}
      {journeyContactId && (
        <div className="mt-4">
          <ContactFlowGraph
            contactId={journeyContactId}
            onClose={() => setJourneyContactId(null)}
          />
        </div>
      )}

      {hasSearched && contacts.length > 0 && (
        <div className="mt-4 flex items-center justify-between text-sm text-slate-400">
          <p>{contacts.length} result(s)</p>
          <div className="flex items-center gap-3">
            <button type="button" disabled={page === 1} onClick={() => setPage((p) => Math.max(p - 1, 1))} className="rounded-xl border border-slate-700 px-3 py-2 text-slate-100 disabled:opacity-40">Previous</button>
            <span>Page {page} of {totalPages}</span>
            <button type="button" disabled={page === totalPages} onClick={() => setPage((p) => Math.min(p + 1, totalPages))} className="rounded-xl border border-slate-700 px-3 py-2 text-slate-100 disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </section>
  );
}
