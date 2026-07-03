/**
 * TeamsPanel — Microsoft Teams inside the dashboard (spec: docs/teams-integration-spec.md).
 *
 * Rendered permanently (hidden when closed) so it can keep the header unread
 * badge fresh. Slide-over UI mirrors the Contact Detail overlay. Mock mode is
 * fully interactive; real mode signs in with MSAL and talks to Microsoft Graph.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, LogOut, MessageSquare, RefreshCw, Send, Users, X } from 'lucide-react';
import { getTeamsProvider } from '../services/teams';

const POLL_OPEN_MS = 5_000;    // chat list + thread while the panel is open
const POLL_BADGE_MS = 30_000;  // unread badge while closed

function fmtWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  if (mins < 24 * 60) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

export default function TeamsPanel({ open, onClose, onUnreadChange }) {
  const [state, setState] = useState(null);           // {status, account, mock}
  const [chats, setChats] = useState([]);
  const [activeChat, setActiveChat] = useState(null); // {id, topic}
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);
  const activeChatRef = useRef(null);
  activeChatRef.current = activeChat;

  const refresh = useCallback(async () => {
    const provider = await getTeamsProvider();
    const s = await provider.getState();
    setState(s);
    if (s.status !== 'ready') return;
    try {
      const list = await provider.listChats();
      setChats(list);
      onUnreadChange?.(list.reduce((n, c) => n + (c.unread || 0), 0));
      const current = activeChatRef.current;
      if (current) setMessages(await provider.listMessages(current.id));
      setError(null);
    } catch (e) {
      setError(e.message || 'Failed to reach Microsoft Graph');
    }
  }, [onUnreadChange]);

  // Poll: fast while open, slow badge-only while closed
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      if (open) {
        await refresh();
      } else {
        const provider = await getTeamsProvider();
        const s = await provider.getState();
        if (!cancelled) setState(s);
        if (s.status === 'ready') {
          const n = await provider.unreadCount();
          if (!cancelled) onUnreadChange?.(n);
        }
      }
    };
    tick();
    const t = setInterval(tick, open ? POLL_OPEN_MS : POLL_BADGE_MS);
    return () => { cancelled = true; clearInterval(t); };
  }, [open, refresh, onUnreadChange]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages.length]);

  const openChat = async (chat) => {
    setActiveChat(chat);
    setMessages([]);
    const provider = await getTeamsProvider();
    setMessages(await provider.listMessages(chat.id));
    onUnreadChange?.((await provider.unreadCount?.()) ?? 0);
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || !activeChat) return;
    setBusy(true);
    setDraft('');
    try {
      const provider = await getTeamsProvider();
      await provider.sendMessage(activeChat.id, text);
      setMessages(await provider.listMessages(activeChat.id));
    } catch (e) {
      setError(e.message || 'Send failed');
    } finally {
      setBusy(false);
    }
  };

  const signIn = async () => {
    setBusy(true);
    setError(null);
    try {
      const provider = await getTeamsProvider();
      setState(await provider.signIn());
      await refresh();
    } catch (e) {
      setError(e.message || 'Sign-in failed');
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    const provider = await getTeamsProvider();
    await provider.signOut();
    setChats([]);
    setActiveChat(null);
    setMessages([]);
    onUnreadChange?.(0);
    setState(await provider.getState());
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px]" />
      <div
        className="relative h-full w-[400px] max-w-[92vw] bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 px-4 py-3 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            {activeChat && (
              <button type="button" onClick={() => setActiveChat(null)} className="rounded-lg p-1 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
                <ArrowLeft size={14} />
              </button>
            )}
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600/15 shrink-0">
              <MessageSquare size={14} className="text-indigo-600 dark:text-indigo-400" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate">
                {activeChat ? activeChat.topic : 'Microsoft Teams'}
              </p>
              {state?.account && !activeChat && (
                <p className="text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  {state.account.username}{state.mock && ' · mock'}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {state?.status === 'ready' && !state.mock && (
              <button type="button" onClick={signOut} title="Sign out of Microsoft 365" className="rounded-lg p-1.5 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
                <LogOut size={13} />
              </button>
            )}
            <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:text-rose-600 dark:hover:text-rose-400">
              <X size={14} />
            </button>
          </div>
        </div>

        {error && (
          <p className="px-4 py-2 text-[11px] text-rose-600 dark:text-rose-400 border-b border-slate-200 dark:border-slate-800">{error}</p>
        )}

        {/* Body */}
        {!state && (
          <div className="flex-1 flex items-center justify-center text-sm text-slate-500 dark:text-slate-400 gap-2">
            <RefreshCw size={14} className="animate-spin" /> Connecting…
          </div>
        )}

        {state?.status === 'unconfigured' && (
          <div className="flex-1 px-5 py-6 text-sm text-slate-600 dark:text-slate-300 space-y-3">
            <p className="font-semibold text-slate-800 dark:text-slate-200">Teams isn’t configured yet.</p>
            <p className="text-xs leading-relaxed">
              Create an Entra ID app registration (SPA, redirect URI {window.location.origin},
              delegated permissions <code>User.Read</code>, <code>Chat.ReadWrite</code>,{' '}
              <code>Presence.Read.All</code>) and rebuild the frontend with
              <code className="block mt-2">VITE_TEAMS_CLIENT_ID=…{'\n'}VITE_TEAMS_TENANT_ID=…</code>
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Full steps: docs/teams-integration-spec.md. Tip: switch Dummy Data ON to preview the panel with simulated chats.
            </p>
          </div>
        )}

        {state?.status === 'signed_out' && (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center">
            <MessageSquare size={28} className="text-indigo-500/50" />
            <p className="text-sm text-slate-600 dark:text-slate-300">Sign in with your Microsoft 365 account to see your Teams chats here.</p>
            <button
              type="button"
              onClick={signIn}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition"
            >
              {busy ? <RefreshCw size={13} className="animate-spin" /> : <MessageSquare size={13} />}
              Connect Teams
            </button>
          </div>
        )}

        {state?.status === 'ready' && !activeChat && (
          <div className="flex-1 overflow-y-auto">
            {chats.length === 0 && (
              <p className="px-4 py-6 text-sm text-slate-500 dark:text-slate-400">No recent chats.</p>
            )}
            {chats.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => openChat(c)}
                className="w-full flex items-start gap-3 px-4 py-3 text-left border-b border-slate-100 dark:border-slate-800/60 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition"
              >
                <span className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-full bg-indigo-500/15 text-indigo-600 dark:text-indigo-300 shrink-0">
                  {c.group ? <Users size={14} /> : (c.topic || '?').slice(0, 1)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">{c.topic}</span>
                    <span className="text-[10px] text-slate-400 shrink-0">{fmtWhen(c.last?.at)}</span>
                  </span>
                  <span className="block text-xs text-slate-500 dark:text-slate-400 truncate">
                    {c.last ? `${c.last.mine ? 'You: ' : ''}${c.last.text}` : '—'}
                  </span>
                </span>
                {c.unread > 0 && (
                  <span className="mt-1 flex h-5 min-w-[20px] items-center justify-center rounded-full bg-indigo-600 px-1.5 text-[10px] font-semibold text-white shrink-0">
                    {c.unread}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        {state?.status === 'ready' && activeChat && (
          <>
            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
              {messages.map((m) => (
                <div key={m.id} className={`flex ${m.mine ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-xs leading-relaxed ${
                    m.mine
                      ? 'bg-indigo-600 text-white rounded-br-sm'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 rounded-bl-sm'
                  }`}>
                    {!m.mine && <p className="text-[9px] font-semibold opacity-70 mb-0.5">{m.from}</p>}
                    {m.text}
                    <p className={`mt-1 text-[9px] ${m.mine ? 'text-indigo-200' : 'text-slate-400'}`}>{fmtWhen(m.at)}</p>
                  </div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
            <div className="border-t border-slate-200 dark:border-slate-800 p-3 shrink-0">
              <div className="flex items-end gap-2">
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder={`Message ${activeChat.topic}…`}
                  rows={1}
                  className="flex-1 resize-none rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-xs text-slate-800 dark:text-slate-200 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500"
                />
                <button
                  type="button"
                  onClick={send}
                  disabled={busy || !draft.trim()}
                  className="rounded-xl bg-indigo-600 p-2 text-white hover:bg-indigo-700 disabled:opacity-40 transition"
                >
                  <Send size={14} />
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
