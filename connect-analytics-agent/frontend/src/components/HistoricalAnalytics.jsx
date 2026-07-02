/**
 * HistoricalAnalytics — dedicated screen for historical contact centre metrics.
 *
 * Combines the historical charts from MetricsDashboard and the full
 * BotMetricsDashboard into a single, cohesive analytics view with a shared
 * period selector and an "Ask AI" shortcut.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ComposedChart, Bar, Line, BarChart, LineChart, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import {
  AlertTriangle, Bot, PhoneOff, PhoneCall, Percent, RefreshCw, Sparkles, TrendingUp,
  Users, MessageSquare, MessagesSquare, Zap, ChevronDown, ChevronUp,
  BarChart2, UserCheck,
} from 'lucide-react';
import {
  getHistoricalMetrics, getBotMetrics, getBotIntentTrend, getHistoricalBreakdown,
  startDisconnectReasonScan, getDisconnectReasonStatus,
  startCallbackScan, getCallbackStatus,
} from '../services/api';
import TranscriptThemes from './TranscriptThemes';

// ── constants ──────────────────────────────────────────────────────────────────

const CHART_COLOURS = {
  CONTACTS_HANDLED:            '#10b981',
  // Handle time — darker = avg per contact, lighter = total capacity
  AVG_HANDLE_TIME_MIN:         '#2563eb',
  TOTAL_HANDLE_TIME_MIN:       '#93c5fd',
  // Keep raw-seconds key for backward compat (unused in charts now)
  AVG_HANDLE_TIME:             '#2563eb',
  CONTACTS_ABANDONED:          '#f59e0b',
  CONTACTS_QUEUED:             '#818cf8',
  // Talk time — the "actual conversation" slice of handle time
  AVG_TALK_TIME_MIN:           '#0891b2',
  TOTAL_TALK_TIME_MIN:         '#67e8f9',
  AVG_TALK_TIME:               '#0891b2',
  // ACW time — pink = avg per contact, amber = total capacity
  AVG_ACW_TIME_MIN:            '#db2777',
  TOTAL_ACW_TIME_MIN:          '#fb923c',
  AVG_AFTER_CONTACT_WORK_TIME: '#db2777',
};

const METRIC_LABELS = {
  CONTACTS_HANDLED:            'Contacts Handled',
  AVG_HANDLE_TIME_MIN:         'Avg Handle Time',
  TOTAL_HANDLE_TIME_MIN:       'Total Handle Time',
  AVG_HANDLE_TIME:             'Avg Handle Time',
  CONTACTS_ABANDONED:          'Contacts Abandoned',
  CONTACTS_QUEUED:             'Contacts Queued',
  AVG_TALK_TIME_MIN:           'Avg Talk Time',
  TOTAL_TALK_TIME_MIN:         'Total Talk Time',
  AVG_TALK_TIME:               'Avg Talk Time',
  AVG_ACW_TIME_MIN:            'Avg Wrap (ACW) Time',
  TOTAL_ACW_TIME_MIN:          'Total ACW Time',
  AVG_AFTER_CONTACT_WORK_TIME: 'Avg ACW Time',
};

const PIE_COLORS = ['#10b981', '#f59e0b', '#f43f5e', '#6366f1', '#22d3ee'];

// Palette for up to 10 entities (queues or agents) in breakdown charts
const ENTITY_PALETTE = [
  '#6366f1', '#10b981', '#f59e0b', '#f43f5e', '#22d3ee',
  '#a855f7', '#3b82f6', '#ec4899', '#84cc16', '#fb923c',
];

function entityColor(idx) { return ENTITY_PALETTE[idx % ENTITY_PALETTE.length]; }

// ── Stacked bar chart for daily entity breakdowns ────────────────────────────

function BreakdownStackedChart({ title, data, entities, valueExtractor, yTickFmt, chartHeight = 220, emptyMsg }) {
  const tickColor  = '#94a3b8';
  const gridColor  = '#334155';
  const tooltipBg  = '#1e293b';
  const tooltipBdr = '#334155';

  // Pivot raw data to [{label, EntityA: val, EntityB: val}]
  const chartData = useMemo(() => data.map((row) => {
    const out = { label: row.label };
    entities.forEach((ent) => {
      out[ent] = valueExtractor(row[ent] ?? {});
    });
    return out;
  }), [data, entities, valueExtractor]);

  if (!chartData.length) return (
    <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500">{emptyMsg ?? 'No data'}</div>
  );

  return (
    <div>
      <p className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">{title}</p>
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 32 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
          <XAxis
            dataKey="label"
            tick={{ fill: tickColor, fontSize: 10 }}
            angle={-30}
            textAnchor="end"
            interval={0}
          />
          <YAxis
            tick={{ fill: tickColor, fontSize: 10 }}
            tickFormatter={yTickFmt}
            width={yTickFmt ? 44 : 32}
            allowDecimals={!!yTickFmt}
          />
          <Tooltip
            contentStyle={{ backgroundColor: tooltipBg, border: `1px solid ${tooltipBdr}`, borderRadius: 8 }}
            labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
            itemStyle={{ color: tickColor }}
            formatter={(v, name) => [yTickFmt ? yTickFmt(v) : v, name]}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, color: tickColor, paddingTop: 6 }}
            iconSize={10}
          />
          {entities.map((ent, i) => (
            <Bar key={ent} dataKey={ent} stackId="stack" fill={entityColor(i)} radius={i === entities.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Grouped bar for Handled vs Abandoned totals per entity ──────────────────

function HandledVsAbandonedChart({ title, totals, chartHeight = 240 }) {
  const tickColor  = '#94a3b8';
  const gridColor  = '#334155';
  const tooltipBg  = '#1e293b';

  if (!totals?.length) return (
    <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500">No data</div>
  );

  return (
    <div>
      <p className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">{title}</p>
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart data={totals} layout="vertical" margin={{ top: 4, right: 12, left: 80, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} horizontal={false} />
          <XAxis type="number" tick={{ fill: tickColor, fontSize: 10 }} allowDecimals={false} />
          <YAxis
            type="category"
            dataKey="entity"
            tick={{ fill: tickColor, fontSize: 10 }}
            width={76}
          />
          <Tooltip
            contentStyle={{ backgroundColor: tooltipBg, border: '1px solid #334155', borderRadius: 8 }}
            labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
            itemStyle={{ color: tickColor }}
          />
          <Legend wrapperStyle={{ fontSize: 10, color: tickColor, paddingTop: 4 }} iconSize={10} />
          <Bar dataKey="CONTACTS_HANDLED" name="Handled" fill="#10b981" radius={[0, 3, 3, 0]} />
          <Bar dataKey="CONTACTS_ABANDONED" name="Abandoned" fill="#f59e0b" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Performance Breakdown section ───────────────────────────────────────────

function BreakdownSection({ days, onAskAssistant }) {
  const [groupBy, setGroupBy]   = useState('QUEUE');
  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);

  const load = async (d, gb) => {
    setLoading(true); setError(null);
    try {
      const res = await getHistoricalBreakdown(d, gb);
      setData(res);
    } catch (e) {
      setData(null);
      setError(e?.response?.data?.detail || e?.message || 'Failed to load breakdown');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(days, groupBy); }, [days, groupBy]); // eslint-disable-line

  const entities = data?.entities ?? [];

  // Minutes extractor for handle time: avg_ht × contacts ÷ 60
  const handleTimeMin = (m) => m.CONTACTS_HANDLED
    ? Math.round((m.AVG_HANDLE_TIME * m.CONTACTS_HANDLED) / 60 * 10) / 10
    : 0;

  const acwTimeMin = (m) => m.CONTACTS_HANDLED
    ? Math.round((m.AVG_AFTER_CONTACT_WORK_TIME * m.CONTACTS_HANDLED) / 60 * 10) / 10
    : 0;

  const handledCount = (m) => m.CONTACTS_HANDLED ?? 0;

  const askLabel = groupBy === 'QUEUE' ? 'queue' : 'agent';

  return (
    <SectionCard
      title="Performance Breakdown"
      subtitle={`${groupBy === 'QUEUE' ? 'By queue' : 'By agent'} — ${data?.period ?? `Last ${days} days`}`}
      icon={groupBy === 'QUEUE' ? BarChart2 : UserCheck}
      iconCls={groupBy === 'QUEUE' ? 'text-cyan-600 dark:text-cyan-400' : 'text-violet-600 dark:text-violet-400'}
    >
      {/* Tab bar + AI button */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex rounded-xl overflow-hidden border border-slate-300 dark:border-slate-700">
          {['QUEUE', 'AGENT'].map((gb) => (
            <button
              key={gb}
              type="button"
              onClick={() => setGroupBy(gb)}
              className={`px-4 py-2 text-xs font-medium transition ${
                groupBy === gb
                  ? 'bg-connect-500 text-white'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {gb === 'QUEUE' ? 'By Queue' : 'By Agent'}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => load(days, groupBy)}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
        {onAskAssistant && (
          <button
            type="button"
            onClick={() => onAskAssistant(
              `Analyse contact centre performance breakdown by ${askLabel} over the last ${days} days. Which ${askLabel}s are busiest, which have the highest handle or ACW time, and which have the most abandoned contacts?`
            )}
            className="inline-flex items-center gap-2 rounded-xl bg-connect-500 px-3 py-2 text-sm font-medium text-white hover:bg-connect-700 transition"
          >
            <Sparkles size={14} /> Ask AI
          </button>
        )}
        {data?.mock && (
          <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-300">mock data</span>
        )}
      </div>

      {loading && (
        <div className="flex h-40 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
          <RefreshCw size={18} className="mr-2 animate-spin" /> Loading breakdown…
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-600 dark:text-rose-300 flex items-start gap-2">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />{error}
        </div>
      )}
      {!loading && !error && data && (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* 1 — Contacts Handled per Day */}
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
            <BreakdownStackedChart
              title={`Contacts Handled per Day — by ${groupBy === 'QUEUE' ? 'Queue' : 'Agent'}`}
              data={data.daily}
              entities={entities}
              valueExtractor={handledCount}
              chartHeight={220}
            />
          </div>

          {/* 2 — Handle Time per Day */}
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
            <BreakdownStackedChart
              title={`Handle Time per Day (min) — by ${groupBy === 'QUEUE' ? 'Queue' : 'Agent'}`}
              data={data.daily}
              entities={entities}
              valueExtractor={handleTimeMin}
              yTickFmt={fmtMinutes}
              chartHeight={220}
            />
          </div>

          {/* 3 — Contacts Handled vs Abandoned (totals per entity) */}
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4 lg:col-span-2">
            <HandledVsAbandonedChart
              title={`Contacts Handled vs Abandoned — by ${groupBy === 'QUEUE' ? 'Queue' : 'Agent'}`}
              totals={data.totals}
              chartHeight={Math.max(180, entities.length * 44 + 60)}
            />
          </div>

          {/* 4 — ACW Time per Day */}
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4 lg:col-span-2">
            <BreakdownStackedChart
              title={`ACW Time per Day (min) — by ${groupBy === 'QUEUE' ? 'Queue' : 'Agent'}`}
              data={data.daily}
              entities={entities}
              valueExtractor={acwTimeMin}
              yTickFmt={fmtMinutes}
              chartHeight={200}
            />
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ── PCA (Percentage Calls Answered) per queue ────────────────────────────────
// PCA = CONTACTS_HANDLED ÷ (CONTACTS_HANDLED + CONTACTS_ABANDONED) × 100,
// across all channels. Computed client-side from the same
// /historical-breakdown payload BreakdownSection uses, so no extra
// GetMetricDataV2 call is made.

function pcaOf(handled, abandoned) {
  const total = (handled ?? 0) + (abandoned ?? 0);
  if (!total) return null;
  return Math.round(((handled ?? 0) / total) * 1000) / 10;
}

function pcaColour(v) {
  if (v == null) return '#475569';
  return v >= 80 ? '#10b981' : v >= 60 ? '#f59e0b' : '#f43f5e';
}

function QueuePcaSection({ days, onAskAssistant }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  const load = async (d) => {
    setLoading(true); setError(null);
    try {
      setData(await getHistoricalBreakdown(d, 'QUEUE'));
    } catch (e) {
      setData(null);
      setError(e?.response?.data?.detail || e?.message || 'Failed to load queue metrics');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(days); }, [days]); // eslint-disable-line

  const entities = data?.entities ?? [];

  const totalsPca = useMemo(() => (data?.totals ?? []).map((t) => ({
    entity: t.entity,
    pca: pcaOf(t.CONTACTS_HANDLED, t.CONTACTS_ABANDONED),
    handled: t.CONTACTS_HANDLED ?? 0,
    abandoned: t.CONTACTS_ABANDONED ?? 0,
  })), [data]);

  const dailyPca = useMemo(() => (data?.daily ?? []).map((row) => {
    const out = { label: row.label };
    entities.forEach((ent) => {
      const m = row[ent] ?? {};
      out[ent] = pcaOf(m.CONTACTS_HANDLED, m.CONTACTS_ABANDONED);
    });
    return out;
  }), [data, entities]);

  return (
    <SectionCard
      title="Percentage Calls Answered (PCA) by Queue"
      subtitle={`Handled ÷ (Handled + Abandoned) — ${data?.period ?? `Last ${days} days`}`}
      icon={Percent}
      iconCls="text-emerald-600 dark:text-emerald-400"
    >
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <button
          type="button"
          onClick={() => load(days)}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
        {onAskAssistant && (
          <button
            type="button"
            onClick={() => onAskAssistant(
              `Analyse the percentage of calls answered (PCA = contacts handled ÷ (handled + abandoned)) per queue over the last ${days} days. Which queues are underperforming, and what should the team do about it?`
            )}
            className="inline-flex items-center gap-2 rounded-xl bg-connect-500 px-3 py-2 text-sm font-medium text-white hover:bg-connect-700 transition"
          >
            <Sparkles size={14} /> Ask AI
          </button>
        )}
        {data?.mock && (
          <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-300">mock data</span>
        )}
      </div>

      <p className="mb-3 text-[11px] text-slate-600 dark:text-slate-500 leading-snug">
        PCA counts all channels. Queues with no handled or abandoned contacts in the period are shown without a value.
      </p>

      {loading && (
        <div className="flex h-40 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
          <RefreshCw size={18} className="mr-2 animate-spin" /> Loading PCA…
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-600 dark:text-rose-300 flex items-start gap-2">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />{error}
        </div>
      )}
      {!loading && !error && data && (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* 1 — PCA per queue (period totals) */}
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
            <p className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">PCA per Queue — period total</p>
            {totalsPca.length === 0 ? (
              <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500">No data</div>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(180, totalsPca.length * 44 + 60)}>
                <BarChart data={totalsPca} layout="vertical" margin={{ top: 4, right: 12, left: 80, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                  <XAxis type="number" domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
                  <YAxis type="category" dataKey="entity" tick={{ fill: '#94a3b8', fontSize: 10 }} width={76} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                    labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
                    itemStyle={{ color: '#94a3b8' }}
                    formatter={(v, _name, { payload }) => [
                      `${v}% (${payload.handled} handled / ${payload.abandoned} abandoned)`, 'PCA',
                    ]}
                  />
                  <Bar dataKey="pca" name="PCA" radius={[0, 3, 3, 0]}>
                    {totalsPca.map((row) => (
                      <Cell key={row.entity} fill={pcaColour(row.pca)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* 2 — Daily PCA trend per queue */}
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
            <p className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">Daily PCA Trend — per queue</p>
            {dailyPca.length === 0 ? (
              <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500">No data</div>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(220, totalsPca.length * 44 + 60)}>
                <LineChart data={dailyPca} margin={{ top: 4, right: 8, left: 0, bottom: 28 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} angle={-30} textAnchor="end" interval={0} />
                  <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => `${v}%`} width={40} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                    labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
                    itemStyle={{ color: '#94a3b8' }}
                    formatter={(v) => [`${v}%`]}
                  />
                  <Legend wrapperStyle={{ fontSize: 10, color: '#94a3b8', paddingTop: 6 }} iconSize={10} />
                  {entities.map((ent, i) => (
                    <Line
                      key={ent}
                      type="monotone"
                      dataKey={ent}
                      stroke={entityColor(i)}
                      strokeWidth={2}
                      connectNulls
                      dot={{ r: 2.5, fill: entityColor(i), strokeWidth: 0 }}
                      activeDot={{ r: 4 }}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ── helpers ────────────────────────────────────────────────────────────────────

function fmtSeconds(v) {
  if (!v) return '0s';
  const s = Math.round(v);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m === 0 ? `${sec}s` : `${m}m ${sec < 10 ? '0' + sec : sec}s`;
}

function fmtMinutes(v) {
  if (v == null || v === 0) return '0m';
  const m = Math.floor(v);
  const s = Math.round((v - m) * 60);
  return s === 0 ? `${m}m` : `${m}m ${s < 10 ? '0' + s : s}s`;
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
// bars       → left Y-axis bars (counts or normalised values)
// rightBars  → right Y-axis bars (legacy / secondary metric)
// rightLines → right Y-axis lines (legacy)
// yTickFmt   → optional left-axis tick formatter (default: number)
// chartHeight → chart height in px (default 200)

function HistoricChart({ title, subtitle, data, bars = [], rightBars = [], rightLines = [], yTickFmt, chartHeight = 200, stackBars = false }) {
  const gridColor   = '#334155';
  const tickColor   = '#94a3b8';
  const tooltipBg   = '#1e293b';
  const tooltipBdr  = '#334155';
  const tooltipLbl  = '#f1f5f9';
  const tooltipItem = '#94a3b8';

  const hasLeft  = bars.length > 0;
  const hasRight = rightBars.length > 0 || rightLines.length > 0;

  if (!data?.length) return (
    <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500">No data available</div>
  );

  // Tooltip: _MIN keys → fmtMinutes, time/acw keys → fmtSeconds, else raw
  const tooltipFormatter = (v, name) => {
    if (yTickFmt) return [yTickFmt(v), METRIC_LABELS[name] ?? name];
    if (/_MIN$/i.test(name)) return [fmtMinutes(v), METRIC_LABELS[name] ?? name];
    if (/time|duration|acw/i.test(name)) return [fmtSeconds(v), METRIC_LABELS[name] ?? name];
    return [v, METRIC_LABELS[name] ?? name];
  };

  const rightTickFmt = (v) =>
    (rightLines.length > 0 && rightBars.length === 0) ? fmtMinutes(v) : fmtSeconds(v);

  return (
    <div>
      <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">{title}</p>
      {subtitle
        ? <p className="mb-2 text-[11px] text-slate-600 dark:text-slate-500">{subtitle}</p>
        : <div className="mb-3" />}
      <ResponsiveContainer width="100%" height={chartHeight}>
        <ComposedChart
          data={data}
          margin={{ top: 4, right: hasRight ? 56 : 8, left: hasLeft ? 0 : -20, bottom: 28 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
          <XAxis
            dataKey="label"
            tickFormatter={fmtXLabel}
            tick={{ fill: tickColor, fontSize: 10 }}
            angle={-30}
            textAnchor="end"
            interval={0}
          />
          {hasLeft && (
            <YAxis
              yAxisId="left"
              tick={{ fill: tickColor, fontSize: 10 }}
              tickFormatter={yTickFmt}
              allowDecimals={!yTickFmt}
              width={yTickFmt ? 44 : 28}
            />
          )}
          {hasRight && (
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fill: tickColor, fontSize: 10 }}
              tickFormatter={rightTickFmt}
              width={48}
            />
          )}
          <Tooltip
            contentStyle={{ backgroundColor: tooltipBg, border: `1px solid ${tooltipBdr}`, borderRadius: 8 }}
            labelStyle={{ color: tooltipLbl, fontWeight: 600 }}
            itemStyle={{ color: tooltipItem }}
            formatter={tooltipFormatter}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: tickColor, paddingTop: 8 }}
            formatter={(v) => METRIC_LABELS[v] ?? v}
          />
          {bars.map((key, i) => (
            <Bar
              key={key}
              yAxisId="left"
              dataKey={key}
              name={key}
              fill={CHART_COLOURS[key] ?? '#6366f1'}
              radius={!stackBars || i === bars.length - 1 ? [3, 3, 0, 0] : 0}
              {...(stackBars ? { stackId: 'left' } : {})}
            />
          ))}
          {rightBars.map((key) => (
            <Bar key={key} yAxisId="right" dataKey={key} name={key}
              fill={CHART_COLOURS[key] ?? '#8b5cf6'} radius={[3, 3, 0, 0]} />
          ))}
          {rightLines.map((key) => (
            <Line
              key={key}
              yAxisId="right"
              type="monotone"
              dataKey={key}
              name={key}
              stroke={CHART_COLOURS[key] ?? '#f97316'}
              strokeWidth={2}
              dot={{ r: 3, fill: CHART_COLOURS[key] ?? '#f97316', strokeWidth: 0 }}
              activeDot={{ r: 5 }}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Section header with collapse ───────────────────────────────────────────────

function SectionCard({ title, subtitle, icon: Icon, iconCls = 'text-connect-700 dark:text-connect-400', children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 p-4 text-left hover:bg-slate-100 dark:hover:bg-slate-800/30 transition rounded-2xl"
      >
        {Icon && <Icon size={18} className={iconCls} />}
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">{title}</h3>
          {subtitle && <p className="text-xs text-slate-600 dark:text-slate-500">{subtitle}</p>}
        </div>
        {open ? <ChevronUp size={14} className="text-slate-600 dark:text-slate-500" /> : <ChevronDown size={14} className="text-slate-600 dark:text-slate-500" />}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
}

// ── StatCard ───────────────────────────────────────────────────────────────────

function StatCard({ label, value, icon: Icon, accentCls = 'text-slate-700 dark:text-slate-300', sub }) {
  return (
    <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/50 dark:bg-slate-800/50 p-3">
      <div className="flex items-start justify-between mb-1">
        <span className="text-[10px] font-semibold text-slate-600 dark:text-slate-500 uppercase tracking-wider">{label}</span>
        {Icon && <Icon size={14} className={accentCls} />}
      </div>
      <p className={`text-2xl font-bold ${accentCls}`}>{value ?? '—'}</p>
      {sub && <p className="text-[10px] text-slate-600 dark:text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Disconnect-reason breakdown ("Why Contacts Didn't Complete") ───────────────
// Backend: agent/disconnect_reasons.py — buckets Amazon Connect's own
// DisconnectReason/DisconnectDetails.PotentialDisconnectIssue fields into
// Customer/Agent/Technical/Other for (a) contacts abandoned in queue and
// (b) agent-connected contacts that ended abnormally. Normal, successfully
// completed calls are excluded — see that module's docstring for the exact
// scoping rule.

const REASON_COLOURS = { customer: '#3b82f6', agent: '#a855f7', technical: '#f59e0b', other: '#64748b' };
const REASON_LABELS  = { customer: 'Customer', agent: 'Agent', technical: 'Technical', other: 'Other' };
const REASON_KEYS = ['customer', 'agent', 'technical', 'other'];

function fmtDayLabel(dateStr) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
}

function DisconnectReasonsChart({ daily }) {
  if (!daily?.length) return (
    <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500">No data available</div>
  );
  const data = daily.map((d) => ({ ...d, label: fmtDayLabel(d.date) }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 28 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} angle={-30} textAnchor="end" interval={0} />
        <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} allowDecimals={false} width={28} />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
          labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
          itemStyle={{ color: '#94a3b8' }}
          formatter={(v, name) => [v, REASON_LABELS[name] ?? name]}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8', paddingTop: 8 }} formatter={(v) => REASON_LABELS[v] ?? v} />
        {REASON_KEYS.map((key, i) => (
          <Bar
            key={key}
            dataKey={key}
            name={key}
            stackId="reasons"
            fill={REASON_COLOURS[key]}
            radius={i === REASON_KEYS.length - 1 ? [3, 3, 0, 0] : 0}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function DisconnectReasonsPanel({ days, onAskAssistant }) {
  const [scan, setScan] = useState(null);
  const [error, setError] = useState(null);
  const [expandedBucket, setExpandedBucket] = useState(null);
  const esRef = useRef(null);

  const closeStream = () => {
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
  };

  const openStream = () => {
    closeStream();
    const es = new EventSource('/api/disconnect-reasons/stream');
    es.onmessage = (evt) => {
      let data;
      try { data = JSON.parse(evt.data); } catch { return; }
      setScan((prev) => ({ ...prev, ...data }));
      if (data.type === 'scan_complete' || data.type === 'already_complete') {
        closeStream();
      } else if (data.type === 'scan_error') {
        setError(data.message || 'Disconnect-reason scan failed');
        closeStream();
      }
    };
    es.onerror = () => closeStream();
    esRef.current = es;
  };

  useEffect(() => {
    (async () => {
      try {
        const status = await getDisconnectReasonStatus();
        setScan(status);
        if (status.running) openStream();
      } catch {
        // No prior scan yet — fine.
      }
    })();
    return () => closeStream();
  }, []);

  const runScan = async () => {
    setError(null);
    setExpandedBucket(null);
    try {
      const end = new Date();
      const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
      const result = await startDisconnectReasonScan({ start: start.toISOString(), end: end.toISOString() });
      setScan(result);
      openStream();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to start disconnect-reason scan');
    }
  };

  const running = !!scan?.running;
  const result = scan?.result;
  const totals = result?.totals;

  return (
    <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4 lg:col-span-2">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          <PhoneOff size={14} className="inline mr-1.5 text-rose-600 dark:text-rose-400" />
          Why Contacts Didn't Complete
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={runScan}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={12} className={running ? 'animate-spin' : ''} />
            {running ? 'Scanning…' : `Scan Last ${days} Days`}
          </button>
          {onAskAssistant && totals && (
            <button
              type="button"
              onClick={() => onAskAssistant(
                `Over the last ${days} days, contacts didn't complete for these reasons: `
                + `${totals.customer} customer, ${totals.agent} agent, ${totals.technical} technical, ${totals.other} other. `
                + 'What should the contact centre team investigate first?'
              )}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
            >
              <Sparkles size={12} /> Ask AI
            </button>
          )}
          {scan?.mock_mode && (
            <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-300">mock data</span>
          )}
        </div>
      </div>

      <p className="mb-3 text-[11px] text-slate-600 dark:text-slate-500 leading-snug">
        Includes contacts abandoned in queue (never reached an agent) plus agent-connected contacts that ended
        via an agent-side or technical disconnect. Normal, successfully completed calls are excluded.
      </p>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-600 dark:text-rose-300 flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {error}
        </div>
      )}

      {running && (
        <div className="mb-3 rounded-xl border border-indigo-700/30 bg-indigo-900/20 p-3 text-xs text-slate-700 dark:text-slate-300">
          <div className="flex items-center gap-2 mb-1">
            <RefreshCw size={12} className="animate-spin text-indigo-600 dark:text-indigo-400" />
            <span>{scan?.message || 'Scanning…'}</span>
          </div>
          <p className="text-slate-600 dark:text-slate-500">
            {scan?.contacts_scanned ?? 0}/{scan?.contacts_found ?? '…'} contacts checked
            {' · '}{scan?.unsuccessful_found ?? 0} unsuccessful so far
          </p>
        </div>
      )}

      {!running && !result && (
        <p className="text-xs text-slate-600 dark:text-slate-500">Click Scan to break down why contacts didn't complete, by reason.</p>
      )}

      {result && totals && (
        <>
          <div className="grid grid-cols-2 gap-2 mb-4 sm:grid-cols-4">
            {REASON_KEYS.map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setExpandedBucket((prev) => (prev === key ? null : key))}
                className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/60 dark:bg-slate-800/60 p-2.5 text-left hover:bg-slate-200 dark:hover:bg-slate-700/40 transition"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: REASON_COLOURS[key] }}>
                    {REASON_LABELS[key]}
                  </span>
                  {expandedBucket === key ? <ChevronUp size={11} className="text-slate-600 dark:text-slate-500" /> : <ChevronDown size={11} className="text-slate-600 dark:text-slate-500" />}
                </div>
                <p className="text-xl font-bold text-slate-900 dark:text-slate-100">{totals[key] ?? 0}</p>
                {expandedBucket === key && (
                  <div className="mt-2 space-y-0.5 border-t border-slate-300 dark:border-slate-700/60 pt-2">
                    {(result.top_reasons?.[key] || []).length === 0 && (
                      <p className="text-[10px] text-slate-600 dark:text-slate-500">No contacts in this bucket.</p>
                    )}
                    {(result.top_reasons?.[key] || []).map(([reason, count]) => (
                      <p key={reason} className="text-[10px] text-slate-500 dark:text-slate-400 font-mono">
                        {reason} <span className="text-slate-600">×{count}</span>
                      </p>
                    ))}
                  </div>
                )}
              </button>
            ))}
          </div>
          <DisconnectReasonsChart daily={result.daily} />
          <p className="mt-2 text-[10px] text-slate-600 dark:text-slate-500">
            {totals.abandoned ?? 0} abandoned in queue · {totals.handled_problem ?? 0} reached an agent but ended abnormally
          </p>
        </>
      )}
    </div>
  );
}

