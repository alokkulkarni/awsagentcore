/**
 * SupervisorBargePanel
 *
 * Allows a logged-in supervisor to silently monitor a live voice call and
 * then barge in if intervention is needed.
 *
 * Flow:
 *   1. Supervisor clicks "Connect as Supervisor" → CCP iframe initialises.
 *   2. Supervisor logs in via Connect popup → CCP ready, supervisorId extracted.
 *   3. Supervisor clicks "Start Monitoring" → agent.monitorContact() called via
 *      Connect Streams (primary) or backend MonitorContact API (fallback).
 *   4. Supervisor's CCP rings a MONITOR contact → they accept in the CCP panel.
 *   5. Monitoring state detected → "Barge In" button enabled.
 *   6. Clicking "Barge In" calls monitoringContact.bargeIn() via Streams.
 *   7. "Stop" disconnects the monitoring contact.
 *
 * Requirements:
 *   • VITE_CONNECT_ALIAS env var set.
 *   • Supervisor's Connect security profile must have "Monitor calls" permission.
 *   • Origin must be in Connect Approved Origins.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  AudioLines,
  CheckCircle2,
  EarOff,
  Headphones,
  Loader2,
  Mic,
  MicOff,
  PhoneOff,
  Radio,
  ShieldCheck,
  WifiOff,
} from 'lucide-react';
import { useConnectStreams } from '../hooks/useConnectStreams';
import { monitorContact as monitorContactApi, stopMonitorContact as stopMonitorApi } from '../services/api';

// ── State labels & colours ─────────────────────────────────────────────────────
const STATES = {
  disconnected: { label: 'Not connected',    colour: 'text-slate-600 dark:text-slate-500', bg: 'bg-slate-200/50 dark:bg-slate-800/50 border-slate-300/50 dark:border-slate-700/50' },
  connecting:   { label: 'Connecting CCP…',  colour: 'text-amber-600 dark:text-amber-400',  bg: 'bg-amber-500/10 border-amber-500/30' },
  ccp_ready:    { label: 'CCP ready',         colour: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' },
  initiating:   { label: 'Initiating monitor…', colour: 'text-sky-600 dark:text-sky-400', bg: 'bg-sky-500/10 border-sky-500/30' },
  monitoring:   { label: 'Silent monitoring', colour: 'text-violet-600 dark:text-violet-400', bg: 'bg-violet-500/10 border-violet-500/30' },
  barging:      { label: 'BARGE IN active',   colour: 'text-rose-600 dark:text-rose-400',   bg: 'bg-rose-500/10 border-rose-500/30' },
  error:        { label: 'Error',             colour: 'text-rose-600 dark:text-rose-400',   bg: 'bg-rose-500/10 border-rose-500/30' },
};

export default function SupervisorBargePanel({ contact, openSignal = 0 }) {
  const streams     = useConnectStreams();
  const ccpRef      = useRef(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [err, setErr] = useState(null);
  // Monitoring driven through the backend MonitorContact API rather than a
  // connected CCP — the real UI flow in mock mode, and the initiation path in
  // real mode when the supervisor hasn't embedded their CCP yet.
  const [simState, setSimState] = useState(null); // null | 'monitoring' | 'barging'

  // "Suggest Intervention" (and similar) bump openSignal to pop this panel open
  useEffect(() => {
    if (openSignal > 0) setPanelOpen(true);
  }, [openSignal]);

  // Compute display state from streams (API/simulated monitoring wins when active)
  const displayState = (() => {
    if (streams.monitorState === 'initiating')      return 'initiating';
    if (streams.monitorState === 'monitoring')      return 'monitoring';
    if (streams.monitorState === 'barging')         return 'barging';
    if (simState)                                   return simState;
    if (streams.connecting)                         return 'connecting';
    if (streams.connected)                          return 'ccp_ready';
    return 'disconnected';
  })();

  const { label, colour, bg } = STATES[displayState] || STATES.disconnected;

  // Wire CCP container ref to Streams hook when panel opens
  useEffect(() => {
    if (panelOpen && ccpRef.current) {
      streams.containerRef.current = ccpRef.current;
    }
  }, [panelOpen, streams.containerRef]);

  // Only show for live voice calls.
  // Monitoring requires a human AGENT participant — not available during bot/IVR
  // phase. Declared before handleMonitor: its dependency array reads isBot, and a
  // later const would be in the temporal dead zone (ReferenceError on render).
  const hasAgent   = contact?.escalatedToAgent ||
                     contact?.contactState === 'CONNECTED_TO_AGENT' ||
                     contact?.agentArn;
  const isBot      = contact?.contactState === 'CONNECTED_TO_SYSTEM' && !hasAgent;
  // MonitorContact supports both voice and chat contacts
  const isEligible = contact && !contact.contactTerminal &&
    (contact.channel === 'VOICE' || contact.channel === 'CHAT' || !contact.channel) &&
    contact.contactState !== 'QUEUED';

  // Show panel but disable monitoring when still in bot/IVR phase
  const canMonitor = isEligible && !isBot;

  // ── Actions ──────────────────────────────────────────────────────────────────

  const handleConnect = useCallback(() => {
    if (!streams.ccpAvailable) {
      setErr('VITE_CONNECT_ALIAS is not configured.');
      return;
    }
    setErr(null);
    streams.connect();
  }, [streams]);

  const handleMonitor = useCallback(async () => {
    setErr(null);
    if (!contact?.contactId) { setErr('No contact selected.'); return; }

    // Amazon Connect MonitorContact requires a human agent participant.
    // During CONNECTED_TO_SYSTEM (bot/IVR) phase there is no agent — the API will
    // reject with "No AGENT participant found".  Block early with a clear message.
    if (isBot) {
      setErr('Cannot monitor yet — call is still with the bot/IVR. Wait until it transfers to a human agent.');
      return;
    }

    // Primary: use Connect Streams agent.monitorContact()
    if (streams.connected && streams.supervisorId) {
      try {
        await streams.monitorContact(contact.contactId);
      } catch (e) {
        // Fallback: call backend MonitorContact API
        try {
          await monitorContactApi(contact.contactId, streams.supervisorId, true);
        } catch (e2) {
          setErr(e2?.response?.data?.detail || e2.message || 'Monitor failed');
        }
      }
      return;
    }

    // If streams not connected or no supervisorId, use the backend API.
    // In mock mode this simulates the full monitor → barge flow; in real mode
    // it needs a supervisor ID, so guide the user to connect their CCP.
    try {
      const resp = await monitorContactApi(
        contact.contactId, streams.supervisorId || 'supervisor-dashboard', true,
      );
      if (resp?.mock) {
        setSimState('monitoring');
      } else if (!streams.supervisorId) {
        setErr('Monitoring initiated — accept the ring in your Connect CCP.');
      }
    } catch (e) {
      setErr(streams.supervisorId
        ? (e?.response?.data?.detail || e.message || 'Monitor failed')
        : 'Connect to CCP first so your supervisor ID can be determined.');
    }
  }, [contact, isBot, streams]);

  const handleBargeIn = useCallback(() => {
    setErr(null);
    if (simState === 'monitoring') {
      setSimState('barging');
      return;
    }
    try {
      streams.bargeIn();
    } catch (e) {
      setErr(e.message);
    }
  }, [streams, simState]);

  const handleStop = useCallback(() => {
    setErr(null);
    if (simState) {
      setSimState(null);
      stopMonitorApi(contact.contactId).catch(() => {});
      return;
    }
    streams.stopMonitoring();
  }, [streams, simState, contact]);

  const handleDisconnect = useCallback(() => {
    streams.disconnect();
    setPanelOpen(false);
    setErr(null);
  }, [streams]);

  if (!isEligible) return null;

  return (
    <div className="space-y-3">
      {/* Section header + toggle */}
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-500 flex items-center gap-1.5">
          <Radio size={10} />
          Supervisor Monitor / Barge-In
        </p>
        <button
          type="button"
          onClick={() => setPanelOpen((v) => !v)}
          className="text-[10px] text-slate-600 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition"
        >
          {panelOpen ? 'hide ▲' : 'show ▼'}
        </button>
      </div>

      {!panelOpen && (
        // Collapsed — show status pill only
        <div className={`flex items-center gap-2 rounded-xl border px-3 py-2 ${bg}`}>
          <StatusIcon state={displayState} />
          <span className={`text-[11px] font-medium ${colour}`}>{label}</span>
          {displayState === 'disconnected' && (
            <button
              type="button"
              onClick={() => { setPanelOpen(true); }}
              className="ml-auto text-[10px] text-connect-700 dark:text-connect-400 hover:text-connect-500 dark:hover:text-connect-400 transition"
            >
              Open →
            </button>
          )}
        </div>
      )}

      {panelOpen && (
        <div className={`rounded-xl border p-3 space-y-3 ${bg}`}>
          {/* Status row */}
          <div className="flex items-center gap-2">
            <StatusIcon state={displayState} />
            <span className={`text-[11px] font-semibold ${colour}`}>{label}</span>
            {streams.supervisorId && (
              <span className="ml-auto text-[9px] font-mono text-slate-600 dark:text-slate-500 truncate max-w-[120px]"
                    title={`Supervisor ID: ${streams.supervisorId}`}>
                …{streams.supervisorId.slice(-8)}
              </span>
            )}
          </div>

          {/* Error */}
          {err && (
            <div className="flex items-start gap-2 rounded-lg bg-rose-500/10 border border-rose-500/30 px-2.5 py-2 text-[11px] text-rose-600 dark:text-rose-300">
              <AlertCircle size={12} className="shrink-0 mt-0.5" />
              {err}
            </div>
          )}

          {/* Instructions */}
          {isBot && (
            <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 border border-amber-500/30 px-2.5 py-2 text-[11px] text-amber-600 dark:text-amber-300">
              <Radio size={12} className="shrink-0 mt-0.5" />
              <span>
                Call is with the <strong>Bot / IVR</strong> — no human agent yet.
                Monitoring will be available automatically once the call transfers to an agent.
              </span>
            </div>
          )}
          {displayState === 'ccp_ready' && !isBot && (
            <p className="text-[10px] text-slate-600 dark:text-slate-500 leading-relaxed">
              Your CCP is connected. Click <strong className="text-slate-700 dark:text-slate-300">Start Monitoring</strong> to silently listen to this call.
              Your supervisor CCP will ring — accept it to begin.
            </p>
          )}
          {displayState === 'monitoring' && (
            <p className="text-[10px] text-violet-600 dark:text-violet-300 leading-relaxed">
              You are <strong>silently monitoring</strong> this call. The customer and agent cannot hear you.
              Click <strong>Barge In</strong> to join the conversation.
            </p>
          )}
          {displayState === 'barging' && (
            <p className="text-[10px] text-rose-600 dark:text-rose-300 font-medium leading-relaxed">
              You are <strong>LIVE in the call</strong>. Both customer and agent can hear you.
            </p>
          )}

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2">
            {displayState === 'disconnected' && (
              <button
                type="button"
                onClick={handleConnect}
                disabled={!streams.ccpAvailable}
                className="inline-flex items-center gap-1.5 rounded-xl bg-connect-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-connect-700 disabled:opacity-40 transition"
              >
                <Headphones size={11} />
                Connect as Supervisor
              </button>
            )}

            {(displayState === 'ccp_ready' || displayState === 'disconnected') && (
              <button
                type="button"
                onClick={handleMonitor}
                disabled={isBot}
                title={isBot ? 'Waiting for agent — call is still with bot/IVR' : 'Silently monitor this contact'}
                className="inline-flex items-center gap-1.5 rounded-xl bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                <EarOff size={11} />
                {isBot ? 'Waiting for Agent…' : 'Start Monitoring'}
              </button>
            )}

            {displayState === 'initiating' && (
              <button type="button" disabled
                className="inline-flex items-center gap-1.5 rounded-xl bg-sky-600/50 px-3 py-1.5 text-xs font-medium text-sky-200 cursor-not-allowed">
                <Loader2 size={11} className="animate-spin" />
                Waiting for CCP ring…
              </button>
            )}

            {displayState === 'monitoring' && (
              <>
                <button
                  type="button"
                  onClick={handleBargeIn}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-rose-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-rose-700 transition animate-pulse"
                >
                  <Mic size={11} />
                  Barge In
                </button>
                <button
                  type="button"
                  onClick={handleStop}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 dark:border-slate-600 bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
                >
                  <PhoneOff size={11} />
                  Stop Monitoring
                </button>
              </>
            )}

            {displayState === 'barging' && (
              <button
                type="button"
                onClick={handleStop}
                className="inline-flex items-center gap-1.5 rounded-xl bg-rose-700 px-3 py-1.5 text-xs font-bold text-white hover:bg-rose-800 transition"
              >
                <MicOff size={11} />
                Leave Call
              </button>
            )}

            {streams.connected && displayState !== 'barging' && displayState !== 'monitoring' && (
              <button
                type="button"
                onClick={handleDisconnect}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-slate-200/50 dark:bg-slate-800/50 px-3 py-1.5 text-xs text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 transition"
              >
                <WifiOff size={11} />
                Disconnect CCP
              </button>
            )}
          </div>

          {/* Hidden CCP iframe — Streams mounts the CCP here */}
          <div
            ref={ccpRef}
            className="overflow-hidden rounded-xl border border-slate-300/50 dark:border-slate-700/50 bg-white dark:bg-slate-950"
            style={{
              width: '100%',
              height: streams.connected ? '380px' : '0px',
              transition: 'height 0.3s ease',
            }}
          />

          {!streams.ccpAvailable && (
            <p className="text-[10px] text-rose-600 dark:text-rose-400">
              VITE_CONNECT_ALIAS is not set. Rebuild the frontend with the correct env var.
            </p>
          )}

          {/* Capability note */}
          <p className="text-[9px] text-slate-600 leading-relaxed">
            Requires <em>Monitor calls</em> permission in your Connect security profile.
            Barge-in requires <em>Barge calls</em> permission.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Status icon helper ────────────────────────────────────────────────────────
function StatusIcon({ state }) {
  switch (state) {
    case 'disconnected': return <WifiOff    size={12} className="text-slate-600" />;
    case 'connecting':   return <Loader2    size={12} className="text-amber-600 dark:text-amber-400 animate-spin" />;
    case 'ccp_ready':    return <ShieldCheck size={12} className="text-emerald-600 dark:text-emerald-400" />;
    case 'initiating':   return <Loader2    size={12} className="text-sky-600 dark:text-sky-400 animate-spin" />;
    case 'monitoring':   return <AudioLines  size={12} className="text-violet-600 dark:text-violet-400" />;
    case 'barging':      return <Mic        size={12} className="text-rose-600 dark:text-rose-400" />;
    case 'error':        return <AlertCircle size={12} className="text-rose-600 dark:text-rose-400" />;
    default:             return <CheckCircle2 size={12} className="text-slate-600 dark:text-slate-500" />;
  }
}
