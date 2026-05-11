/**
 * useConnectStreams — Amazon Connect Streams SDK integration.
 *
 * Amazon Connect Streams lets a browser observe ALL contacts being processed by
 * Connect (including IVR / bot state) in real time, without any server-side
 * polling.  It works by embedding a hidden Connect CCP iframe that authenticates
 * with the Connect instance and fires JS events for every contact state change.
 *
 * Pre-requisite (one-time admin setup):
 *   Amazon Connect console → Application integrations → Approved origins
 *   Add: http://localhost:5274  (local dev)
 *        https://<your-cloudfront-domain>  (production)
 *
 * VITE_CONNECT_ALIAS env var must be set (e.g. "conversationalbot").
 * The CCP URL is built as: https://{alias}.my.connect.aws/ccp-v2/
 */

import { useCallback, useEffect, useRef, useState } from 'react';

const CCP_ALIAS = import.meta.env.VITE_CONNECT_ALIAS || '';
const CCP_URL   = CCP_ALIAS ? `https://${CCP_ALIAS}.my.connect.aws/ccp-v2/` : '';

/**
 * @typedef {Object} StreamsContact
 * @property {string} contactId
 * @property {string} channel  - "VOICE" | "CHAT"
 * @property {string} state    - Connect contact state name
 * @property {boolean} isBot   - true when contact is in IVR/bot state (no agent)
 * @property {boolean} isAgent - true when an agent is actively connected
 * @property {boolean} isQueue - true when contact is waiting in queue
 * @property {string|null} queueName
 * @property {string|null} agentName
 * @property {string} initiatedAt   - ISO timestamp
 * @property {string} updatedAt     - ISO timestamp
 * @property {string} source        - always "streams"
 */

/**
 * @returns {{
 *   connected: boolean,
 *   connecting: boolean,
 *   error: string|null,
 *   contacts: StreamsContact[],
 *   agentState: string|null,
 *   supervisorId: string|null,       // Connect userId extracted from agent ARN
 *   monitorState: string,            // 'idle'|'initiating'|'monitoring'|'barging'
 *   ccpAvailable: boolean,
 *   connect: () => void,
 *   disconnect: () => void,
 *   monitorContact: (contactId: string) => Promise<void>,
 *   bargeIn: () => void,
 *   stopMonitoring: () => void,
 *   ccpUrl: string,
 * }}
 */