// ── Callback analytics ────────────────────────────────────────────────────────
// Backend: agent/callback_analytics.py — enumerates CALLBACK-initiated
// contacts, groups dial attempts belonging to one callback request via
// InitialContactId, and classifies each request as handled (reached an
// agent), failed (all attempts disconnected without an agent, with the final
// DisconnectReason as the failure reason) or pending. Retried = requests
// with more than one dial attempt.

const CALLBACK_COLOURS = {
  requested: '#6366f1',
  handled:   '#10b981',
  retried:   '#a855f7',
  failed:    '#f43f5e',
};

const CALLBACK_CARDS = [
  { key: 'requested', label: 'Requested', sub: 'unique callback requests' },
  { key: 'handled',   label: 'Handled',   sub: 'reached an agent' },
  { key: 'retried',   label: 'Retried',   sub: 'subset — >1 dial attempt' },
  { key: 'failed',    label: 'Failed',    sub: 'never reached an agent' },
];

function CallbackAnalyticsPanel({ days, onAskAssistant }) {
  const [scan, setScan] = useState(null);
  const [error, setError] = useState(null);
  const esRef = useRef(null);

  const closeStream = () => {
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
  };

  const openStream = () => {
    closeStream();
    const es = new EventSource('/api/callback-analytics/stream');
    es.onmessage = (evt) => {
      let data;
      try { data = JSON.parse(evt.data); } catch { return; }
      setScan((prev) => ({ ...prev, ...data }));
      if (data.type === 'scan_complete' || data.type === 'already_complete') {
        closeStream();
      } else if (data.type === 'scan_error') {
        setError(data.message || 'Callback scan failed');
        closeStream();
      }
    };
    es.onerror = () => closeStream();
    esRef.current = es;
  };

  useEffect(() => {
    (async () => {
      try {
        const status = await getCallbackStatus();
        setScan(status);
        if (status.running) openStream();
      } catch {
        // No prior scan yet — fine.
      }
    })();
    return () => closeStream();
  }, []);

  const runScan = async () => {
    setError(null);
    try {
      const end = new Date();
      const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
      const result = await startCallbackScan({ start: start.toISOString(), end: end.toISOString() });
      setScan(result);
      openStream();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to start callback scan');
    }
  };

  const running = !!scan?.running;
  const result = scan?.result;
  const totals = result?.totals;
  const clamped = !!(result?.window?.clamped ?? scan?.clamped);

  const totalsChartData = useMemo(() => (totals
    ? CALLBACK_CARDS.map(({ key, label }) => ({ name: label, key, value: totals[key] ?? 0 }))
    : []), [totals]);

  const dailyChartData = useMemo(() => (result?.daily ?? []).map((d) => ({
    ...d, label: fmtDayLabel(d.date),
  })), [result]);

  const failedTotal = totals?.failed ?? 0;

  return (
    <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          <PhoneCall size={14} className="inline mr-1.5 text-indigo-600 dark:text-indigo-400" />
          Callback Outcomes
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={runScan}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={12} className={running ? 'animate-spin' : ''} />
            {running ? 'Scanning…' : `Scan Last ${Math.min(days, 55)} Days`}
          </button>
          {onAskAssistant && totals && (
            <button
              type="button"
              onClick={() => onAskAssistant(
                `Over the last ${Math.min(days, 55)} days there were ${totals.requested} callback requests: `
                + `${totals.handled} handled, ${totals.failed} failed, ${totals.retried} retried. `
                + `Top failure reasons: ${(result.failure_reasons || []).slice(0, 3).map((r) => `${r.label} ×${r.count}`).join(', ') || 'none'}. `
                + 'What should the contact centre team do to improve callback success?'
              )}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
            >
              <Sparkles size={12} /> Ask AI
            </button>
          )}
          {scan?.mock_mode && (
            <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-300">mock data</span>
          )}
        </div>
      </div>

      <p className="mb-3 text-[11px] text-slate-600 dark:text-slate-500 leading-snug">
        A callback request is <span className="font-medium">handled</span> when a dial attempt reached an agent and{' '}
        <span className="font-medium">failed</span> when every attempt ended without one.{' '}
        <span className="font-medium">Retried</span> counts requests with more than one dial attempt — it is a subset
        of the others, so don't sum the four numbers. Retry detection groups contact records that share an initial
        contact, so "0 retried" means none were detected.
        {clamped && (
          <span className="text-amber-600 dark:text-amber-400"> Range clamped to the last 55 days — Amazon Connect's contact search window limit.</span>
        )}
      </p>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-600 dark:text-rose-300 flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {error}
        </div>
      )}

      {running && (
        <div className="mb-3 rounded-xl border border-indigo-700/30 bg-indigo-900/20 p-3 text-xs text-slate-700 dark:text-slate-300">
          <div className="flex items-center gap-2 mb-1">
            <RefreshCw size={12} className="animate-spin text-indigo-600 dark:text-indigo-400" />
            <span>{scan?.message || 'Scanning…'}</span>
          </div>
          <p className="text-slate-600 dark:text-slate-500">
            {scan?.contacts_scanned ?? 0}/{scan?.contacts_found ?? '…'} callback contacts checked
            {' · '}{scan?.callbacks_found ?? 0} callback requests so far
          </p>
        </div>
      )}

      {!running && !result && (
        <p className="text-xs text-slate-600 dark:text-slate-500">
          Click Scan to analyse callback requests, outcomes, retries and failure reasons.
        </p>
      )}

      {result && totals && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 gap-2 mb-4 sm:grid-cols-4">
            {CALLBACK_CARDS.map(({ key, label, sub }) => (
              <div key={key} className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/60 dark:bg-slate-800/60 p-2.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: CALLBACK_COLOURS[key] }}>
                  {label}
                </span>
                <p className="text-xl font-bold text-slate-900 dark:text-slate-100">{totals[key] ?? 0}</p>
                <p className="text-[10px] text-slate-600 dark:text-slate-500">
                  {key === 'handled' && totals.handle_rate != null ? `${totals.handle_rate}% handle rate` : sub}
                </p>
              </div>
            ))}
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            {/* Totals bar chart */}
            <div>
              <p className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">Callback Totals</p>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={totalsChartData} margin={{ top: 4, right: 8, left: -20, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                    labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
                    itemStyle={{ color: '#94a3b8' }}
                    formatter={(v) => [v, 'Callbacks']}
                  />
                  <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                    {totalsChartData.map((row) => (
                      <Cell key={row.key} fill={CALLBACK_COLOURS[row.key]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Failure reasons */}
            <div>
              <p className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">Failure Reasons</p>
              {(result.failure_reasons ?? []).length === 0 ? (
                <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500">
                  No failed callbacks in this period.
                </div>
              ) : (
                <div className="space-y-2">
                  {result.failure_reasons.map(({ reason, label, count }) => (
                    <div key={reason}>
                      <div className="flex items-center justify-between text-xs mb-0.5">
                        <span className="text-slate-700 dark:text-slate-300">{label}</span>
                        <span className="font-semibold text-slate-900 dark:text-slate-100 tabular-nums">{count}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-slate-300/60 dark:bg-slate-700 rounded-full h-1.5">
                          <div
                            className="h-1.5 rounded-full"
                            style={{
                              width: `${failedTotal ? Math.round((count / failedTotal) * 100) : 0}%`,
                              background: CALLBACK_COLOURS.failed,
                            }}
                          />
                        </div>
                        <span className="text-[10px] text-slate-600 dark:text-slate-500 font-mono">{reason}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Daily trend */}
            <div className="lg:col-span-2">
              <p className="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">Callbacks per Day</p>
              {dailyChartData.length === 0 ? (
                <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500">No data</div>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={dailyChartData} margin={{ top: 4, right: 8, left: -20, bottom: 28 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} angle={-30} textAnchor="end" interval={0} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                      labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
                      itemStyle={{ color: '#94a3b8' }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8', paddingTop: 8 }} />
                    <Bar dataKey="requested" name="Requested" fill={CALLBACK_COLOURS.requested} radius={[3, 3, 0, 0]} />
                    <Bar dataKey="handled"   name="Handled"   fill={CALLBACK_COLOURS.handled}   radius={[3, 3, 0, 0]} />
                    <Bar dataKey="failed"    name="Failed"    fill={CALLBACK_COLOURS.failed}    radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {(totals.pending ?? 0) > 0 && (
            <p className="mt-2 text-[10px] text-slate-600 dark:text-slate-500">
              {totals.pending} callback request{totals.pending !== 1 ? 's' : ''} still in progress — counted in
              Requested but not yet Handled or Failed.
            </p>
          )}
        </>
      )}
    </div>
  );
}

// ── Contact-centre historical section ──────────────────────────────────────────

function ContactCentreHistory({ onAskAssistant, histDays, setHistDays }) {
  const [historical, setHistorical] = useState(null);
  const [loading, setLoading]       = useState(false);
  const [loadError, setLoadError]   = useState(null);

  const load = async (days) => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await getHistoricalMetrics(days);
      setHistorical(data);
    } catch (err) {
      setHistorical(null);
      setLoadError(err?.response?.data?.detail || err?.message || 'Failed to load metrics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(histDays); }, [histDays]); // eslint-disable-line react-hooks/exhaustive-deps

  // Normalise avg times to minutes so they share the same Y-axis scale
  const timeData = useMemo(() => (historical?.data ?? []).map((r) => ({
    ...r,
    AVG_HANDLE_TIME_MIN: r.AVG_HANDLE_TIME ? Math.round((r.AVG_HANDLE_TIME / 60) * 100) / 100 : 0,
    AVG_TALK_TIME_MIN:   r.AVG_TALK_TIME ? Math.round((r.AVG_TALK_TIME / 60) * 100) / 100 : 0,
    AVG_ACW_TIME_MIN:    r.AVG_AFTER_CONTACT_WORK_TIME ? Math.round((r.AVG_AFTER_CONTACT_WORK_TIME / 60) * 100) / 100 : 0,
  })), [historical]);

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
      iconCls="text-connect-700 dark:text-connect-400"
    >
      <div className="flex items-center gap-3 mb-4">
        <select
          value={histDays}
          onChange={(e) => setHistDays(Number(e.target.value))}
          className="rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-200 focus:outline-none focus:border-connect-500"
        >
          {[7, 14, 30, 60, 90].map((d) => (
            <option key={d} value={d}>Last {d} days</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => load(histDays)}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
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
          <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-300">mock data</span>
        )}
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
          <RefreshCw size={18} className="mr-2 animate-spin" /> Loading historical data…
        </div>
      ) : loadError ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-600 dark:text-rose-300 flex items-start gap-2">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          <span>{loadError}</span>
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
            <HistoricChart title="Contacts Handled per Day" data={historical?.data ?? []} bars={['CONTACTS_HANDLED']} />
          </div>
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
            <HistoricChart
              title="Handle Time per Day (minutes)"
              subtitle="Talk time vs wrap (ACW) time — the two components of handle time agents spend the most on"
              data={timeData}
              bars={['AVG_TALK_TIME_MIN', 'AVG_ACW_TIME_MIN']}
              stackBars
              yTickFmt={fmtMinutes}
              chartHeight={220}
            />
          </div>
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4 lg:col-span-2">
            <HistoricChart title="Contacts Handled vs Abandoned" data={mergedHandledAbandoned} bars={['CONTACTS_HANDLED', 'CONTACTS_ABANDONED']} />
          </div>
          <DisconnectReasonsPanel days={histDays} onAskAssistant={onAskAssistant} />
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
            <HistoricChart title="Contacts in Queue per Day" data={historical?.data ?? []} bars={['CONTACTS_QUEUED']} />
          </div>
          <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
            <HistoricChart
              title="ACW Time per Day (minutes)"
              data={timeData}
              bars={['AVG_ACW_TIME_MIN', 'TOTAL_ACW_TIME_MIN']}
              yTickFmt={fmtMinutes}
              chartHeight={220}
            />
          </div>
        </div>
      )}
    </SectionCard>
  );
}

// ── Bot / Conversational AI section ───────────────────────────────────────────

// ── Intent category inference ──────────────────────────────────────────────────

const CATEGORY_RULES = [
  { re: /bill|payment|invoice|charge|fee|cost|price|refund|balance/i,   label: 'Billing & Payments',  color: '#3b82f6' },
  { re: /order|delivery|ship|track|package|dispatch|return/i,           label: 'Orders & Delivery',   color: '#8b5cf6' },
  { re: /tech|error|issue|problem|bug|fix|broken|device|internet/i,     label: 'Technical Support',   color: '#f59e0b' },
  { re: /account|profile|login|password|user|setting|update|detail/i,   label: 'Account Management',  color: '#10b981' },
  { re: /cancel|terminate|close|end|stop|leave/i,                       label: 'Cancellations',       color: '#f43f5e' },
  { re: /new|signup|register|upgrade|plan|subscribe|quote|offer/i,      label: 'Sales & Onboarding',  color: '#06b6d4' },
  { re: /complaint|complain|escalat|dissatisf/i,                        label: 'Complaints',          color: '#ec4899' },
];

function inferCategory(intentName) {
  // Match both raw AWS name (AmazonQinConnect) and display name (Q in Connect)
  if (/AmazonQinConnect|QinConnect|Q in Connect/i.test(intentName)) return { label: 'Q in Connect (LLM)', color: '#6366f1' };
  if (/fallback|unmatched|default/i.test(intentName))               return { label: 'Unmatched',          color: '#475569' };
  for (const { re, label, color } of CATEGORY_RULES) {
    if (re.test(intentName)) return { label, color };
  }
  return { label: 'General Enquiry', color: '#64748b' };
}

// ── Intent Details Table ───────────────────────────────────────────────────────

function IntentDetailsTable({ rows }) {
  if (!rows.length) return null;
  return (
    <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4 lg:col-span-2">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">Intent Performance by Category</p>
        <span className="text-xs text-slate-600 dark:text-slate-500">{rows.length} intent{rows.length !== 1 ? 's' : ''}</span>
      </div>
      {/* Explanation banner */}
      <div className="mb-3 rounded-lg bg-indigo-900/20 border border-indigo-700/30 px-3 py-2 text-[11px] text-slate-500 dark:text-slate-400 leading-snug">
        <span className="text-indigo-600 dark:text-indigo-400 font-semibold">How to read these metrics: </span>
        <span className="text-emerald-600 dark:text-emerald-400 font-semibold">Session Containment</span> (top stat card) = % of unique conversations fully handled by the bot.&nbsp;
        <span className="text-indigo-600 dark:text-indigo-400 font-semibold">Bot Resolved %</span> (table below) = (Successful + Switched) ÷ Total intent invocations — both count as "bot handled" since Switched is an internal LLM re-delegation, never reaching a human.&nbsp;
        <span className="text-purple-600 dark:text-purple-400 font-semibold">Switched</span> = internal LLM re-delegation to another flow in the same session (not a failure — the bot stayed in control).
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-300 dark:border-slate-700/60">
              <th className="text-left py-2 px-3 font-medium text-slate-500 dark:text-slate-400">Intent</th>
              <th className="text-left py-2 px-3 font-medium text-slate-500 dark:text-slate-400">Category</th>
              <th className="text-right py-2 px-3 font-medium text-slate-500 dark:text-slate-400">Total</th>
              <th className="text-right py-2 px-3 font-medium text-emerald-600 dark:text-emerald-400">Successful</th>
              <th className="text-right py-2 px-3 font-medium text-purple-600 dark:text-purple-400">Switched</th>
              <th className="text-right py-2 px-3 font-medium text-amber-600 dark:text-amber-400">Abandoned</th>
              <th className="text-right py-2 px-3 font-medium text-rose-600 dark:text-rose-400">Failed</th>
              <th className="text-left py-2 px-3 font-medium text-indigo-600 dark:text-indigo-400 w-36">Bot Resolved %</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-slate-200 dark:border-slate-800/50 hover:bg-slate-200 dark:hover:bg-slate-700/20 transition">
                <td className="py-2.5 px-3 text-slate-800 dark:text-slate-200 font-medium">{row.name}</td>
                <td className="py-2.5 px-3">
                  <span
                    className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                    style={{ background: row.category.color + '25', color: row.category.color }}
                  >
                    {row.category.label}
                  </span>
                </td>
                <td className="py-2.5 px-3 text-right text-slate-700 dark:text-slate-300 font-semibold tabular-nums">{row.Total ?? 0}</td>
                <td className="py-2.5 px-3 text-right text-emerald-600 dark:text-emerald-400 font-semibold tabular-nums">{row.Successful ?? 0}</td>
                <td className="py-2.5 px-3 text-right text-purple-600 dark:text-purple-400 font-semibold tabular-nums">{row.Switched ?? 0}</td>
                <td className="py-2.5 px-3 text-right text-amber-600 dark:text-amber-400 font-semibold tabular-nums">{row.Dropped ?? 0}</td>
                <td className="py-2.5 px-3 text-right text-rose-600 dark:text-rose-400 font-semibold tabular-nums">{row.Failed ?? 0}</td>
                <td className="py-2.5 px-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 min-w-[48px]">
                      <div
                        className="h-1.5 rounded-full"
                        style={{
                          width: `${row.hitRate}%`,
                          background: row.hitRate >= 70 ? '#10b981' : row.hitRate >= 40 ? '#f59e0b' : '#f43f5e',
                        }}
                      />
                    </div>
                    <span className="text-slate-700 dark:text-slate-300 w-8 text-right tabular-nums">{row.hitRate}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Intent Outcome Trend Chart ─────────────────────────────────────────────────

const TREND_SERIES = [
  { key: 'Successful', color: '#10b981', label: 'Successful' },
  { key: 'Dropped',    color: '#f59e0b', label: 'Abandoned'  },
  { key: 'Failed',     color: '#f43f5e', label: 'Failed'     },
];

function IntentTrendChart({ data = [], synthesized = false, aggSuccessRate = null, intentHitRate = null }) {
  const [focused, setFocused] = useState(null);

  const visibleSeries = TREND_SERIES.filter(
    (s) => s.key !== 'Failed' || data.some((d) => (d.Failed ?? 0) > 0),
  );

  if (!data.length) {
    return (
      <div className="flex h-40 items-center justify-center text-xs text-slate-600 dark:text-slate-500 lg:col-span-2">
        No intent trend data available
      </div>
    );
  }

  // aggSuccessRate = session containment (passed from sessionContainmentRate)
  // intentHitRate  = per-invocation hit rate (passed from aggSuccessRate)
  const sessionRate = aggSuccessRate;
  const hitRate     = intentHitRate;

  return (
    <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4 lg:col-span-2">
      {/* header */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">Intent Outcome Trend</p>
          {sessionRate !== null && (
            <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400"
              title="Session Containment: % of conversations fully handled by the bot without escalation">
              {sessionRate}% session containment
            </span>
          )}
          {hitRate !== null && (
            <span className="rounded-full bg-indigo-500/15 px-2 py-0.5 text-[10px] font-medium text-indigo-600 dark:text-indigo-400"
              title="Bot Resolved Rate: % of intent invocations handled by the bot (directly resolved + re-delegated internally). One session may invoke multiple intents.">
              {hitRate}% bot resolved (invocations)
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {synthesized && (
            <span className="rounded bg-slate-200/60 dark:bg-slate-700/60 px-1.5 py-0.5 text-[10px] text-slate-600 dark:text-slate-500">
              estimated distribution
            </span>
          )}
          <span className="text-[10px] text-slate-600">Click series to focus</span>
        </div>
      </div>
      <p className="text-xs text-slate-600 dark:text-slate-500 mb-3">Daily successful vs abandoned intents over the selected period</p>

      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} allowDecimals={false} width={28} />
          <Tooltip
            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
            labelStyle={{ color: '#f1f5f9' }}
            itemStyle={{ color: '#94a3b8' }}
          />
          {visibleSeries.map(({ key, color }) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={color}
              strokeWidth={focused && focused !== key ? 0.8 : 2}
              strokeOpacity={focused && focused !== key ? 0.2 : 1}
              dot={{ r: 3, fill: color, strokeWidth: 0 }}
              activeDot={{ r: 5 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>

      {/* clickable legend */}
      <div className="flex gap-5 justify-center mt-2">
        {visibleSeries.map(({ key, color, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => setFocused((prev) => (prev === key ? null : key))}
            className="flex items-center gap-1.5 text-xs transition-opacity"
            style={{ opacity: focused && focused !== key ? 0.3 : 1 }}
          >
            <span className="inline-block h-[3px] w-5 rounded-full" style={{ background: color }} />
            <span className="text-slate-500 dark:text-slate-400">{label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Bot section ────────────────────────────────────────────────────────────────

function BotSection({ onAskAssistant }) {
  const [days, setDays]         = useState(7);
  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [intentTrend, setIntentTrend]   = useState([]);
  const [trendSynth, setTrendSynth]     = useState(false);

  const load = async (d) => {
    setLoading(true); setError(null);
    try {
      const [metrics, trend] = await Promise.all([
        getBotMetrics(d),
        getBotIntentTrend(d).catch(() => ({ trend: [], synthesized: false })),
      ]);
      setData(metrics);
      setIntentTrend(trend?.trend || []);
      setTrendSynth(trend?.synthesized ?? false);
    }
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
      Switched:   i.switched,
      Dropped:    i.dropped,
      Failed:     i.failed,
    }));
  }, [primaryBot]);

  // Rows enriched with category + hit rate — for IntentDetailsTable
  const intentTableRows = useMemo(() =>
    intentChartData.map((row) => ({
      ...row,
      category: inferCategory(row.name),
      // Bot Resolved = directly resolved + re-delegated within bot (both never reached a human)
      botResolved: (row.Successful || 0) + (row.Switched || 0),
      hitRate: row.Total > 0
        ? Math.round(((row.Successful || 0) + (row.Switched || 0)) / row.Total * 100)
        : 0,
    }))
  , [intentChartData]);

  // Bot-resolved rate from intent_metrics aggregates (Successful + Switched / Total)
  const aggSuccessRate = useMemo(() => {
    const totS   = intentChartData.reduce((a, i) => a + (i.Successful || 0) + (i.Switched || 0), 0);
    const totAll = intentChartData.reduce((a, i) => a + (i.Total || 0), 0);
    return totAll > 0 ? Math.round((totS / totAll) * 100) : null;
  }, [intentChartData]);

  // Session-level containment rate (from session_metrics — matches the stat card)
  const sessionContainmentRate = useMemo(() => {
    const sm = primaryBot?.session_metrics;
    const total = sm?.total_sessions ?? sm?.total;
    if (!total) return aggSuccessRate;
    return Math.round(((sm.successful ?? 0) / total) * 100);
  }, [primaryBot, aggSuccessRate]);

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
      iconCls="text-indigo-600 dark:text-indigo-400"
    >
      {/* Controls */}
      <div className="flex items-center gap-3 mb-4">
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-2 text-sm text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500"
        >
          {[1, 7, 14, 30].map((d) => (
            <option key={d} value={d}>{d === 1 ? 'Last 24h' : `Last ${d} days`}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => load(days)}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-3 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
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
          <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-300">mock data</span>
        )}
      </div>

      {loading && (
        <div className="flex h-40 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
          <RefreshCw size={18} className="mr-2 animate-spin" /> Loading bot metrics…
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-600 dark:text-rose-300">
          <AlertTriangle size={14} className="inline mr-1" /> {error}
        </div>
      )}

      {!loading && !error && !inventory.total_bots && (
        <div className="rounded-xl border border-dashed border-slate-300 dark:border-slate-700 p-8 text-center">
          <Bot size={32} className="mx-auto mb-2 text-slate-600" />
          <p className="text-sm font-semibold text-slate-500 dark:text-slate-400">No bots associated with this Connect instance</p>
          <p className="text-xs text-slate-600 dark:text-slate-500 mt-1">Associate a Lex V2 bot or enable Amazon Q in Connect.</p>
        </div>
      )}

      {!loading && !error && inventory.total_bots > 0 && (
        <div className="space-y-5">
          {/* Bot inventory stat cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard
              label="Total Sessions"
              value={
                primaryBot?.session_metrics?.total_sessions
                ?? primaryBot?.session_metrics?.total
                ?? cwByMetric['RuntimeInvokedIntents']
                ?? 0
              }
              icon={MessageSquare}
              accentCls="text-indigo-600 dark:text-indigo-400"
            />
            <StatCard
              label="Escalated"
              value={primaryBot?.session_metrics?.escalated ?? 0}
              icon={Users}
              accentCls="text-amber-600 dark:text-amber-400"
              sub="transferred to agent"
            />
            <StatCard
              label="Containment Rate"
              value={(() => {
                const sm = primaryBot?.session_metrics;
                const total = sm?.total_sessions ?? sm?.total;
                if (!total) return '—';
                return `${Math.round(((sm.successful ?? 0) / total) * 100)}%`;
              })()}
              icon={Zap}
              accentCls="text-emerald-600 dark:text-emerald-400"
              sub="sessions not escalated"
            />
            <StatCard
              label="Bots Active"
              value={inventory.total_bots}
              icon={Bot}
              accentCls="text-indigo-600 dark:text-indigo-400"
            />
          </div>

          {/* Charts */}
          <div className="grid gap-5 lg:grid-cols-2">
            {/* Session outcome pie */}
            {sessionPieData.length > 0 && (
              <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">Session Outcomes</p>
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
                        <span className="text-slate-700 dark:text-slate-300">{d.name}</span>
                        <span className="font-semibold text-slate-900 dark:text-slate-100 ml-auto">{d.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Intent breakdown */}
            {intentChartData.length > 0 && (
              <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">Intent Breakdown</p>
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
                    <Bar dataKey="Switched"   fill="#a855f7" radius={[2, 2, 0, 0]} name="Switched (re-delegated)" />
                    <Bar dataKey="Dropped"    fill="#f59e0b" radius={[2, 2, 0, 0]} name="Abandoned" />
                    <Bar dataKey="Failed"     fill="#f43f5e" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Intent outcome trend — full-width row */}
            <IntentTrendChart data={intentTrend} synthesized={trendSynth} aggSuccessRate={sessionContainmentRate} intentHitRate={aggSuccessRate} />

            {/* Intent details by category — full-width row */}
            <IntentDetailsTable rows={intentTableRows} />

            {/* Flow metrics */}
            {flowMetrics.length > 0 && (
              <div className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4 lg:col-span-2">
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">Contact Flow Metrics</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-100 dark:bg-slate-800">
                      <tr>
                        {['Flow', 'Type', 'Started', 'Outcome', 'Outcome %'].map((c) => (
                          <th key={c} className="px-3 py-2 text-left font-medium text-slate-500 dark:text-slate-400">{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {flowMetrics.map((f, i) => (
                        <tr key={i} className="border-t border-slate-200 dark:border-slate-800/60">
                          <td className="px-3 py-2 text-slate-800 dark:text-slate-200 font-medium">{f.flow_name || '—'}</td>
                          <td className="px-3 py-2 text-slate-500 dark:text-slate-400">{f.flow_type || '—'}</td>
                          <td className="px-3 py-2 text-indigo-600 dark:text-indigo-400 font-semibold">{f.metrics?.FLOWS_STARTED ?? 0}</td>
                          <td className="px-3 py-2 text-emerald-600 dark:text-emerald-400 font-semibold">{f.metrics?.FLOWS_OUTCOME ?? 0}</td>
                          <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
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
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500 mb-2">Bot Inventory</p>
            <div className="space-y-1">
              {(inventory.bots || []).map((bot, i) => (
                <div key={i} className="flex items-center gap-3 rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-3 text-xs">
                  <Bot size={14} className="text-indigo-600 dark:text-indigo-400 shrink-0" />
                  <div className="flex-1">
                    <p className="font-medium text-slate-800 dark:text-slate-200">{bot.bot_name || bot.name || `Bot ${i + 1}`}</p>
                    {bot.bot_type && <p className="text-slate-600 dark:text-slate-500">{bot.bot_type}</p>}
                  </div>
                  {bot.status && (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${bot.status === 'Available' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : 'bg-slate-600/30 text-slate-500 dark:text-slate-400'}`}>
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

// ── Tab bar ──────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'overview', label: 'Overview', icon: TrendingUp },
  { id: 'callbacks', label: 'Callbacks', icon: PhoneCall },
  { id: 'bots', label: 'Conversational AI & Bot Analytics', icon: Bot },
  { id: 'themes', label: 'Discussion Themes', icon: MessagesSquare },
];

function TabBar({ activeTab, setActiveTab }) {
  return (
    <div className="flex items-center gap-1.5 border-b border-slate-200 dark:border-slate-800 overflow-x-auto">
      {TABS.map(({ id, label, icon: Icon }) => {
        const active = activeTab === id;
        return (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            className={`inline-flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium transition ${
              active
                ? 'border-connect-500 text-connect-700 dark:text-connect-400'
                : 'border-transparent text-slate-600 hover:text-slate-900 dark:text-slate-500 dark:hover:text-slate-300'
            }`}
          >
            <Icon size={15} />
            {label}
          </button>
        );
      })}
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────────

export default function HistoricalAnalytics({ onAskAssistant }) {
  const [histDays, setHistDays] = useState(30);
  const [activeTab, setActiveTab] = useState('overview');

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Historical Analytics</h2>
          <p className="text-xs text-slate-600 dark:text-slate-500 mt-0.5">
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

      <TabBar activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* Each tab stays mounted (just hidden) when inactive, so in-progress scans
          (Discussion Themes' SSE connection) and loaded data aren't lost on switch. */}
      <div className={activeTab === 'overview' ? 'flex flex-col gap-5' : 'hidden'}>
        <ContactCentreHistory onAskAssistant={onAskAssistant} histDays={histDays} setHistDays={setHistDays} />
        <BreakdownSection days={histDays} onAskAssistant={onAskAssistant} />
        <QueuePcaSection days={histDays} onAskAssistant={onAskAssistant} />
      </div>

      <div className={activeTab === 'callbacks' ? '' : 'hidden'}>
        <SectionCard
          title="Callback Analytics"
          subtitle="Requested vs handled callbacks, retries, and failure reasons — from contact records"
          icon={PhoneCall}
          iconCls="text-indigo-600 dark:text-indigo-400"
        >
          <CallbackAnalyticsPanel days={histDays} onAskAssistant={onAskAssistant} />
        </SectionCard>
      </div>

      <div className={activeTab === 'bots' ? '' : 'hidden'}>
        <BotSection onAskAssistant={onAskAssistant} />
      </div>

      <div className={activeTab === 'themes' ? '' : 'hidden'}>
        <SectionCard
          title="Discussion Themes"
          subtitle="Scan stored transcripts in a date range to see what customers and agents are talking about"
          icon={MessagesSquare}
          iconCls="text-indigo-600 dark:text-indigo-400"
        >
          <TranscriptThemes onAskAssistant={onAskAssistant} />
        </SectionCard>
      </div>
    </div>
  );
}
