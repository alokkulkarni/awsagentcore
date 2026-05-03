import React, { useState } from 'react';
import { Dashboard } from './pages/Dashboard.js';
import { ScenariosPage } from './pages/ScenariosPage.js';
import { RunsPage } from './pages/RunsPage.js';
import { TranscriptsPage } from './pages/TranscriptsPage.js';
import { ReportsPage } from './pages/ReportsPage.js';
import { SettingsPage } from './pages/SettingsPage.js';

type Page = 'dashboard' | 'scenarios' | 'runs' | 'transcripts' | 'reports' | 'settings';

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
            <span className="text-2xl">🤖</span>
            <div>
              <h1 className="text-lg font-bold tracking-tight">ARIA Evaluator</h1>
              <p className="text-xs text-blue-200">Amazon Connect AI Quality Assurance</p>
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
