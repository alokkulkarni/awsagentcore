import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { queryAgent, listSessions, getSession, upsertSession, deleteSession as apiDeleteSession, deleteAllSessions } from '../services/api';

const MAX_SESSIONS = 40;

const createSessionId = () =>
  window.crypto?.randomUUID?.() || `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;

const ts = () => new Date().toISOString();

const deriveTitle = (messages) => {
  const first = messages.find((m) => m.role === 'user');
  if (!first) return 'New session';
  return first.content.length > 60 ? `${first.content.slice(0, 60)}…` : first.content;
};

const serializeMsgs = (msgs) =>
  msgs.map((m) => ({ ...m, timestamp: m.timestamp instanceof Date ? m.timestamp.toISOString() : m.timestamp }));

const deserializeMsgs = (msgs) =>
  (msgs || []).map((m) => ({ ...m, timestamp: new Date(m.timestamp) }));

export default function useAgentChat() {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [allSessions, setAllSessions] = useState([]);
  const [sessionId, setSessionId] = useState(() => createSessionId());

  // Persist timer ref for debouncing upserts
  const persistTimer = useRef(null);

  // Load session list on mount
  useEffect(() => {
    listSessions()
      .then((sessions) => {
        setAllSessions(sessions.slice(0, MAX_SESSIONS));
        // If there's a most-recent session with messages, restore it
        if (sessions.length > 0) {
          const latest = sessions[0];
          setSessionId(latest.id);
          getSession(latest.id)
            .then((s) => { if (s?.messages?.length) setMessages(deserializeMsgs(s.messages)); })
            .catch(() => {});
        }
      })
      .catch(() => {}); // offline / first boot — no sessions yet
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshSessions = useCallback(() => {
    listSessions()
      .then((sessions) => setAllSessions(sessions.slice(0, MAX_SESSIONS)))
      .catch(() => {});
  }, []);

  const persistSession = useCallback((id, msgs) => {
    if (!msgs.length) return;
    // Debounce — wait 400 ms after last message before writing
    clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => {
      upsertSession({
        id,
        title: deriveTitle(msgs),
        createdAt: ts(),
        updatedAt: ts(),
        messages: serializeMsgs(msgs),
      })
        .then(refreshSessions)
        .catch(() => {});
    }, 400);
  }, [refreshSessions]);

  const sendMessage = useCallback(async (text) => {
    const content = text?.trim();
    if (!content) return;

    const userMsg = { role: 'user', content, timestamp: new Date() };
    setMessages((prev) => {
      const next = [...prev, userMsg];
      persistSession(sessionId, next);
      return next;
    });
    setIsLoading(true);

    try {
      const response = await queryAgent(content, sessionId);
      setMessages((prev) => {
        const next = [...prev, { role: 'assistant', content: response.response, timestamp: new Date() }];
        persistSession(sessionId, next);
        return next;
      });
    } catch (error) {
      setMessages((prev) => {
        const next = [...prev, {
          role: 'assistant',
          content: error?.response?.data?.error || error.message || 'Something went wrong.',
          timestamp: new Date(),
        }];
        persistSession(sessionId, next);
        return next;
      });
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, persistSession]);

  const clearChat = useCallback(() => {
    const nextId = createSessionId();
    setSessionId(nextId);
    setMessages([]);
  }, []);

  const loadSession = useCallback((id) => {
    getSession(id)
      .then((s) => {
        if (!s) return;
        setSessionId(id);
        setMessages(deserializeMsgs(s.messages));
      })
      .catch(() => {});
  }, []);

  const deleteSession = useCallback((id) => {
    apiDeleteSession(id)
      .then(() => {
        refreshSessions();
        if (id === sessionId) clearChat();
      })
      .catch(() => {});
  }, [sessionId, clearChat, refreshSessions]);

  return useMemo(
    () => ({ messages, sendMessage, isLoading, sessionId, clearChat, allSessions, loadSession, deleteSession }),
    [messages, sendMessage, isLoading, sessionId, clearChat, allSessions, loadSession, deleteSession],
  );
}
