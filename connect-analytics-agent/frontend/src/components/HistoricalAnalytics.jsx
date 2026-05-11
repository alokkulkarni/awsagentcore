/**
 * HistoricalAnalytics — dedicated screen for historical contact centre metrics.
 *
 * Combines the historical charts from MetricsDashboard and the full
 * BotMetricsDashboard into a single, cohesive analytics view with a shared
 * period selector and an "Ask AI" shortcut.
 */

import { useEffect, useMemo, useState } from 'react';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import {
  AlertTriangle, Bot, RefreshCw, Sparkles, TrendingUp,
  Users, MessageSquare, Zap, ChevronDown, ChevronUp,
} from 'lucide-react';
import { getHistoricalMetrics, getBotMetrics } from '../services/api';

// ── constants ──────────────────────────────────────────────────────────────────

const CHART_COLOURS = {
  CONTACTS_HANDLED:            '#10b981',
  AVG_HANDLE_TIME:             '#2563eb',
  CONTACTS_ABANDONED:          '#f59e0b',
  CONTACTS_QUEUED:             '#818cf8',
  AVG_AFTER_CONTACT_WORK_TIME: '#f472b6',
};

const METRIC_LABELS = {
  CONTACTS_HANDLED:            'Contacts Handled',
  AVG_HANDLE_TIME:             'Avg Handle Time',
  CONTACTS_ABANDONED:          'Contacts Abandoned',
  CONTACTS_QUEUED:             'Contacts Queued',
  AVG_AFTER_CONTACT_WORK_TIME: 'Avg ACW Time',
};

const PIE_COLORS = ['#10b981', '#f59e0b', '#f43f5e', '#6366f1', '#22d3ee'];

// ── helpers ────────────────────────────────────────────────────────────────────

function fmtSeconds(v) {
  if (!v) return '0s';
  const s = Math.round(v);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m === 0 ? `${sec}s` : `${m}m ${sec < 10 ? '0' + sec : sec}s`;
}

// "08:00" → "8am–9am", everything else unchanged
function fmtXLabel(label) {
  const m = String(label).match(/^(\d{1,2}):(\d{2})$/);
  if (m) {
    const h = parseInt(m[1], 10);
    const nextH = (h + 1) % 24;
    const fmt = (n) => n === 0 ? '12am' : n === 12 ? '12pm' : n < 12 ? `${n}am` : `${n - 12}pm`;
    return `${fmt(h)}–${fmt(nextH)}`;
  }
  return label;
}

// ── shared chart wrapper ────────────────────────────────────────────────────────

