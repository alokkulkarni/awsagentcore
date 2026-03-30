import { useState, useCallback, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { signedFetch } from '../helpers/agentcoreClient.js';

/**
 * HTTP chat logic for ARIA banking agent.
 * @param {{ config: object, chatUrl: string }} connection
 */
export function useChat(connection) {
  const { config, chatUrl } = connection;

  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const sessionId = useRef(uuidv4()).current;

  const sendMessage = useCallback(async (text) => {
    if (!text || !text.trim()) return;

    if (!chatUrl) {
      setError('Chat URL is not configured. Please set it in Connection Settings.');
      return;
    }

    const userMsg = {
      id: uuidv4(),
      role: 'user',
      content: text.trim(),
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setError(null);

    try {
      const invokeUrl = chatUrl.endsWith('/invocations')
        ? chatUrl
        : `${chatUrl.replace(/\/$/, '')}/invocations`;

      const payload = {
        message: text.trim(),
        authenticated: config.authenticated,
        customer_id: config.customerId,
      };

      const bodyStr = JSON.stringify(payload);
      const useSignedRequest =
        config.mode === 'agentcore' &&
        config.authenticated &&
        config.cognitoIdentityPoolId;

      let response;
      if (useSignedRequest) {
        response = await signedFetch(
          invokeUrl,
          { method: 'POST', body: bodyStr },
          config.awsRegion || 'eu-west-2'
        );
      } else {
        response = await fetch(invokeUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: bodyStr,
        });
      }

      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        throw new Error(`Server responded with ${response.status}: ${errText || response.statusText}`);
      }

      const responseText = await response.text();

      const assistantMsg = {
        id: uuidv4(),
        role: 'assistant',
        content: responseText,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errMsg = err?.message || 'Failed to reach ARIA. Please check your connection settings.';
      setError(errMsg);

      const errorMsg = {
        id: uuidv4(),
        role: 'assistant',
        content: `⚠️ ${errMsg}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  }, [chatUrl, config]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return { messages, isLoading, error, sessionId, sendMessage, clearMessages };
}
