import { useEffect, useMemo, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { ArrowUpRight, RefreshCw, Sparkles } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { getMetrics, getHistoricalMetrics } from '../services/api';

const metricDefinitions = [
  { key: 'agents_online', label: 'Agents Online', tone: 'good', query: 'How many agents are online right now?' },
  { key: 'agents_available', label: 'Agents Available', tone: 'good', query: 'How many agents are available right now?' },
  { key: 'agents_on_call', label: 'Agents on Call', tone: 'warning', query: 'How many agents are currently on calls?' },
  { key: 'agents_in_acw', label: 'Agents in ACW', tone: 'warning', query: 'How many agents are in after contact work right now?' },
  { key: 'contacts_in_queue', label: 'Contacts in Queue', tone: 'critical', query: 'How many contacts are waiting in queue right now?' },
  { key: 'oldest_contact_age', label: 'Oldest Contact Age', tone: 'critical', query: 'What is the oldest contact age right now?' },
];

const CHART_COLOURS = {
  CONTACTS_HANDLED: '#10b981',
  AVG_HANDLE_TIME: '#2563eb',
  CONTACTS_ABANDONED: '#f59e0b',
  CONTACTS_QUEUED: '#818cf8',
  AVG_AFTER_CONTACT_WORK_TIME: '#f472b6',
};

const METRIC_LABELS = {
  CONTACTS_HANDLED: 'Contacts Handled',
  AVG_HANDLE_TIME: 'Avg Handle Time',
  CONTACTS_ABANDONED: 'Contacts Abandoned',
  CONTACTS_QUEUED: 'Contacts Queued',
  AVG_AFTER_CONTACT_WORK_TIME: 'Avg ACW Time',
};

function fmtSeconds(v) {
  if (!v) return '0s';
  const s = Math.round(v);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m === 0 ? `${sec}s` : `${m}m ${sec < 10 ? '0' + sec : sec}s`;
}

function HistoricChart({ title, data, bars, rightBars = [], darkMode = true }) {
  const gridColor   = darkMode ? '#334155' : '#e2e8f0';
  const tickColor   = darkMode ? '#94a3b8' : '#64748b';
  const tooltipBg   = darkMode ? '#1e293b' : '#ffffff';
  const tooltipBdr  = darkMode ? '#334155' : '#e2e8f0';
  const tooltipLbl  = darkMode ? '#f1f5f9' : '#0f172a';
  const tooltipItem = darkMode ? '#94a3b8' : '#334155';

  if (!data?.length) return (
    <div className="flex h-48 items-center justify-center text-sm text-slate-500">No data available</div>
  );
  return (
    <div>
      <p className="mb-3 text-sm font-semibold text-slate-300">{title}</p>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: rightBars.length ? 52 : 8, left: 0, bottom: 28 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
          <XAxis dataKey="label" tick={{ fill: tickColor, fontSize: 10 }} angle={-30} textAnchor="end" interval={0} />
          <YAxis yAxisId="left" tick={{ fill: tickColor, fontSize: 10 }} allowDecimals={false} width={28} />
          {rightBars.length > 0 && (
            <YAxis yAxisId="right" orientation="right" tick={{ fill: tickColor, fontSize: 10 }}
              tickFormatter={fmtSeconds} width={44} />
          )}
          <Tooltip
            contentStyle={{ backgroundColor: tooltipBg, border: `1px solid ${tooltipBdr}`, borderRadius: 8 }}
            labelStyle={{ color: tooltipLbl, fontWeight: 600 }}
            itemStyle={{ color: tooltipItem }}
            formatter={(v, name) => [
              /time|duration|acw/i.test(name) ? fmtSeconds(v) : v,
              METRIC_LABELS[name] ?? name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: tickColor, paddingTop: 8 }}
            formatter={(v) => METRIC_LABELS[v] ?? v} />
          {bars.map((key) => (
            <Bar key={key} yAxisId="left" dataKey={key} name={key}
              fill={CHART_COLOURS[key] ?? '#6366f1'} radius={[3, 3, 0, 0]} />
          ))}
          {rightBars.map((key) => (
            <Bar key={key} yAxisId="right" dataKey={key} name={key}
              fill={CHART_COLOURS[key] ?? '#8b5cf6'} radius={[3, 3, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function MetricsDashboard({ onAskQuery, darkMode = true }) {
  const tones = darkMode ? {
    good:     'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
    warning:  'border-amber-500/25  bg-amber-500/10  text-amber-300',
    critical: 'border-rose-500/25   bg-rose-500/10   text-rose-300',
  } : {
    good:     'border-emerald-500/40 bg-emerald-50  text-emerald-700',
    warning:  'border-amber-500/40  bg-amber-50    text-amber-700',
    critical: 'border-rose-500/40   bg-rose-50     text-rose-700',
  };
  const numColour = darkMode ? 'text-white' : 'text-slate-800';
  const [metrics, setMetrics] = useState({});
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(false);
  const [historical, setHistorical] = useState(null);
  const [histDays, setHistDays] = useState(30);
  const [histLoading, setHistLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const response = await getMetrics();
      setMetrics(response.metrics || {});
      setLastUpdated(response.last_updated || new Date().toISOString());
    } catch {
      setMetrics({
        agents_online: 19, agents_available: 7, agents_on_call: 8,
        agents_in_acw: 3, contacts_in_queue: 5, oldest_contact_age: '00:03:42',
      });
      setLastUpdated(new Date().toISOString());
    } finally {
      setLoading(false);
    }
  };

  const refreshHistorical = async (days) => {
    setHistLoading(true);
    try {
      const data = await getHistoricalMetrics(days);
      setHistorical(data);
    } catch {
      setHistorical(null);
    } finally {
      setHistLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);
  useEffect(() => { refreshHistorical(histDays); }, [histDays]);

  const summaryPrompt = useMemo(() => {
    const formatted = metricDefinitions
      .map(({ key, label }) => `${label}: ${metrics[key] ?? 'n/a'}`)
      .join(', ');
    return `Analyze this live dashboard snapshot and tell me the operational story: ${formatted}`;
  }, [metrics]);

  return (
    <div className="flex flex-col gap-6">
      {/* ── Live Dashboard ─────────────────────────────────────────────────── */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-panel">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h3 className="text-xl font-semibold">Live Dashboard</h3>
            <p className="mt-1 text-sm text-slate-400">
              Last updated {lastUpdated ? formatDistanceToNow(new Date(lastUpdated), { addSuffix: true }) : 'just now'}
            </p>
          </div>
          <div className="flex gap-3">
            <button type="button" onClick={() => onAskQuery(summaryPrompt)}
              className="inline-flex items-center gap-2 rounded-2xl bg-connect-500 px-4 py-3 text-sm font-medium text-white hover:bg-connect-700">
              <Sparkles size={16} />Ask AI about this data
            </button>
            <button type="button" onClick={refresh}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-100 hover:border-connect-500">
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />Refresh
            </button>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {metricDefinitions.map((metric) => (
            <button key={metric.key} type="button" onClick={() => onAskQuery(metric.query)}
              className={`rounded-3xl border p-5 text-left transition hover:-translate-y-0.5 ${tones[metric.tone]}`}>
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium uppercase tracking-[0.18em] text-current/80">{metric.label}</p>
                <ArrowUpRight size={16} />
              </div>
              <p className={`mt-6 text-4xl font-semibold ${numColour}`}>{metrics[metric.key] ?? '—'}</p>
              <p className="mt-3 text-sm text-current/80">Click to ask AI for explanation</p>
            </button>
          ))}
        </div>
      </section>

      {/* ── Historic Dashboard ─────────────────────────────────────────────── */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-panel">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h3 className="text-xl font-semibold">Historic Dashboard</h3>
            <p className="mt-1 text-sm text-slate-400">
              {historical?.period ?? `Last ${histDays} days`}
              {historical?.mock && <span className="ml-2 rounded bg-amber-500/20 px-1.5 py-0.5 text-xs text-amber-300">mock</span>}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={histDays}
              onChange={(e) => setHistDays(Number(e.target.value))}
              className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-connect-500"
            >
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={60}>Last 60 days</option>
              <option value={90}>Last 90 days</option>
            </select>
            <button type="button" onClick={() => refreshHistorical(histDays)}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-100 hover:border-connect-500">
              <RefreshCw size={16} className={histLoading ? 'animate-spin' : ''} />Refresh
            </button>
            <button type="button"
              onClick={() => onAskQuery(`Show me a breakdown of contact activity over the last ${histDays} days`)}
              className="inline-flex items-center gap-2 rounded-2xl bg-connect-500 px-4 py-3 text-sm font-medium text-white hover:bg-connect-700">
              <Sparkles size={16} />Ask AI
            </button>
          </div>
        </div>

        {histLoading ? (
          <div className="mt-6 flex h-48 items-center justify-center text-sm text-slate-400">
            <RefreshCw size={20} className="mr-2 animate-spin" />Loading historical data…
          </div>
        ) : (
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-slate-700 bg-slate-800/40 p-4">
              <HistoricChart
                title="Contacts Handled per Day"
                data={historical?.data ?? []}
                bars={['CONTACTS_HANDLED']}
                darkMode={darkMode}
              />
            </div>
            <div className="rounded-2xl border border-slate-700 bg-slate-800/40 p-4">
              <HistoricChart
                title="Avg Handle Time per Day"
                data={historical?.data ?? []}
                bars={[]}
                rightBars={['AVG_HANDLE_TIME']}
                darkMode={darkMode}
              />
            </div>
            <div className="rounded-2xl border border-slate-700 bg-slate-800/40 p-4 lg:col-span-2">
              <HistoricChart
                title="Contacts Handled vs Abandoned"
                data={(() => {
                  const map = {};
                  (historical?.data ?? []).forEach(r => {
                    const k = r.date_key ?? r.label;
                    map[k] = { label: r.label, date_key: k, CONTACTS_HANDLED: r.CONTACTS_HANDLED };
                  });
                  (historical?.abandoned ?? []).forEach(r => {
                    const k = r.date_key ?? r.label;
                    if (!map[k]) map[k] = { label: r.label, date_key: k, CONTACTS_HANDLED: 0 };
                    map[k].CONTACTS_ABANDONED = r.CONTACTS_ABANDONED;
                  });
                  return Object.values(map).sort((a, b) => (a.date_key ?? a.label) < (b.date_key ?? b.label) ? -1 : 1);
                })()}
                bars={['CONTACTS_HANDLED', 'CONTACTS_ABANDONED']}
                darkMode={darkMode}
              />
            </div>
            <div className="rounded-2xl border border-slate-700 bg-slate-800/40 p-4">
              <HistoricChart
                title="Contacts in Queue per Day"
                data={historical?.data ?? []}
                bars={['CONTACTS_QUEUED']}
                darkMode={darkMode}
              />
            </div>
            <div className="rounded-2xl border border-slate-700 bg-slate-800/40 p-4">
              <HistoricChart
                title="Avg ACW Time per Day"
                data={historical?.data ?? []}
                bars={[]}
                rightBars={['AVG_AFTER_CONTACT_WORK_TIME']}
                darkMode={darkMode}
              />
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

