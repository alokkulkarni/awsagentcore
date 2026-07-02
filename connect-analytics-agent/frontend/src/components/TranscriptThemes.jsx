/**
 * TranscriptThemes — scans every stored transcript in a supervisor-chosen date
 * range and surfaces the top discussion themes between customers and agents.
 *
 * Backend: agent/theme_scan.py (exhaustive search_contacts pagination + batched
 * Bedrock theme extraction, seeded with Contact Lens categories/issues, folded
 * into a running canonical list). Progress streams over SSE from
 * GET /api/transcript-themes/stream, matching the StartupScan.jsx convention;
 * GET /api/transcript-themes/status is the polling/reload fallback.
 */
import { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle, ChevronDown, ChevronUp, MessagesSquare, RefreshCw, Sparkles, Tag,
} from 'lucide-react';
import { startTranscriptThemeScan, getTranscriptThemeStatus } from '../services/api';

function isoStartOfDay(dateStr) {
  return `${dateStr}T00:00:00.000Z`;
}
function isoEndOfDay(dateStr) {
  return `${dateStr}T23:59:59.999Z`;
}
function defaultDateStr(daysAgo) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - daysAgo);
  return d.toISOString().slice(0, 10);
}

function barColour(count, maxCount) {
  const ratio = maxCount > 0 ? count / maxCount : 0;
  if (ratio >= 0.66) return '#10b981';
  if (ratio >= 0.33) return '#f59e0b';
  return '#6366f1';
}

