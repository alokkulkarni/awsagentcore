import { useState, useRef, useCallback, useEffect } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { AudioCapture } from '../helpers/audioCapture.js';
import { AudioPlayer } from '../helpers/audioPlayer.js';
import { createPresignedWebSocketUrl } from '../helpers/agentcoreClient.js';

/**
 * Voice WebSocket + audio logic for ARIA banking agent.
 * @param {{ config: object, wsUrl: string }} connection
 */
export function useVoice(connection) {
  const { config, wsUrl } = connection;

  const [status, setStatus] = useState('idle');
  const [transcript, setTranscript] = useState([]);
  const [error, setError] = useState(null);
  const [analyserNode, setAnalyserNode] = useState(null);

  const wsRef = useRef(null);
  const audioCaptureRef = useRef(null);
  const audioPlayerRef = useRef(null);
  const isCleaningUp = useRef(false);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isCleaningUp.current = true;
      cleanupAll();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function cleanupAll() {
    if (audioCaptureRef.current) {
      audioCaptureRef.current.stop();
      audioCaptureRef.current = null;
    }
    if (audioPlayerRef.current) {
      audioPlayerRef.current.stop();
      audioPlayerRef.current = null;
    }
    if (wsRef.current) {
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    }
  }

  const connect = useCallback(async () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    setStatus('connecting');
    setError(null);

    let resolvedWsUrl;

    if (config.mode === 'local') {
      if (!wsUrl) {
        setError('WebSocket URL is not configured. Please set it in Connection Settings.');
        setStatus('error');
        return;
      }
      resolvedWsUrl = wsUrl;
    } else {
      // AgentCore mode — generate a SigV4 presigned WSS URL
      if (!config.authenticated) {
        setError('AgentCore voice requires authentication. Enable "Authenticated" mode and configure Cognito Identity Pool ID.');
        setStatus('error');
        return;
      }
      if (!config.agentcoreRuntimeId) {
        setError('AgentCore Runtime ID not configured. Add it in Connection Settings.');
        setStatus('error');
        return;
      }
      try {
        resolvedWsUrl = await createPresignedWebSocketUrl({
          runtimeId: config.agentcoreRuntimeId,
          region: config.awsRegion,
          qualifier: 'DEFAULT',
          expiresIn: 3600,
        });
      } catch (err) {
        setError(`Failed to create presigned URL: ${err.message}. Check Cognito Identity Pool configuration.`);
        setStatus('error');
        return;
      }
    }

    const player = new AudioPlayer({ sampleRate: 24000 });
    player.init();
    audioPlayerRef.current = player;

    let ws;
    try {
      ws = new WebSocket(resolvedWsUrl);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;
    } catch (err) {
      setError(`Failed to open WebSocket: ${err.message}`);
      setStatus('error');
      return;
    }

    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      const configMsg = JSON.stringify({
        type: 'session.config',
        authenticated: config.authenticated,
        customer_id: config.customerId,
      });
      ws.send(configMsg);
      setStatus('connected');
    };

    ws.onmessage = (evt) => {
      if (wsRef.current !== ws) return;

      if (evt.data instanceof ArrayBuffer) {
        // Binary: raw 24kHz 16-bit mono PCM audio from ARIA
        if (audioPlayerRef.current) {
          const int16 = new Int16Array(evt.data);
          audioPlayerRef.current.playChunk(int16);
        }
        setStatus('aria-speaking');
        return;
      }

      // Text JSON messages
      try {
        const msg = JSON.parse(evt.data);
        switch (msg.type) {
          case 'session.started':
            setStatus('connected');
            break;

          case 'transcript.user':
            setTranscript((prev) => [
              ...prev,
              { id: uuidv4(), role: 'user', text: msg.text, timestamp: new Date().toISOString() },
            ]);
            break;

          case 'transcript.aria':
            setTranscript((prev) => [
              ...prev,
              { id: uuidv4(), role: 'aria', text: msg.text, timestamp: new Date().toISOString() },
            ]);
            setStatus('aria-speaking');
            break;

          case 'session.ended':
            setStatus('idle');
            cleanupAll();
            break;

          case 'error':
            setError(msg.message || 'An error occurred during voice session.');
            setStatus('error');
            break;

          default:
            break;
        }
      } catch {
        // Non-JSON text, ignore
      }
    };

    ws.onerror = (evt) => {
      if (isCleaningUp.current) return;
      setError('WebSocket connection error. Check that the server is running.');
      setStatus('error');
    };

    ws.onclose = (evt) => {
      if (isCleaningUp.current) return;
      if (wsRef.current === ws) {
        wsRef.current = null;
        if (audioCaptureRef.current) {
          audioCaptureRef.current.stop();
          audioCaptureRef.current = null;
        }
        setStatus('idle');
      }
    };
  }, [wsUrl, config]);

  const disconnect = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'session.end' }));
      } catch {
        // ignore
      }
    }

    if (audioCaptureRef.current) {
      audioCaptureRef.current.stop();
      audioCaptureRef.current = null;
    }

    setAnalyserNode(null);
    cleanupAll();
    setStatus('idle');
    setError(null);
  }, []);

  const startListening = useCallback(async () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setError('Not connected. Please connect first.');
      return;
    }

    try {
      const capture = new AudioCapture({
        onChunk: (int16Chunk) => {
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(int16Chunk.buffer);
          }
        },
        onWaveform: () => {
          // Waveform data is accessed via the analyser node directly
        },
        targetSampleRate: 16000,
        chunkSize: 1024,
      });

      await capture.start();
      audioCaptureRef.current = capture;
      setAnalyserNode(capture.getAnalyserNode());
      setStatus('listening');
    } catch (err) {
      setError(`Microphone access failed: ${err.message}`);
      setStatus('error');
    }
  }, []);

  const stopListening = useCallback(() => {
    if (audioCaptureRef.current) {
      audioCaptureRef.current.stop();
      audioCaptureRef.current = null;
    }
    setAnalyserNode(null);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      setStatus('connected');
    }
  }, []);

  const clearTranscript = useCallback(() => {
    setTranscript([]);
    setError(null);
  }, []);

  return {
    status,
    transcript,
    error,
    connect,
    disconnect,
    startListening,
    stopListening,
    clearTranscript,
    analyserNode,
  };
}
