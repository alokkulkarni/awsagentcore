/**
 * TodayStatsPanels — "today so far" cards for the Real-Time Command Centre.
 *
 * AbandonedTodayPanel  — calls abandoned in queue today, bucketed by how long
 *                        the customer waited (≤10s … >2m). Polls
 *                        /abandonment-buckets with start=end=today.
 * CallbacksTodayPanel  — live callback snapshot: waiting in queue now,
 *                        connected to an agent now, plus today's outcomes
 *                        (succeeded / customer-leg failed / abandoned) and
 *                        retries. Polls /callback-metrics/today.
 *
 * Both are self-contained (own polling, own error state) so the command
 * centre just renders them.
 */

import { useEffect, useState } from 'react';
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { AlertTriangle, Clock, PhoneForwarded, RefreshCw } from 'lucide-react';
import { getAbandonmentBuckets, getCallbackToday } from '../services/api';

const ABANDON_BUCKET_COLOURS = {
  lt10: '#fbbf24', lt20: '#f59e0b', lt30: '#f97316', lt40: '#ea580c',
  lt60: '#dc2626', lt120: '#b91c1c', over120: '#7f1d1d',
};

const ABANDON_POLL_MS = 60_000;
const CALLBACK_POLL_MS = 30_000;

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

export function AbandonedTodayPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const today = todayStr();
      setData(await getAbandonmentBuckets({ start: today, end: today }));
      setError(null);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to load abandonment stats');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, ABANDON_POLL_MS);
    return () => clearInterval(t);
  }, []); // eslint-disable-line

  const buckets = data?.buckets ?? [];
  const total = data?.total_abandoned ?? 0;

  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 p-4">
      <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
        <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
          <Clock size={14} className="inline mr-1.5 text-amber-600 dark:text-amber-400" />
          Abandoned Today — by Wait Time
        </p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-600 dark:text-slate-500">{total} total</span>
          {data?.mock && (
            <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-600 dark:text-amber-300">mock data</span>
          )}
        </div>
      </div>
      <p className="mb-2 text-[10px] text-slate-600 dark:text-slate-500">
        Time from entering the queue to hanging up, for calls that never reached an agent. Refreshes every minute.
      </p>

      {loading && (
        <div className="flex h-28 items-center justify-center text-xs text-slate-500 dark:text-slate-400">
          <RefreshCw size={14} className="mr-2 animate-spin" /> Loading…
        </div>
      )}
      {error && !loading && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-600 dark:text-rose-300 flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {error}
        </div>
      )}
      {!loading && !error && (
        total === 0 ? (
          <div className="flex h-24 items-center justify-center text-xs text-slate-600 dark:text-slate-500">
            No abandoned calls yet today.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={buckets} margin={{ top: 4, right: 8, left: -24, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 9 }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 9 }} allowDecimals={false} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                labelStyle={{ color: '#f1f5f9', fontWeight: 600 }}
                itemStyle={{ color: '#94a3b8' }}
                formatter={(v) => [v, 'Abandoned']}
              />
              <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                {buckets.map((b) => (
                  <Cell key={b.key} fill={ABANDON_BUCKET_COLOURS[b.key]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )
      )}
    </div>
  );
}

const CALLBACK_CHIPS = [
  { key: 'waiting',         label: 'In queue now',    cls: 'text-indigo-600 dark:text-indigo-400' },
  { key: 'connected',       label: 'With agent now',  cls: 'text-cyan-600 dark:text-cyan-400' },
  { key: 'succeeded',       label: 'Succeeded',       cls: 'text-emerald-600 dark:text-emerald-400' },
  { key: 'customer_failed', label: 'Customer failed', cls: 'text-rose-600 dark:text-rose-400' },
  { key: 'abandoned',       label: 'Abandoned',       cls: 'text-amber-600 dark:text-amber-400' },
  { key: 'retried',         label: 'Retried',         cls: 'text-purple-600 dark:text-purple-400' },
];

export function CallbacksTodayPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setData(await getCallbackToday());
      setError(null);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to load callback snapshot');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, CALLBACK_POLL_MS);
    return () => clearInterval(t);
  }, []); // eslint-disable-line

  return (
    <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 p-4">
      <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
        <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
          <PhoneForwarded size={14} className="inline mr-1.5 text-indigo-600 dark:text-indigo-400" />
          Callbacks Today
        </p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-600 dark:text-slate-500">{data?.requested ?? 0} requested</span>
          {data?.mock && (
            <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-600 dark:text-amber-300">mock data</span>
          )}
        </div>
      </div>
      <p className="mb-2 text-[10px] text-slate-600 dark:text-slate-500">
        Succeeded = agent and customer both connected. Customer failed = agent accepted but the customer leg failed.
        Refreshes every 30s.
      </p>

      {loading && (
        <div className="flex h-20 items-center justify-center text-xs text-slate-500 dark:text-slate-400">
          <RefreshCw size={14} className="mr-2 animate-spin" /> Loading…
        </div>
      )}
      {error && !loading && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-600 dark:text-rose-300 flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {error}
        </div>
      )}
      {!loading && !error && data && (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {CALLBACK_CHIPS.map(({ key, label, cls }) => (
            <div key={key} className="rounded-xl border border-slate-300 dark:border-slate-700/60 bg-slate-200/50 dark:bg-slate-800/50 p-2 text-center">
              <p className={`text-lg font-bold ${cls}`}>{data[key] ?? 0}</p>
              <p className="text-[9px] text-slate-600 dark:text-slate-500 uppercase tracking-wide">{label}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
