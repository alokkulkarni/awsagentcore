import { useState, useEffect, useMemo } from 'react';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { Bot, Zap, AlertTriangle, TrendingUp, MessageSquare, Users, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';
import { getBotMetrics } from '../services/api';

const COLORS = ['#6366f1','#22d3ee','#f59e0b','#10b981','#f43f5e','#a78bfa','#fb923c'];

function StatCard({ label, value, sub, accent, icon: Icon, badge }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl p-4 border border-gray-200 dark:border-gray-700 shadow-sm">
      <div className="flex items-start justify-between mb-1">
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">{label}</span>
        {Icon && <Icon className={`w-4 h-4 ${accent || 'text-indigo-500'}`} />}
      </div>
      <div className={`text-3xl font-bold ${accent || 'text-gray-900 dark:text-white'}`}>{value}</div>
      {sub  && <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{sub}</div>}
      {badge && <span className="mt-2 inline-block text-xs px-2 py-0.5 rounded-full bg-violet-100 dark:bg-violet-900 text-violet-700 dark:text-violet-300 font-semibold">{badge}</span>}
    </div>
  );
}

function SectionHeader({ title, subtitle, icon: Icon }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      {Icon && <Icon className="w-5 h-5 text-indigo-500" />}
      <div>
        <h3 className="text-base font-semibold text-gray-800 dark:text-gray-100">{title}</h3>
        {subtitle && <p className="text-xs text-gray-500 dark:text-gray-400">{subtitle}</p>}
      </div>
    </div>
  );
}

function QInConnectBadge() {
  return (
    <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-violet-100 dark:bg-violet-900 text-violet-700 dark:text-violet-300 font-semibold border border-violet-300 dark:border-violet-700">
      <Zap className="w-3 h-3" /> Amazon Q in Connect
    </span>
  );
}

function EscalationRow({ s }) {
  return (
    <tr className="border-b border-gray-100 dark:border-gray-700 text-xs">
      <td className="py-1.5 px-2 text-gray-600 dark:text-gray-300 font-mono">{s.session_id?.slice(-8)}</td>
      <td className="py-1.5 px-2 text-gray-700 dark:text-gray-200">{s.channel || '—'}</td>
      <td className="py-1.5 px-2 text-gray-700 dark:text-gray-200">{s.mode || '—'}</td>
      <td className="py-1.5 px-2 text-gray-700 dark:text-gray-200">{s.turns ?? '—'}</td>
      <td className="py-1.5 px-2 text-gray-500 dark:text-gray-400">
        {s.start_time ? new Date(s.start_time).toLocaleString() : '—'}
      </td>
      <td className="py-1.5 px-2">
        <span className="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300 text-xs">Escalated</span>
      </td>
    </tr>
  );
}

function MissedUtteranceRow({ u }) {
  return (
    <tr className="border-b border-gray-100 dark:border-gray-700 text-xs">
      <td className="py-1.5 px-2 text-gray-800 dark:text-gray-200 max-w-xs truncate">{u.utterance}</td>
      <td className="py-1.5 px-2 text-gray-600 dark:text-gray-300">{u.intent || 'FallbackIntent'}</td>
      <td className="py-1.5 px-2 text-gray-600 dark:text-gray-300">{u.channel || '—'}</td>
      <td className="py-1.5 px-2 text-gray-500 dark:text-gray-400">
        {u.timestamp ? new Date(u.timestamp).toLocaleString() : '—'}
      </td>
    </tr>
  );
}

