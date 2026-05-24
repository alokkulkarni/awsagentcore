import axios from 'axios';

const configuredBase = import.meta.env.VITE_API_URL || '/api';
const baseURL = configuredBase.startsWith('http') ? configuredBase : '/api';

const api = axios.create({
  baseURL,
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('connect.analytics.jwt');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem('connect.analytics.jwt');
      if (window.location.hostname !== 'localhost') {
        window.location.assign('/login');
      }
    }
    return Promise.reject(error);
  },
);

export const queryAgent = async (message, sessionId) => {
  const response = await api.post('/query', { message, session_id: sessionId });
  return response.data;
};

export const getHealth = async () => {
  const response = await api.get('/health');
  return response.data;
};

export const getConfig = async () => {
  const response = await api.get('/config');
  return response.data;
};

export const getMetrics = async () => {
  const response = await api.get('/metrics');
  return response.data;
};

export const getHistoricalMetrics = async (days = 30) => {
  const response = await api.get('/historical-metrics', { params: { days } });
  return response.data;
};

export const getHistoricalBreakdown = async (days = 30, groupBy = 'QUEUE') => {
  const response = await api.get('/historical-breakdown', { params: { days, group_by: groupBy } });
  return response.data;
};

export const getAgentStates = async () => {
  const response = await api.get('/agent-states');
  return response.data;
};

export const getActiveCalls = async () => {
  const response = await api.get('/active-calls');
  return response.data;
};

export const searchContacts = async (params = {}) => {
  const response = await api.get('/contacts', { params });
  return response.data;
};

export const getQueues = async () => {
  const response = await api.get('/queues');
  return response.data;
};

export const getAgentsForSearch = async () => {
  const response = await api.get('/agents-list');
  return response.data;
};

export const getTranscript = async (contactId) => {
  const response = await api.get(`/transcript/${contactId}`);
  return response.data;
};

export const summarizeTranscript = async (contactId) => {
  const response = await api.get(`/transcript/${contactId}/summarize`);
  return response.data;
};

export const getRecording = async (contactId) => {
  const response = await api.get(`/recording/${contactId}`);
  return response.data;
};

export const monitorContact = async (contactId, supervisorUserId, allowBarge = true) => {
  const response = await api.post(`/contacts/${contactId}/monitor`, {
    supervisor_user_id: supervisorUserId,
    allow_barge: allowBarge,
  });
  return response.data;
};

export const stopMonitorContact = async (contactId) => {
  const response = await api.delete(`/contacts/${contactId}/monitor`);
  return response.data;
};

export const getBotMetrics = async (days = 7) => {
  const response = await api.get('/bot-metrics', { params: { days } });
  return response.data;
};

export const getBotIntentTrend = async (days = 7) => {
  const response = await api.get('/bot-intent-trend', { params: { days } });
  return response.data;
};

export const getContactFlowEvents = async (contactId) => {
  const response = await api.get('/contact-flow-events', { params: { contact_id: contactId } });
  return response.data;
};

export const getContactFunnel = async (flowName = '', days = 30) => {
  const response = await api.get('/contact-funnel', { params: { flow_name: flowName, days } });
  return response.data;
};

export const getContactFlows = async () => {
  const response = await api.get('/contact-flows');
  return response.data;
};

export const getScanStatus = async () => {
  const response = await api.get('/startup-scan/status');
  return response.data;
};

export const getScanResources = async () => {
  const response = await api.get('/startup-scan/resources');
  return response.data;
};

export const triggerRescan = async () => {
  const response = await api.post('/startup-scan/rescan');
  return response.data;
};

// ── Live contact activity (EventBridge → SQS) ─────────────────────────────────

export const getLiveBotContacts = async () => {
  const response = await api.get('/live-bot-contacts');
  return response.data;
};

export const getLiveContacts = async () => {
  const response = await api.get('/live-contacts');
  return response.data;
};

export const getContactSentiment = async (contactId) => {
  const response = await api.get(`/sentiment/${contactId}`);
  return response.data;
};

export const getLiveCallbacks = async () => {
  const response = await api.get('/live-callbacks');
  return response.data;
};

export const getLiveOutbound = async () => {
  const response = await api.get('/live-outbound');
  return response.data;
};

export const getRecentBotContacts = async (hours = 24) => {
  const response = await api.get('/recent-bot-contacts', { params: { hours } });
  return response.data;
};

export const getStreamsConfig = async () => {
  const response = await api.get('/config/streams');
  return response.data;
};



export const listSessions = async () => {
  const response = await api.get('/sessions');
  return response.data; // [{id, title, createdAt, updatedAt}]
};

export const getSession = async (sessionId) => {
  const response = await api.get(`/sessions/${sessionId}`);
  return response.data; // {id, title, createdAt, updatedAt, messages}
};

export const upsertSession = async (session) => {
  const response = await api.put(`/sessions/${session.id}`, session);
  return response.data;
};

export const deleteSession = async (sessionId) => {
  const response = await api.delete(`/sessions/${sessionId}`);
  return response.data;
};

export const forceLogoutAgent = async (agentId, reason = '') => {
  const response = await api.post(`/agents/${encodeURIComponent(agentId)}/force-logout`, { reason });
  return response.data;
};

export const getRealtimeQueueMetrics = async () => {
  const response = await api.get('/realtime-queue-metrics');
  return response.data;
};

export const deleteAllSessions = async () => {
  const response = await api.delete('/sessions');
  return response.data;
};

export default api;
