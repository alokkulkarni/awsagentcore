import { useState, useRef, useCallback, useEffect } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { AudioCapture } from '../helpers/audioCapture.js';
import { AudioPlayer } from '../helpers/audioPlayer.js';
import { createPresignedWebSocketUrl } from '../helpers/agentcoreClient.js';

const VAD_RMS_THRESHOLD = 600;   // RMS threshold for 16-bit PCM speech detection
const ARIA_DONE_TIMEOUT_MS = 600; // ms of audio silence before ARIA is "done speaking"
const BARGEIN_COOLDOWN_MS = 1000; // ms between consecutive barge-ins

/**
 * Voice WebSocket + always-on audio logic for ARIA banking agent.
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

  // Always-current config ref — async callbacks (ws.onopen, ws.onmessage) must
  // read from this ref, not from the closure-captured `config`, to avoid stale
  // values when the user changes auth/customerId just before connecting.
  const configRef = useRef(config);
  useEffect(() => { configRef.current = config; }, [config]);

  // Barge-in / ARIA speaking state (refs for access inside callbacks)
  const ariaIsSpeakingRef = useRef(false);
  const ariaSpeakingTimerRef = useRef(null);
  const bargeinCooldownRef = useRef(0);

  useEffect(() => {
    return () => {
      isCleaningUp.current = true;
      cleanupAll();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function cleanupAll() {
    clearTimeout(ariaSpeakingTimerRef.current);
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
    ariaIsSpeakingRef.current = false;
  }

  /** Mark ARIA as speaking; reset the "done" debounce timer */
  function markAriaSpeaking() {
    ariaIsSpeakingRef.current = true;
    clearTimeout(ariaSpeakingTimerRef.current);
    ariaSpeakingTimerRef.current = setTimeout(() => {
      ariaIsSpeakingRef.current = false;
      setStatus((prev) => (prev === 'aria-speaking' ? 'connected' : prev));
    }, ARIA_DONE_TIMEOUT_MS);
  }

  /** Compute RMS energy of an Int16Array chunk */
  function computeRMS(int16Chunk) {
    let sum = 0;
    for (let i = 0; i < int16Chunk.length; i++) {
      sum += int16Chunk[i] * int16Chunk[i];
    }
    return Math.sqrt(sum / int16Chunk.length);
  }

  /** Start the microphone — called automatically after WS connect */
  async function startMic(ws) {
    try {
      const capture = new AudioCapture({
        onChunk: (int16Chunk) => {
          // Forward audio to server
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(int16Chunk.buffer);
          }

          // Barge-in detection: if ARIA is speaking and user starts talking
          const now = Date.now();
          if (
            ariaIsSpeakingRef.current &&
            computeRMS(int16Chunk) > VAD_RMS_THRESHOLD &&
            now - bargeinCooldownRef.current > BARGEIN_COOLDOWN_MS
          ) {
            bargeinCooldownRef.current = now;
            // Stop ARIA audio immediately
            audioPlayerRef.current?.bargeIn();
            // Tell server to stop generating
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ interrupted: true }));
            }
            ariaIsSpeakingRef.current = false;
            clearTimeout(ariaSpeakingTimerRef.current);
            setStatus('connected');
          }
        },
        onWaveform: () => {},
        targetSampleRate: 16000,
        chunkSize: 1024,
      });

      await capture.start();
      audioCaptureRef.current = capture;
      setAnalyserNode(capture.getAnalyserNode());
    } catch (err) {
      setError(`Microphone access failed: ${err.message}`);
      setStatus('error');
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

    if (config.mode === 'local') {
      const pingUrl = resolvedWsUrl.replace(/^ws(s?):\/\//, 'http$1://').replace(/\/ws(\?.*)?$/, '/ping');
      try {
        const resp = await fetch(pingUrl, { signal: AbortSignal.timeout(4000) });
        if (!resp.ok) throw new Error(`Server returned ${resp.status}`);
      } catch (pingErr) {
        const isTimeout = pingErr.name === 'TimeoutError' || pingErr.name === 'AbortError';
        setError(
          isTimeout
            ? `ARIA server not reachable at ${pingUrl}. Start it with: uvicorn aria.agentcore_app:app --host 0.0.0.0 --port 8080 --workers 1`
            : `ARIA server error: ${pingErr.message}. Make sure uvicorn is running on port 8080.`
        );
        setStatus('error');
        if (audioPlayerRef.current) { audioPlayerRef.current.stop(); audioPlayerRef.current = null; }
        return;
      }
    }

    let ws;
    let connectTimeout;
    try {
      ws = new WebSocket(resolvedWsUrl);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;
    } catch (err) {
      setError(`Failed to open WebSocket: ${err.message}`);
      setStatus('error');
      return;
    }

    connectTimeout = setTimeout(() => {
      if (wsRef.current === ws && ws.readyState === WebSocket.CONNECTING) {
        ws.close();
        setError(
          config.mode === 'local'
            ? 'WebSocket upgrade timed out. Check the ARIA server is running.'
            : 'AgentCore WebSocket timed out. Check runtime status and presigned URL validity.'
        );
        setStatus('error');
      }
    }, 12000);

    ws.onopen = async () => {
      clearTimeout(connectTimeout);
      if (wsRef.current !== ws) return;
      // Read configRef.current here — guaranteed to be the latest value even if
      // the user toggled auth or changed customerId between connect() being called
      // and the WS handshake completing.
      const liveConfig = configRef.current;
      ws.send(JSON.stringify({
        type: 'session.config',
        authenticated: liveConfig.authenticated,
        customer_id: liveConfig.customerId,
      }));
      setStatus('connected');
      // Start mic immediately — always-on, no button press needed
      await startMic(ws);
    };

    ws.onmessage = (evt) => {
      if (wsRef.current !== ws) return;

      if (evt.data instanceof ArrayBuffer) {
        if (audioPlayerRef.current) {
          audioPlayerRef.current.playChunk(new Int16Array(evt.data));
        }
        markAriaSpeaking();
        setStatus('aria-speaking');
        return;
      }

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
            markAriaSpeaking();
            setStatus('aria-speaking');
            break;

          case 'interrupt':
            // Server confirmed barge-in — already handled client-side
            ariaIsSpeakingRef.current = false;
            clearTimeout(ariaSpeakingTimerRef.current);
            setStatus('connected');
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
        // Non-JSON, ignore
      }
    };

    ws.onerror = () => {
      clearTimeout(connectTimeout);
      if (isCleaningUp.current) return;
      setError('WebSocket connection error. Check that the server is running.');
      setStatus('error');
    };

    ws.onclose = () => {
      clearTimeout(connectTimeout);
      if (isCleaningUp.current) return;
      if (wsRef.current === ws) {
        wsRef.current = null;
        if (audioCaptureRef.current) {
          audioCaptureRef.current.stop();
          audioCaptureRef.current = null;
        }
        setAnalyserNode(null);
        setStatus('idle');
      }
    };
  }, [wsUrl, config]); // eslint-disable-line react-hooks/exhaustive-deps

  const disconnect = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: 'session.end' })); } catch {}
    }
    setAnalyserNode(null);
    cleanupAll();
    setStatus('idle');
    setError(null);
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
    clearTranscript,
    analyserNode,
    // Keep legacy API stubs so nothing else breaks
    startListening: () => {},
    stopListening: () => {},
  };
}
