// src/types/scenario.ts
// Mirrors the YAML scenario format used in aria-evaluator-v2/scenarios/

import type { EscalationReason } from './transcript.js';

export interface Scenario {
  name: string;
  description?: string;
  channel: 'chat' | 'voice';
  mode: 'agent' | 'script';
  authenticated: boolean;
  opening_message: string;
  goal: string;
  customer_persona: string;
  max_turns: number;
  default_timeout_seconds?: number;
  turn_delay_seconds?: number;
  /**
   * Whether this scenario is expected to result in ARIA escalating to a human agent.
   * If undefined, escalation outcome is not asserted by the judge.
   */
  expected_escalation?: boolean;
  /**
   * The expected reason for escalation. Used by ESCALATION_APPROPRIATENESS dimension.
   */
  escalation_reason?: EscalationReason;
  /**
   * Policy reference explaining why escalation is (or is not) appropriate.
   * Passed verbatim to the judge prompt so it can assess compliance.
   */
  escalation_policy?: string;
  // filled in by scenario-loader after parsing
  filePath?: string;
}

export interface ScenarioFile {
  scenarios: Scenario[];
  filePath: string;
}

/** Template variables available in scenario YAML strings */
export interface TemplateVars {
  customer_name: string;
  customer_first_name: string;
  customer_id: string;
  [key: string]: string;
}
