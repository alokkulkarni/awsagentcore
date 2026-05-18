/**
 * FlowFunnelPage — standalone page showing aggregate funnel drop-off analysis
 * across all contacts passing through a selected Amazon Connect flow.
 *
 * Time period and flow name are selectable. Pulls data from GET /contact-funnel.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  LabelList,
} from 'recharts';
import {
  AlertCircle,
  BarChart2,
  RefreshCw,
  TrendingDown,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { getContactFunnel, getContactFlows } from '../services/api';

// ── Colour helpers ─────────────────────────────────────────────────────────────

const DROP_LOW  = 5;
const DROP_MID  = 15;

function dropColor(pct) {
  if (!pct)           return '#22d3ee';   // cyan — low / no drop
  if (pct > DROP_MID) return '#f43f5e';   // rose  — high drop
  if (pct > DROP_LOW) return '#f59e0b';   // amber — moderate
  return '#22d3ee';
}

// ── Outcome colours & labels ───────────────────────────────────────────────────

const OUTCOME_CONFIG = {
  completed: { color: '#34d399', bg: 'bg-emerald-500/15', text: 'text-emerald-400', label: 'Completed',  icon: '✓', desc: 'Reached end of flow (Disconnect block)' },
  escalated: { color: '#fb923c', bg: 'bg-orange-500/15',  text: 'text-orange-400',  label: 'Escalated',  icon: '↗', desc: 'Transferred to a human agent' },
  abandoned: { color: '#f43f5e', bg: 'bg-rose-500/15',    text: 'text-rose-400',    label: 'Abandoned',  icon: '✕', desc: 'Contact hung up mid-flow' },
  error:     { color: '#c084fc', bg: 'bg-purple-500/15',  text: 'text-purple-400',  label: 'Error',      icon: '!', desc: 'Lambda / API error was last recorded event' },
  unknown:   { color: '#64748b', bg: 'bg-slate-700/50',   text: 'text-slate-400',   label: 'Unknown',    icon: '?', desc: 'Last block was not a recognised terminal type — may have transitioned to a sub-flow whose logs are in a different log group' },
};

function OutcomeBadge({ intent, small = false }) {
  const cfg = OUTCOME_CONFIG[intent] || OUTCOME_CONFIG.unknown;
  if (small) {
    return (
      <span
        className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${cfg.bg} ${cfg.text}`}
        title={cfg.desc}
      >
        {cfg.icon} {cfg.label}
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${cfg.bg} ${cfg.text}`}
      title={cfg.desc}
    >
      {cfg.icon} {cfg.label}
    </span>
  );
}

// ── Outcomes summary cards ─────────────────────────────────────────────────────

function OutcomesSummary({ summary, total }) {
  if (!summary) return null;
  const outcomeTotal = Object.values(summary).reduce((a, b) => a + b, 0);
  const keys = ['completed', 'escalated', 'abandoned', 'error', 'unknown'];
  return (
    <div className="mb-6">
      <p className="text-[10px] text-slate-500 mb-2 italic">
        Contact outcomes — based on the last flow block each contact reached
        ({outcomeTotal} contacts classified, {total} unique contacts in log group)
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {keys.map((k) => {
          const cfg = OUTCOME_CONFIG[k];
          const count = summary[k] || 0;
          const pct   = outcomeTotal ? Math.round(count / outcomeTotal * 100) : 0;
          return (
            <div
              key={k}
              className={`rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 flex flex-col gap-1 ${cfg.bg}`}
              title={cfg.desc}
            >
              <div className={`text-[10px] font-semibold uppercase tracking-widest ${cfg.text}`}>
                {cfg.icon} {cfg.label}
              </div>
              <div className={`text-2xl font-bold ${cfg.text}`}>{count}</div>
              <div className="text-[10px] text-slate-500">{pct}% of classified</div>
              <div className="text-[9px] text-slate-600 leading-snug">{cfg.desc}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Block-type colour dots (mirrors ContactFlowGraph BLOCK_DEF) ────────────────

const BLOCK_COLORS = {
  PlayPrompt: '#38bdf8', MessageParticipant: '#38bdf8',
  GetCustomerInput: '#818cf8', GetUserInput: '#818cf8',
  CheckContactAttributes: '#fbbf24', CheckAttribute: '#fbbf24',
  CheckHoursOfOperation: '#fbbf24', CheckStaffingLevel: '#fbbf24', Branch: '#fbbf24',
  InvokeExternalResource: '#c084fc', InvokeLambdaFunction: '#c084fc',
  SetContactAttributes: '#34d399', SetAttributes: '#34d399', UpdateContactAttributes: '#34d399',
  TransferToQueue: '#fb923c', Transfer: '#fb923c', SetQueue: '#fb923c',
  DisconnectParticipant: '#fb7185', Disconnect: '#fb7185', EndFlowModuleExecution: '#fb7185',
  StartContactRecording: '#a78bfa', StopContactRecording: '#a78bfa', SetRecordingBehavior: '#a78bfa',
  _default: '#94a3b8',
};

const blockColor = (type) => BLOCK_COLORS[type] || BLOCK_COLORS._default;

// ── Tooltip ────────────────────────────────────────────────────────────────────

function FunnelTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const nextCount = d.count - d.drop_count;
  // Check if the block name has an occurrence suffix like "(2)"
  const occurrenceMatch = d.block_name.match(/\((\d+)\)$/);
  const occurrence = occurrenceMatch ? parseInt(occurrenceMatch[1], 10) : null;
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2.5 text-xs shadow-xl min-w-[220px]">
      <p className="font-semibold text-slate-200 mb-2">{d.block_name}</p>
      <div className="space-y-1">
        <p className="text-slate-400">
          Type: <span className="text-slate-300">{d.block_type}</span>
        </p>
        {occurrence && (
          <p className="text-[10px] text-slate-500 italic">
            {occurrence === 1 ? '1st' : occurrence === 2 ? '2nd' : occurrence === 3 ? '3rd' : `${occurrence}th`} occurrence of this block type in the flow
          </p>
        )}
        <p className="text-slate-400">
          Contacts reached:{' '}
          <span className="text-emerald-400 font-semibold">{d.count}</span>
          <span className="text-slate-600 ml-1">({d.pct?.toFixed(1)}% of total)</span>
        </p>
        {d.drop_count > 0 ? (
          <>
            <div className="border-t border-slate-800 my-1.5" />
            <p className="text-slate-400">
              Continued to next step:{' '}
              <span className="text-cyan-400 font-semibold">{nextCount}</span>
            </p>
            <p className="text-slate-400">
              Exited after this block:{' '}
              <span className="font-semibold" style={{ color: dropColor(d.drop_pct) }}>
                {d.drop_count} ({d.drop_pct?.toFixed(1)}%)
              </span>
              {d.drop_pct > DROP_MID && (
                <span className="ml-1.5 rounded-full bg-red-500/15 px-1.5 py-0.5 text-[9px] font-medium text-red-400">
                  HIGH
                </span>
              )}
              {d.drop_pct > DROP_LOW && d.drop_pct <= DROP_MID && (
                <span className="ml-1.5 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-medium text-amber-400">
                  MODERATE
                </span>
              )}
            </p>
            {d.exit_intent && (
              <div className="mt-1.5 flex items-center gap-1.5">
                <span className="text-slate-500 text-[10px]">Exit type:</span>
                <OutcomeBadge intent={d.exit_intent} small />
              </div>
            )}
            <p className="text-[10px] text-slate-600 italic mt-1">
              {d.drop_count} contact{d.drop_count !== 1 ? 's' : ''} did not proceed to the following block
            </p>
          </>
        ) : (
          <p className="text-slate-600 text-[10px] italic">No drop-off — all contacts continued</p>
        )}
      </div>
    </div>
  );
}

// ── Main chart component ───────────────────────────────────────────────────────

function FunnelChart({ data }) {
  if (!data?.blocks?.length) {
    return (
      <div className="flex h-64 items-center justify-center text-xs text-slate-500">
        No funnel data available for this flow / period.
      </div>
    );
  }

  const total  = data.total_contacts;
  const height = Math.max(data.blocks.length * 52 + 80, 300);
  const chartData = [...data.blocks].reverse(); // recharts horizontal renders bottom→top

  return (
    <div>
      {/* Outcomes summary cards */}
      <OutcomesSummary summary={data.outcomes_summary} total={total} />

      {/* Legend row */}
      <div className="mb-4 flex flex-wrap items-center gap-5 text-xs text-slate-400">
        <span>
          <span className="text-slate-200 font-semibold">{total}</span> total contacts over{' '}
          <span className="text-slate-200 font-semibold">{data.period_days}</span> days
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-cyan-400" /> Low drop-off (&lt;{DROP_LOW}%)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-amber-400" /> Moderate ({DROP_LOW}–{DROP_MID}%)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-rose-400" /> High drop-off (&gt;{DROP_MID}%)
        </span>
        <span className="ml-auto text-[10px] text-slate-600 italic">
          Numbers in brackets e.g. <span className="text-slate-500">SetContactData (2)</span> = 2nd occurrence of that block type in this flow
        </span>
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          layout="vertical"
          data={chartData}
          margin={{ top: 4, right: 90, bottom: 4, left: 210 }}
          barSize={28}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, total]}
            tick={{ fill: '#64748b', fontSize: 10 }}
            tickLine={{ stroke: '#334155' }}
            axisLine={{ stroke: '#334155' }}
          />
          <YAxis
            type="category"
            dataKey="block_name"
            width={205}
            tick={{ fill: '#cbd5e1', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<FunnelTooltip />} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={dropColor(entry.drop_pct)} fillOpacity={0.8} />
            ))}
            <LabelList
              dataKey="count"
              position="right"
              formatter={(v) => {
                const item = chartData.find((d) => d.count === v);
                return `${v} (${item?.pct?.toFixed(0) ?? 0}%)`;
              }}
              style={{ fill: '#94a3b8', fontSize: 10 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Step-by-step drop table */}
      <div className="mt-6 rounded-xl border border-slate-800 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-800/60">
              <th className="text-left py-2.5 px-4 font-medium text-slate-400">#</th>
              <th className="text-left py-2.5 px-4 font-medium text-slate-400">Block</th>
              <th className="text-right py-2.5 px-4 font-medium text-slate-400">Contacts</th>
              <th className="text-right py-2.5 px-4 font-medium text-slate-400">% of Total</th>
              <th className="text-right py-2.5 px-4 font-medium text-slate-400">
                Exited after block
                <span className="ml-1 text-[9px] text-slate-600">(didn't reach next)</span>
              </th>
              <th className="text-right py-2.5 px-4 font-medium text-slate-400">Exit Type</th>
            </tr>
          </thead>
          <tbody>
            {data.blocks.map((b, i) => {
              const color = blockColor(b.block_type);
              return (
                <tr key={i} className="border-t border-slate-800/40 hover:bg-slate-800/20 transition">
                  <td className="py-2.5 px-4 text-slate-600 tabular-nums">{b.sequence}</td>
                  <td className="py-2.5 px-4">
                    <div className="flex items-center gap-2">
                      <span
                        className="h-2 w-2 rounded-full shrink-0"
                        style={{ background: color }}
                      />
                      <span className="text-slate-200">{b.block_name}</span>
                      <span
                        className="text-[9px] rounded-full px-1.5 py-0.5"
                        style={{ background: color + '20', color }}
                      >
                        {b.block_type}
                      </span>
                    </div>
                  </td>
                  <td className="py-2.5 px-4 text-right font-semibold text-slate-200 tabular-nums">
                    {b.count}
                  </td>
                  <td className="py-2.5 px-4 text-right tabular-nums">
                    <div className="flex items-center justify-end gap-2">
                      <div className="w-24 bg-slate-800 rounded-full h-1.5">
                        <div
                          className="h-1.5 rounded-full"
                          style={{ width: `${b.pct}%`, background: color }}
                        />
                      </div>
                      <span className="text-slate-300 w-10">{b.pct?.toFixed(1)}%</span>
                    </div>
                  </td>
                  <td className="py-2.5 px-4 text-right tabular-nums">
                    {b.drop_count > 0 ? (
                      <span className="font-semibold" style={{ color: dropColor(b.drop_pct) }}>
                        −{b.drop_count} ({b.drop_pct?.toFixed(1)}%)
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="py-2.5 px-4 text-right">
                    {b.drop_count > 0 && b.exit_intent ? (
                      <OutcomeBadge intent={b.exit_intent} small />
                    ) : (
                      <span className="text-slate-700">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const PERIOD_OPTIONS = [
  { label: '24 hours', value: 1  },
  { label: '7 days',   value: 7  },
  { label: '14 days',  value: 14 },
  { label: '30 days',  value: 30 },
  { label: '60 days',  value: 60 },
  { label: '90 days',  value: 90 },
];

// Flow suggestions are loaded from the Connect instance at runtime
// (no hardcoded list)

export default function FlowFunnelPage() {
  const [flowName,    setFlowName]    = useState('');
  const [days,        setDays]        = useState(30);
  const [data,        setData]        = useState(null);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState(null);
  const [flows,       setFlows]       = useState([]);   // real flows from Connect
  const [flowsLoaded, setFlowsLoaded] = useState(false);

  // Load real flow list from Connect on mount
  useEffect(() => {
    getContactFlows()
      .then((res) => {
        const list = res.flows || [];
        setFlows(list);
        setFlowsLoaded(true);
        // Auto-select the first flow with logging enabled, or the first flow overall
        const withLogging = list.filter((f) => f.logging_enabled);
        const first = withLogging[0] || list[0];
        if (first && !flowName) setFlowName(first.name);
      })
      .catch(() => {
        setFlowsLoaded(true); // allow manual entry even if fetch fails
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    if (!flowName.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getContactFunnel(flowName.trim(), days);
      setData(result);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to load funnel data');
    } finally {
      setLoading(false);
    }
  }, [flowName, days]);

  // Auto-load when flowName is set (don't fire with empty name on mount)
  useEffect(() => { if (flowName) load(); }, [load]);

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">

      {/* ── Page header ── */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/15">
            <TrendingDown size={18} className="text-cyan-400" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-slate-100">Flow Funnel Analysis</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Aggregate drop-off across all contacts for a selected flow and time period
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-slate-300 hover:text-slate-100 transition disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* ── Controls ── */}
      <div className="flex flex-wrap items-end gap-4 rounded-2xl border border-slate-800 bg-slate-900/60 px-5 py-4">

        {/* Flow name */}
        <div className="flex flex-col gap-1.5 min-w-[280px]">
          <label className="text-[10px] font-medium uppercase tracking-widest text-slate-500">
            Flow Name
          </label>
          <input
            type="text"
            value={flowName}
            onChange={(e) => setFlowName(e.target.value)}
            placeholder={flowsLoaded ? 'Type or select a flow below' : 'Loading flows…'}
            className="h-8 rounded-lg border border-slate-700 bg-slate-800 px-3 text-xs text-slate-200 placeholder-slate-600 focus:border-cyan-500 focus:outline-none transition"
          />
          {/* Quick-pick chips from real Connect flows */}
          <div className="flex flex-wrap gap-1 mt-0.5">
            {!flowsLoaded && (
              <span className="text-[9px] text-slate-600 italic">Loading flows from Connect…</span>
            )}
            {flows.map((f) => (
              <button
                key={f.id || f.name}
                type="button"
                onClick={() => setFlowName(f.name)}
                title={f.logging_enabled ? 'Flow logging enabled' : 'No CloudWatch log group found'}
                className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[9px] font-medium transition ${
                  flowName === f.name
                    ? 'bg-cyan-500/25 text-cyan-300'
                    : 'bg-slate-800 text-slate-500 hover:text-slate-300'
                }`}
              >
                {f.logging_enabled
                  ? <Wifi size={8} className="text-emerald-400 shrink-0" />
                  : <WifiOff size={8} className="text-slate-600 shrink-0" />}
                {f.name}
              </button>
            ))}
          </div>
        </div>

        {/* Time period */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-medium uppercase tracking-widest text-slate-500">
            Time Period
          </label>
          <div className="flex rounded-lg border border-slate-700 overflow-hidden">
            {PERIOD_OPTIONS.map(({ label, value }) => (
              <button
                key={value}
                type="button"
                onClick={() => setDays(value)}
                className={`px-3 py-1.5 text-xs transition ${
                  days === value
                    ? 'bg-cyan-600 text-white'
                    : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Content ── */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        {loading && (
          <div className="flex h-64 items-center justify-center gap-2 text-sm text-slate-400">
            <RefreshCw size={16} className="animate-spin text-cyan-400" />
            Loading funnel for <span className="font-mono text-slate-200">{flowName}</span>…
          </div>
        )}

        {!loading && error && (
          <div className="flex items-center gap-3 rounded-xl border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            <AlertCircle size={16} className="shrink-0" />
            {error}
          </div>
        )}

        {!loading && !error && data && (
          <>
            <div className="mb-4 flex items-center gap-3">
              <BarChart2 size={14} className="text-cyan-400" />
              <p className="text-sm font-semibold text-slate-200">
                Funnel Drop-off —{' '}
                <span className="font-mono text-cyan-400">{flowName}</span>
              </p>
              {data.mock && (
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[9px] text-amber-400">
                  sample data
                </span>
              )}
            </div>
            <FunnelChart data={data} />
          </>
        )}

        {!loading && !error && !data && (
          <div className="flex h-64 items-center justify-center text-xs text-slate-500">
            Enter a flow name and select a time period to view the funnel.
          </div>
        )}
      </div>
    </div>
  );
}
