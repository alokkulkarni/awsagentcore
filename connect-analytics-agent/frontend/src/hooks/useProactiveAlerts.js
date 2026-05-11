/**
 * useProactiveAlerts — background monitoring hook for the supervisor dashboard.
 *
 * Polls /metrics and /live-contacts every 30 seconds, detects operational anomalies,
 * and emits typed alerts. For CRITICAL alerts it automatically queries the AI agent
 * (rate-limited to once per 5 minutes per alert type) for a supervisor recommendation.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getMetrics, getLiveContacts, queryAgent } from '../services/api';

const POLL_MS          = 30_000;       // how often we check
const AI_COOLDOWN_MS   = 5 * 60_000;  // min gap between AI queries per alert type
const AI_SESSION_ID    = 'proactive-monitor-internal';

// ── thresholds ─────────────────────────────────────────────────────────────────
const THRESHOLDS = {
  QUEUE_HIGH_WARN:    5,    // contacts_in_queue > N → warning
  QUEUE_HIGH_CRIT:   10,   // contacts_in_queue > N → critical
  LONG_WAIT_WARN:   300,   // oldest contact > 5 min → warning
  LONG_WAIT_CRIT:   600,   // oldest contact > 10 min → critical
  LONG_CALL_WARN:   900,   // any active call > 15 min → warning
  BOT_STUCK_WARN:   600,   // bot session > 10 min without escalation → warning
};

// ── helpers ────────────────────────────────────────────────────────────────────

/** Parse "HH:MM:SS" or a raw number into total seconds. */
function parseAgeSeconds(v) {
  if (!v) return 0;
  if (typeof v === 'number') return v;
  const parts = String(v).split(':');
  if (parts.length === 3) return +parts[0] * 3600 + +parts[1] * 60 + +parts[2];
  if (parts.length === 2) return +parts[0] * 60 + +parts[1];
  return parseFloat(v) || 0;
}

function elapsedSeconds(iso) {
  if (!iso) return 0;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
}

function buildAiQuery(alert, metrics) {
  const queueCount  = metrics.contacts_in_queue ?? '?';
  const agentsAvail = metrics.agents_available  ?? '?';
  const agentsOnline = metrics.agents_online    ?? '?';
  const oldestWait  = metrics.oldest_contact_age ?? '?';
  return (
    `SUPERVISOR ALERT — ${alert.title}\n` +
    `Current metrics: ${agentsOnline} agents online, ${agentsAvail} available, ` +
    `${queueCount} contacts in queue, oldest wait: ${oldestWait}.\n` +
    `${alert.message}\n\n` +
    `What should the contact-centre supervisor do right now? ` +
    `Provide a concise, actionable recommendation in 2–3 sentences.`
  );
}

// ── hook ───────────────────────────────────────────────────────────────────────

