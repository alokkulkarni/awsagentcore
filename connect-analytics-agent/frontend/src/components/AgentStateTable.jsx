import { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, ArrowUpDown, RefreshCw, AlertCircle } from 'lucide-react';
import { getAgentStates } from '../services/api';

const badgeStyles = {
  Available: 'bg-emerald-500/15 text-emerald-300',
  'On Call': 'bg-sky-500/15 text-sky-300',
  'After Contact Work': 'bg-orange-500/15 text-orange-300',
  'Non-Productive': 'bg-amber-500/15 text-amber-300',
  Offline: 'bg-slate-500/15 text-slate-300',
  Error: 'bg-rose-500/15 text-rose-300',
};

export default function AgentStateTable({ onAskQuery }) {
  const [agentRows, setAgentRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('All');
  const [sortBy, setSortBy] = useState('name');
  const [direction, setDirection] = useState('asc');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAgentStates();
      setAgentRows(data.agents || []);
    } catch {
      setError('Could not load agent states from the API.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const statuses = useMemo(() => ['All', ...new Set(agentRows.map((r) => r.status))], [agentRows]);

  const rows = useMemo(() => {
    const filtered = statusFilter === 'All' ? agentRows : agentRows.filter((row) => row.status === statusFilter);
    return [...filtered].sort((a, b) => {
      const result = String(a[sortBy] || '').localeCompare(String(b[sortBy] || ''));
      return direction === 'asc' ? result : -result;
    });
  }, [agentRows, statusFilter, sortBy, direction]);

  const updateSort = (column) => {
    if (column === sortBy) {
      setDirection((current) => (current === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortBy(column);
    setDirection('asc');
  };

  const exportCsv = () => {
    const header = ['Name', 'Status', 'Current Queue', 'Time in Status', 'Contact ID'];
    const csv = [header.join(','), ...rows.map((row) => [row.name, row.status, row.currentQueue, row.timeInStatus, row.contactId].join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'agent-states.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-panel">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="text-xl font-semibold">Current agent states</h3>
          <p className="mt-1 text-sm text-slate-400">Sortable roster with quick supervisor drill-down actions.</p>
        </div>
        <div className="flex gap-3">
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none">
            {statuses.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
          <button type="button" onClick={refresh} className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 hover:border-connect-500">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button type="button" onClick={exportCsv} disabled={rows.length === 0} className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 hover:border-connect-500 disabled:opacity-40">
            <Download size={16} />
            Export CSV
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-3 rounded-2xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {loading && agentRows.length === 0 ? (
        <div className="mt-8 flex items-center justify-center gap-3 py-12 text-sm text-slate-400">
          <RefreshCw size={18} className="animate-spin" />
          Loading agent states…
        </div>
      ) : (
      <div className="mt-5 overflow-hidden rounded-3xl border border-slate-800">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-950/80 text-slate-400">
            <tr>
              {[
                ['name', 'Name'],
                ['status', 'Status'],
                ['currentQueue', 'Current Queue'],
                ['timeInStatus', 'Time in Status'],
                ['contactId', 'Contact ID'],
              ].map(([key, label]) => (
                <th key={key} className="px-4 py-3 text-left font-medium">
                  <button type="button" onClick={() => updateSort(key)} className="inline-flex items-center gap-2 hover:text-white">
                    {label}
                    <ArrowUpDown size={14} />
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900/70">
            {rows.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">No agents found{statusFilter !== 'All' ? ` with status "${statusFilter}"` : ''}.</td></tr>
            ) : rows.map((row) => (
              <tr key={`${row.name}-${row.status}`} onClick={() => onAskQuery(`Summarize ${row.name}'s current workload and status.`)} className="cursor-pointer hover:bg-slate-800/70">
                <td className="px-4 py-4 font-medium text-white">{row.name}</td>
                <td className="px-4 py-4">
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold ${badgeStyles[row.status] || 'bg-slate-500/15 text-slate-300'}`}>{row.status}</span>
                </td>
                <td className="px-4 py-4 text-slate-300">{row.currentQueue}</td>
                <td className="px-4 py-4 text-slate-300">{row.timeInStatus}</td>
                <td className="px-4 py-4 text-slate-300">{row.contactId || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </section>
  );
}
