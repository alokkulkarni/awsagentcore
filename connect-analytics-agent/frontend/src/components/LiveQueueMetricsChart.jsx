/**
 * LiveQueueMetricsChart
 * ---------------------
 * Continuously-updating multi-queue line chart for the Real-Time Command Centre.
 *
 * • Polls /api/realtime-queue-metrics every 5 s
 * • Maintains a rolling 30-point time-series (≈ 2.5 min of history)
 * • Three metric tabs: In Queue | Available Agents | On Call
 * • Click a queue in the legend to focus it — all others fade to 15 % opacity
 * • Agent utilisation-by-queue panel below the chart — deliberately NOT fed by
 *   the 5s live-snapshot poll above (that's far too noisy for a "utilisation"
 *   figure); it fetches its own real, time-averaged AGENT_OCCUPANCY from
 *   /api/agent-occupancy on a cadence matching the chosen averaging window.
 */

import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { Activity, Clock, Percent, Users, PhoneCall, TrendingUp } from 'lucide-react';
import { getRealtimeQueueMetrics, getAgentOccupancy, getAgentOccupancyDayToDate, getPcaByQueue } from '../services/api';

// ── Colour palette (cycles if > 12 queues) ────────────────────────────────────
const PALETTE = [
  '#38bdf8', '#34d399', '#a78bfa', '#fb923c', '#f472b6',
  '#facc15', '#60a5fa', '#4ade80', '#c084fc', '#f87171',
  '#22d3ee', '#e879f9',
];

const METRICS = [
  { key: 'contacts_in_queue',  label: 'In Queue',        icon: PhoneCall,   colour: 'text-amber-600 dark:text-amber-400',   unit: '' },
  { key: 'agents_available',   label: 'Available Agents', icon: Users,       colour: 'text-emerald-600 dark:text-emerald-400', unit: '' },
  { key: 'agents_on_call',     label: 'On Call',         icon: Activity,    colour: 'text-sky-600 dark:text-sky-400',     unit: '' },
  { key: 'agents_acw',         label: 'ACW',             icon: Clock,       colour: 'text-orange-600 dark:text-orange-400', unit: '' },
  { key: 'oldest_contact_age', label: 'Oldest Wait',     icon: TrendingUp,  colour: 'text-rose-600 dark:text-rose-400',    unit: 's' },
];

const MAX_POINTS = 30;
const POLL_MS    = 5000;

