import React, { useState } from 'react';
import { Dashboard } from './pages/Dashboard.js';
import { ScenariosPage } from './pages/ScenariosPage.js';
import { RunsPage } from './pages/RunsPage.js';
import { TranscriptsPage } from './pages/TranscriptsPage.js';
import { ReportsPage } from './pages/ReportsPage.js';
import { SettingsPage } from './pages/SettingsPage.js';

type Page = 'dashboard' | 'scenarios' | 'runs' | 'transcripts' | 'reports' | 'settings';

function LogoIcon() {
  return (
    <svg width="38" height="38" viewBox="0 0 38 38" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      {/* Hexagon shield */}
      <path d="M19 2L35 11V27L19 36L3 27V11L19 2Z" fill="#1E40AF" stroke="#93C5FD" strokeWidth="1.5"/>
      {/* Neural triangle — top node */}
      <circle cx="19" cy="12.5" r="2.8" fill="white"/>
      {/* Bottom-left node */}
      <circle cx="12" cy="24.5" r="2.2" fill="#BFDBFE"/>
      {/* Bottom-right node */}
      <circle cx="26" cy="24.5" r="2.2" fill="#BFDBFE"/>
      {/* Connections */}
      <line x1="19" y1="12.5" x2="12" y2="24.5" stroke="#93C5FD" strokeWidth="1.4"/>
      <line x1="19" y1="12.5" x2="26" y2="24.5" stroke="#93C5FD" strokeWidth="1.4"/>
      <line x1="12" y1="24.5" x2="26" y2="24.5" stroke="#93C5FD" strokeWidth="1.4"/>
      {/* Quality tick on top node */}
      <path d="M16.8 12.5L18.3 14.2L21.2 10.8" stroke="#1E3A8A" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: 'dashboard',   label: 'Dashboard',   icon: '🏠' },
  { id: 'scenarios',   label: 'Scenarios',   icon: '📋' },
  { id: 'runs',        label: 'Runs',        icon: '▶️'  },
  { id: 'transcripts', label: 'Transcripts', icon: '💬' },
  { id: 'reports',     label: 'Reports',     icon: '📊' },
  { id: 'settings',    label: 'Settings',    icon: '⚙️' },
];

function getInitialPage(): Page {
  if (typeof window === 'undefined') return 'dashboard';
  const page = new URLSearchParams(window.location.search).get('page');
  if (page === 'dashboard' || page === 'scenarios' || page === 'runs' || page === 'transcripts' || page === 'reports' || page === 'settings') {
    return page;
  }
  return 'dashboard';
}

export default function App() {
  const [page, setPage] = useState<Page>(getInitialPage);
  const initialTranscriptFile = typeof window !== 'undefined'
    ? (new URLSearchParams(window.location.search).get('file') ?? undefined)
    : undefined;

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="bg-[#0D2A66] text-white shadow-md">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="flex-shrink-0"><LogoIcon /></span>
            <div>
              <h1 className="text-lg font-bold tracking-tight">ARIA Evaluator</h1>
              <p className="text-xs text-blue-200">Agentic AI Evaluation Platform</p>
            </div>
          </div>
          <nav className="flex gap-1">
            {NAV.map((n) => (
              <button
                key={n.id}
                onClick={() => setPage(n.id)}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  page === n.id
                    ? 'bg-white/20 text-white'
                    : 'text-blue-100 hover:bg-white/10 hover:text-white'
                }`}
              >
                <span className="mr-1.5">{n.icon}</span>
                {n.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-8">
        {page === 'dashboard'   && <Dashboard   onNavigate={setPage} />}
        {page === 'scenarios'   && <ScenariosPage />}
        {page === 'runs'        && <RunsPage />}
        {page === 'transcripts' && <TranscriptsPage initialFilename={initialTranscriptFile} />}
        {page === 'reports'     && <ReportsPage />}
        {page === 'settings'    && <SettingsPage />}
      </main>
    </div>
  );
}
