import { useState, useEffect, useCallback } from 'react';

const STORAGE_KEY = 'aria_connection_config';

const DEFAULT_CONFIG = {
  // Auto-detect: if AgentCore URL is baked into the build (CloudFront deploy),
  // default to agentcore mode so the app works immediately without manual setup.
  mode: import.meta.env.VITE_AGENTCORE_CHAT_URL ? 'agentcore' : 'local',
  authenticated: false,
  customerId: 'CUST-001',

  // Local endpoints
  localChatUrl: import.meta.env.VITE_LOCAL_CHAT_URL || 'http://localhost:8080/invocations',
  localVoiceUrl: import.meta.env.VITE_LOCAL_WS_URL || 'ws://localhost:8080/ws',

  // AgentCore endpoints
  agentcoreChatUrl: import.meta.env.VITE_AGENTCORE_CHAT_URL || '',
  // agentcoreVoiceUrl is computed from runtimeId + region — not stored separately
  agentcoreRuntimeId: import.meta.env.VITE_AGENTCORE_RUNTIME_ID || '',

  // Cognito (for AgentCore auth — provides temp credentials for SigV4)
  cognitoIdentityPoolId: import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID || '',
  awsRegion: import.meta.env.VITE_AWS_REGION || 'eu-west-2',
};

function loadConfig() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return { ...DEFAULT_CONFIG, ...JSON.parse(stored) };
    }
  } catch {
    // ignore parse errors
  }
  return { ...DEFAULT_CONFIG };
}

function saveConfig(config) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // ignore storage errors
  }
}

/**
 * Manages all connection configuration with localStorage persistence.
 * @returns {{ config: object, updateConfig: function, chatUrl: string, wsUrl: string }}
 */
export function useConnection() {
  const [config, setConfig] = useState(loadConfig);

  const chatUrl = config.mode === 'local'
    ? config.localChatUrl
    : config.agentcoreChatUrl;

  // wsUrl is only meaningful for local mode — AgentCore mode uses presigned URL generated in useVoice
  const wsUrl = config.mode === 'local'
    ? config.localVoiceUrl
    : null;

  const updateConfig = useCallback((updates) => {
    setConfig((prev) => {
      const next = { ...prev, ...updates };
      saveConfig(next);
      return next;
    });
  }, []);

  // Persist whenever config changes
  useEffect(() => {
    saveConfig(config);
  }, [config]);

  return { config, updateConfig, chatUrl, wsUrl };
}

/**
 * Derive the AgentCore WebSocket base URL from runtimeId + region.
 * Presigning happens later in useVoice — this just gives the base wss:// URL.
 */
export function getAgentcoreVoiceWssBase(config) {
  if (!config.agentcoreRuntimeId || !config.awsRegion) return '';
  return `wss://bedrock-agentcore.${config.awsRegion}.amazonaws.com/runtimes/${config.agentcoreRuntimeId}/ws?qualifier=DEFAULT`;
}
