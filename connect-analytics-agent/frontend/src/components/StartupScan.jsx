import { useState, useEffect, useRef, useCallback } from 'react';
import {
  PhoneCall, Bot, Zap, Archive, BarChart3, Brain,
  Shield, CheckCircle2, Wifi, Database,
} from 'lucide-react';

/* ── Phase definitions ─────────────────────────────────────────────────────── */
const PHASES = [
  { id: 'connect_core', label: 'Connect Core',      icon: PhoneCall, color: '#3b82f6', angle:  0 },
  { id: 'bots_ai',      label: 'Conversational AI', icon: Bot,       color: '#8b5cf6', angle: 60 },
  { id: 'lambda_fns',   label: 'Lambda',            icon: Zap,       color: '#f59e0b', angle: 120 },
  { id: 'data_storage', label: 'Data Storage',      icon: Archive,   color: '#10b981', angle: 180 },
  { id: 'analytics',    label: 'Analytics',         icon: BarChart3, color: '#f97316', angle: 240 },
  { id: 'ai_ml',        label: 'AI & Bedrock',      icon: Brain,     color: '#ec4899', angle: 300 },
];

const CATEGORY_LABELS = {
  instance: 'Instance', queues: 'Queues', agents: 'Agents',
  flows: 'Flows', phone_numbers: 'Phone Numbers', storage_configs: 'Storage',
  routing_profiles: 'Routing Profiles', lex_v2_bots: 'Lex V2 Bots',
  lex_v1_bots: 'Lex V1 Bots', q_assistants: 'Q in Connect',
  lambda_associations: 'Connect Lambdas', lambda_functions: 'Lambda Functions',
  s3_buckets: 'S3 Buckets', kinesis_streams: 'Kinesis Streams',
  firehose_streams: 'Firehose', athena_workgroups: 'Athena WGs',
  athena_databases: 'Athena DBs', glue_databases: 'Glue DBs',
  log_groups: 'Log Groups', bedrock_models: 'Bedrock Models',
  knowledge_bases: 'Knowledge Bases', account: 'Account',
};

/* ── Injected CSS animations ───────────────────────────────────────────────── */
const ANIM_CSS = `
@keyframes radar-spin {
  to { transform: rotate(360deg); }
}
@keyframes ring-ping {
  0%   { transform: scale(0.85); opacity: 0.7; }
  100% { transform: scale(1.8);  opacity: 0; }
}
@keyframes particle-fly {
  0%   { opacity: 1; transform: translate(0,0) scale(1.2); }
  100% { opacity: 0; transform: translate(var(--px), var(--py)) scale(0); }
}
@keyframes item-pop {
  0%   { opacity: 0; transform: translateY(8px) scale(0.95); }
  60%  { opacity: 1; transform: translateY(-2px) scale(1.02); }
  100% { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes log-slide {
  from { opacity: 0; transform: translateX(-12px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes grid-drift {
  0%, 100% { opacity: 0.04; }
  50%       { opacity: 0.09; }
}
@keyframes title-glow {
  0%, 100% { text-shadow: 0 0 12px rgba(139,92,246,0.5); }
  50%       { text-shadow: 0 0 32px rgba(139,92,246,0.9), 0 0 64px rgba(59,130,246,0.4); }
}
@keyframes complete-burst {
  0%   { transform: scale(0.8);  opacity: 0; }
  50%  { transform: scale(1.08); opacity: 1; }
  100% { transform: scale(1);    opacity: 1; }
}
@keyframes fade-out-splash {
  0%   { opacity: 1; }
  100% { opacity: 0; pointer-events: none; }
}
.radar-spin    { animation: radar-spin 3s linear infinite; transform-origin: center; }
.ring-ping-1   { animation: ring-ping 2.4s ease-out 0s   infinite; }
.ring-ping-2   { animation: ring-ping 2.4s ease-out 0.8s infinite; }
.ring-ping-3   { animation: ring-ping 2.4s ease-out 1.6s infinite; }
.item-pop      { animation: item-pop 0.35s ease-out forwards; }
.log-slide     { animation: log-slide 0.25s ease-out forwards; }
.grid-drift    { animation: grid-drift 4s ease-in-out infinite; }
.title-glow    { animation: title-glow 3s ease-in-out infinite; }
.complete-burst { animation: complete-burst 0.6s cubic-bezier(0.34,1.56,0.64,1) forwards; }
.fade-out-splash { animation: fade-out-splash 0.8s ease-out forwards; }
`;

