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
import type { Scenario, TemplateVars } from '../types/index.js';
import type { Transcript, Turn, EscalationEvent } from '../types/transcript.js';
import { AgentDriver } from './agent-driver.js';
import { applyTemplateVars } from './scenario-loader.js';

export interface RunnerConfig {
  transcriptsDir?: string;
  templateVars?: TemplateVars;
  onProgress?: (event: RunnerEvent) => void;
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
  ): Promise<Transcript> {
    const id = runId ?? randomUUID();
    const resolvedScenario = applyTemplateVars(scenario, this.config.templateVars);
    const startedAt = new Date().toISOString();
    const turns: Turn[] = [];
    let error: string | undefined;

    this.driver.reset();

    const timeoutMs =
      (resolvedScenario.default_timeout_seconds ?? 40) * 1000;
    const turnDelayMs =
      (resolvedScenario.turn_delay_seconds ?? 2) * 1000;

    this.log(`\n  ▶  ${resolvedScenario.name}`);

    try {
      await adapter.connect({
        sessionId: id,
        customerId: this.config.templateVars.customer_id,
        authenticated: resolvedScenario.authenticated,
        channel: resolvedScenario.channel,
        scenarioName: resolvedScenario.name,
      });

      let turnIndex = 0;
      let goalAchieved = false;
      let isOpening = true;

      while (turnIndex < resolvedScenario.max_turns && !goalAchieved) {
        // ── Customer turn ──────────────────────────────────────────────────
        const { message, goalAchieved: achieved, giveUp } = await this.driver.nextMessage(
          resolvedScenario,
          turns,
          isOpening,
        );
        isOpening = false;

        if (giveUp) {
          this.log(`  ⚠  agent driver gave up after ${turnIndex} turns`);
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

        // Send to adapter
        await adapter.sendMessage(message, true);
        turnIndex++;

        // ── Agent turn ─────────────────────────────────────────────────────
        // Always receive ARIA's response — even if goal is achieved, we want
        // ARIA's acknowledgement/closing message in the transcript.
        const beforeReceive = Date.now();
        let agentMsg = await adapter.receive(timeoutMs);

        if (!agentMsg) {
          if (achieved) {
            goalAchieved = true;
          } else {
            this.log(`\n  ⏱  TIMEOUT waiting for agent response (${timeoutMs / 1000}s)`);
          }
          break;
        }

        // Collect follow-on messages (agents sometimes send multiple quick chunks)
        const parts = [agentMsg.content];
        while (true) {
          const next = await adapter.receive(2000);
          if (!next) break;
          parts.push(next.content);
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

        const displayContent = agentTurn.content.slice(0, 120);
        this.log(`    🤖 agent: ${displayContent}${agentTurn.content.length > 120 ? '…' : ''}`);

        turnIndex++;

        if (achieved) {
          goalAchieved = true;
          break;
        }

        if (turnDelayMs > 0) await sleep(turnDelayMs);
      }
    } catch (err: unknown) {
      if (err instanceof SessionEndedError) {
        const escalEv =
          adapter instanceof ConnectWebRTCAdapter ? adapter.escalationEvent :
          adapter instanceof ConnectChatAdapter   ? adapter.escalationEvent :
          null;
        if (escalEv) {
          this.log(`  ⚡ Escalated to human agent (reason: ${escalEv.reason})`);
        } else {
          this.log(`  ℹ  Session ended by agent`);
        }
      } else {
        error = (err as Error).message;
        this.log(`  ✗  Scenario failed: ${error}`);
        this.config.onProgress({ type: 'error', error: error ?? 'unknown' });
      }
    } finally {
      try {
        await adapter.disconnect();
      } catch {
        // ignore
      }
    }

    // Save call recording for voice runs
    let audioPath: string | undefined;
    if (adapter instanceof ConnectVoiceAdapter && adapter.hasAudio()) {
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
      channel: resolvedScenario.channel,
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