export function useConnectStreams() {
  const containerRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState(null);
  const [contacts, setContacts] = useState([]);
  const [agentState, setAgentState] = useState(null);
  const [supervisorId, setSupervisorId] = useState(null);
  const [monitorState, setMonitorState] = useState('idle'); // idle|initiating|monitoring|barging
  const [sdkLoaded, setSdkLoaded] = useState(false);

  const ccpAvailable = Boolean(CCP_URL);
  const monitoringContactRef = useRef(null); // the active monitoring Contact object
  const agentRef = useRef(null);             // live agent object
  const contactsRef = useRef({});  // contactId → StreamsContact

  const _upsert = useCallback((patch) => {
    contactsRef.current[patch.contactId] = {
      ...(contactsRef.current[patch.contactId] || {}),
      ...patch,
      updatedAt: new Date().toISOString(),
      source: 'streams',
    };
    setContacts(Object.values(contactsRef.current));
  }, []);

  const _remove = useCallback((contactId) => {
    delete contactsRef.current[contactId];
    setContacts(Object.values(contactsRef.current));
  }, []);

  // Lazy-load the amazon-connect-streams UMD library via a <script> tag.
  // We cannot use import() because Vite statically analyses dynamic imports and
  // amazon-connect-streams is a legacy browser UMD bundle (not an ES module).
  // The postinstall script copies it to public/connect-streams.js so Vite
  // serves it as a plain static file.
  useEffect(() => {
    if (window.connect) { setSdkLoaded(true); return; }

    const existing = document.getElementById('connect-streams-sdk');
    if (existing) {
      // Script tag already injected by a prior mount — wait for it
      existing.addEventListener('load', () => setSdkLoaded(true), { once: true });
      existing.addEventListener('error', () =>
        setError('Failed to load Connect Streams SDK (script load error)'), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.id  = 'connect-streams-sdk';
    script.src = '/connect-streams.js';   // served from public/ via postinstall copy
    script.async = true;
    script.onload  = () => setSdkLoaded(true);
    script.onerror = () => setError('Failed to load Connect Streams SDK. Make sure /connect-streams.js is served.');
    document.head.appendChild(script);
  }, []);

  const connect = useCallback(() => {
    if (!ccpAvailable) {
      setError('CONNECT_ALIAS is not configured. Set VITE_CONNECT_ALIAS (your Connect instance alias) and rebuild.');
      return;
    }
    if (!sdkLoaded || !window.connect) {
      setError('Connect Streams SDK is not loaded yet. Please wait a moment and try again.');
      return;
    }
    if (!containerRef.current) {
      setError('CCP container element is not mounted.');
      return;
    }
    if (connecting || connected) return;

    setConnecting(true);
    setError(null);

    try {
      window.connect.core.initCCP(containerRef.current, {
        ccpUrl: CCP_URL,
        loginPopup: true,           // open Connect login in a popup
        loginPopupAutoClose: true,
        softphone: { allowFramedSoftphone: true },
        // Streams will reject requests from origins not in Approved Origins in the Connect console
      });

      window.connect.core.onInitialized(() => {
        setConnected(true);
        setConnecting(false);
        setError(null);
      });

      // ── Agent state ───────────────────────────────────────────────────────
      window.connect.agent((agent) => {
        agentRef.current = agent;
        const refresh = () => setAgentState(agent.getState()?.name || null);
        refresh();
        agent.onStateChange(refresh);
        agent.onRefresh(refresh);

        // Extract supervisorId (Connect userId) from agent ARN
        // ARN format: arn:aws:connect:region:account:instance/{instanceId}/agent/{agentId}
        try {
          const arn = agent.getConfiguration?.()?.agentARN;
          if (arn) {
            const id = arn.split('/').pop();
            if (id) setSupervisorId(id);
          }
        } catch { /* ignore */ }
      });

      // ── Contact events ────────────────────────────────────────────────────
      window.connect.contact((contact) => {
        const cid = contact.getContactId();

        const _read = () => {
          const stateName = contact.getStatus()?.name || 'UNKNOWN';
          const channel   = contact.getChannel?.() || 'VOICE';
          const queue     = contact.getQueue?.();
          const conns     = contact.getConnections?.() || [];
          const agentConn = conns.find((c) => c.getType?.() === window.connect.ConnectionType.AGENT);
          const isAgent   = Boolean(agentConn && agentConn.isActive?.());
          const isQueue   = stateName === 'QUEUED' || stateName === 'PENDING_BUSY';
          const isBot     = !isAgent && !isQueue;  // in IVR or bot

          _upsert({
            contactId: cid,
            channel,
            state: stateName,
            isBot,
            isQueue,
            isAgent,
            queueName: queue?.name || null,
            agentName: isAgent ? (agentConn.getEndpoint?.()?.name || null) : null,
            initiatedAt: contact.getStatusStartTimestamp?.()?.toISOString?.() || new Date().toISOString(),
          });
        };

        _read();
        contact.onRefresh(_read);
        contact.onConnected(_read);
        contact.onAccepted(_read);
        contact.onPending(_read);
        contact.onEnded(() => _remove(cid));
        contact.onDestroy(() => _remove(cid));

        // Detect if this is a supervisor monitoring contact
        try {
          const cType = contact.getType?.();
          const isMonitoring = cType === (window.connect?.ContactType?.MONITORING || 'monitoring');
          if (isMonitoring) {
            monitoringContactRef.current = contact;
            setMonitorState('monitoring');
            contact.onEnded(() => {
              if (monitoringContactRef.current === contact) {
                monitoringContactRef.current = null;
                setMonitorState('idle');
              }
            });
            contact.onDestroy(() => {
              if (monitoringContactRef.current === contact) {
                monitoringContactRef.current = null;
                setMonitorState('idle');
              }
            });
          }
        } catch { /* ignore */ }
      });

    } catch (e) {
      setConnecting(false);
      setError(`Failed to initialize CCP: ${e.message}`);
    }
  }, [ccpAvailable, sdkLoaded, connecting, connected, _upsert, _remove]);

  const disconnect = useCallback(() => {
    try { window.connect?.core?.terminate?.(); } catch { /* ignore */ }
    setConnected(false);
    setConnecting(false);
    contactsRef.current = {};
    setContacts([]);
    setAgentState(null);
    setSupervisorId(null);
    setMonitorState('idle');
    monitoringContactRef.current = null;
    agentRef.current = null;
  }, []);

  // ── Supervisor: initiate silent monitor → barge on a live contact ───────────

  const monitorContact = useCallback((contactId) => {
    return new Promise((resolve, reject) => {
      const agent = agentRef.current;
      if (!agent) { reject(new Error('CCP not connected')); return; }
      setMonitorState('initiating');
      try {
        agent.monitorContact({
          contactId,
          success: () => resolve(),
          failure: (e) => {
            setMonitorState('idle');
            reject(new Error(e?.message || 'Monitor initiation failed'));
          },
        });
      } catch (e) {
        setMonitorState('idle');
        reject(e);
      }
    });
  }, []);

  const bargeIn = useCallback(() => {
    const mc = monitoringContactRef.current;
    if (!mc) throw new Error('No active monitoring contact');
    try {
      mc.bargeIn?.();
      setMonitorState('barging');
    } catch (e) {
      throw new Error(`Barge-in failed: ${e.message}`);
    }
  }, []);

  const stopMonitoring = useCallback(() => {
    const mc = monitoringContactRef.current;
    if (mc) {
      try { mc.getAgentConnection?.()?.destroy?.(); } catch { /* ignore */ }
    }
    monitoringContactRef.current = null;
    setMonitorState('idle');
  }, []);

  // Expose the hidden container div ref — caller must attach to a real DOM element
  return {
    containerRef,
    connected,
    connecting,
    error,
    contacts,
    agentState,
    supervisorId,
    monitorState,
    ccpAvailable,
    connect,
    disconnect,
    monitorContact,
    bargeIn,
    stopMonitoring,
    ccpUrl: CCP_URL,
  };
}