/* ── Particle component ─────────────────────────────────────────────────────── */
function Particle({ id, color, tx, ty, onDone }) {
  useEffect(() => {
    const t = setTimeout(onDone, 900);
    return () => clearTimeout(t);
  }, [onDone]);

  return (
    <div
      key={id}
      style={{
        position: 'absolute', top: '50%', left: '50%',
        width: 8, height: 8, borderRadius: '50%',
        backgroundColor: color, boxShadow: `0 0 6px ${color}`,
        '--px': `${tx}px`, '--py': `${ty}px`,
        animation: 'particle-fly 0.9s ease-out forwards',
        pointerEvents: 'none', zIndex: 20,
      }}
    />
  );
}

/* ── Phase card ─────────────────────────────────────────────────────────────── */
function PhaseCard({ phase, status, count, active, cardRef }) {
  const Icon = phase.icon;
  const isDone  = status === 'complete';
  const isActive = active;

  return (
    <div
      ref={cardRef}
      className="item-pop"
      style={{
        background: isDone
          ? `linear-gradient(135deg, ${phase.color}22, ${phase.color}11)`
          : isActive
            ? `linear-gradient(135deg, ${phase.color}18, transparent)`
            : 'rgba(255,255,255,0.03)',
        border: `1px solid ${isDone ? phase.color + '66' : isActive ? phase.color + '44' : 'rgba(255,255,255,0.08)'}`,
        borderRadius: 12,
        padding: '12px 14px',
        display: 'flex', alignItems: 'center', gap: 10,
        transition: 'all 0.4s ease',
        boxShadow: isActive ? `0 0 16px ${phase.color}33` : 'none',
      }}
    >
      <div style={{
        width: 36, height: 36, borderRadius: 8,
        background: isDone ? `${phase.color}33` : isActive ? `${phase.color}22` : 'rgba(255,255,255,0.06)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        border: `1px solid ${isDone || isActive ? phase.color + '44' : 'transparent'}`,
        transition: 'all 0.3s',
      }}>
        {isDone
          ? <CheckCircle2 size={18} color={phase.color} />
          : <Icon size={18} color={isActive ? phase.color : '#6b7280'} />
        }
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: isDone ? phase.color : isActive ? '#e2e8f0' : '#6b7280', lineHeight: 1.2 }}>
          {phase.label}
        </div>
        {count > 0 && (
          <div style={{ fontSize: 11, color: isDone ? phase.color + 'cc' : '#9ca3af', marginTop: 2 }}>
            {count} resource{count !== 1 ? 's' : ''} found
          </div>
        )}
        {isActive && count === 0 && (
          <div style={{ fontSize: 11, color: phase.color + 'aa', marginTop: 2 }}>scanning…</div>
        )}
      </div>
      {count > 0 && (
        <div style={{
          fontSize: 14, fontWeight: 700, color: phase.color,
          minWidth: 28, textAlign: 'right',
        }}>
          {count}
        </div>
      )}
    </div>
  );
}

