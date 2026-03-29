import { useState, useEffect, useCallback } from 'react';

const STORAGE_KEY = 'aria_connection_config';

const DEFAULT_CONFIG = {
  mode: 'local',
  localChatUrl: 'http://localhost:8080',
  localWsUrl: 'ws://localhost:8080/ws',
  agentcoreChatUrl: '',
  agentcoreWsUrl: '',
  authenticated: false,
  customerId: 'CUST-001',
  awsRegion: 'us-east-1',
  awsAccessKeyId: '',
  awsSecretAccessKey: '',
  awsSessionToken: '',
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

  const wsUrl = config.mode === 'local'
    ? config.localWsUrl
    : config.agentcoreWsUrl;

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