export default function useProactiveAlerts({ enabled = true } = {}) {
  const [alerts, setAlerts] = useState([]);
  const lastAiQueryAt = useRef({});  // alertType → ms timestamp
  const timerRef      = useRef(null);

  const dismissAlert = useCallback((id) => {
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, dismissed: true } : a)));
  }, []);

  const dismissAll = useCallback(() => {
    setAlerts((prev) => prev.map((a) => ({ ...a, dismissed: true })));
  }, []);

  /** Re-enable a previously dismissed alert (used after manual "Ask AI" click). */
  const undismissAlert = useCallback((id) => {
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, dismissed: false } : a)));
  }, []);

  /** Manually trigger an AI query for an alert (e.g. button click). */
  const queryAlertAI = useCallback(async (alertId) => {
    const found = alerts.find((a) => a.id === alertId);
    if (!found) return;
    setAlerts((prev) => prev.map((a) => (a.id === alertId ? { ...a, aiQuerying: true } : a)));
    try {
      const resp = await queryAgent(buildAiQuery(found, found._metrics || {}), AI_SESSION_ID);
      setAlerts((prev) => prev.map((a) =>
        a.id === alertId ? { ...a, aiQuerying: false, aiResponse: resp.response } : a,
      ));
    } catch {
      setAlerts((prev) => prev.map((a) =>
        a.id === alertId ? { ...a, aiQuerying: false } : a,
      ));
    }
  }, [alerts]);

  const check = useCallback(async () => {
    if (!enabled) return;
    try {
      const [metricsResp, contactsResp] = await Promise.allSettled([
        getMetrics(),
        getLiveContacts(),
      ]);

      const metrics  = metricsResp.status  === 'fulfilled' ? (metricsResp.value?.metrics  || {}) : {};
      const contacts = contactsResp.status === 'fulfilled' ? (contactsResp.value || {})            : {};

      const inbound     = contacts.inbound      || [];
      const botContacts = contacts.bot_contacts || [];

      const newAlerts = [];

      // ── 1. Queue depth ────────────────────────────────────────────────
      const queueCount = +(metrics.contacts_in_queue ?? 0);
      if (queueCount > THRESHOLDS.QUEUE_HIGH_WARN) {
        newAlerts.push({
          id:       'QUEUE_HIGH',
          type:     'QUEUE_HIGH',
          severity: queueCount >= THRESHOLDS.QUEUE_HIGH_CRIT ? 'critical' : 'warning',
          title:    `${queueCount} contacts waiting in queue`,
          message:  `Queue depth is above threshold (>${THRESHOLDS.QUEUE_HIGH_WARN}). Customer satisfaction at risk.`,
          contactId: null,
          _metrics: metrics,
        });
      }

      // ── 2. Oldest contact wait time ───────────────────────────────────
      const ageSeconds = parseAgeSeconds(metrics.oldest_contact_age);
      if (ageSeconds >= THRESHOLDS.LONG_WAIT_WARN) {
        const m = Math.floor(ageSeconds / 60);
        const s = ageSeconds % 60;
        newAlerts.push({
          id:       'LONG_WAIT',
          type:     'LONG_WAIT',
          severity: ageSeconds >= THRESHOLDS.LONG_WAIT_CRIT ? 'critical' : 'warning',
          title:    `Longest wait: ${m}m ${s}s`,
          message:  `A contact has been waiting over ${Math.floor(THRESHOLDS.LONG_WAIT_WARN / 60)} minutes. Immediate agent assignment recommended.`,
          contactId: null,
          _metrics: metrics,
        });
      }

      // ── 3. No agents available while queue non-empty ──────────────────
      const agentsAvail = +(metrics.agents_available ?? 0);
      if (agentsAvail === 0 && queueCount > 0) {
        newAlerts.push({
          id:       'NO_AGENTS',
          type:     'NO_AGENTS',
          severity: 'critical',
          title:    `No agents available — ${queueCount} contact${queueCount !== 1 ? 's' : ''} in queue`,
          message:  'All agents are busy or unavailable. Consider asking agents to finish ACW or pulling agents from other queues.',
          contactId: null,
          _metrics: metrics,
        });
      }

      // ── 4. Long-running inbound calls ────────────────────────────────
      for (const c of inbound) {
        const age = elapsedSeconds(c.initiatedAt);
        if (age >= THRESHOLDS.LONG_CALL_WARN) {
          const m = Math.floor(age / 60);
          newAlerts.push({
            id:       `LONG_CALL_${c.contactId}`,
            type:     'LONG_CALL',
            severity: 'warning',
            title:    `Long call — ${m}m ${age % 60}s`,
            message:  `Contact …${c.contactId?.slice(-8)} has been active for ${m} minutes. Supervisor check-in may help.`,
            contactId: c.contactId,
            contactMeta: c,
            _metrics: metrics,
          });
        }
      }

      // ── 5. Bot sessions stuck without escalation ─────────────────────
      for (const c of botContacts) {
        if (c.escalatedToAgent) continue;
        const age = elapsedSeconds(c.initiatedAt);
        if (age >= THRESHOLDS.BOT_STUCK_WARN) {
          const m = Math.floor(age / 60);
          newAlerts.push({
            id:       `BOT_STUCK_${c.contactId}`,
            type:     'BOT_STUCK',
            severity: 'warning',
            title:    `Bot session ${m}m without resolution`,
            message:  `Bot session …${c.contactId?.slice(-8)} running ${m} minutes without human escalation. May indicate bot failure or complex query.`,
            contactId: c.contactId,
            contactMeta: c,
            _metrics: metrics,
          });
        }
      }

      // Merge with existing alerts (preserve dismissed + aiResponse state)
      setAlerts((prev) => {
        const prevMap = new Map(prev.map((a) => [a.id, a]));
        return newAlerts.map((na) => {
          const existing = prevMap.get(na.id);
          if (existing) {
            return {
              ...na,
              dismissed:  existing.dismissed,
              aiResponse: existing.aiResponse,
              aiQuerying: existing.aiQuerying || false,
            };
          }
          return { ...na, dismissed: false, aiResponse: null, aiQuerying: false };
        });
      });

      // Auto-query AI for CRITICAL alerts (rate-limited)
      for (const alert of newAlerts) {
        if (alert.severity !== 'critical') continue;
        const last = lastAiQueryAt.current[alert.type] || 0;
        if (Date.now() - last < AI_COOLDOWN_MS) continue;

        lastAiQueryAt.current[alert.type] = Date.now();
        const query = buildAiQuery(alert, metrics);

        // Mark as querying first
        setAlerts((prev) =>
          prev.map((a) => (a.id === alert.id ? { ...a, aiQuerying: true } : a)),
        );

        queryAgent(query, AI_SESSION_ID)
          .then((resp) => {
            setAlerts((prev) =>
              prev.map((a) =>
                a.id === alert.id
                  ? { ...a, aiQuerying: false, aiResponse: resp.response }
                  : a,
              ),
            );
          })
          .catch(() => {
            setAlerts((prev) =>
              prev.map((a) => (a.id === alert.id ? { ...a, aiQuerying: false } : a)),
            );
          });
      }
    } catch {
      // Silently ignore — don't disrupt the UI
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    check();
    timerRef.current = setInterval(check, POLL_MS);
    return () => clearInterval(timerRef.current);
  }, [check, enabled]);

  const activeAlerts = alerts.filter((a) => !a.dismissed);

  return {
    alerts: activeAlerts,
    alertCount: activeAlerts.length,
    criticalCount: activeAlerts.filter((a) => a.severity === 'critical').length,
    dismissAlert,
    dismissAll,
    undismissAlert,
    queryAlertAI,
    refresh: check,
  };
}