export default function BotMetricsDashboard({ darkMode }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [days, setDays]       = useState(7);
  const [showEscalations, setShowEscalations] = useState({});
  const [showMissed, setShowMissed]           = useState({});

  const load = async (d = days) => {
    setLoading(true); setError(null);
    try {
      const res = await getBotMetrics(d);
      setData(res);
    } catch (e) {
      setError(e.message || 'Failed to load bot metrics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [days]);  // eslint-disable-line react-hooks/exhaustive-deps

  // ── derived data ─────────────────────────────────────────────────────────

  const inventory = data?.bot_inventory || { total_bots: 0, bots: [] };
  const lexAnalytics = data?.lex_analytics || [];
  const flowMetrics  = data?.flow_metrics  || [];
  const cwMetrics    = data?.lex_cloudwatch_metrics || [];

  // First bot's analytics (usually only one Connect instance has 1-2 bots)
  const primaryBot = lexAnalytics[0] || null;

  // Intent breakdown chart data
  const intentChartData = useMemo(() => {
    if (!primaryBot) return [];
    return (primaryBot.intent_metrics || []).map(i => ({
      name:       i.intent_name === 'AmazonQinConnect' ? 'Q in Connect' : i.intent_name,
      Total:      i.total,
      Successful: i.successful,
      Dropped:    i.dropped,
      Failed:     i.failed,
    }));
  }, [primaryBot]);

  // Session outcome pie
  const sessionPieData = useMemo(() => {
    if (!primaryBot?.session_metrics) return [];
    const sm = primaryBot.session_metrics;
    return [
      { name: 'Successful',  value: sm.successful },
      { name: 'Escalated',   value: sm.escalated  },
      { name: 'Failed',      value: sm.failed      },
    ].filter(d => d.value > 0);
  }, [primaryBot]);

  // Flow chart data
  const flowChartData = useMemo(() =>
    flowMetrics.map(f => ({
      name:    f.flow_type || f.flow_name,
      Started: f.metrics?.FLOWS_STARTED || 0,
      Outcome: f.metrics?.FLOWS_OUTCOME || 0,
      'Outcome %': f.metrics?.PERCENT_FLOWS_OUTCOME || 0,
    })),
  [flowMetrics]);

  // CW metrics pivot by bot
  const cwByMetric = useMemo(() => {
    const grouped = {};
    cwMetrics.forEach(m => { grouped[m.metric_name] = (grouped[m.metric_name] || 0) + (m.total || m.total_or_avg || 0); });
    return grouped;
  }, [cwMetrics]);

  // ── render ────────────────────────────────────────────────────────────────

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-gray-500 dark:text-gray-400">
      <RefreshCw className="w-6 h-6 animate-spin mr-2" /> Loading conversational AI metrics…
    </div>
  );

  if (error) return (
    <div className="m-6 p-4 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm">
      <AlertTriangle className="w-4 h-4 inline mr-1" /> {error}
    </div>
  );

  if (!inventory.total_bots) return (
    <div className="m-6 p-6 rounded-xl border border-dashed border-gray-300 dark:border-gray-600 text-center text-gray-500 dark:text-gray-400">
      <Bot className="w-10 h-10 mx-auto mb-2 opacity-40" />
      <p className="font-semibold">No bots associated with this Connect instance</p>
      <p className="text-xs mt-1">Associate a Lex V2 bot or enable Amazon Q in Connect to see metrics here.</p>
    </div>
  );

  return (
    <div className="p-6 space-y-8 text-gray-900 dark:text-gray-100">

      {/* ── Controls ────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Bot className="w-6 h-6 text-indigo-500" /> Conversational AI Dashboard
          </h2>
          {data?.mock && (
            <span className="text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 px-2 py-0.5 rounded-full">
              Mock data — set MOCK_MODE=false to use real AWS data
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-1.5 text-gray-700 dark:text-gray-200"
          >
            <option value={1}>Last 24 h</option>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
          <button
            onClick={() => load(days)}
            className="flex items-center gap-1.5 text-sm bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-3 py-1.5"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>
      </div>

      {/* ── Bot Inventory ───────────────────────────────────────────────── */}
      <section>
        <SectionHeader title="Bot Inventory" subtitle={`${inventory.total_bots} bot(s) associated with this Connect instance`} icon={Bot} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          <StatCard label="Total Bots"     value={inventory.total_bots}   icon={Bot} />
          <StatCard label="Lex V2 Bots"    value={inventory.lex_v2_count || 0} icon={Bot} accent="text-indigo-500" />
          <StatCard label="Lex V1 Bots"    value={inventory.lex_v1_count || 0} icon={Bot} accent="text-sky-500" />
          <StatCard label="Q in Connect"   value={inventory.q_in_connect || 0} icon={Zap} accent="text-violet-500" badge="LLM-powered" />
        </div>

        <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-700/60 text-xs text-gray-500 dark:text-gray-400 uppercase">
              <tr>
                <th className="px-4 py-2 text-left">Bot Name</th>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-left">Bot ID / Alias</th>
                <th className="px-4 py-2 text-left">Locale / Region</th>
                <th className="px-4 py-2 text-left">Engine</th>
                <th className="px-4 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-100 dark:divide-gray-700">
              {inventory.bots.map((b, i) => {
                const prodAlias = b.aliases?.find(a => a.is_prod) || b.aliases?.[0];
                return (
                  <tr key={i}>
                    <td className="px-4 py-2 font-medium text-gray-800 dark:text-gray-100">{b.bot_name}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                        b.bot_type === 'LexV2'
                          ? 'bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300'
                          : 'bg-sky-100 dark:bg-sky-900 text-sky-700 dark:text-sky-300'
                      }`}>{b.bot_type}</span>
                    </td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-300 font-mono text-xs">
                      {b.bot_id || '—'} {prodAlias ? `/ ${prodAlias.alias_name}` : ''}
                    </td>
                    <td className="px-4 py-2 text-gray-600 dark:text-gray-300 text-xs">
                      {b.locales?.[0]?.locale_name || b.lex_region || '—'}
                    </td>
                    <td className="px-4 py-2">
                      {b.has_q_in_connect ? <QInConnectBadge /> : <span className="text-xs text-gray-500">Lex NLU</span>}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                        b.bot_status === 'Available'
                          ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
                      }`}>{b.bot_status || 'Active'}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Per-bot analytics ───────────────────────────────────────────── */}
      {lexAnalytics.map((bot, bi) => (
        <section key={bi} className="space-y-6">
          <div className="flex items-center gap-3 border-b border-gray-200 dark:border-gray-700 pb-2">
            <Bot className="w-5 h-5 text-indigo-400" />
            <span className="text-lg font-semibold text-gray-800 dark:text-gray-100">{bot.bot_name}</span>
            {bot.has_q_in_connect && <QInConnectBadge />}
            {bot.note && (
              <span className="text-xs text-gray-400 dark:text-gray-500 italic hidden md:block">{bot.note}</span>
            )}
          </div>

          {/* Session overview */}
          {bot.session_metrics && (
            <div>
              <SectionHeader
                title="Session Overview"
                subtitle={`Last ${days} day(s) — all conversations through this bot`}
                icon={Users}
              />
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <StatCard label="Total Sessions"    value={bot.session_metrics.total_sessions} icon={Users} />
                <StatCard label="Successful"        value={bot.session_metrics.successful}      icon={TrendingUp} accent="text-green-500" />
                <StatCard label="Escalated (Human)" value={bot.session_metrics.escalated}       icon={Users}      accent="text-amber-500"
                  sub={`${bot.session_metrics.escalation_rate_pct}% escalation rate`} />
                <StatCard label="Avg Duration"      value={bot.session_metrics.avg_duration_fmt} icon={RefreshCw} />
                <StatCard label="Avg Turns"         value={bot.session_metrics.avg_turns}        icon={MessageSquare} />
              </div>
            </div>
          )}

          {/* Session outcome pie + intent bar */}
          {bi === 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

              {sessionPieData.length > 0 && (
                <div className="bg-white dark:bg-gray-800 rounded-xl p-4 border border-gray-200 dark:border-gray-700">
                  <p className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3">Session Outcomes</p>
                  <ResponsiveContainer width="100%" height={220}>
                    <PieChart>
                      <Pie data={sessionPieData} cx="50%" cy="50%" outerRadius={80} dataKey="value" label={({ name, value }) => `${name}: ${value}`}>
                        {sessionPieData.map((_, idx) => <Cell key={idx} fill={[COLORS[2], COLORS[4], COLORS[0]][idx % 3]} />)}
                      </Pie>
                      <Tooltip />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}

              {intentChartData.length > 0 && (
                <div className="bg-white dark:bg-gray-800 rounded-xl p-4 border border-gray-200 dark:border-gray-700">
                  <p className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3">Intent Breakdown</p>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={intentChartData} margin={{ top: 5, right: 10, left: 0, bottom: 30 }}>
                      <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.3} />
                      <XAxis dataKey="name" tick={{ fontSize: 11, fill: darkMode ? '#9ca3af' : '#6b7280' }} angle={-20} textAnchor="end" />
                      <YAxis tick={{ fontSize: 11, fill: darkMode ? '#9ca3af' : '#6b7280' }} />
                      <Tooltip contentStyle={{ background: darkMode ? '#1f2937' : '#fff', border: '1px solid #374151' }} />
                      <Legend />
                      <Bar dataKey="Total"      fill={COLORS[0]} radius={[3,3,0,0]} />
                      <Bar dataKey="Successful" fill={COLORS[3]} radius={[3,3,0,0]} />
                      <Bar dataKey="Dropped"    fill={COLORS[2]} radius={[3,3,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          )}

          {/* Utterance metrics */}
          {bot.utterance_metrics && (
            <div>
              <SectionHeader
                title={bot.has_q_in_connect ? 'Utterance Processing (Q in Connect)' : 'Utterance Analytics'}
                subtitle={bot.has_q_in_connect
                  ? 'Q in Connect handles all utterances via LLM — Missed reflects Q in Connect delegation'
                  : 'Detected utterances matched an intent; Missed went to FallbackIntent'}
                icon={MessageSquare}
              />
              <div className="grid grid-cols-3 gap-4">
                <StatCard
                  label="Total Utterances"
                  value={bot.utterance_metrics.total}
                  icon={MessageSquare}
                />
                <StatCard
                  label={bot.has_q_in_connect ? 'Q in Connect (LLM)' : 'Detected / Matched'}
                  value={bot.has_q_in_connect ? bot.utterance_metrics.missed : bot.utterance_metrics.detected}
                  icon={Zap}
                  accent={bot.has_q_in_connect ? 'text-violet-500' : 'text-green-500'}
                  sub={bot.has_q_in_connect
                    ? 'Handled by Amazon Q / Nova Sonic'
                    : `${bot.utterance_metrics.detection_rate_pct}% detection rate`}
                />
                <StatCard
                  label={bot.has_q_in_connect ? 'Classic Lex Matched' : 'Missed / Fallback'}
                  value={bot.has_q_in_connect ? bot.utterance_metrics.detected : bot.utterance_metrics.missed}
                  icon={AlertTriangle}
                  accent={bot.has_q_in_connect ? 'text-green-500' : 'text-red-500'}
                  sub={bot.has_q_in_connect ? 'Matched by Lex NLU before Q in Connect' : `${bot.utterance_metrics.missed_rate_pct}% miss rate`}
                />
              </div>
            </div>
          )}

          {/* Missed utterances table (classic Lex bots only) */}
          {!bot.has_q_in_connect && (bot.missed_utterances || []).length > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <button
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                onClick={() => setShowMissed(s => ({ ...s, [bi]: !s[bi] }))}
              >
                <span className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-500" />
                  Recent Missed / Unmatched Utterances ({bot.missed_utterances.length})
                </span>
                {showMissed[bi] ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {showMissed[bi] && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-700/60 text-xs text-gray-500 dark:text-gray-400 uppercase">
                      <tr>
                        <th className="px-3 py-2 text-left">Utterance</th>
                        <th className="px-3 py-2 text-left">Intent</th>
                        <th className="px-3 py-2 text-left">Channel</th>
                        <th className="px-3 py-2 text-left">Time</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                      {bot.missed_utterances.map((u, ui) => <MissedUtteranceRow key={ui} u={u} />)}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Escalations */}
          {bot.escalations && bot.escalations.total_escalated > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <button
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                onClick={() => setShowEscalations(s => ({ ...s, [bi]: !s[bi] }))}
              >
                <span className="flex items-center gap-2">
                  <Users className="w-4 h-4 text-amber-500" />
                  Escalations to Human Agent — {bot.escalations.total_escalated} sessions
                  {bot.has_q_in_connect && <span className="text-xs text-gray-400">(Q in Connect hand-off)</span>}
                </span>
                {showEscalations[bi] ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {showEscalations[bi] && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-700/60 text-xs text-gray-500 dark:text-gray-400 uppercase">
                      <tr>
                        <th className="px-3 py-2 text-left">Session</th>
                        <th className="px-3 py-2 text-left">Channel</th>
                        <th className="px-3 py-2 text-left">Mode</th>
                        <th className="px-3 py-2 text-left">Turns</th>
                        <th className="px-3 py-2 text-left">Start Time</th>
                        <th className="px-3 py-2 text-left">Outcome</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                      {bot.escalations.sessions.slice(0, 20).map((s, si) => <EscalationRow key={si} s={s} />)}
                    </tbody>
                  </table>
                  {bot.escalations.total_escalated > 20 && (
                    <p className="text-xs text-center text-gray-400 py-2">
                      Showing 20 of {bot.escalations.total_escalated} escalated sessions
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

        </section>
      ))}

      {/* ── Contact Flow Performance ─────────────────────────────────────── */}
      {flowChartData.length > 0 && (
        <section>
          <SectionHeader title="Contact Flow Performance" subtitle="Flow starts vs outcomes by flow type" icon={TrendingUp} />
          <div className="bg-white dark:bg-gray-800 rounded-xl p-4 border border-gray-200 dark:border-gray-700">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={flowChartData} margin={{ top: 5, right: 20, left: 0, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.3} />
                <XAxis dataKey="name" tick={{ fontSize: 12, fill: darkMode ? '#9ca3af' : '#6b7280' }} />
                <YAxis tick={{ fontSize: 12, fill: darkMode ? '#9ca3af' : '#6b7280' }} />
                <Tooltip contentStyle={{ background: darkMode ? '#1f2937' : '#fff', border: '1px solid #374151' }} />
                <Legend />
                <Bar dataKey="Started" fill={COLORS[0]} radius={[3,3,0,0]} />
                <Bar dataKey="Outcome" fill={COLORS[3]} radius={[3,3,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* ── CloudWatch Lex Runtime ───────────────────────────────────────── */}
      {Object.keys(cwByMetric).length > 0 && (
        <section>
          <SectionHeader title="Lex Runtime (CloudWatch)" subtitle="Aggregate across all bots for selected period" icon={Zap} />
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {Object.entries(cwByMetric).map(([metric, total]) => (
              <StatCard
                key={metric}
                label={metric.replace(/([A-Z])/g, ' $1').trim()}
                value={typeof total === 'number' ? (total < 1 ? total.toFixed(2) : Math.round(total).toLocaleString()) : total}
                icon={metric.includes('Latency') ? TrendingUp : Zap}
                accent={metric.includes('Throttled') || metric.includes('Missed') ? 'text-red-500' : 'text-indigo-500'}
              />
            ))}
          </div>
        </section>
      )}

    </div>
  );
}
