/**
 * LiveQueueMetricsChart
 * ---------------------
 * Continuously-updating multi-queue line chart for the Real-Time Command Centre.
 *
 * • Polls /api/realtime-queue-metrics every 5 s
 * • Maintains a rolling 30-point time-series (≈ 2.5 min of history)
 * • Three metric tabs: In Queue | Available Agents | On Call
 * • Click a queue in the legend to focus it — all others fade to 15 % opacity
 * • Agent performance summary strip below the chart
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { Activity, Users, PhoneCall, TrendingUp } from 'lucide-react';
import { getRealtimeQueueMetrics } from '../services/api';

// ── Colour palette (cycles if > 12 queues) ────────────────────────────────────
const PALETTE = [
  '#38bdf8', '#34d399', '#a78bfa', '#fb923c', '#f472b6',
  '#facc15', '#60a5fa', '#4ade80', '#c084fc', '#f87171',
  '#22d3ee', '#e879f9',
];

const METRICS = [
  { key: 'contacts_in_queue',  label: 'In Queue',        icon: PhoneCall,   colour: 'text-amber-400',   unit: '' },
  { key: 'agents_available',   label: 'Available Agents', icon: Users,       colour: 'text-emerald-400', unit: '' },
  { key: 'agents_on_call',     label: 'On Call',         icon: Activity,    colour: 'text-sky-400',     unit: '' },
  { key: 'oldest_contact_age', label: 'Oldest Wait',     icon: TrendingUp,  colour: 'text-rose-400',    unit: 's' },
];

const MAX_POINTS = 30;
const POLL_MS    = 5000;

// ── Custom tooltip ─────────────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label, metricUnit }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/95 px-3 py-2 shadow-xl text-[11px] min-w-[140px]">
      <p className="text-slate-400 mb-1.5 font-medium">{label}</p>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
            <span className="text-slate-300 truncate max-w-[120px]">{p.name}</span>
          </span>
          <span className="font-semibold text-white tabular-nums">
            {p.value}{metricUnit}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Custom legend ──────────────────────────────────────────────────────────────
function ChartLegend({ queues, colourMap, focusedQueue, onFocus }) {
  return (
    <div className="flex flex-wrap gap-1.5 mt-2 px-1">
      {queues.map((q) => {
        const isFocused = !focusedQueue || focusedQueue === q.id;
        return (
          <button
            key={q.id}
            onClick={() => onFocus(focusedQueue === q.id ? null : q.id)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-medium transition-all
              ${isFocused
                ? 'border-slate-600 bg-slate-800 text-slate-200'
                : 'border-slate-800 bg-slate-900 text-slate-600 opacity-40'
              } hover:opacity-100`}
          >
            <span
              className="inline-block w-2 h-2 rounded-full shrink-0"
              style={{ background: colourMap[q.id] }}
            />
            {q.name}
          </button>
        );
      })}
      {focusedQueue && (
        <button
          onClick={() => onFocus(null)}
          className="inline-flex items-center gap-1 rounded-full border border-slate-700 px-2 py-0.5 text-[10px] text-slate-500 hover:text-slate-300 transition"
        >
          ✕ Clear focus
        </button>
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

      // Build new data point
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
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 mt-3">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-connect-400" />
          <span className="text-[12px] font-semibold text-slate-200">Live Queue Metrics</span>
          {lastUpdate && (
            <span className="text-[10px] text-slate-500">updated {lastUpdate}</span>
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
                  ? 'bg-connect-600 text-white shadow'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
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
                    ? 'border-connect-500 bg-connect-600/20 text-white'
                    : focusedQueue
                      ? 'border-slate-800 text-slate-600 opacity-40'
                      : 'border-slate-700 bg-slate-800/60 text-slate-300 hover:border-slate-600'
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
        <div className="flex items-center justify-center h-40 text-[11px] text-slate-500">
          <span className="text-rose-400 mr-1">⚠</span> {error}
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center h-40 text-[11px] text-slate-500 gap-2">
          <span className="inline-block w-3 h-3 rounded-full border-2 border-connect-400 border-t-transparent animate-spin" />
          Loading queue metrics…
        </div>
      ) : series.length < 2 ? (
        <div className="flex items-center justify-center h-40 text-[11px] text-slate-500">
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

      {/* ── Legend / focus selector ──────────────────────────────────────────── */}
      {queues.length > 0 && !loading && !error && (
        <ChartLegend
          queues={queues}
          colourMap={colourMap}
          focusedQueue={focusedQueue}
          onFocus={setFocusedQueue}
        />
      )}

      {/* ── Agent performance strip ──────────────────────────────────────────── */}
      {queues.length > 0 && (
        <AgentPerformanceStrip latest={latest} queues={queues} colourMap={colourMap} />
      )}
    </div>
  );
}

// ── Agent performance strip ────────────────────────────────────────────────────
// Shows per-queue available vs on-call bar with utilisation %
function AgentPerformanceStrip({ latest, queues, colourMap }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? queues : queues.slice(0, 5);

  if (!queues.length) return null;

  return (
    <div className="mt-4 border-t border-slate-800 pt-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 flex items-center gap-1">
          <Users size={10} /> Agent utilisation by queue
        </span>
        {queues.length > 5 && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[10px] text-connect-400 hover:text-connect-300"
          >
            {expanded ? 'Show less' : `Show all ${queues.length}`}
          </button>
        )}
      </div>
      <div className="space-y-1.5">
        {visible.map((q) => {
          const available = latest[`${q.id}_avail`] ?? 0;
          const onCall    = latest[`${q.id}_oc`]    ?? 0;
          const total     = available + onCall;
          const utilPct   = total > 0 ? Math.round((onCall / total) * 100) : 0;
          const colour    = colourMap[q.id];
          return (
            <div key={q.id} className="flex items-center gap-2 text-[10px]">
              <span
                className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                style={{ background: colour }}
              />
              <span className="text-slate-400 truncate w-32 shrink-0">{q.name}</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{ width: `${utilPct}%`, background: colour, opacity: 0.7 }}
                />
              </div>
              <span className="text-slate-500 w-8 text-right tabular-nums">{utilPct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
