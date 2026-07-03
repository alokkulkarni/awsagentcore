/**
 * TeamsPanel — Microsoft Teams inside the dashboard (spec: docs/teams-integration-spec.md).
 *
 * The real Teams web client cannot be embedded (frame-ancestors), so this
 * panel replicates its two-pane layout on the same data: chat list with
 * search on the left, the open conversation on the right — rendered from the
 * Mock provider (dummy-data mode) or Microsoft Graph (work/school account).
 * Rendered permanently (hidden when closed) so the header unread badge stays
 * fresh. Note: Graph chat APIs require a work/school (Entra) account —
 * personal teams.live.com accounts have no chat API.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { LogOut, MessageSquare, RefreshCw, Search, Send, SquarePen, Users, X } from 'lucide-react';
import { getTeamsProvider } from '../services/teams';

const POLL_OPEN_MS = 5_000;    // chat list + thread while the panel is open
const POLL_BADGE_MS = 30_000;  // unread badge while closed

// Teams brand purple
const BRAND = '#5B5FC7';

const AVATAR_PALETTE = [
  'bg-violet-500/20 text-violet-700 dark:text-violet-300',
  'bg-sky-500/20 text-sky-700 dark:text-sky-300',
  'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300',
  'bg-amber-500/25 text-amber-700 dark:text-amber-300',
  'bg-rose-500/20 text-rose-700 dark:text-rose-300',
  'bg-cyan-500/20 text-cyan-700 dark:text-cyan-300',
  'bg-fuchsia-500/20 text-fuchsia-700 dark:text-fuchsia-300',
  'bg-indigo-500/20 text-indigo-700 dark:text-indigo-300',
];

function avatarClass(name) {
  let h = 0;
  for (const c of name || '') h = (h * 31 + c.charCodeAt(0)) % 997;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}

function initials(name) {
  const parts = (name || '?').trim().split(/\s+/);
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '?';
}

function Avatar({ name, group, size = 'h-9 w-9 text-[12px]' }) {
  return (
    <span className={`flex ${size} items-center justify-center rounded-full font-semibold shrink-0 ${avatarClass(name)}`}>
      {group ? <Users size={13} /> : initials(name)}
    </span>
  );
}

function fmtListTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  if (d.toDateString() === new Date().toDateString()) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

function fmtClock(iso) {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
}

function fmtDay(iso) {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
}

/** Group consecutive messages by sender within 5 minutes, with day separators. */
function buildTimeline(messages) {
  const items = [];
  let prev = null;
  for (const m of messages) {
    if (!prev || new Date(m.at).toDateString() !== new Date(prev.at).toDateString()) {
      items.push({ kind: 'day', id: `day-${m.id}`, at: m.at });
    }
    const sameGroup = prev
      && prev.mine === m.mine && prev.from === m.from
      && new Date(m.at) - new Date(prev.at) < 5 * 60 * 1000
      && new Date(m.at).toDateString() === new Date(prev.at).toDateString();
    items.push({ kind: 'msg', ...m, groupStart: !sameGroup });
    prev = m;
  }
  // Mark group ends (timestamp shown there)
  for (let i = 0; i < items.length; i += 1) {
    if (items[i].kind !== 'msg') continue;
    const next = items[i + 1];
    items[i].groupEnd = !next || next.kind !== 'msg' || next.groupStart;
  }
  return items;
}

