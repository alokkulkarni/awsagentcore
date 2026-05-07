// src/conversation/runner.ts
// ScenarioRunner — drives one scenario through an adapter, builds a Transcript,
// and persists it to disk + DB.

import { writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import type { BaseAdapter } from '../adapters/base.js';
import { SessionEndedError } from '../adapters/base.js';
import { ConnectVoiceAdapter } from '../adapters/connect-voice.js';
import { ConnectWebRTCAdapter } from '../adapters/connect-webrtc.js';
import { ConnectChatAdapter } from '../adapters/connect-chat.js';
import type { Scenario, ScriptTurn, TemplateVars } from '../types/index.js';
import type { Transcript, Turn, EscalationEvent } from '../types/transcript.js';
import { AgentDriver } from './agent-driver.js';
import { applyTemplateVars } from './scenario-loader.js';

export interface RunnerConfig {
  transcriptsDir?: string;
  templateVars?: TemplateVars;
  onProgress?: (event: RunnerEvent) => void;
  provider?: string;
}

export interface RunOptions {
  connect?: boolean;
  disconnect?: boolean;
}

export type RunnerEvent =
  | { type: 'turn'; turn: Turn }
  | { type: 'error'; error: string }
  | { type: 'complete'; transcript: Transcript }
  | { type: 'log'; message: string };

export class ScenarioRunner {
  private readonly config: Required<RunnerConfig>;
  private readonly driver: AgentDriver;

  constructor(config: RunnerConfig = {}) {
    this.config = {
      transcriptsDir: config.transcriptsDir ?? './transcripts',
      templateVars: config.templateVars ?? {
        customer_name: process.env['EVAL_CUSTOMER_NAME'] ?? 'James Wilson',
        customer_first_name: (process.env['EVAL_CUSTOMER_NAME'] ?? 'James Wilson').split(' ')[0]!,
        customer_id: process.env['EVAL_CUSTOMER_ID'] ?? 'CUST-001',
      },
      onProgress: config.onProgress ?? (() => undefined),
      provider: config.provider ?? process.env['EVAL_PROVIDER'] ?? process.env['EVAL_PROVIDER_DEFAULT'] ?? 'connect',
    };
    this.driver = new AgentDriver();
  }

  private log(msg: string): void {
    console.log(msg);
    this.config.onProgress({ type: 'log', message: msg });
  }

  async run(
    scenario: Scenario,
    adapter: BaseAdapter,
    runId?: string,
    options: RunOptions = {},
  ): Promise<Transcript> {
    const id = runId ?? randomUUID();
    const resolvedScenario = applyTemplateVars(scenario, this.config.templateVars);
    const startedAt = new Date().toISOString();
    const turns: Turn[] = [];
    let error: string | undefined;
    const shouldConnect = options.connect ?? true;
    const shouldDisconnect = options.disconnect ?? true;

    this.driver.reset();

    const timeoutMs =
      (resolvedScenario.default_timeout_seconds ?? DEFAULT_TURN_TIMEOUT_SECONDS) * 1000;
    const turnDelayMs =
      (resolvedScenario.turn_delay_seconds ?? 2) * 1000;

    this.log(`\n  ▶  ${resolvedScenario.name}`);
    const runtimeChannel: 'chat' | 'voice' =
      adapter.channel
      ?? (adapter instanceof ConnectWebRTCAdapter || adapter instanceof ConnectVoiceAdapter
        ? 'voice'
        : 'chat');

    try {
      if (shouldConnect) {
        await adapter.connect({
          sessionId: id,
          customerId: this.config.templateVars.customer_id,
          authenticated: resolvedScenario.authenticated,
          channel: runtimeChannel,
          scenarioName: resolvedScenario.name,
        });
      }

      // Capture opening greeting as turn 0 (chat authenticated OR voice IVR greeting)
      if (shouldConnect) {
        const openingGreeting =
          adapter instanceof ConnectChatAdapter    ? adapter.openingGreeting :
          adapter instanceof ConnectWebRTCAdapter  ? adapter.openingGreeting :
          null;
        if (openingGreeting && openingGreeting.content.trim()) {
          const greetingTurn: Turn = {
            index: 0,
            role: 'agent',
            content: openingGreeting.content,
            timestampMs: Date.now(),
          };
          turns.push(greetingTurn);
          this.config.onProgress({ type: 'turn', turn: greetingTurn });
          this.log(`    🤖 agent (greeting): ${greetingTurn.content}`);
        }
      }
      let turnIndex = 0;
      let goalAchieved = false;
      let isOpening = true;
      let consecutiveSilentWaits = 0;
      const shouldAcceptGoalAchieved = (achieved: boolean): boolean => {
        if (!achieved) return false;
        const lastAgentTurn = [...turns].reverse().find((t) => t.role === 'agent');
        if (!lastAgentTurn) return true;
        if (isLikelyDeferredAgentReply(lastAgentTurn.content)) {
          this.log('    ℹ  Ignoring premature goal completion signal — awaiting actual answer content.');
          return false;
        }
        return true;
      };
      const receiveAndRecordAgentTurn = async (goalFromDriver: boolean): Promise<boolean> => {
        // ── Agent turn ─────────────────────────────────────────────────────
        // Always receive the agent's response — even if goal is achieved, we want
        // the agent's acknowledgement/closing message in the transcript.
        const beforeReceive = Date.now();
        const agentMsg = await adapter.receive(timeoutMs);

        if (!agentMsg) {
          const endedReason = getSessionEndedReason(adapter);
          if (endedReason) {
            if (goalFromDriver) {
              this.log(`  ℹ  Session ended after final customer turn (${endedReason}); treating run as complete.`);
              goalAchieved = true;
              return false;
            }
            error = `Session ended before response: ${endedReason}`;
            this.log(`  ✗  Scenario failed: ${error}`);
            this.config.onProgress({ type: 'error', error });
            return false;
          }
          const escalEv = getEscalationEvent(adapter);
          if (escalEv) {
            this.log(`  ⚡ Session ended after escalation (${escalEv.reason})`);
            goalAchieved = true;
            return false;
          }
          if (goalFromDriver) {
            goalAchieved = true;
            return false;
          }
          error = `Timeout waiting for agent response (${timeoutMs / 1000}s)`;
          this.log(`\n  ⏱  ${error}`);
          this.config.onProgress({ type: 'error', error });
          return false;
        }

        // Collect the agent's complete response using conversational timing only
        // (no keyword/phrase validation).
        const parts = [agentMsg.content];

        if (runtimeChannel === 'chat') {
          // Collect any rapid follow-on packets from the agent
          while (true) {
            const next = await adapter.receive(2_500);
            if (!next) break;
            parts.push(next.content);
          }
        } else if (runtimeChannel === 'voice') {
          // Do not interrupt the agent mid-utterance. Wait for a short quiet window
          // before sending the next customer message, and merge any trailing
          // speech chunks into the same agent turn.
          const settleDeadline = Date.now() + VOICE_TURN_SETTLE_MAX_MS;
          while (true) {
            const remaining = settleDeadline - Date.now();
            if (remaining <= 0) break;
            const tail = await adapter.receive(Math.min(VOICE_TURN_SETTLE_TIMEOUT_MS, remaining));
            if (!tail) break;
            parts.push(tail.content);
          }
        }

        const agentTurn: Turn = {
          index: turnIndex,
          role: 'agent',
          content: parts.join('\n'),
          timestampMs: Date.now(),
          durationMs: Date.now() - beforeReceive,
        };
        turns.push(agentTurn);
        this.config.onProgress({ type: 'turn', turn: agentTurn });

        this.log(`    🤖 agent: ${agentTurn.content}`);

        turnIndex++;
        return true;
      };

      const isScriptMode = resolvedScenario.mode === 'script' || (
        !resolvedScenario.mode && Array.isArray(resolvedScenario.turns) && resolvedScenario.turns.length > 0
      );

      if (isScriptMode) {
        // ── Script mode: send each pre-defined turn in order ──────────────────
        const scriptTurns: ScriptTurn[] = resolvedScenario.turns ?? [];
        for (const turnDef of scriptTurns) {
          const message = (
            turnDef.send ?? turnDef.customer ?? turnDef.content ?? turnDef.message ?? ''
          ).trim();
          if (!message) continue;

          const turnTimeoutMs = turnDef.timeout_seconds != null
            ? turnDef.timeout_seconds * 1000
            : timeoutMs;

          const customerTurn: Turn = {
            index: turnIndex,
            role: 'customer',
            content: message,
            timestampMs: Date.now(),
          };
          turns.push(customerTurn);
          this.config.onProgress({ type: 'turn', turn: customerTurn });
          this.log(`    🧑 customer: ${message}`);

          try {
            await adapter.sendMessage(message, true);
          } catch (sendErr) {
            if (sendErr instanceof SessionEndedError) {
              this.log('    ℹ  Session ended by agent — conversation complete');
              break;
            }
            throw sendErr;
          }
          turnIndex++;

          const agentMsg = await adapter.receive(turnTimeoutMs);
          if (!agentMsg) {
            const endedReason = getSessionEndedReason(adapter);
            if (endedReason) {
              this.log(`    ℹ  Session ended (${endedReason})`);
              break;
            }
            this.log(`    ⏰ TIMEOUT waiting for agent (turn ${turnIndex}, ${turnTimeoutMs / 1000}s) — continuing`);
            continue;
          }

          // Collect follow-on chat packets
          const parts = [agentMsg.content];
          if (runtimeChannel === 'chat') {
            while (true) {
              const next = await adapter.receive(2_500);
              if (!next) break;
              parts.push(next.content);
            }
          }

          const agentTurn: Turn = {
            index: turnIndex,
            role: 'agent',
            content: parts.join('\n'),
            timestampMs: Date.now(),
          };
          turns.push(agentTurn);
          this.config.onProgress({ type: 'turn', turn: agentTurn });
          this.log(`    🤖 agent: ${agentTurn.content}`);

          if (turnDelayMs > 0) await sleep(turnDelayMs);
        }
      } else {
      // ── Agent mode ────────────────────────────────────────────────────────
      while (turnIndex < (resolvedScenario.max_turns ?? 10) && !goalAchieved) {
        if (runtimeChannel === 'voice') {
          const lastTurn = turns.at(-1);
          if (lastTurn?.role === 'agent') {
            const trailing = await adapter.receive(VOICE_PRE_SEND_GUARD_TIMEOUT_MS);
            if (trailing) {
              lastTurn.content = `${lastTurn.content}\n${trailing.content}`;
              lastTurn.timestampMs = Date.now();
              this.config.onProgress({ type: 'turn', turn: lastTurn });
              this.log(`    🤖 agent (continued): ${trailing.content}`);
              continue;
            }
            const endedReason = getSessionEndedReason(adapter);
            if (endedReason) {
              error = `Session ended before next customer turn: ${endedReason}`;
              this.log(`  ✗  Scenario failed: ${error}`);
              this.config.onProgress({ type: 'error', error });
              break;
            }
          }
        }

        // ── Customer turn ──────────────────────────────────────────────────
        const { message, goalAchieved: achieved, giveUp, waitForAgent } = await this.driver.nextMessage(
          resolvedScenario,
          turns,
          isOpening,
        );
        isOpening = false;

        if (giveUp) {
          this.log(`  ⚠  agent driver gave up after ${turnIndex} turns`);
          break;
        }

        if (waitForAgent) {
          if (consecutiveSilentWaits >= VOICE_MAX_CONSECUTIVE_SILENT_WAITS) {
            const followup = VOICE_SILENT_WAIT_FOLLOWUP_PROMPT;
            this.log(`    ℹ  the agent still has not delivered the result — prompting for completion.`);
            const customerTurn: Turn = {
              index: turnIndex,
              role: 'customer',
              content: followup,
              timestampMs: Date.now(),
            };
            turns.push(customerTurn);
            this.config.onProgress({ type: 'turn', turn: customerTurn });
            this.log(`    🧑 customer: ${followup}`);

            if (runtimeChannel === 'voice' && VOICE_PRE_SEND_DELAY_MS > 0) {
              await sleep(VOICE_PRE_SEND_DELAY_MS);
            }
            await adapter.sendMessage(followup, true);
            turnIndex++;
            consecutiveSilentWaits = 0;

            const received = await receiveAndRecordAgentTurn(achieved);
            if (!received) break;

            if (shouldAcceptGoalAchieved(achieved)) {
              goalAchieved = true;
              break;
            }

            if (turnDelayMs > 0) await sleep(turnDelayMs);
            continue;
          }

          this.log(`    ⏳ customer is waiting for the agent to finish...`);
          consecutiveSilentWaits += 1;
          const received = await receiveAndRecordAgentTurn(achieved);
          if (!received) break;

          if (shouldAcceptGoalAchieved(achieved)) {
            goalAchieved = true;
            break;
          }

          if (turnDelayMs > 0) await sleep(turnDelayMs);
          continue;
        }

        consecutiveSilentWaits = 0;

        // If goal is achieved and driver produced no follow-up text, end immediately
        // rather than sending a blank message (Connect Chat rejects empty content).
        if (!message && shouldAcceptGoalAchieved(achieved)) {
          goalAchieved = true;
          break;
        }

        // Skip sending if message is somehow empty to avoid adapter errors.
        if (!message) {
          this.log('    ⚠  driver returned empty message without goal; skipping turn');
          break;
        }

        const customerTurn: Turn = {
          index: turnIndex,
          role: 'customer',
          content: message,
          timestampMs: Date.now(),
        };
        turns.push(customerTurn);
        this.config.onProgress({ type: 'turn', turn: customerTurn });
        this.log(`    🧑 customer: ${customerTurn.content}`);

        // Send to adapter
        if (runtimeChannel === 'voice' && VOICE_PRE_SEND_DELAY_MS > 0) {
          await sleep(VOICE_PRE_SEND_DELAY_MS);
        }
        // Keep human-like speech pacing for voice to avoid barging at turn boundaries.
        await adapter.sendMessage(message, true);
        turnIndex++;
        const received = await receiveAndRecordAgentTurn(achieved);
        if (!received) break;

        if (shouldAcceptGoalAchieved(achieved)) {
          goalAchieved = true;
          break;
        }

        if (turnDelayMs > 0) await sleep(turnDelayMs);
      }
      } // end agent mode
    } catch (err: unknown) {
      if (err instanceof SessionEndedError) {
        const escalEv = getEscalationEvent(adapter);
        if (escalEv) {
          this.log(`  ⚡ Escalated to human agent (reason: ${escalEv.reason})`);
        } else {
          error = err.message || 'Session ended by agent';
          this.log(`  ✗  Scenario failed: ${error}`);
          this.config.onProgress({ type: 'error', error });
        }
      } else {
        error = (err as Error).message;
        this.log(`  ✗  Scenario failed: ${error}`);
        this.config.onProgress({ type: 'error', error: error ?? 'unknown' });
      }
    } finally {
      if (shouldDisconnect) {
        try {
          await adapter.disconnect();
        } catch {
          // ignore
        }
      }
    }

    // Save call recording for voice runs
    let audioPath: string | undefined;
    if (shouldDisconnect && supportsAudioSave(adapter) && adapter.hasAudio()) {
      try {
        const safeName = resolvedScenario.name
          .toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 60);
        const ts = startedAt.replace(/[:.]/g, '-').slice(0, 19);
        const audioDir = resolve(this.config.transcriptsDir, 'audio');
        const wavFilename = `${safeName}_${ts}.wav`;
        adapter.saveAudio(join(audioDir, wavFilename));
        audioPath = wavFilename;
        this.log(`    🎙  audio saved → transcripts/audio/${wavFilename}`);
      } catch (audioErr) {
        this.log(`    ⚠  audio save failed: ${(audioErr as Error).message}`);
      }
    }

    // Capture escalation event from adapter (after disconnect)
    let escalationEvent: EscalationEvent | undefined;
    if (adapter instanceof ConnectWebRTCAdapter && adapter.escalationEvent) {
      escalationEvent = adapter.escalationEvent;
      if (escalationEvent.detectedAtTurn === -1) {
        escalationEvent = { ...escalationEvent, detectedAtTurn: turns.length - 1 };
      }
    } else if (adapter instanceof ConnectChatAdapter && adapter.escalationEvent) {
      escalationEvent = adapter.escalationEvent;
    }

    const transcript: Transcript = {
      id,
      scenarioName: resolvedScenario.name,
      provider: this.config.provider,
      channel: runtimeChannel,
      startedAt,
      completedAt: new Date().toISOString(),
      turns,
      error,
      audioPath,
      escalated: !!escalationEvent,
      escalation: escalationEvent,
    };

    this.saveTranscript(transcript);
    this.config.onProgress({ type: 'complete', transcript });

    const status = error ? '✗' : '✓';
    const turnCount = turns.length;
    this.log(`    ${status} ${resolvedScenario.name} (${turnCount} turns)`);

    return transcript;
  }

  private saveTranscript(transcript: Transcript): void {
    mkdirSync(this.config.transcriptsDir, { recursive: true });
    const safeName = transcript.scenarioName
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .slice(0, 60);
    const ts = transcript.startedAt.replace(/[:.]/g, '-').slice(0, 19);
    const filename = `${safeName}_${ts}.json`;
    const filePath = join(this.config.transcriptsDir, filename);
    writeFileSync(filePath, JSON.stringify(transcript, null, 2));
    this.log(`    💾 transcript saved → ${filePath}`);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function getEscalationEvent(adapter: BaseAdapter): EscalationEvent | null {
  if (adapter instanceof ConnectWebRTCAdapter || adapter instanceof ConnectChatAdapter) {
    return adapter.escalationEvent;
  }
  return null;
}

function getSessionEndedReason(adapter: BaseAdapter): string | null {
  if (adapter instanceof ConnectWebRTCAdapter) {
    return adapter.lastSessionEndReason;
  }
  return null;
}

function supportsAudioSave(
  adapter: BaseAdapter,
): adapter is BaseAdapter & { hasAudio: () => boolean; saveAudio: (outputPath: string) => string } {
  return (
    typeof (adapter as { hasAudio?: unknown }).hasAudio === 'function'
    && typeof (adapter as { saveAudio?: unknown }).saveAudio === 'function'
  );
}

const VOICE_PRE_SEND_DELAY_MS = parsePositiveInt(
  process.env['VOICE_PRE_SEND_DELAY_MS'],
  1_200,
);
const VOICE_MAX_CONSECUTIVE_SILENT_WAITS = parsePositiveInt(
  process.env['VOICE_MAX_CONSECUTIVE_SILENT_WAITS'],
  1,
);
const VOICE_SILENT_WAIT_FOLLOWUP_PROMPT =
  process.env['VOICE_SILENT_WAIT_FOLLOWUP_PROMPT'] ?? 'Could you share the result now, please?';
const DEFAULT_TURN_TIMEOUT_SECONDS = parsePositiveInt(
  process.env['EVAL_RESPONSE_TIMEOUT_SECONDS'],
  120,
);
const VOICE_PRE_SEND_GUARD_TIMEOUT_MS = parsePositiveInt(
  process.env['VOICE_PRE_SEND_GUARD_TIMEOUT_MS'],
  4_000,
);
const VOICE_TURN_SETTLE_TIMEOUT_MS = parsePositiveInt(
  process.env['VOICE_TURN_SETTLE_TIMEOUT_MS'],
  4_000,
);
const VOICE_TURN_SETTLE_MAX_MS = parsePositiveInt(
  process.env['VOICE_TURN_SETTLE_MAX_MS'],
  15_000,
);

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(raw ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function isLikelyDeferredAgentReply(text: string): boolean {
  const lower = text.toLowerCase();
  return (
    /let me|pull (that|this|it) up|checking|look into|one moment|just a moment|bear with me|while i|hold on/.test(lower)
    || /i'?ll (check|look into|get|pull)/.test(lower)
  );
}