function HistoricChart({ title, data, bars, rightBars = [] }) {
  const gridColor   = '#334155';
  const tickColor   = '#94a3b8';
  const tooltipBg   = '#1e293b';
  const tooltipBdr  = '#334155';
  const tooltipLbl  = '#f1f5f9';
  const tooltipItem = '#94a3b8';

  if (!data?.length) return (
    <div className="flex h-40 items-center justify-center text-xs text-slate-500">No data available</div>
  );
  return (
    <div>
      <p className="mb-3 text-sm font-semibold text-slate-300">{title}</p>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: rightBars.length ? 52 : 8, left: 0, bottom: 28 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
          <XAxis
            dataKey="label"
            tickFormatter={fmtXLabel}
            tick={{ fill: tickColor, fontSize: 10 }}
            angle={-30}
            textAnchor="end"
            interval={0}
          />
          <YAxis yAxisId="left" tick={{ fill: tickColor, fontSize: 10 }} allowDecimals={false} width={28} />
          {rightBars.length > 0 && (
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fill: tickColor, fontSize: 10 }}
              tickFormatter={fmtSeconds}
              width={44}
            />
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
          <Legend
            wrapperStyle={{ fontSize: 11, color: tickColor, paddingTop: 8 }}
            formatter={(v) => METRIC_LABELS[v] ?? v}
          />
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

// ── Section header with collapse ───────────────────────────────────────────────

function SectionCard({ title, subtitle, icon: Icon, iconCls = 'text-connect-400', children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 p-4 text-left hover:bg-slate-800/30 transition rounded-2xl"
      >
        {Icon && <Icon size={18} className={iconCls} />}
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
        </div>
        {open ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
}

// ── StatCard ───────────────────────────────────────────────────────────────────

function StatCard({ label, value, icon: Icon, accentCls = 'text-slate-300', sub }) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-3">
      <div className="flex items-start justify-between mb-1">
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">{label}</span>
        {Icon && <Icon size={14} className={accentCls} />}
      </div>
      <p className={`text-2xl font-bold ${accentCls}`}>{value ?? '—'}</p>
      {sub && <p className="text-[10px] text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Contact-centre historical section ──────────────────────────────────────────

function ContactCentreHistory({ onAskAssistant }) {
  const [histDays, setHistDays]     = useState(30);
  const [historical, setHistorical] = useState(null);
  const [loading, setLoading]       = useState(false);

  const load = async (days) => {
    setLoading(true);
    try { setHistorical(await getHistoricalMetrics(days)); }
    catch { setHistorical(null); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(histDays); }, [histDays]); // eslint-disable-line react-hooks/exhaustive-deps

  const mergedHandledAbandoned = useMemo(() => {
    const map = {};
    (historical?.data ?? []).forEach((r) => {
      const k = r.date_key ?? r.label;
      map[k] = { label: r.label, date_key: k, CONTACTS_HANDLED: r.CONTACTS_HANDLED };
    });
    (historical?.abandoned ?? []).forEach((r) => {
      const k = r.date_key ?? r.label;
      if (!map[k]) map[k] = { label: r.label, date_key: k, CONTACTS_HANDLED: 0 };
      map[k].CONTACTS_ABANDONED = r.CONTACTS_ABANDONED;
    });
    return Object.values(map).sort((a, b) => (a.date_key ?? a.label) < (b.date_key ?? b.label) ? -1 : 1);
  }, [historical]);

  return (
    <SectionCard
      title="Contact Centre Performance"
      subtitle={historical?.period ?? `Last ${histDays} days`}
      icon={TrendingUp}
      iconCls="text-connect-400"
    >
      <div className="flex items-center gap-3 mb-4">
        <select
          value={histDays}
          onChange={(e) => setHistDays(Number(e.target.value))}
          className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-connect-500"
        >
          {[7, 14, 30, 60, 90].map((d) => (
            <option key={d} value={d}>Last {d} days</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => load(histDays)}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700 transition"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
        {onAskAssistant && (
          <button
            type="button"
            onClick={() => onAskAssistant(`Analyse contact centre performance over the last ${histDays} days. Highlight trends, peaks, and any areas of concern.`)}
            className="inline-flex items-center gap-2 rounded-xl bg-connect-500 px-3 py-2 text-sm font-medium text-white hover:bg-connect-700 transition"
          >
            <Sparkles size={14} /> Ask AI
          </button>
        )}
        {historical?.mock && (
          <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-300">mock data</span>
        )}
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center text-sm text-slate-400">
          <RefreshCw size={18} className="mr-2 animate-spin" /> Loading historical data…
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
            <HistoricChart title="Contacts Handled per Day" data={historical?.data ?? []} bars={['CONTACTS_HANDLED']} />
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
            <HistoricChart title="Avg Handle Time per Day" data={historical?.data ?? []} bars={[]} rightBars={['AVG_HANDLE_TIME']} />
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4 lg:col-span-2">
            <HistoricChart title="Contacts Handled vs Abandoned" data={mergedHandledAbandoned} bars={['CONTACTS_HANDLED', 'CONTACTS_ABANDONED']} />
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
            <HistoricChart title="Contacts in Queue per Day" data={historical?.data ?? []} bars={['CONTACTS_QUEUED']} />
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
            <HistoricChart title="Avg ACW Time per Day" data={historical?.data ?? []} bars={[]} rightBars={['AVG_AFTER_CONTACT_WORK_TIME']} />
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ── Bot / Conversational AI section ───────────────────────────────────────────

function BotSection({ onAskAssistant }) {
  const [days, setDays]     = useState(7);
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  const load = async (d) => {
    setLoading(true); setError(null);
    try { setData(await getBotMetrics(d)); }
    catch (e) { setError(e.message || 'Failed to load bot metrics'); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(days); }, [days]); // eslint-disable-line react-hooks/exhaustive-deps

  const inventory    = data?.bot_inventory  || { total_bots: 0, bots: [] };
  const lexAnalytics = data?.lex_analytics  || [];
  const flowMetrics  = data?.flow_metrics   || [];
  const cwMetrics    = data?.lex_cloudwatch_metrics || [];
  const primaryBot   = lexAnalytics[0] || null;

  const intentChartData = useMemo(() => {
    if (!primaryBot) return [];
    return (primaryBot.intent_metrics || []).map((i) => ({
      name:       i.intent_name === 'AmazonQinConnect' ? 'Q in Connect' : i.intent_name,
      Total:      i.total,
      Successful: i.successful,
      Dropped:    i.dropped,
      Failed:     i.failed,
    }));
  }, [primaryBot]);

  const sessionPieData = useMemo(() => {
    if (!primaryBot?.session_metrics) return [];
    const sm = primaryBot.session_metrics;
    return [
      { name: 'Successful', value: sm.successful },
      { name: 'Escalated',  value: sm.escalated  },
      { name: 'Failed',     value: sm.failed      },
    ].filter((d) => d.value > 0);
  }, [primaryBot]);

  const cwByMetric = useMemo(() => {
    const grouped = {};
    cwMetrics.forEach((m) => {
      grouped[m.metric_name] = (grouped[m.metric_name] || 0) + (m.total || m.total_or_avg || 0);
    });
    return grouped;
  }, [cwMetrics]);

  return (
    <SectionCard
      title="Conversational AI & Bot Analytics"
      subtitle={inventory.total_bots ? `${inventory.total_bots} bot${inventory.total_bots !== 1 ? 's' : ''} associated` : 'No bots configured'}
      icon={Bot}
      iconCls="text-indigo-400"
    >
      {/* Controls */}
      <div className="flex items-center gap-3 mb-4">
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
        >
          {[1, 7, 14, 30].map((d) => (
            <option key={d} value={d}>{d === 1 ? 'Last 24h' : `Last ${d} days`}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => load(days)}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700 transition"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
        {onAskAssistant && (
          <button
            type="button"
            onClick={() => onAskAssistant(`What are the key bot and conversational AI trends over the last ${days} day${days !== 1 ? 's' : ''}? Include containment rate, escalations, and any areas needing attention.`)}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition"
          >
            <Sparkles size={14} /> Ask AI
          </button>
        )}
        {data?.mock && (
          <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-300">mock data</span>
        )}
      </div>

      {loading && (
        <div className="flex h-40 items-center justify-center text-sm text-slate-400">
          <RefreshCw size={18} className="mr-2 animate-spin" /> Loading bot metrics…
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">
          <AlertTriangle size={14} className="inline mr-1" /> {error}
        </div>
      )}

      {!loading && !error && !inventory.total_bots && (
        <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center">
          <Bot size={32} className="mx-auto mb-2 text-slate-600" />
          <p className="text-sm font-semibold text-slate-400">No bots associated with this Connect instance</p>
          <p className="text-xs text-slate-500 mt-1">Associate a Lex V2 bot or enable Amazon Q in Connect.</p>
        </div>
      )}

      {!loading && !error && inventory.total_bots > 0 && (
        <div className="space-y-5">
          {/* Bot inventory stat cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard
              label="Total Sessions"
              value={primaryBot?.session_metrics?.total ?? cwByMetric['RuntimeInvokedIntents'] ?? 0}
              icon={MessageSquare}
              accentCls="text-indigo-400"
            />
            <StatCard
              label="Escalated"
              value={primaryBot?.session_metrics?.escalated ?? 0}
              icon={Users}
              accentCls="text-amber-400"
              sub="transferred to agent"
            />
            <StatCard
              label="Containment Rate"
              value={(() => {
                const sm = primaryBot?.session_metrics;
                if (!sm?.total) return '—';
                return `${Math.round((sm.successful / sm.total) * 100)}%`;
              })()}
              icon={Zap}
              accentCls="text-emerald-400"
            />
            <StatCard
              label="Bots Active"
              value={inventory.total_bots}
              icon={Bot}
              accentCls="text-indigo-400"
            />
          </div>

          {/* Charts */}
          <div className="grid gap-5 lg:grid-cols-2">
            {/* Session outcome pie */}
            {sessionPieData.length > 0 && (
              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
                <p className="text-sm font-semibold text-slate-300 mb-3">Session Outcomes</p>
                <div className="flex items-center gap-4">
                  <ResponsiveContainer width="50%" height={180}>
                    <PieChart>
                      <Pie data={sessionPieData} dataKey="value" cx="50%" cy="50%" outerRadius={70} label={false}>
                        {sessionPieData.map((_, i) => (
                          <Cell key={i} fill={PIE_COLORS[i]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                        labelStyle={{ color: '#f1f5f9' }}
                        itemStyle={{ color: '#94a3b8' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="space-y-2">
                    {sessionPieData.map((d, i) => (
                      <div key={d.name} className="flex items-center gap-2 text-xs">
                        <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: PIE_COLORS[i] }} />
                        <span className="text-slate-300">{d.name}</span>
                        <span className="font-semibold text-slate-100 ml-auto">{d.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Intent breakdown */}
            {intentChartData.length > 0 && (
              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
                <p className="text-sm font-semibold text-slate-300 mb-3">Intent Breakdown</p>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={intentChartData} margin={{ top: 4, right: 8, left: 0, bottom: 28 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 9 }} angle={-20} textAnchor="end" interval={0} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} allowDecimals={false} width={24} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                      labelStyle={{ color: '#f1f5f9' }}
                      itemStyle={{ color: '#94a3b8' }}
                    />
                    <Legend wrapperStyle={{ fontSize: 10, color: '#94a3b8' }} />
                    <Bar dataKey="Total"      fill="#6366f1" radius={[2, 2, 0, 0]} />
                    <Bar dataKey="Successful" fill="#10b981" radius={[2, 2, 0, 0]} />
                    <Bar dataKey="Dropped"    fill="#f59e0b" radius={[2, 2, 0, 0]} />
                    <Bar dataKey="Failed"     fill="#f43f5e" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Flow metrics */}
            {flowMetrics.length > 0 && (
              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4 lg:col-span-2">
                <p className="text-sm font-semibold text-slate-300 mb-3">Contact Flow Metrics</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-800">
                      <tr>
                        {['Flow', 'Type', 'Started', 'Outcome', 'Outcome %'].map((c) => (
                          <th key={c} className="px-3 py-2 text-left font-medium text-slate-400">{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {flowMetrics.map((f, i) => (
                        <tr key={i} className="border-t border-slate-800/60">
                          <td className="px-3 py-2 text-slate-200 font-medium">{f.flow_name || '—'}</td>
                          <td className="px-3 py-2 text-slate-400">{f.flow_type || '—'}</td>
                          <td className="px-3 py-2 text-indigo-400 font-semibold">{f.metrics?.FLOWS_STARTED ?? 0}</td>
                          <td className="px-3 py-2 text-emerald-400 font-semibold">{f.metrics?.FLOWS_OUTCOME ?? 0}</td>
                          <td className="px-3 py-2 text-slate-300">
                            {f.metrics?.PERCENT_FLOWS_OUTCOME != null
                              ? `${Math.round(f.metrics.PERCENT_FLOWS_OUTCOME * 100)}%`
                              : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {/* Bot inventory list */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Bot Inventory</p>
            <div className="space-y-1">
              {(inventory.bots || []).map((bot, i) => (
                <div key={i} className="flex items-center gap-3 rounded-xl border border-slate-700/60 bg-slate-800/40 p-3 text-xs">
                  <Bot size={14} className="text-indigo-400 shrink-0" />
                  <div className="flex-1">
                    <p className="font-medium text-slate-200">{bot.bot_name || bot.name || `Bot ${i + 1}`}</p>
                    {bot.bot_type && <p className="text-slate-500">{bot.bot_type}</p>}
                  </div>
                  {bot.status && (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${bot.status === 'Available' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-slate-600/30 text-slate-400'}`}>
                      {bot.status}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ── Main export ────────────────────────────────────────────────────────────────

export default function HistoricalAnalytics({ onAskAssistant }) {
  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Historical Analytics</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Contact centre performance trends and conversational AI insights
          </p>
        </div>
        {onAskAssistant && (
          <button
            type="button"
            onClick={() => onAskAssistant('Give me a complete operational summary of the contact centre performance and bot analytics for the past 30 days. What are the key trends and what actions should leadership take?')}
            className="inline-flex items-center gap-2 rounded-xl bg-connect-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-connect-700 transition"
          >
            <Sparkles size={15} /> Ask AI for Full Report
          </button>
        )}
      </div>

      <ContactCentreHistory onAskAssistant={onAskAssistant} />
      <BotSection onAskAssistant={onAskAssistant} />
    </div>
  );
}