export default function TeamsPanel({ open, onClose, onUnreadChange, chatTarget }) {
  const [state, setState] = useState(null);           // {status, account, mock}
  const [chats, setChats] = useState([]);
  const [activeChat, setActiveChat] = useState(null); // {id, topic, group}
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [chatSearch, setChatSearch] = useState('');
  const [people, setPeople] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);
  const searchRef = useRef(null);
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

  const openChat = useCallback(async (chat) => {
    setActiveChat(chat);
    setMessages([]);
    const provider = await getTeamsProvider();
    setMessages(await provider.listMessages(chat.id));
    onUnreadChange?.((await provider.unreadCount?.()) ?? 0);
  }, [onUnreadChange]);

  // Two-pane like the Teams client: keep a conversation open on the right
  useEffect(() => {
    if (open && !activeChat && chats.length) openChat(chats[0]);
  }, [open, chats, activeChat, openChat]);

  // Roster "chat with agent" requests: jump straight into (or create) that
  // 1:1 thread. If the supervisor isn't signed in yet the sign-in view shows
  // first and the request completes right after a successful sign-in.
  const pendingTargetRef = useRef(null);
  const openTarget = useCallback(async (target) => {
    const provider = await getTeamsProvider();
    const s = await provider.getState();
    setState(s);
    if (s.status !== 'ready') {
      pendingTargetRef.current = target;
      return;
    }
    if (!provider.openChatWith) return;
    try {
      const chat = await provider.openChatWith(target);
      setActiveChat(chat);
      setMessages(await provider.listMessages(chat.id));
      setError(null);
    } catch (e) {
      setError(e.message || 'Could not open the chat');
    }
  }, []);

  useEffect(() => {
    if (chatTarget) openTarget(chatTarget);
  }, [chatTarget, openTarget]);

  // Directory search (debounced): typing a name also finds people in the
  // organisation so a brand-new chat can be started — not just filtering
  // existing threads.
  useEffect(() => {
    const q = chatSearch.trim();
    if (!open || q.length < 2) { setPeople([]); return undefined; }
    const t = setTimeout(async () => {
      try {
        const provider = await getTeamsProvider();
        const s = await provider.getState();
        if (s.status === 'ready' && provider.searchPeople) {
          setPeople(await provider.searchPeople(q));
        }
      } catch { setPeople([]); }
    }, 400);
    return () => clearTimeout(t);
  }, [chatSearch, open]);

  const startChatWithPerson = (person) => {
    setChatSearch('');
    setPeople([]);
    openTarget({ name: person.displayName, email: person.email });
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
      if (pendingTargetRef.current) {
        const target = pendingTargetRef.current;
        pendingTargetRef.current = null;
        await openTarget(target);
      }
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

  const q = chatSearch.trim().toLowerCase();
  const visibleChats = q ? chats.filter((c) => (c.topic || '').toLowerCase().includes(q)) : chats;
  const timeline = buildTimeline(messages);

  return (
    // z-[60]: must layer above the z-50 FloatingAssistant launcher, which
    // otherwise floats over the composer's send button
    <div className="fixed inset-0 z-[60] flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[2px]" />
      <div
        className="relative h-full w-[860px] max-w-[96vw] bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Brand header ─────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-4 py-3 shrink-0 border-b border-slate-200 dark:border-slate-800"
             style={{ background: 'linear-gradient(90deg, rgba(91,95,199,0.08), transparent 60%)' }}>
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl shrink-0" style={{ background: BRAND }}>
              <MessageSquare size={15} className="text-white" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-200 leading-tight">Microsoft Teams</p>
              {state?.account && (
                <p className="text-[10px] text-slate-500 dark:text-slate-400 truncate">
                  {state.account.username}{state.mock && ' · mock data'}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {state?.account && (
              <span className="relative mr-1">
                <Avatar name={state.account.name || state.account.username} size="h-7 w-7 text-[10px]" />
                <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-emerald-500 ring-2 ring-white dark:ring-slate-900" />
              </span>
            )}
            {state?.status === 'ready' && !state.mock && (
              <button type="button" onClick={signOut} title="Sign out of Microsoft 365" className="rounded-lg p-1.5 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition">
                <LogOut size={13} />
              </button>
            )}
            <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition">
              <X size={14} />
            </button>
          </div>
        </div>

        {error && (
          <p className="px-4 py-2 text-[11px] text-rose-600 dark:text-rose-400 border-b border-slate-200 dark:border-slate-800 bg-rose-500/5">{error}</p>
        )}

        {!state && (
          <div className="flex-1 flex items-center justify-center text-sm text-slate-500 dark:text-slate-400 gap-2">
            <RefreshCw size={14} className="animate-spin" /> Connecting…
          </div>
        )}

        {state?.status === 'unconfigured' && (
          <div className="flex-1 px-6 py-8 text-sm text-slate-600 dark:text-slate-300 space-y-3 max-w-lg">
            <p className="font-semibold text-slate-800 dark:text-slate-200">Teams isn’t configured yet.</p>
            <p className="text-xs leading-relaxed">
              Create an Entra ID app registration (SPA, redirect URI {window.location.origin}/auth-redirect.html,
              delegated permissions <code>User.Read</code>, <code>User.ReadBasic.All</code>, <code>Chat.ReadWrite</code>,{' '}
              <code>Presence.Read.All</code>) and set
              <code className="block mt-2">TEAMS_CLIENT_ID / TEAMS_TENANT_ID in docker/.env</code>
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Requires a work/school Microsoft 365 account. Tip: switch Dummy Data ON to preview the panel with simulated chats.
            </p>
          </div>
        )}

        {state?.status === 'signed_out' && (
          <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6 text-center">
            <span className="flex h-14 w-14 items-center justify-center rounded-2xl" style={{ background: 'rgba(91,95,199,0.12)' }}>
              <MessageSquare size={24} style={{ color: BRAND }} />
            </span>
            <p className="text-sm text-slate-600 dark:text-slate-300 max-w-xs">
              Sign in with your Microsoft 365 work account to chat with your team without leaving the dashboard.
            </p>
            <button
              type="button"
              onClick={signIn}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50 transition hover:brightness-110"
              style={{ background: BRAND }}
            >
              {busy ? <RefreshCw size={13} className="animate-spin" /> : <MessageSquare size={13} />}
              Connect Teams
            </button>
            {state.clientId && (
              <p className="font-mono text-[10px] text-slate-400 dark:text-slate-500">
                app {state.clientId.slice(0, 8)}… · tenant {state.tenantId?.slice(0, 8)}…
              </p>
            )}
          </div>
        )}

        {state?.status === 'ready' && (
          <div className="flex-1 flex min-h-0">
            {/* ── Left: chat list ─────────────────────────────────────────── */}
            <aside className="w-[290px] shrink-0 border-r border-slate-200 dark:border-slate-800 flex flex-col min-h-0 bg-slate-50/60 dark:bg-slate-950/30">
              <div className="px-3 pt-3 pb-2 shrink-0">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">Chat</p>
                  <button
                    type="button"
                    title="New chat — search a name"
                    onClick={() => searchRef.current?.focus()}
                    className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-200/70 dark:hover:bg-slate-800 transition"
                  >
                    <SquarePen size={13} />
                  </button>
                </div>
                <div className="relative">
                  <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                  <input
                    ref={searchRef}
                    type="text"
                    value={chatSearch}
                    onChange={(e) => setChatSearch(e.target.value)}
                    placeholder="Search people and chats…"
                    className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 pl-7 pr-2 py-1.5 text-[11px] text-slate-800 dark:text-slate-200 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-400/40 focus:border-indigo-400"
                  />
                </div>
              </div>
              <div className="flex-1 overflow-y-auto px-1.5 pb-2">
                {people.length > 0 && (
                  <div className="mb-1">
                    <p className="px-2 pt-1 pb-1 text-[9px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      People — start a new chat
                    </p>
                    {people.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => startChatWithPerson(p)}
                        className="w-full flex items-center gap-2.5 rounded-xl px-2 py-2 text-left hover:bg-indigo-500/10 transition"
                      >
                        <Avatar name={p.displayName} size="h-8 w-8 text-[11px]" />
                        <span className="min-w-0">
                          <span className="block text-xs font-medium text-slate-800 dark:text-slate-200 truncate">{p.displayName}</span>
                          <span className="block text-[10px] text-slate-500 dark:text-slate-400 truncate">{p.email}</span>
                        </span>
                      </button>
                    ))}
                    <div className="mx-2 my-1 border-b border-slate-200 dark:border-slate-800" />
                  </div>
                )}
                {visibleChats.length === 0 && people.length === 0 && (
                  <div className="px-3 py-8 text-center">
                    <MessageSquare size={20} className="mx-auto mb-2 text-slate-300 dark:text-slate-600" />
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {q ? `Nothing matches “${chatSearch.trim()}”.` : 'No chats yet — search a name to start one.'}
                    </p>
                  </div>
                )}
                {visibleChats.map((c) => {
                  const active = activeChat?.id === c.id;
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => openChat(c)}
                      className={`w-full flex items-center gap-2.5 rounded-xl px-2 py-2 text-left transition ${
                        active ? 'bg-white dark:bg-slate-800 shadow-sm ring-1 ring-slate-200 dark:ring-slate-700'
                               : 'hover:bg-slate-200/50 dark:hover:bg-slate-800/60'
                      }`}
                    >
                      <Avatar name={c.topic} group={c.group} />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className={`text-xs truncate ${c.unread ? 'font-semibold text-slate-900 dark:text-white' : 'font-medium text-slate-800 dark:text-slate-200'}`}>
                            {c.topic}
                          </span>
                          <span className="text-[9px] text-slate-400 shrink-0">{fmtListTime(c.last?.at)}</span>
                        </span>
                        <span className={`block text-[10px] truncate ${c.unread ? 'text-slate-700 dark:text-slate-300 font-medium' : 'text-slate-500 dark:text-slate-400'}`}>
                          {c.last ? `${c.last.mine ? 'You: ' : ''}${c.last.text}` : 'No messages yet'}
                        </span>
                      </span>
                      {c.unread > 0 && (
                        <span className="flex h-4.5 min-w-[18px] items-center justify-center rounded-full px-1 text-[9px] font-semibold text-white shrink-0" style={{ background: BRAND }}>
                          {c.unread}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </aside>

            {/* ── Right: conversation ─────────────────────────────────────── */}
            <main className="flex-1 flex flex-col min-h-0">
              {!activeChat ? (
                <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-8">
                  <span className="flex h-14 w-14 items-center justify-center rounded-2xl" style={{ background: 'rgba(91,95,199,0.10)' }}>
                    <MessageSquare size={24} style={{ color: BRAND }} />
                  </span>
                  <p className="text-sm text-slate-500 dark:text-slate-400">Pick a chat on the left, or search a name to start a new one.</p>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2.5 border-b border-slate-200 dark:border-slate-800 px-4 py-2.5 shrink-0">
                    <Avatar name={activeChat.topic} group={activeChat.group} size="h-8 w-8 text-[11px]" />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate leading-tight">{activeChat.topic}</p>
                      <p className="text-[10px] text-slate-500 dark:text-slate-400">{activeChat.group ? 'Group chat' : 'Chat'}</p>
                    </div>
                  </div>

                  <div className="flex-1 overflow-y-auto px-4 py-3 bg-slate-50/50 dark:bg-slate-950/20">
                    {/* Bottom-anchored like every chat client: sparse threads sit
                        just above the composer instead of floating in whitespace */}
                    <div className="min-h-full flex flex-col justify-end">
                    {timeline.length === 0 && (
                      <div className="flex flex-col items-center gap-3 text-center pb-6">
                        <Avatar name={activeChat.topic} group={activeChat.group} size="h-12 w-12 text-[15px]" />
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          Say hello to {activeChat.topic} — this is the start of your conversation.
                        </p>
                      </div>
                    )}
                    {timeline.map((item) => {
                      if (item.kind === 'day') {
                        return (
                          <div key={item.id} className="flex items-center gap-3 my-3">
                            <span className="flex-1 border-b border-slate-200 dark:border-slate-800" />
                            <span className="text-[9px] font-medium uppercase tracking-wider text-slate-400 dark:text-slate-500">{fmtDay(item.at)}</span>
                            <span className="flex-1 border-b border-slate-200 dark:border-slate-800" />
                          </div>
                        );
                      }
                      const m = item;
                      return (
                        <div key={m.id} className={`flex gap-2 ${m.mine ? 'justify-end' : 'justify-start'} ${m.groupStart ? 'mt-2.5' : 'mt-0.5'}`}>
                          {!m.mine && (
                            <span className="w-7 shrink-0 self-end">
                              {m.groupEnd && <Avatar name={m.from} size="h-7 w-7 text-[10px]" />}
                            </span>
                          )}
                          <div className={`max-w-[70%] ${m.mine ? 'items-end' : 'items-start'} flex flex-col`}>
                            {m.groupStart && !m.mine && (
                              <p className="text-[9px] font-medium text-slate-500 dark:text-slate-400 mb-0.5 px-1">{m.from}</p>
                            )}
                            <div
                              title={new Date(m.at).toLocaleString()}
                              className={`rounded-2xl px-3.5 py-2 text-xs leading-relaxed shadow-sm ${
                                m.mine
                                  ? 'text-white rounded-br-md'
                                  : 'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-700/60 rounded-bl-md'
                              }`}
                              style={m.mine ? { background: BRAND } : undefined}
                            >
                              {m.text}
                            </div>
                            {m.groupEnd && (
                              <p className="text-[9px] text-slate-400 dark:text-slate-500 mt-0.5 px-1">{fmtClock(m.at)}</p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    <div ref={bottomRef} />
                    </div>
                  </div>

                  <div className="border-t border-slate-200 dark:border-slate-800 px-4 py-3 shrink-0">
                    <div className="flex items-end gap-2 rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 focus-within:ring-2 focus-within:ring-indigo-400/40 focus-within:border-indigo-400 transition">
                      <textarea
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
                        placeholder={`Message ${activeChat.topic}…`}
                        rows={Math.min(4, Math.max(1, draft.split('\n').length))}
                        className="flex-1 resize-none bg-transparent text-xs text-slate-800 dark:text-slate-200 placeholder:text-slate-400 focus:outline-none leading-relaxed"
                      />
                      <button
                        type="button"
                        onClick={send}
                        disabled={busy || !draft.trim()}
                        title="Send (Enter)"
                        className="rounded-xl p-2 text-white disabled:opacity-30 transition hover:brightness-110 shrink-0"
                        style={{ background: BRAND }}
                      >
                        <Send size={14} />
                      </button>
                    </div>
                    <p className="mt-1 px-1 text-[9px] text-slate-400 dark:text-slate-500">Enter to send · Shift+Enter for a new line</p>
                  </div>
                </>
              )}
            </main>
          </div>
        )}
      </div>
    </div>
  );
}
