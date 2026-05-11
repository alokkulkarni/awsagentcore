/**
 * FloatingAssistant — persistent floating AI chat panel.
 *
 * Renders as a bottom-right FAB when collapsed.
 * Expands to a full chat panel (400 × 600 px) on click.
 * Shows an alert badge when proactive alerts are active.
 * Accepts a `prefilledMessage` prop to pre-load a query (e.g. from an alert action).
 */

import { useEffect, useRef, useState } from 'react';
import {
  Bot,
  ChevronDown,
  Maximize2,
  Minimize2,
  RefreshCw,
  SendHorizonal,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import { formatDistanceToNow } from 'date-fns';

export default function FloatingAssistant({
  chat,
  alertCount = 0,
  prefilledMessage = '',
  onPrefillConsumed,
}) {
  const [open, setOpen]         = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [input, setInput]       = useState('');
  const inputRef   = useRef(null);
  const bottomRef  = useRef(null);

  // Auto-expand when a prefilled message arrives
  useEffect(() => {
    if (prefilledMessage) {
      setOpen(true);
      setInput(prefilledMessage);
    }
  }, [prefilledMessage]);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 150);
    }
  }, [open]);

  // Scroll to bottom on new messages
  useEffect(() => {
    if (open) {
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);
    }
  }, [chat.messages, open]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || chat.isLoading) return;
    chat.sendMessage(text);
    setInput('');
    if (prefilledMessage && onPrefillConsumed) onPrefillConsumed();
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const panelW = expanded ? 'w-[680px]' : 'w-[400px]';
  const panelH = expanded ? 'h-[80vh]'  : 'h-[540px]';

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3">
      {/* ── Expanded panel ─────────────────────────────────────────────────── */}
      {open && (
        <div
          className={`${panelW} ${panelH} flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl transition-all duration-200 overflow-hidden`}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-800 bg-slate-950/80 px-4 py-3 shrink-0">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-connect-500/20 text-connect-400">
                <Bot size={14} />
              </div>
              <span className="text-sm font-semibold text-slate-100">AI Assistant</span>
              {chat.isLoading && (
                <span className="inline-flex items-center gap-1 text-[10px] text-slate-400">
                  <RefreshCw size={10} className="animate-spin" /> thinking…
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                title="New chat"
                onClick={chat.clearChat}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition"
              >
                <Trash2 size={14} />
              </button>
              <button
                type="button"
                title={expanded ? 'Shrink' : 'Expand'}
                onClick={() => setExpanded((v) => !v)}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100 transition"
              >
                {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              </button>
              <button
                type="button"
                title="Minimise"
                onClick={() => setOpen(false)}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-rose-400 transition"
              >
                <ChevronDown size={14} />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4 scrollbar-thin">
            {chat.messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
                <Sparkles size={28} className="text-connect-400 opacity-60" />
                <p className="text-sm text-slate-400">
                  Ask me anything about your contact centre — agents, queues, metrics, or a specific call.
                </p>
                {[
                  'How many agents are available right now?',
                  'Who is my busiest agent today?',
                  'What is the average handle time this week?',
                ].map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => { setInput(q); inputRef.current?.focus(); }}
                    className="text-xs text-connect-400 border border-connect-500/30 rounded-xl px-3 py-1.5 hover:bg-connect-500/10 transition"
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}

            {chat.messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                    msg.role === 'user'
                      ? 'bg-connect-500 text-white rounded-br-sm'
                      : 'bg-slate-800 text-slate-100 rounded-bl-sm'
                  }`}
                >
                  {msg.role === 'assistant' ? (
                    <div className="prose prose-invert prose-sm max-w-none leading-relaxed">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <p>{msg.content}</p>
                  )}
                  <p className={`mt-1 text-[10px] ${msg.role === 'user' ? 'text-white/60' : 'text-slate-500'}`}>
                    {formatDistanceToNow(new Date(msg.timestamp), { addSuffix: true })}
                  </p>
                </div>
              </div>
            ))}

            {chat.isLoading && (
              <div className="flex justify-start">
                <div className="bg-slate-800 rounded-2xl rounded-bl-sm px-4 py-3">
                  <span className="flex gap-1">
                    {[0, 1, 2].map((d) => (
                      <span
                        key={d}
                        className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce"
                        style={{ animationDelay: `${d * 0.15}s` }}
                      />
                    ))}
                  </span>
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t border-slate-800 bg-slate-950/60 p-3 shrink-0">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about agents, queues, calls…"
                rows={1}
                className="flex-1 resize-none rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-connect-500 max-h-32"
                style={{ fieldSizing: 'content' }}
              />
              <button
                type="button"
                onClick={handleSend}
                disabled={!input.trim() || chat.isLoading}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-connect-500 text-white hover:bg-connect-700 disabled:opacity-40 transition"
              >
                <SendHorizonal size={15} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── FAB ─────────────────────────────────────────────────────────────── */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`relative flex h-14 w-14 items-center justify-center rounded-full shadow-xl transition-all duration-200 ${
          open
            ? 'bg-slate-700 text-slate-100'
            : 'bg-connect-500 text-white hover:bg-connect-700'
        }`}
        title={open ? 'Close AI Assistant' : 'Open AI Assistant'}
      >
        {open ? <X size={22} /> : <Bot size={22} />}

        {/* Alert badge */}
        {!open && alertCount > 0 && (
          <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-rose-500 text-[10px] font-bold text-white ring-2 ring-slate-900">
            {alertCount > 9 ? '9+' : alertCount}
          </span>
        )}
      </button>
    </div>
  );
}