/* ── Main component ─────────────────────────────────────────────────────────── */
export default function StartupScan({ onComplete }) {
  const [phaseStates, setPhaseStates]  = useState({});   // phase_id → {status,count}
  const [log, setLog]                  = useState([]);
  const [progress, setProgress]        = useState(0);
  const [currentPhaseId, setPhaseId]   = useState('');
  const [message, setMessage]          = useState('Initialising resource discovery…');
  const [totalFound, setTotal]         = useState(0);
  const [found, setFound]              = useState({});
  const [scanDone, setScanDone]        = useState(false);
  const [particles, setParticles]      = useState([]);
  const [isLeader, setIsLeader]        = useState(true);
  const [completing, setCompleting]    = useState(false);
  const [fadingOut, setFadingOut]      = useState(false);

  const logRef      = useRef(null);
  const radarRef    = useRef(null);
  const cardRefs    = useRef({});   // phase_id → DOM node
  const radarCenter = useRef({ x: 0, y: 0 });
  const nextPid     = useRef(0);

  /* ── SSE connection ── */
  useEffect(() => {
    const es = new EventSource('/api/startup-scan/stream');

    es.onmessage = (evt) => {
      let data;
      try { data = JSON.parse(evt.data); } catch { return; }

      const { type, phase_id, phase_label, phase_index, progress: prog,
              total_found, found: foundMap, message: msg, log_line,
              category, name, duration_sec } = data;

      if (prog !== undefined) setProgress(prog);
      if (total_found !== undefined) setTotal(total_found);
      if (foundMap) setFound(foundMap);
      if (msg) setMessage(msg);

      if (log_line) {
        setLog(prev => [...prev.slice(-120), { text: log_line, ts: Date.now() }]);
      }

      switch (type) {
        case 'scan_skipped':
        case 'scan_complete':
          setScanDone(true);
          setCompleting(true);
          setProgress(1);
          setMessage(duration_sec
            ? `Discovery complete — ${total_found ?? 0} resources in ${duration_sec}s`
            : 'Resources already discovered — loading dashboard…');
          setTimeout(() => {
            setFadingOut(true);
            setTimeout(onComplete, 800);
          }, 2000);
          break;

        case 'already_complete': {
          // Scan finished before browser loaded — populate all phases as complete
          const categoriesByPhase = {
            connect_core:  ['instance','queues','agents','routing_profiles','flows','phone_numbers','storage_configs'],
            bots_ai:       ['lex_v2_bots','lex_v1_bots','q_assistants','lambda_associations'],
            lambda_fns:    ['lambda_functions'],
            data_storage:  ['s3_buckets','kinesis_streams','firehose_streams'],
            analytics:     ['athena_workgroups','athena_databases','glue_databases','log_groups'],
            ai_ml:         ['bedrock_models','knowledge_bases','qconn_knowledge_bases'],
          };
          const fullFound = foundMap || {};
          setFound(fullFound);
          setTotal(total_found ?? 0);
          setProgress(1);
          setPhaseStates(Object.fromEntries(
            Object.entries(categoriesByPhase).map(([pid, cats]) => [
              pid,
              { status: 'complete', count: cats.reduce((s, c) => s + (fullFound[c] ?? 0), 0) },
            ])
          ));
          setMessage(`Resources already discovered — ${total_found ?? 0} found. Loading dashboard…`);
          setScanDone(true);
          setCompleting(true);
          setTimeout(() => {
            setFadingOut(true);
            setTimeout(onComplete, 800);
          }, 2500);
          break;
        }

        case 'phase_start':
          setPhaseId(phase_id);
          setPhaseStates(prev => ({
            ...prev,
            [phase_id]: { status: 'active', count: prev[phase_id]?.count ?? 0 },
          }));
          break;

        case 'phase_complete':
          setPhaseStates(prev => ({
            ...prev,
            [phase_id]: { status: 'complete', count: prev[phase_id]?.count ?? 0 },
          }));
          break;

        case 'item_found':
          if (phase_id) {
            setPhaseStates(prev => ({
              ...prev,
              [phase_id]: {
                status: prev[phase_id]?.status ?? 'active',
                count: (prev[phase_id]?.count ?? 0) + 1,
              },
            }));
            // Spawn particle toward the phase card
            spawnParticle(phase_id);
          }
          break;

        case 'scan_error':
          setMessage(`Error: ${data.message}`);
          break;

        case 'progress_update':
          // message already handled above
          break;

        default:
          break;
      }
    };

    es.onerror = () => {
      // Fall back to polling
      es.close();
      pollStatus();
    };

    return () => es.close();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Polling fallback ── */
  const pollStatus = useCallback(() => {
    const iv = setInterval(async () => {
      try {
        const r = await fetch('/api/startup-scan/status');
        const d = await r.json();
        if (d.progress !== undefined) setProgress(d.progress);
        if (d.total_found !== undefined) setTotal(d.total_found);
        if (d.found) setFound(d.found);
        if (d.message) setMessage(d.message);
        if (d.log?.length) setLog(d.log.map(t => ({ text: t, ts: Date.now() })));
        if (d.complete || d.mock_mode) {
          clearInterval(iv);
          setScanDone(true);
          setCompleting(true);
          setTimeout(() => { setFadingOut(true); setTimeout(onComplete, 800); }, 2000);
        }
      } catch { /* ignore */ }
    }, 1500);
  }, [onComplete]);

  /* ── Auto-scroll log ── */
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  /* ── Track radar center for particles ── */
  useEffect(() => {
    const update = () => {
      if (radarRef.current) {
        const rect = radarRef.current.getBoundingClientRect();
        radarCenter.current = {
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        };
      }
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  /* ── Particle spawner ── */
  const spawnParticle = useCallback((phase_id) => {
    const phase = PHASES.find(p => p.id === phase_id);
    if (!phase) return;

    // Calculate direction from radar center to card center
    const cardEl = cardRefs.current[phase_id];
    let tx = 0, ty = 0;
    if (cardEl) {
      const rect = cardEl.getBoundingClientRect();
      tx = (rect.left + rect.width / 2) - radarCenter.current.x;
      ty = (rect.top + rect.height / 2) - radarCenter.current.y;
      // Scale down so particle doesn't overshoot too much
      const dist = Math.sqrt(tx * tx + ty * ty);
      if (dist > 0) { tx = (tx / dist) * Math.min(dist, 220); ty = (ty / dist) * Math.min(dist, 220); }
    } else {
      // Fallback: scatter by angle
      const rad = (phase.angle * Math.PI) / 180;
      tx = Math.cos(rad) * 140; ty = Math.sin(rad) * 140;
    }

    const pid = nextPid.current++;
    setParticles(prev => [
      ...prev.slice(-30),
      { id: pid, color: phase.color, tx, ty },
    ]);
  }, []);

  const removeParticle = useCallback((pid) => {
    setParticles(prev => prev.filter(p => p.id !== pid));
  }, []);

  /* ── Compute per-phase counts from found map ── */
  const phaseCountFromFound = (phase_id) => {
    const categoriesByPhase = {
      connect_core:  ['instance','queues','agents','routing_profiles','flows','phone_numbers','storage_configs'],
      bots_ai:       ['lex_v2_bots','lex_v1_bots','q_assistants','lambda_associations'],
      lambda_fns:    ['lambda_functions'],
      data_storage:  ['s3_buckets','kinesis_streams','firehose_streams'],
      analytics:     ['athena_workgroups','athena_databases','glue_databases','log_groups'],
      ai_ml:         ['bedrock_models','knowledge_bases','qconn_knowledge_bases'],
      security:      ['account'],
    };
    return (categoriesByPhase[phase_id] || []).reduce((s, cat) => s + (found[cat] ?? 0), 0);
  };

  /* ── Inject CSS ── */
  useEffect(() => {
    const el = document.createElement('style');
    el.textContent = ANIM_CSS;
    document.head.appendChild(el);
    return () => el.remove();
  }, []);

  /* ── Render ── */
  const progressPct = Math.round(progress * 100);

  return (
    <div
      className={fadingOut ? 'fade-out-splash' : ''}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'linear-gradient(135deg, #050a14 0%, #0a0f1e 50%, #0d0d1f 100%)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}
    >
      {/* Animated grid background */}
      <div className="grid-drift" style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        backgroundImage: `
          linear-gradient(rgba(59,130,246,0.06) 1px, transparent 1px),
          linear-gradient(90deg, rgba(59,130,246,0.06) 1px, transparent 1px)
        `,
        backgroundSize: '40px 40px',
      }} />

      {/* Header */}
      <div style={{
        padding: '24px 40px 16px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        flexShrink: 0, display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 10,
          background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 0 20px rgba(139,92,246,0.4)',
        }}>
          <Wifi size={20} color="#fff" />
        </div>
        <div>
          <h1 className="title-glow" style={{
            fontSize: 20, fontWeight: 700, color: '#e2e8f0', margin: 0,
            letterSpacing: '-0.02em',
          }}>
            Amazon Connect Analytics
          </h1>
          <p style={{ fontSize: 12, color: '#6b7280', margin: 0, marginTop: 2 }}>
            {isLeader ? 'First-time resource discovery' : 'Waiting for leader instance…'}
          </p>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={{ fontSize: 26, fontWeight: 800, color: '#e2e8f0', lineHeight: 1 }}>
            {totalFound}
          </div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>resources found</div>
        </div>
      </div>

      {/* Main content */}
      <div style={{
        flex: 1, display: 'flex', gap: 0, overflow: 'hidden', position: 'relative',
      }}>

        {/* ── Left: terminal log ── */}
        <div style={{
          width: 320, flexShrink: 0,
          borderRight: '1px solid rgba(255,255,255,0.06)',
          display: 'flex', flexDirection: 'column',
          background: 'rgba(0,0,0,0.3)',
        }}>
          <div style={{
            padding: '10px 16px',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            fontSize: 11, color: '#4b5563', fontFamily: 'monospace',
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#10b981',
                          boxShadow: '0 0 6px #10b981', animation: 'ring-ping-1 1.5s ease-out infinite' }} />
            DISCOVERY LOG
          </div>
          <div
            ref={logRef}
            style={{
              flex: 1, overflowY: 'auto', padding: '12px 16px',
              fontFamily: "'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
              fontSize: 11.5, lineHeight: 1.7,
            }}
          >
            {log.length === 0 && (
              <div style={{ color: '#374151', fontStyle: 'italic' }}>
                Waiting for scan events…
              </div>
            )}
            {log.map((entry, i) => {
              const isCheck = entry.text.startsWith('✅');
              const isDot   = entry.text.startsWith('  ');
              return (
                <div
                  key={i}
                  className="log-slide"
                  style={{
                    color: isCheck ? '#10b981' : isDot ? '#9ca3af' : '#60a5fa',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                    opacity: i < log.length - 20 ? 0.5 : 1,
                  }}
                >
                  {entry.text}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Center: radar + particles ── */}
        <div
          style={{
            flex: 1, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            position: 'relative',
          }}
        >
          {/* Particles live here (positioned relative to radar center) */}
          <div ref={radarRef} style={{ position: 'relative', width: 260, height: 260 }}>
            {/* Ping rings */}
            {['ring-ping-1', 'ring-ping-2', 'ring-ping-3'].map((cls, i) => (
              <div key={i} className={cls} style={{
                position: 'absolute', inset: -i * 18,
                borderRadius: '50%',
                border: `1px solid rgba(59,130,246,${0.25 - i * 0.06})`,
                pointerEvents: 'none',
              }} />
            ))}

            {/* Static background circle */}
            <div style={{
              position: 'absolute', inset: 0, borderRadius: '50%',
              background: 'radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)',
              border: '1px solid rgba(59,130,246,0.2)',
            }} />

            {/* Radar sweep arm */}
            {!scanDone && (
              <div className="radar-spin" style={{
                position: 'absolute', inset: 0, borderRadius: '50%',
                background: `conic-gradient(
                  from 0deg,
                  rgba(59,130,246,0) 0deg,
                  rgba(59,130,246,0.35) 60deg,
                  rgba(59,130,246,0) 61deg
                )`,
              }} />
            )}

            {/* Center content */}
            {scanDone ? (
              <div className="complete-burst" style={{
                position: 'absolute', inset: 0, borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(16,185,129,0.15) 0%, transparent 70%)',
                border: '2px solid #10b981',
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
              }}>
                <CheckCircle2 size={56} color="#10b981" />
                <div style={{ fontSize: 13, color: '#10b981', marginTop: 8, fontWeight: 600 }}>
                  Complete
                </div>
              </div>
            ) : (
              <div style={{
                position: 'absolute', inset: 0, borderRadius: '50%',
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                pointerEvents: 'none',
              }}>
                <div style={{
                  fontSize: 52, fontWeight: 800,
                  background: 'linear-gradient(135deg, #60a5fa, #a78bfa)',
                  WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                  lineHeight: 1,
                }}>
                  {totalFound}
                </div>
                <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                  resources
                </div>
                <div style={{
                  fontSize: 10, color: '#4b5563', marginTop: 8,
                  fontFamily: 'monospace', letterSpacing: '0.08em',
                }}>
                  {progressPct}%
                </div>
              </div>
            )}

            {/* Particles (rendered relative to radar center) */}
            {particles.map(p => (
              <Particle key={p.id} {...p} onDone={() => removeParticle(p.id)} />
            ))}
          </div>

          {/* Current action message */}
          <div style={{
            marginTop: 28, textAlign: 'center',
            maxWidth: 340, padding: '0 20px',
          }}>
            <div style={{
              fontSize: 13, color: '#9ca3af', lineHeight: 1.5,
              minHeight: 40,
            }}>
              {message}
            </div>
          </div>

          {/* Category badge cloud */}
          <div style={{
            marginTop: 20, display: 'flex', flexWrap: 'wrap',
            gap: 6, justifyContent: 'center', maxWidth: 380, padding: '0 16px',
          }}>
            {Object.entries(found).filter(([, v]) => v > 0).map(([cat, count]) => (
              <div key={cat} className="item-pop" style={{
                fontSize: 10.5, color: '#9ca3af',
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 20, padding: '3px 10px',
                display: 'flex', alignItems: 'center', gap: 5,
              }}>
                <Database size={9} color="#6b7280" />
                <span>{CATEGORY_LABELS[cat] ?? cat}</span>
                <span style={{ color: '#60a5fa', fontWeight: 700 }}>{count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Right: phase cards ── */}
        <div style={{
          width: 280, flexShrink: 0, padding: '20px 16px',
          borderLeft: '1px solid rgba(255,255,255,0.06)',
          display: 'flex', flexDirection: 'column', gap: 8,
          overflowY: 'auto',
        }}>
          <div style={{ fontSize: 11, color: '#4b5563', marginBottom: 4,
                        textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Scan Phases
          </div>
          {PHASES.map(phase => {
            const st = phaseStates[phase.id] ?? {};
            const count = phaseCountFromFound(phase.id) || st.count || 0;
            return (
              <PhaseCard
                key={phase.id}
                phase={phase}
                status={st.status ?? 'pending'}
                count={count}
                active={currentPhaseId === phase.id}
                cardRef={el => { cardRefs.current[phase.id] = el; }}
              />
            );
          })}
        </div>
      </div>

      {/* ── Footer progress bar ── */}
      <div style={{
        padding: '16px 40px',
        borderTop: '1px solid rgba(255,255,255,0.06)',
        flexShrink: 0, background: 'rgba(0,0,0,0.2)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{
            flex: 1, height: 4, background: 'rgba(255,255,255,0.08)',
            borderRadius: 2, overflow: 'hidden',
          }}>
            <div style={{
              height: '100%', borderRadius: 2,
              width: `${progressPct}%`,
              background: scanDone
                ? 'linear-gradient(90deg, #10b981, #34d399)'
                : 'linear-gradient(90deg, #3b82f6, #8b5cf6)',
              transition: 'width 0.6s ease, background 0.4s',
              boxShadow: scanDone ? '0 0 8px #10b981' : '0 0 8px rgba(139,92,246,0.6)',
            }} />
          </div>
          <div style={{ fontSize: 12, color: scanDone ? '#10b981' : '#6b7280',
                        fontWeight: 600, minWidth: 40, textAlign: 'right' }}>
            {progressPct}%
          </div>
        </div>
        <div style={{ fontSize: 11, color: '#4b5563', marginTop: 6, textAlign: 'center' }}>
          {scanDone
            ? '✓ Discovery complete — preparing your dashboard…'
            : 'Scanning your AWS environment for Amazon Connect resources…'}
        </div>
      </div>
    </div>
  );
}