// ── Custom tooltip ─────────────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label, metricUnit }) {
  if (!active || !payload?.length) return null;
  // At 56 queues a full series list towers over the page — show only queues
  // with activity (top 8 by value) and summarise the rest in one line.
  const nonZero = payload
    .filter((p) => (p.value ?? 0) > 0)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  const shown = nonZero.slice(0, 8);
  const hiddenActive = nonZero.length - shown.length;
  const zeroCount = payload.length - nonZero.length;
  return (
    <div className="rounded-xl border border-slate-300 dark:border-slate-700 bg-white/95 dark:bg-slate-900/95 px-3 py-2 shadow-xl text-[11px] min-w-[160px]">
      <p className="text-slate-500 dark:text-slate-400 mb-1.5 font-medium">{label}</p>
      {shown.length === 0 && (
        <p className="text-slate-600 dark:text-slate-400">All {payload.length} queues at 0{metricUnit}</p>
      )}
      {shown.map((p) => (
        <div key={p.dataKey} className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
            <span className="text-slate-700 dark:text-slate-300 truncate max-w-[150px]">{p.name}</span>
          </span>
          <span className="font-semibold text-slate-900 dark:text-white tabular-nums">
            {p.value}{metricUnit}
          </span>
        </div>
      ))}
      {(hiddenActive > 0 || (zeroCount > 0 && shown.length > 0)) && (
        <p className="mt-1 border-t border-slate-200 dark:border-slate-700/60 pt-1 text-[10px] text-slate-500 dark:text-slate-400">
          {hiddenActive > 0 && `+${hiddenActive} more active`}
          {hiddenActive > 0 && zeroCount > 0 && ' · '}
          {zeroCount > 0 && `${zeroCount} at 0`}
        </p>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function LiveQueueMetricsChart() {
  const [series, setSeries]         = useState([]);   // [{time, queueId: value, ...}]
  const [queues, setQueues]         = useState([]);   // [{id, name}] — stable list
  const [colourMap, setColourMap]   = useState({});
  const [activeMetric, setActiveMetric] = useState(0);
  const [focusedQueue, setFocusedQueue] = useState(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const colourMapRef = useRef({});
  const queuesRef    = useRef([]);

  const fetchMetrics = useCallback(async () => {
    try {
      const data = await getRealtimeQueueMetrics();
      if (!data?.queues?.length) return;

      const ts = new Date(data.timestamp + 'Z');
      const timeLabel = ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      setLastUpdate(timeLabel);

      // Assign stable colours for any new queue IDs
      const newColours = { ...colourMapRef.current };
      let idx = Object.keys(newColours).length;
      const newQueues = data.queues.map((q) => ({ id: q.id, name: q.name }));

      newQueues.forEach((q) => {
        if (!newColours[q.id]) {
          newColours[q.id] = PALETTE[idx % PALETTE.length];
          idx++;
        }
      });

      // Stable queue list — only grows, never shrinks (preserves chart lines)
      const merged = [...queuesRef.current];
      newQueues.forEach((q) => {
        if (!merged.find((x) => x.id === q.id)) merged.push(q);
      });

      colourMapRef.current = newColours;
      queuesRef.current    = merged;
      setColourMap(newColours);
      setQueues(merged);

      // Build new data point — the chart line only needs whichever metric tab
      // is currently active. (Agent utilisation by queue is intentionally NOT
      // derived from this snapshot poll — see AgentUtilisationByQueue below.)
      const point = { time: timeLabel };
      data.queues.forEach((q) => {
        point[q.id] = q[METRICS[activeMetric]?.key ?? 'contacts_in_queue'] ?? 0;
      });

      setSeries((prev) => {
        const next = [...prev, point];
        return next.length > MAX_POINTS ? next.slice(next.length - MAX_POINTS) : next;
      });
      setError(null);
      setLoading(false);
    } catch (err) {
      setError(err?.response?.data?.error || err.message || 'Failed to fetch queue metrics');
      setLoading(false);
    }
  }, [activeMetric]);

  // Re-build entire series when user switches metric tab
  useEffect(() => {
    setSeries([]);
    setLoading(true);
  }, [activeMetric]);

  useEffect(() => {
    fetchMetrics();
    const t = setInterval(fetchMetrics, POLL_MS);
    return () => clearInterval(t);
  }, [fetchMetrics]);

  const metric = METRICS[activeMetric];
  const Icon   = metric.icon;

  // Latest snapshot values (last data point)
  const latest = series[series.length - 1] || {};

  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 p-4 mt-3">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-connect-700 dark:text-connect-400" />
          <span className="text-[12px] font-semibold text-slate-800 dark:text-slate-200">Live Queue Metrics</span>
          {lastUpdate && (
            <span className="text-[10px] text-slate-600 dark:text-slate-500">updated {lastUpdate}</span>
          )}
          {loading && (
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-connect-400 animate-pulse" />
          )}
        </div>

        {/* Metric selector tabs */}
        <div className="flex items-center gap-1">
          {METRICS.map((m, i) => (
            <button
              key={m.key}
              onClick={() => setActiveMetric(i)}
              className={`rounded-lg px-2.5 py-1 text-[10px] font-medium transition-all
                ${activeMetric === i
                  ? 'bg-connect-500 text-white shadow'
                  : 'text-slate-600 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Summary stat chips (latest snapshot) ────────────────────────────── */}
      {queues.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {queues.map((q) => {
            const val = latest[q.id] ?? 0;
            return (
              <button
                key={q.id}
                onClick={() => setFocusedQueue(focusedQueue === q.id ? null : q.id)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[10px] transition-all
                  ${focusedQueue === q.id
                    ? 'border-connect-500 bg-connect-500/20 text-slate-900 dark:text-white'
                    : focusedQueue
                      ? 'border-slate-200 dark:border-slate-800 text-slate-600 opacity-40'
                      : 'border-slate-300 dark:border-slate-700 bg-slate-200/60 dark:bg-slate-800/60 text-slate-700 dark:text-slate-300 hover:border-slate-400 dark:hover:border-slate-600'
                  }`}
              >
                <span
                  className="inline-block w-2 h-2 rounded-full shrink-0"
                  style={{ background: colourMap[q.id] }}
                />
                <span className="max-w-[110px] truncate">{q.name}</span>
                <span
                  className="font-semibold tabular-nums ml-0.5"
                  style={{ color: colourMap[q.id] }}
                >
                  {val}{metric.unit}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* ── Chart area ──────────────────────────────────────────────────────── */}
      {error ? (
        <div className="flex items-center justify-center h-40 text-[11px] text-slate-600 dark:text-slate-500">
          <span className="text-rose-600 dark:text-rose-400 mr-1">⚠</span> {error}
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center h-40 text-[11px] text-slate-600 dark:text-slate-500 gap-2">
          <span className="inline-block w-3 h-3 rounded-full border-2 border-connect-400 border-t-transparent animate-spin" />
          Loading queue metrics…
        </div>
      ) : series.length < 2 ? (
        <div className="flex items-center justify-center h-40 text-[11px] text-slate-600 dark:text-slate-500">
          Collecting data… chart will appear shortly
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={series} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 9, fill: '#475569' }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 9, fill: '#475569' }}
              tickLine={false}
              axisLine={false}
              width={28}
            />
            <Tooltip
              content={<ChartTooltip metricUnit={metric.unit} />}
              cursor={{ stroke: '#334155', strokeWidth: 1 }}
              wrapperStyle={{ zIndex: 40 }}
            />
            {queues.map((q) => {
              const focused  = !focusedQueue || focusedQueue === q.id;
              const opacity  = focused ? 1 : 0.12;
              const strokeW  = focusedQueue === q.id ? 2.5 : focused ? 1.5 : 1;
              return (
                <Line
                  key={q.id}
                  type="monotone"
                  dataKey={q.id}
                  name={q.name}
                  stroke={colourMap[q.id]}
                  strokeWidth={strokeW}
                  strokeOpacity={opacity}
                  dot={false}
                  activeDot={{ r: 3, strokeWidth: 0 }}
                  isAnimationActive={false}
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      )}

      {/* The stat-chip strip above the chart doubles as the legend/focus
          selector — a second full queue list below the chart was pure
          duplication at 56 queues. */}
      {focusedQueue && !loading && !error && (
        <button
          onClick={() => setFocusedQueue(null)}
          className="mt-2 inline-flex items-center gap-1 rounded-full border border-slate-300 dark:border-slate-700 px-2 py-0.5 text-[10px] text-slate-600 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition"
        >
          ✕ Clear focus
        </button>
      )}

      {/* ── Agent utilisation by queue ────────────────────────────────────────── */}
      <AgentUtilisationByQueue colourMap={colourMap} />

      {/* ── PCA by queue (day to date) ────────────────────────────────────────── */}
      <PcaByQueue colourMap={colourMap} />
    </div>
  );
}

// ── Agent utilisation by queue ─────────────────────────────────────────────────
// Real, time-averaged AGENT_OCCUPANCY — independently fetched from
// /api/agent-occupancy (a caller-chosen rolling window, 5-120 min, refreshed
// only once per window rather than every poll) plus /api/agent-occupancy/
// day-to-date (each queue's real Hours-of-Operation-bounded average for today).
const OCCUPANCY_WINDOW_OPTIONS = [5, 15, 30, 60, 120];

function occupancyWindowLabel(minutes) {
  return minutes < 60 ? `${minutes} min avg` : `${minutes / 60}h avg`;
}

function dayStatusLabel(status) {
  switch (status) {
    case 'open':            return 'so far today';
    case 'closed_for_day':  return 'today (day closed)';
    case 'not_yet_open':    return 'not yet open today';
    case 'closed_today':    return 'closed today';
    default:                return 'today';
  }
}

function AgentUtilisationByQueue({ colourMap }) {
  const [windowMinutes, setWindowMinutes] = useState(30);
  const [windowData, setWindowData]       = useState(null);
  const [dayData, setDayData]             = useState(null);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState(null);
  const [expanded, setExpanded]           = useState(false);

  const fetchWindow = useCallback(async () => {
    try {
      const data = await getAgentOccupancy(windowMinutes);
      setWindowData(data);
      setError(null);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load utilisation');
    } finally {
      setLoading(false);
    }
  }, [windowMinutes]);

  const fetchDay = useCallback(async () => {
    try {
      const data = await getAgentOccupancyDayToDate();
      setDayData(data);
    } catch {
      // Non-critical secondary figure — keep showing the last known value.
    }
  }, []);

  // Refresh cadence intentionally equals the chosen window — a 30-min average
  // that changes every 5s would defeat the point of averaging.
  useEffect(() => {
    setLoading(true);
    fetchWindow();
    const t = setInterval(fetchWindow, windowMinutes * 60 * 1000);
    return () => clearInterval(t);
  }, [fetchWindow, windowMinutes]);

  useEffect(() => {
    fetchDay();
    const t = setInterval(fetchDay, 5 * 60 * 1000);
    return () => clearInterval(t);
  }, [fetchDay]);

  const queues = windowData?.queues || [];
  const dayByQueue = useMemo(
    () => Object.fromEntries((dayData?.queues || []).map((q) => [q.queue_id, q])),
    [dayData],
  );
  const visible = expanded ? queues : queues.slice(0, 5);

  if (loading && !windowData) {
    return (
      <div className="mt-4 border-t border-slate-200 dark:border-slate-800 pt-3">
        <p className="text-[10px] text-slate-600 dark:text-slate-500">Loading utilisation…</p>
      </div>
    );
  }

  if (!queues.length) return null;

  return (
    <div className="mt-4 border-t border-slate-200 dark:border-slate-800 pt-3">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500 flex items-center gap-1">
          <Users size={10} /> Agent utilisation by queue
        </span>
        <div className="flex items-center gap-2">
          <select
            value={windowMinutes}
            onChange={(e) => setWindowMinutes(Number(e.target.value))}
            title="How many trailing minutes to average utilisation over"
            className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-700 dark:text-slate-300 focus:outline-none"
          >
            {OCCUPANCY_WINDOW_OPTIONS.map((m) => (
              <option key={m} value={m}>{occupancyWindowLabel(m)}</option>
            ))}
          </select>
          {queues.length > 5 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-[10px] text-connect-700 dark:text-connect-400 hover:text-connect-500 dark:hover:text-connect-400"
            >
              {expanded ? 'Show less' : `Show all ${queues.length}`}
            </button>
          )}
        </div>
      </div>
      {error && <p className="mb-1.5 text-[10px] text-rose-600 dark:text-rose-400">{error}</p>}
      <div className="space-y-1.5">
        {visible.map((q, i) => {
          const pct = q.occupancy_pct ?? 0;
          const dayInfo = dayByQueue[q.queue_id];
          const colour = colourMap[q.queue_id] || PALETTE[i % PALETTE.length];
          return (
            <div key={q.queue_id} className="flex items-center gap-2 text-[10px]">
              <span
                className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                style={{ background: colour }}
              />
              <span className="text-slate-500 dark:text-slate-400 truncate w-32 shrink-0">{q.queue_name}</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{ width: `${pct}%`, background: colour, opacity: 0.7 }}
                />
              </div>
              <span className="text-slate-600 dark:text-slate-500 w-8 text-right tabular-nums">{pct}%</span>
              {dayInfo && (
                <span
                  className="text-slate-500 dark:text-slate-500 w-24 text-right tabular-nums shrink-0"
                  title={dayStatusLabel(dayInfo.status)}
                >
                  {dayInfo.occupancy_pct != null ? `${dayInfo.occupancy_pct}% today` : dayStatusLabel(dayInfo.status)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── PCA by queue (day to date) ─────────────────────────────────────────────────
// Percentage Calls Answered = handled / (handled + abandoned), midnight → now.
// A day-so-far figure from GetMetricDataV2 totals, refreshed once a minute.
const pcaColour = (pca) => (pca >= 80 ? '#10b981' : pca >= 60 ? '#f59e0b' : '#f43f5e');

function PcaByQueue() {
  const [data, setData]         = useState(null);
  const [error, setError]       = useState(null);
  const [expanded, setExpanded] = useState(false);

  const fetchPca = useCallback(async () => {
    try {
      const d = await getPcaByQueue();
      setData(d);
      setError(null);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load PCA');
    }
  }, []);

  useEffect(() => {
    fetchPca();
    const t = setInterval(fetchPca, 60 * 1000);
    return () => clearInterval(t);
  }, [fetchPca]);

  const queues = (data?.queues || []).filter((q) => q.pca != null);
  const visible = expanded ? queues : queues.slice(0, 5);

  if (error) {
    return (
      <div className="mt-4 border-t border-slate-200 dark:border-slate-800 pt-3">
        <p className="text-[10px] text-rose-600 dark:text-rose-400">PCA by queue: {error}</p>
      </div>
    );
  }
  if (!queues.length) return null;

  return (
    <div className="mt-4 border-t border-slate-200 dark:border-slate-800 pt-3">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500 flex items-center gap-1">
          <Percent size={10} /> PCA by queue — today
        </span>
        {queues.length > 5 && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[10px] text-connect-700 dark:text-connect-400 hover:text-connect-500 dark:hover:text-connect-400"
          >
            {expanded ? 'Show less' : `Show all ${queues.length}`}
          </button>
        )}
      </div>
      <div className="space-y-1.5">
        {visible.map((q) => (
          <div
            key={q.queue_id}
            className="flex items-center gap-2 text-[10px]"
            title={`${q.handled} answered · ${q.abandoned} abandoned`}
          >
            <span
              className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
              style={{ background: pcaColour(q.pca) }}
            />
            <span className="text-slate-500 dark:text-slate-400 truncate w-32 shrink-0">{q.queue_name}</span>
            <div className="flex-1 h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{ width: `${q.pca}%`, background: pcaColour(q.pca), opacity: 0.75 }}
              />
            </div>
            <span className="text-slate-600 dark:text-slate-500 w-10 text-right tabular-nums">{q.pca}%</span>
            <span className="text-slate-500 dark:text-slate-500 w-20 text-right tabular-nums shrink-0">
              {q.handled}/{q.handled + q.abandoned} ans.
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
