// src/types/transcript.ts

export type TurnRole = 'customer' | 'agent';

export interface Turn {
  index: number;
  role: TurnRole;
  content: string;
  /** Wall-clock timestamp (ms since epoch) */
  timestampMs: number;
  /** How long the adapter took to receive this turn (ms) */
  durationMs?: number;
}

/**
 * How escalation was detected.
 *  text_keyword     – the agent's utterance contained a known transfer phrase
 *  meeting_ended    – Chime MeetingEnded fired while conversation was active (voice only)
 *  contact_attribute – DescribeContact returned an escalation attribute set by the Contact Flow
 */
export type EscalationTrigger = 'text_keyword' | 'meeting_ended' | 'contact_attribute';

/**
 * Why the agent escalated. Mirrors the values set by the ARIA Contact Flow and scenario YAML.
 *  customer_requested   – Customer explicitly asked for a human agent
 *  auth_failure         – Authentication failed too many times
 *  vulnerable_customer  – Vulnerability indicators detected (FCA Consumer Duty)
 *  compliance_blocked   – Request blocked by regulatory policy (formal complaint, bereavement, etc.)
 *  unresolvable         – the agent could not resolve the issue after multiple attempts
 *  out_of_scope         – Request outside the agent's permitted scope
 *  unknown              – Escalation detected but reason not determined
 */
export type EscalationReason =
  | 'customer_requested'
  | 'auth_failure'
  | 'vulnerable_customer'
  | 'compliance_blocked'
  | 'unresolvable'
  | 'out_of_scope'
  | 'unknown';

export interface EscalationEvent {
  /** Turn index (agent turn) at which escalation was detected */
  detectedAtTurn: number;
  /** How the escalation was detected */
  trigger: EscalationTrigger;
  /** The agent's utterance that triggered detection (for text_keyword trigger) */
  detectedFrom?: string;
  /** Reason inferred from text or contact attributes */
  reason: EscalationReason;
  /** Raw contact attributes from DescribeContact (may contain richer context) */
  contactAttributes?: Record<string, string>;
}

export interface Transcript {
  id: string;
  scenarioName: string;
  provider?: 'connect' | 'lex' | 'azure' | 'strands' | 'copilot' | 'custom' | string;
  channel: 'chat' | 'voice';
  startedAt: string;       // ISO-8601
  completedAt?: string;
  turns: Turn[];
  error?: string;
  /** Relative path to the WAV recording (voice runs only) */
  audioPath?: string;
  /** Whether the agent escalated this conversation to a human agent */
  escalated: boolean;
  /** Details of the escalation event, if escalation occurred */
  escalation?: EscalationEvent;
}
