import { useRef, useEffect, useCallback } from 'react';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';

export default function VoiceTab({ voice }) {
  const {
    status,
    transcript,
    error,
    connect,
    disconnect,
    clearTranscript,
    analyserNode,
  } = voice;

  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  const transcriptEndRef = useRef(null);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  const drawWaveform = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const { width, height } = canvas;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#0a0f1a';
    ctx.fillRect(0, 0, width, height);

    if (analyserNode && (status === 'connected' || status === 'aria-speaking')) {
      const bufLen = analyserNode.frequencyBinCount;
      const data = new Uint8Array(bufLen);
      analyserNode.getByteTimeDomainData(data);
      ctx.beginPath();
      ctx.strokeStyle = status === 'aria-speaking' ? '#f0a500' : '#00b4d8';
      ctx.lineWidth = 2;
      const sliceWidth = width / bufLen;
      let x = 0;
      for (let i = 0; i < bufLen; i++) {
        const v = data[i] / 128.0;
        const y = (v * height) / 2;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        x += sliceWidth;
      }
      ctx.lineTo(width, height / 2);
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.strokeStyle = '#1e2d40';
      ctx.lineWidth = 1.5;
      ctx.moveTo(0, height / 2);
      ctx.lineTo(width, height / 2);
      ctx.stroke();
    }
    animFrameRef.current = requestAnimationFrame(drawWaveform);
  }, [analyserNode, status]);

  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(drawWaveform);
    return () => { if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current); };
  }, [drawWaveform]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    });
    ro.observe(canvas);
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
    return () => ro.disconnect();
  }, []);

  const isConnected = ['connected', 'aria-speaking'].includes(status);

  const formatTime = (iso) => {
    try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
    catch { return ''; }
  };

  const formatText = (text) =>
    text.split(/\n+/).filter(Boolean);

  return (
    <div className="voice-container">
      {/* Top bar */}
      <div className="voice-header">
        <div className="voice-header-left">
          <span className="voice-orb-mini" data-status={status} />
          <span className="voice-header-title">ARIA Voice</span>
          <span className="voice-header-subtitle">
            {status === 'idle' && 'Not connected'}
            {status === 'connecting' && 'Connecting…'}
            {status === 'connected' && 'Listening — speak anytime'}
            {status === 'aria-speaking' && 'ARIA is speaking — interrupt anytime'}
            {status === 'error' && 'Error'}
          </span>
        </div>
        <div className="voice-header-actions">
          {isConnected && (
            <Button variant="icon" iconName="remove" onClick={clearTranscript} disabled={transcript.length === 0}>
              Clear
            </Button>
          )}
          <Button
            variant={isConnected ? 'normal' : 'primary'}
            onClick={isConnected ? disconnect : connect}
            loading={status === 'connecting'}
          >
            {isConnected ? 'Disconnect' : 'Start Voice Session'}
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="voice-error-bar">
          <Alert type="error" dismissible onDismiss={() => {}}>
            {error}
          </Alert>
        </div>
      )}

      {/* Waveform */}
      <canvas ref={canvasRef} className="voice-waveform" aria-hidden="true" />

      {/* Transcript */}
      <div className="voice-messages">
        {!isConnected && status !== 'connecting' && transcript.length === 0 && (
          <div className="voice-empty">
            <div className="voice-orb-large" data-status="idle" />
            <p>Press <strong>Start Voice Session</strong> to begin.<br/>ARIA will start listening immediately — no button press needed.</p>
          </div>
        )}

        {status === 'connecting' && transcript.length === 0 && (
          <div className="voice-empty">
            <div className="voice-orb-large" data-status="connecting" />
            <p>Connecting to ARIA…</p>
          </div>
        )}

        {isConnected && transcript.length === 0 && (
          <div className="voice-empty">
            <div className="voice-orb-large" data-status={status} />
            <p>{status === 'connected' ? 'Listening… speak to ARIA' : 'ARIA is speaking…'}</p>
          </div>
        )}

        {transcript.map((msg) => (
          <div key={msg.id} className={`voice-msg voice-msg--${msg.role}`}>
            {msg.role === 'aria' && (
              <div className="voice-avatar voice-avatar--aria">A</div>
            )}
            <div className="voice-bubble">
              {formatText(msg.text).map((para, i) => (
                <p key={i}>{para}</p>
              ))}
              <span className="voice-msg-time">{formatTime(msg.timestamp)}</span>
            </div>
            {msg.role === 'user' && (
              <div className="voice-avatar voice-avatar--user">You</div>
            )}
          </div>
        ))}
        <div ref={transcriptEndRef} />
      </div>

      {/* Bottom status bar */}
      {isConnected && (
        <div className="voice-statusbar">
          <span className={`voice-mic-indicator ${status === 'aria-speaking' ? 'muted' : 'active'}`}>
            {status === 'aria-speaking' ? '🔊 ARIA speaking — say anything to interrupt' : '🎙️ Mic active'}
          </span>
        </div>
      )}
    </div>
  );
}
