import { useEffect, useMemo, useState } from 'react';
import {
  BarChart2,
  Headphones,
  ListFilter,
  Moon,
  Radio,
  ShieldCheck,
  ShieldAlert,
  Sun,
  TrendingDown,
  X,
} from 'lucide-react';
import ContactSearch from './components/ContactSearch';
import TranscriptViewer from './components/TranscriptViewer';
import StartupScan from './components/StartupScan';
import RealtimeCommandCenter from './components/RealtimeCommandCenter';
import HistoricalAnalytics from './components/HistoricalAnalytics';
import FlowFunnelPage from './components/FlowFunnelPage';
import FloatingAssistant from './components/FloatingAssistant';
import useAgentChat from './hooks/useAgentChat';
import useProactiveAlerts from './hooks/useProactiveAlerts';
import { getHealth, getConfig, getScanStatus } from './services/api';

// ── navigation screens ─────────────────────────────────────────────────────────
const SCREENS = [
  { id: 'realtime',   label: 'Real-Time',  sublabel: 'Command Centre', icon: Radio },
  { id: 'historical', label: 'Historical', sublabel: 'Analytics',      icon: BarChart2 },
  { id: 'contacts',   label: 'Contact',    sublabel: 'Search',         icon: ListFilter },
  { id: 'funnel',     label: 'Flow Funnel', sublabel: 'Drop-off Analysis', icon: TrendingDown },
];