function ThemeRow({ rank, theme, maxCount, expanded, onToggle }) {
  return (
    <>
      <tr
        onClick={onToggle}
        className="cursor-pointer border-b border-slate-200/50 dark:border-slate-800/50 text-xs hover:bg-slate-200 dark:hover:bg-slate-700/20 transition"
      >
        <td className="py-2.5 px-3 text-slate-600 dark:text-slate-500 tabular-nums w-8">{rank}</td>
        <td className="py-2.5 px-3 text-slate-800 dark:text-slate-200 font-medium">
          <span className="inline-flex items-center gap-1.5">
            <Tag size={11} className="text-indigo-600 dark:text-indigo-400" />
            {theme.theme}
          </span>
        </td>
        <td className="py-2.5 px-3">
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 min-w-[48px]">
              <div
                className="h-1.5 rounded-full"
                style={{ width: `${maxCount > 0 ? (theme.count / maxCount) * 100 : 0}%`, background: barColour(theme.count, maxCount) }}
              />
            </div>
            <span className="text-slate-700 dark:text-slate-300 w-6 text-right tabular-nums font-semibold">{theme.count}</span>
          </div>
        </td>
        <td className="py-2.5 px-3 w-6 text-slate-600 dark:text-slate-500">
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-slate-200/50 dark:border-slate-800/50 bg-slate-200/30 dark:bg-slate-800/30">
          <td />
          <td colSpan={3} className="py-3 px-3">
            {(theme.example_quotes || []).length > 0 && (
              <div className="mb-2 space-y-1">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-500 mb-1">Example Quotes</p>
                {theme.example_quotes.map((q, i) => (
                  <p key={i} className="text-slate-700 dark:text-slate-300 italic">&ldquo;{q}&rdquo;</p>
                ))}
              </div>
            )}
            {(theme.contact_ids || []).length > 0 && (
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-500 mb-1">Contacts</p>
                <div className="flex flex-wrap gap-1.5">
                  {theme.contact_ids.map((cid) => (
                    <span key={cid} className="rounded-md bg-slate-200 dark:bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-500 dark:text-slate-400">
                      …{String(cid).slice(-8)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function ThemeTable({ themes, expandedTheme, setExpandedTheme, rankOffset = 0 }) {
  const maxCount = Math.max(1, ...themes.map((t) => t.count || 0));
  return (
    <table className="w-full text-xs">
      <tbody>
        {themes.map((theme, i) => (
          <ThemeRow
            key={theme.theme}
            rank={rankOffset + i + 1}
            theme={theme}
            maxCount={maxCount}
            expanded={expandedTheme === theme.theme}
            onToggle={() => setExpandedTheme((prev) => (prev === theme.theme ? null : theme.theme))}
          />
        ))}
      </tbody>
    </table>
  );
}

export default function TranscriptThemes({ onAskAssistant }) {
  const [startDate, setStartDate] = useState(defaultDateStr(30));
  const [endDate, setEndDate] = useState(defaultDateStr(0));
  const [scan, setScan] = useState(null); // backend state snapshot
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [expandedTheme, setExpandedTheme] = useState(null);
  const esRef = useRef(null);

  const closeStream = () => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  };

  const openStream = () => {
    closeStream();
    const es = new EventSource('/api/transcript-themes/stream');
    es.onmessage = (evt) => {
      let data;
      try { data = JSON.parse(evt.data); } catch { return; }
      setScan((prev) => ({ ...prev, ...data }));
      if (data.type === 'scan_complete' || data.type === 'already_complete') {
        closeStream();
      } else if (data.type === 'scan_error') {
        setError(data.message || 'Theme scan failed');
        closeStream();
      }
    };
    es.onerror = () => closeStream();
    esRef.current = es;
  };

  useEffect(() => {
    (async () => {
      try {
        const status = await getTranscriptThemeStatus();
        setScan(status);
        if (status.running) openStream();
      } catch {
        // No prior scan state — fine, user hasn't run one yet.
      }
    })();
    return () => closeStream();
  }, []);

  const runScan = async () => {
    setError(null);
    setShowAll(false);
    setExpandedTheme(null);
    try {
      const result = await startTranscriptThemeScan({ start: isoStartOfDay(startDate), end: isoEndOfDay(endDate) });
      setScan(result);
      openStream();
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to start theme scan');
    }
  };

  const running = !!scan?.running;
  const themes = scan?.themes;
  const top10 = themes?.top_10 || [];
  const all = themes?.all || [];
  const rest = all.slice(10);

  return (
    <div className="rounded-xl border border-slate-300/60 dark:border-slate-700/60 bg-slate-200/40 dark:bg-slate-800/40 p-4">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-600 dark:text-slate-500">From</label>
          <input
            type="date"
            value={startDate}
            max={endDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-200 dark:bg-slate-800 px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-600 dark:text-slate-500">To</label>
          <input
            type="date"
            value={endDate}
            min={startDate}
            max={defaultDateStr(0)}
            onChange={(e) => setEndDate(e.target.value)}
            className="rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-200 dark:bg-slate-800 px-2.5 py-1.5 text-xs text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <button
          type="button"
          onClick={runScan}
          disabled={running}
          className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RefreshCw size={13} className={running ? 'animate-spin' : ''} />
          {running ? 'Scanning…' : 'Scan Transcripts'}
        </button>
        {onAskAssistant && top10.length > 0 && (
          <button
            type="button"
            onClick={() => onAskAssistant(
              `Summarise these top discussion themes found across contact transcripts between ${startDate} and ${endDate}: `
              + top10.map((t) => `${t.theme} (${t.count})`).join(', ')
              + '. What should the contact centre team pay attention to?'
            )}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-200 dark:bg-slate-800 px-3 py-2 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-300 dark:hover:bg-slate-700 transition"
          >
            <Sparkles size={13} /> Ask AI
          </button>
        )}
        {scan?.mock_mode && (
          <span className="rounded-full bg-amber-500/20 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-300">mock data</span>
        )}
      </div>

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
            {scan?.contacts_scanned ?? 0}/{scan?.contacts_found ?? '…'} contacts scanned
            {' · '}{scan?.transcripts_used ?? 0} with stored transcripts
            {scan?.batches_total ? ` · batch ${scan.batches_processed ?? 0}/${scan.batches_total}` : ''}
          </p>
        </div>
      )}

      {!running && !themes && (
        <p className="text-xs text-slate-600 dark:text-slate-500">
          Pick a date range and scan to discover what customers and agents have been discussing —
          themes are drawn from every transcript that's been fully generated and stored in that window.
        </p>
      )}

      {themes && all.length === 0 && !running && (
        <p className="text-xs text-slate-600 dark:text-slate-500">No stored transcripts with recognisable themes were found in that range.</p>
      )}

      {top10.length > 0 && (
        <div className="overflow-x-auto">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              <MessagesSquare size={14} className="inline mr-1.5 text-indigo-600 dark:text-indigo-400" />
              Top {top10.length} Discussion Themes
            </p>
            <span className="text-xs text-slate-600 dark:text-slate-500">
              {themes.total_themes} theme{themes.total_themes !== 1 ? 's' : ''} recognised across {scan?.transcripts_used ?? 0} transcripts
            </span>
          </div>
          <ThemeTable themes={top10} expandedTheme={expandedTheme} setExpandedTheme={setExpandedTheme} />

          {rest.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="mt-2 text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-500 dark:hover:text-indigo-300 transition"
              >
                {showAll ? 'Show less' : `Show all ${themes.total_themes} themes`}
              </button>
              {showAll && (
                <div className="mt-2">
                  <ThemeTable themes={rest} expandedTheme={expandedTheme} setExpandedTheme={setExpandedTheme} rankOffset={10} />
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
