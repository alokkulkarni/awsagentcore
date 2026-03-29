import { useRef, useEffect, useCallback } from 'react';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Alert from '@cloudscape-design/components/alert';

const STATUS_LABELS = {
  idle: '— Not connected',
  connecting: '⏳ Connecting…',
  connected: '✅ Connected — press mic to speak',
  listening: '🎙️ Listening…',
  'aria-speaking': '🔊 ARIA is speaking…',
  error: '❌ Error',
};

/**
 * Voice tab UI component.
 * @param {{ voice: object }} props
 */
export default function VoiceTab({ voice }) {
  const {
    status,
    transcript,
    error,
    connect,
    disconnect,
    startListening,
    stopListening,
    clearTranscript,
    analyserNode,
  } = voice;

  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  const transcriptEndRef = useRef(null);

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  // Waveform animation
  const drawWaveform = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, width, height);

    if (!analyserNode || status !== 'listening') {
      // Draw flat line when not listening
      ctx.beginPath();
      ctx.strokeStyle = '#00bcd430';
      ctx.lineWidth = 1.5;
      ctx.moveTo(0, height / 2);
      ctx.lineTo(width, height / 2);
      ctx.stroke();
      animFrameRef.current = requestAnimationFrame(drawWaveform);
      return;
    }

    const bufLen = analyserNode.frequencyBinCount;
    const dataArray = new Uint8Array(bufLen);
    analyserNode.getByteTimeDomainData(dataArray);

    ctx.beginPath();
    ctx.strokeStyle = '#00bcd4';
    ctx.lineWidth = 2;

    const sliceWidth = width / bufLen;
    let x = 0;

    for (let i = 0; i < bufLen; i++) {
      const v = dataArray[i] / 128.0;
      const y = (v * height) / 2;
      if (i === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
      x += sliceWidth;
    }

    ctx.lineTo(width, height / 2);
    ctx.stroke();

    animFrameRef.current = requestAnimationFrame(drawWaveform);
  }, [analyserNode, status]);

  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(drawWaveform);
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [drawWaveform]);

  // Resize canvas to match CSS size
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const resizeObserver = new ResizeObserver(() => {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    });
    resizeObserver.observe(canvas);
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
    return () => resizeObserver.disconnect();
  }, []);

  const isConnected = status === 'connected' || status === 'listening' || status === 'aria-speaking';
  const canListen = status === 'connected' || status === 'aria-speaking';
  const isListening = status === 'listening';

  const formatTime = (iso) => {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  return (
    <div className="voice-container">
      {/* Error alert */}
      {error && (
        <Alert type="error" dismissible onDismiss={() => {}}>
          {error}
        </Alert>
      )}

      {/* Controls row */}
      <div className="voice-controls">
        {/* Connect / Disconnect button */}
        <SpaceBetween size="xs" direction="vertical">
          <Button
            variant={isConnected ? 'normal' : 'primary'}
            onClick={isConnected ? disconnect : connect}
            loading={status === 'connecting'}
          >
            {isConnected ? 'Disconnect' : 'Connect'}
          </Button>
          {isConnected && (
            <Button
              variant="normal"
              onClick={clearTranscript}
              disabled={transcript.length === 0}
            >
              Clear
            </Button>
          )}
        </SpaceBetween>

        {/* Mic button */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <button
            className={`mic-button ${!isConnected ? 'disabled' : isListening ? 'listening' : 'idle'}`}
            onClick={isListening ? stopListening : startListening}
            disabled={!canListen && !isListening}
            title={isListening ? 'Stop listening' : 'Start listening'}
            aria-label={isListening ? 'Stop recording' : 'Start recording'}
          >
            {isListening ? '🎙️' : '🎤'}
          </button>
          <div className="voice-status-label">{STATUS_LABELS[status] || status}</div>
        </div>

        {/* Waveform canvas */}
        <canvas ref={canvasRef} className="waveform-canvas" aria-hidden="true" />
      </div>

      {/* Transcript area */}
      <div className="voice-transcript-area">
        {transcript.length === 0 && (
          <div className="empty-state">
            <div className="empty-state-icon">🎙️</div>
            <div style={{ fontWeight: 600 }}>Voice conversation transcript</div>
            <div style={{ fontSize: '13px' }}>Connect and press the mic button to start speaking</div>
          </div>
        )}

        {transcript.map((entry) => (
          <div key={entry.id} className={`transcript-row ${entry.role}`}>
            <div className={`transcript-bubble ${entry.role}`}>{entry.text}</div>
            <div className="message-meta">
              {entry.role === 'user' ? 'You' : 'ARIA'} · {formatTime(entry.timestamp)}
            </div>
          </div>
        ))}

        <div ref={transcriptEndRef} />
      </div>
    </div>
  );
}