export default function App() {
  const chat = useAgentChat();
  const [screen, setScreen]             = useState('realtime');
  const [health, setHealth]             = useState({ status: 'checking' });
  const [connectConfig, setConnectConfig] = useState(null);
  const [assistantMsg, setAssistantMsg] = useState('');
  const [showScan, setShowScan]         = useState(null);
  const [darkMode, setDarkMode]         = useState(
    () => localStorage.getItem('connect.analytics.theme') !== 'light',
  );

  // Contact search → transcript modal
  const [selectedContact, setSelectedContact]   = useState(null);
  const [highlightKeyword, setHighlightKeyword] = useState('');
  const [showTranscriptModal, setShowTranscriptModal] = useState(false);

  // Proactive alert monitoring (only active on realtime screen, but mounted globally)
  const proactive = useProactiveAlerts({ enabled: true });

  // ── theme ───────────────────────────────────────────────────────────────────
  useEffect(() => {
    // Enterprise dashboard is always dark — light mode toggle kept for compatibility
    document.body.classList.toggle('light', !darkMode);
    document.documentElement.classList.toggle('dark', darkMode);
    localStorage.setItem('connect.analytics.theme', darkMode ? 'dark' : 'light');
  }, [darkMode]);

  // ── bootstrap ───────────────────────────────────────────────────────────────
  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth({ status: 'offline', mock_mode: false }));
    getConfig()
      .then(setConnectConfig)
      .catch(() => {});
  }, []);

  useEffect(() => {
    getScanStatus()
      .then((status) => {
        if (status.mock_mode) { setShowScan(false); return; }
        const storedBootId = sessionStorage.getItem('connect.analytics.bootId');
        const isFreshBoot  = status.boot_id && status.boot_id !== storedBootId;
        if (isFreshBoot) {
          sessionStorage.setItem('connect.analytics.bootId', status.boot_id);
          setShowScan(true);
        } else {
          setShowScan(false);
        }
      })
      .catch(() => setShowScan(false));
  }, []);

  const environmentLabel = useMemo(() => {
    if (health.mock_mode) return 'local';
    return import.meta.env.MODE === 'development' ? 'local' : 'cloud';
  }, [health]);

  // ── callbacks ────────────────────────────────────────────────────────────────

  /** Open the floating AI assistant with a pre-filled message. */
  const handleAskAssistant = (message) => {
    setAssistantMsg(message);
  };

  /** Contact Search → open transcript in a modal overlay. */
  const handleSelectContact = (contact, keyword = '') => {
    setSelectedContact(contact);
    setHighlightKeyword(keyword);
    setShowTranscriptModal(true);
  };

  const handleTranscriptModalClose = () => {
    setShowTranscriptModal(false);
    setSelectedContact(null);
    setHighlightKeyword('');
  };

  return (
    <>
      {/* ── Startup scan overlay ───────────────────────────────────────────── */}
      {showScan === true && <StartupScan onComplete={() => setShowScan(false)} />}

      <div className="flex min-h-screen bg-slate-950 text-slate-100">

        {/* ── Left sidebar ─────────────────────────────────────────────────── */}
        <aside className="hidden w-52 shrink-0 flex-col border-r border-slate-800 bg-slate-900/80 lg:flex">
          {/* Logo */}
          <div className="flex items-center gap-3 border-b border-slate-800 px-4 py-5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-connect-500/20 text-connect-400">
              <Headphones size={18} />
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-[0.3em] text-connect-500">Amazon Connect</p>
              <p className="text-xs font-semibold text-slate-100">Analytics Agent</p>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-3 py-4 space-y-1">
            {SCREENS.map(({ id, label, sublabel, icon: Icon }) => {
              const active = screen === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => setScreen(id)}
                  className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition ${
                    active
                      ? 'bg-connect-500/20 text-connect-300'
                      : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                  }`}
                >
                  <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${active ? 'bg-connect-500/30' : 'bg-slate-800'}`}>
                    <Icon size={14} className={active ? 'text-connect-400' : 'text-slate-500'} />
                  </div>
                  <div>
                    <p className={`text-xs font-semibold ${active ? 'text-connect-300' : 'text-slate-300'}`}>{label}</p>
                    <p className="text-[10px] text-slate-500">{sublabel}</p>
                  </div>
                  {id === 'realtime' && proactive.criticalCount > 0 && (
                    <span className="ml-auto flex h-4 w-4 items-center justify-center rounded-full bg-rose-500 text-[9px] font-bold text-white">
                      {proactive.criticalCount}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Connection status + environment */}
          <div className="border-t border-slate-800 px-3 py-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500">Connection</span>
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                health.status === 'ok' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-amber-500/15 text-amber-400'
              }`}>
                <ShieldCheck size={10} />
                {health.status === 'ok' ? 'Healthy' : 'Checking'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500">Environment</span>
              <span className="text-[10px] font-medium text-slate-300">{environmentLabel}</span>
            </div>
            {connectConfig && connectConfig.connect_alias && (
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-slate-500">Instance</span>
                <span className="text-[10px] font-mono text-slate-400">{connectConfig.connect_alias}</span>
              </div>
            )}
            {/* Active alert count */}
            {proactive.alertCount > 0 && (
              <div className="flex items-center gap-2 rounded-xl bg-rose-500/10 border border-rose-500/30 px-2.5 py-2">
                <ShieldAlert size={12} className="text-rose-400 shrink-0" />
                <p className="text-[10px] text-rose-300 font-medium">
                  {proactive.alertCount} active alert{proactive.alertCount !== 1 ? 's' : ''}
                </p>
              </div>
            )}
            {/* Dark/light mode */}
            <button
              type="button"
              onClick={() => setDarkMode((v) => !v)}
              className="flex w-full items-center gap-2 rounded-xl border border-slate-700 bg-slate-800/50 px-3 py-2 text-[11px] text-slate-400 hover:text-slate-200 transition"
            >
              {darkMode ? <Sun size={12} /> : <Moon size={12} />}
              {darkMode ? 'Light mode' : 'Dark mode'}
            </button>
          </div>
        </aside>

        {/* ── Main content ──────────────────────────────────────────────────── */}
        <div className="flex flex-1 flex-col min-w-0">

          {/* Top bar (breadcrumb + quick status) */}
          <header className="shrink-0 flex items-center justify-between border-b border-slate-800 bg-slate-900/60 px-6 py-3">
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Headphones size={13} className="text-connect-500" />
              <span>Amazon Connect Analytics Agent</span>
              <span className="text-slate-700">/</span>
              <span className="text-slate-300 font-medium">
                {SCREENS.find((s) => s.id === screen)?.label}{' '}
                {SCREENS.find((s) => s.id === screen)?.sublabel}
              </span>
            </div>
            <div className="flex items-center gap-3">
              {proactive.alertCount > 0 && (
                <button
                  type="button"
                  onClick={() => setScreen('realtime')}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500/15 px-3 py-1.5 text-[11px] font-medium text-rose-300 hover:bg-rose-500/25 transition animate-pulse"
                >
                  <ShieldAlert size={11} />
                  {proactive.criticalCount > 0
                    ? `${proactive.criticalCount} critical alert${proactive.criticalCount !== 1 ? 's' : ''}`
                    : `${proactive.alertCount} alert${proactive.alertCount !== 1 ? 's' : ''}`}
                </button>
              )}
              {connectConfig?.connect_alias && (
                <span className="text-[10px] text-slate-500 font-mono hidden sm:inline">
                  {connectConfig.connect_alias}.my.connect.aws
                </span>
              )}
            </div>
          </header>

          {/* Screen content */}
          <main className="flex-1 overflow-auto p-5">

            {/* ── Realtime Command Centre ────────────────────────────────────── */}
            <div className={screen === 'realtime' ? 'h-full' : 'hidden'}>
              <RealtimeCommandCenter
                alerts={proactive.alerts}
                onDismissAlert={proactive.dismissAlert}
                onQueryAlertAI={proactive.queryAlertAI}
                onAskAssistant={handleAskAssistant}
                connectConfig={connectConfig}
              />
            </div>

            {/* ── Historical Analytics ───────────────────────────────────────── */}
            <div className={screen === 'historical' ? '' : 'hidden'}>
              <HistoricalAnalytics onAskAssistant={handleAskAssistant} />
            </div>

            {/* ── Contact Search ─────────────────────────────────────────────── */}
            <div className={screen === 'contacts' ? '' : 'hidden'}>
              <ContactSearch
                onAskQuery={handleAskAssistant}
                onSelectContact={handleSelectContact}
              />
            </div>

            {/* ── Flow Funnel Analysis ───────────────────────────────────────── */}
            <div className={screen === 'funnel' ? '' : 'hidden'}>
              <FlowFunnelPage />
            </div>

          </main>
        </div>
      </div>

      {/* ── Transcript modal overlay (Contact Search → Transcript) ─────────── */}
      {showTranscriptModal && selectedContact && (
        <div
          className="fixed inset-0 z-40 flex items-stretch justify-end bg-slate-950/80 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) handleTranscriptModalClose(); }}
        >
          <div className="relative flex w-full max-w-3xl flex-col bg-slate-900 shadow-2xl border-l border-slate-800 overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3 shrink-0">
              <p className="text-sm font-semibold text-slate-200">
                Transcript — <span className="font-mono text-connect-400">…{selectedContact.contactId?.slice(-12)}</span>
              </p>
              <button
                type="button"
                onClick={handleTranscriptModalClose}
                className="rounded-lg p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition"
              >
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-5">
              <TranscriptViewer
                contact={selectedContact}
                highlightKeyword={highlightKeyword}
                onContactClose={handleTranscriptModalClose}
              />
            </div>
          </div>
        </div>
      )}

      {/* ── Floating AI assistant (always visible) ─────────────────────────── */}
      <FloatingAssistant
        chat={chat}
        alertCount={proactive.alertCount}
        prefilledMessage={assistantMsg}
        onPrefillConsumed={() => setAssistantMsg('')}
      />
    </>
  );
}
