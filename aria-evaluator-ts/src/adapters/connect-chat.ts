// src/adapters/connect-chat.ts
// Amazon Connect Chat adapter — WebSocket push, direct port of connect_ws.py
//
// Protocol:
// 1. StartChatContact → participantToken + contactId
// 2. CreateParticipantConnection(WEBSOCKET + CONNECTION_CREDENTIALS) → wsUrl + connectionToken
// 3. WS connect → subscribe → receive push messages
// 4. SendMessage via ConnectParticipantClient (same as the hosted widget)

import {
  ConnectClient,
  StartChatContactCommand,
  ListContactFlowsCommand,
} from '@aws-sdk/client-connect';
import {
  ConnectParticipantClient,
  CreateParticipantConnectionCommand,
  SendMessageCommand,
  SendEventCommand,
  DisconnectParticipantCommand,
} from '@aws-sdk/client-connectparticipant';
import WebSocket from 'ws';
import { randomUUID } from 'node:crypto';
import type { BaseAdapter, AdapterMessage, ConnectOptions } from './base.js';
import { AdapterError, SessionEndedError } from './base.js';
import type { EscalationEvent, EscalationReason } from '../types/index.js';

// Regex patterns for IVR / Contact Flow prompts that should never appear in
// the transcript as agent turns.  Matched case-insensitively against the full
// message text.
const FLOW_NOISE_PATTERNS: RegExp[] = [
  /welcome to (nationwide|meridian)/i,
  /^hello[.!,]?\s+welcome to/i,
  /let me transfer you to one of our agents/i,
  // Generic IVR hold / queue filler messages
  /please (hold|wait)\b/i,
  /^thank you for (calling|contacting|your patience)/i,
  /your (call|chat) is (important|being connected)/i,
];

const BOT_ROLES = new Set(['BOT', 'SYSTEM', 'AGENT', 'CUSTOM_BOT']);

function isFlowNoise(content: string): boolean {
  return FLOW_NOISE_PATTERNS.some((re) => re.test(content));
}

/** Resolve a flow name → flow ID via ListContactFlows */
async function resolveFlowId(
  client: ConnectClient,
  instanceId: string,
  nameOrId: string,
): Promise<string> {
  if (nameOrId.match(/^[0-9a-f-]{36}$/i)) return nameOrId;

  let nextToken: string | undefined;
  do {
    const resp = await client.send(
      new ListContactFlowsCommand({
        InstanceId: instanceId,
        NextToken: nextToken,
      }),
    );
    for (const flow of resp.ContactFlowSummaryList ?? []) {
      if (flow.Name === nameOrId && flow.Id) return flow.Id;
    }
    nextToken = resp.NextToken;
  } while (nextToken);

  throw new AdapterError(`Contact flow not found: "${nameOrId}"`);
}

export interface ChatAdapterConfig {
  instanceId: string;
  /** Flow ID or name — name will be auto-resolved */
  contactFlowIdOrName: string;
  region?: string;
  displayName?: string;
  chatDurationMinutes?: number;
  typingWpm?: number;
  responseTimeoutMs?: number;
}

export class ConnectChatAdapter implements BaseAdapter {
  private readonly connectClient: ConnectClient;
  private readonly participantClient: ConnectParticipantClient;
  private readonly config: Required<ChatAdapterConfig>;

  private _contactId: string | null = null;
  private connectionToken: string | null = null;
  private ws: WebSocket | null = null;
  private messageQueue: AdapterMessage[] = [];
  private messageResolvers: Array<(msg: AdapterMessage | null) => void> = [];
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private resolvedFlowId: string | null = null;
  private sessionEnded = false;
  private _escalationEvent: EscalationEvent | null = null;
  /** the agent's personalized greeting sent before the first customer turn (authenticated sessions) */
  private _openingGreeting: AdapterMessage | null = null;

  // Same patterns as ConnectWebRTCAdapter — applied to chat messages
  private static readonly ESCALATION_PATTERNS: Array<{ re: RegExp; reason: EscalationReason }> = [
    { re: /transferr?ing you (to|now)/i,              reason: 'unresolvable' },
    { re: /connect(ing)? you (to|with) (a )?(human|live|real|our) (agent|advisor|specialist|colleague|team)/i, reason: 'unresolvable' },
    { re: /speak(ing)? to (a )?(human|live|real|our) (agent|advisor|specialist|colleague)/i, reason: 'customer_requested' },
    { re: /pass(ing)? you (over|through) to (a )?/i,  reason: 'unresolvable' },
    { re: /handl(ing|ed) by (a |one of )?our (team|advisors?|specialists?|colleagues?)/i, reason: 'unresolvable' },
    { re: /need(s)? to (speak|talk) with (a |an )?(agent|advisor|human)/i, reason: 'unresolvable' },
    { re: /one of our (advisors?|team|specialists?|colleagues?) will/i, reason: 'unresolvable' },
    { re: /placing you (in|into) (a |the )?(queue|hold)/i, reason: 'unresolvable' },
    { re: /auth(entication)? (has )?fail/i,            reason: 'auth_failure' },
    { re: /vulnerab/i,                                  reason: 'vulnerable_customer' },
    { re: /compliance|regulatory|regulator/i,          reason: 'compliance_blocked' },
    { re: /formal (complaint|dispute)/i,               reason: 'compliance_blocked' },
    { re: /bereavement|bereavements/i,                 reason: 'compliance_blocked' },
  ];

  constructor(config: ChatAdapterConfig) {
    this.config = {
      instanceId: config.instanceId,
      contactFlowIdOrName: config.contactFlowIdOrName,
      region: config.region ?? 'eu-west-2',
      displayName: config.displayName ?? 'ARIAEvaluatorBot',
      chatDurationMinutes: config.chatDurationMinutes ?? 60,
      typingWpm: config.typingWpm ?? 60,
      responseTimeoutMs: config.responseTimeoutMs ?? 90_000,
    };
    this.connectClient = new ConnectClient({ region: this.config.region });
    this.participantClient = new ConnectParticipantClient({ region: this.config.region });
  }

  get contactId(): string | null {
    return this._contactId;
  }

  get channel(): 'chat' {
    return 'chat';
  }

  get escalationEvent(): EscalationEvent | null {
    return this._escalationEvent;
  }

  /** the agent's personalized greeting captured during connect() for authenticated sessions */
  get openingGreeting(): AdapterMessage | null {
    return this._openingGreeting;
  }

  async connect(options: ConnectOptions): Promise<void> {
    const {
      sessionId,
      customerId,
      authenticated = false,
      channel = 'chat',
      scenarioName = '',
    } = options;

    if (!this.resolvedFlowId) {
      this.resolvedFlowId = await resolveFlowId(
        this.connectClient,
        this.config.instanceId,
        this.config.contactFlowIdOrName,
      );
      console.log(`  ℹ  Resolved flow '${this.config.contactFlowIdOrName}' → ${this.resolvedFlowId}`);
    }

    const startResp = await this.connectClient.send(
      new StartChatContactCommand({
        InstanceId: this.config.instanceId,
        ContactFlowId: this.resolvedFlowId,
        ParticipantDetails: { DisplayName: this.config.displayName },
        ChatDurationInMinutes: this.config.chatDurationMinutes,
        Attributes: {
          customerId: customerId ?? '',
          evaluationScenario: scenarioName,
          channel,
          authStatus: authenticated ? 'authenticated' : 'unauthenticated',
        },
      }),
    );

    this._contactId = startResp.ContactId!;
    const participantToken = startResp.ParticipantToken!;
    console.log(`  ℹ  Chat contact started | contactId=${this._contactId}`);

    const connResp = await this.participantClient.send(
      new CreateParticipantConnectionCommand({
        Type: ['WEBSOCKET', 'CONNECTION_CREDENTIALS'],
        ParticipantToken: participantToken,
      }),
    );

    this.connectionToken = connResp.ConnectionCredentials!.ConnectionToken!;
    const wsUrl = connResp.Websocket!.Url!;

    // Acknowledge connection
    try {
      await this.participantClient.send(
        new SendEventCommand({
          ContentType: 'application/vnd.amazonaws.connect.event.connection.acknowledged',
          ConnectionToken: this.connectionToken,
        }),
      );
    } catch {
      // non-fatal
    }

    await this.openWebSocket(wsUrl);
    // Drain IVR / Contact Flow noise, keeping any non-noise messages in the queue
    await this.drainNoise(3000, 15_000);

    if (authenticated && customerId) {
      const sessionStart =
        `SESSION_START: An authenticated customer has connected. ` +
        `X-Channel-Auth: authenticated. ` +
        `X-Customer-ID: ${customerId}. ` +
        `X-Channel: ${channel}. ` +
        `X-Locale: en-GB. ` +
        `Call get_customer_details with this customer ID to fetch their profile, ` +
        `then greet them by their preferred_name and ask how you can help today. ` +
        `Do not ask the customer to re-verify their identity.`;

      console.log(`    [auth] sending SESSION_START for customer ${customerId}`);
      try {
        await this.participantClient.send(
          new SendMessageCommand({
            ContentType: 'text/plain',
            Content: sessionStart,
            ConnectionToken: this.connectionToken,
          }),
        );
      } catch {
        // non-fatal
      }

      // Wait for the agent's personalized greeting so the runner loop starts clean.
      // We capture it as openingGreeting rather than letting it sit in the queue
      // where it would be misidentified as the response to the first customer turn.
      console.log(`    [auth] waiting for agent greeting…`);
      const greeting = await this.receiveOne(8000);
      if (greeting) {
        this._openingGreeting = greeting;
        const preview = greeting.content.slice(0, 80);
        console.log(`    [auth] agent greeting: "${preview}${greeting.content.length > 80 ? '…' : ''}"`);
      } else {
        console.log(`    [auth] ⚠  no agent greeting received within 8s`);
      }
    }
  }

  async sendMessage(content: string, simulateTyping = true): Promise<void> {
    if (!this.connectionToken) throw new AdapterError('sendMessage called before connect()');
    if (this.sessionEnded) throw new SessionEndedError('Chat session has ended');
    if (!content || !content.trim()) throw new AdapterError('sendMessage called with empty content');

    if (simulateTyping) await this.simulateTyping(content);

    try {
      await this.participantClient.send(
        new SendMessageCommand({
          ContentType: 'text/plain',
          Content: content,
          ConnectionToken: this.connectionToken,
        }),
      );
    } catch (err: unknown) {
      const e = err as { name?: string; message?: string };
      if (e.name === 'AccessDeniedException') {
        throw new SessionEndedError('Chat session ended — connection token revoked');
      }
      throw new AdapterError(`sendMessage failed: ${e.message}`);
    }
  }

  async receive(timeoutMs?: number): Promise<AdapterMessage | null> {
    // If session already ended, return null immediately rather than timing out
    if (this.sessionEnded) return null;

    const limit = timeoutMs ?? this.config.responseTimeoutMs;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        const idx = this.messageResolvers.indexOf(resolve);
        if (idx !== -1) this.messageResolvers.splice(idx, 1);
        resolve(null);
      }, limit);

      const wrappedResolve = (msg: AdapterMessage | null) => {
        clearTimeout(timer);
        resolve(msg);
      };

      // Drain any already-queued non-noise messages first
      while (this.messageQueue.length > 0) {
        const msg = this.messageQueue.shift()!;
        if (!msg.isNoise) {
          clearTimeout(timer);
          resolve(msg);
          return;
        }
      }

      this.messageResolvers.push(wrappedResolve);
    });
  }

  async disconnect(): Promise<void> {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // ignore
      }
    }
    if (this._contactId) {
      try {
        await this.participantClient.send(
          new DisconnectParticipantCommand({
            ConnectionToken: this.connectionToken!,
          }),
        );
      } catch {
        // ignore
      }
    }
  }

  // ── Private ────────────────────────────────────────────────────────────────

  private async openWebSocket(wsUrl: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(wsUrl);
      this.ws = ws;

      ws.once('open', () => {
        ws.send(
          JSON.stringify({
            topic: 'aws/subscribe',
            content: { topics: ['aws/chat'] },
          }),
        );
      });

      ws.once('message', (raw: Buffer) => {
        try {
          const ack = JSON.parse(raw.toString()) as { statusCode?: number };
          if (ack.statusCode !== 200) {
            console.warn('  ⚠  WebSocket subscribe ack unexpected:', ack);
          }
        } catch {
          // ignore
        }
        this.startHeartbeat();
        ws.on('message', (data: Buffer) => this.handleWsMessage(data));
        resolve();
      });

      ws.once('error', (err: Error) => reject(new AdapterError(`WebSocket error: ${err.message}`)));

      ws.once('close', () => {
        // Signal session ended to any pending receivers
        this.sessionEnded = true;
        for (const r of this.messageResolvers) {
          r(null);
        }
        this.messageResolvers = [];
      });
    });
  }

  private handleWsMessage(data: Buffer): void {
    let envelope: Record<string, unknown>;
    try {
      envelope = JSON.parse(data.toString()) as Record<string, unknown>;
    } catch {
      return;
    }

    if (envelope['topic'] !== 'aws/chat') return;

    let item: Record<string, unknown>;
    try {
      item = JSON.parse(envelope['content'] as string) as Record<string, unknown>;
    } catch {
      return;
    }

    const contentType = item['ContentType'] as string;

    // Detect Connect chat/participant ended events — signal session end
    if (
      item['Type'] === 'EVENT' &&
      (contentType === 'application/vnd.amazonaws.connect.event.chat.ended' ||
        contentType === 'application/vnd.amazonaws.connect.event.participant.left')
    ) {
      const participantRole = item['ParticipantRole'] as string | undefined;
      // Only end when ARIA/bot/agent leaves, not the customer
      if (participantRole !== 'CUSTOMER') {
        console.log(`\n    ℹ  Connect chat ended (${contentType})`);
        this.sessionEnded = true;
        for (const r of this.messageResolvers) r(null);
        this.messageResolvers = [];
      }
      return;
    }

    if (item['Type'] !== 'MESSAGE') return;
    if (contentType !== 'text/plain' && contentType !== 'text/markdown') return;

    const participantRole = item['ParticipantRole'] as string;
    if (participantRole === 'CUSTOMER') return; // echo of our own message

    const text = (item['Content'] as string | undefined)?.trim() ?? '';
    const displayName = (item['DisplayName'] as string | undefined) ?? participantRole;
    const noise = BOT_ROLES.has(participantRole) && isFlowNoise(text);

    const msg: AdapterMessage = {
      role: BOT_ROLES.has(participantRole) ? 'agent' : 'system',
      content: text,
      displayName,
      isNoise: noise,
    };

    // Escalation keyword detection on agent messages
    if (msg.role === 'agent' && !noise && !this._escalationEvent) {
      for (const { re, reason } of ConnectChatAdapter.ESCALATION_PATTERNS) {
        if (re.test(msg.content)) {
          this._escalationEvent = {
            detectedAtTurn: this.messageQueue.length,
            trigger: 'text_keyword',
            detectedFrom: msg.content,
            reason,
          };
          console.log(`\n  ⚡ Escalation detected (${reason}): "${msg.content.substring(0, 80)}…"`);
          break;
        }
      }
    }

    // Deliver to waiting receivers (skip noise for them)
    if (!noise && this.messageResolvers.length > 0) {
      const resolver = this.messageResolvers.shift()!;
      resolver(msg);
      return;
    }

    this.messageQueue.push(msg);
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      try {
        this.ws?.send(JSON.stringify({ topic: 'aws/ping' }));
      } catch {
        // ignore
      }
    }, 30_000);
  }

  /** Drain flow noise — wait until queue is quiet for stableMs.
   *  Only noise-tagged messages are discarded; non-noise messages are kept in
   *  the queue for later consumption by the runner.
   */
  private async drainNoise(stableMs: number, maxWaitMs: number): Promise<void> {
    const deadline = Date.now() + maxWaitMs;
    let lastNoiseAt = Date.now();
    process.stdout.write('    [drain] waiting for flow');

    while (Date.now() < deadline) {
      await sleep(200);
      let drained = false;
      // Remove noise-only messages from the front of the queue
      while (this.messageQueue.length > 0 && this.messageQueue[0]!.isNoise) {
        this.messageQueue.shift();
        lastNoiseAt = Date.now();
        drained = true;
      }
      if (drained) process.stdout.write('.');
      // Exit once the queue has been quiet (no noise) for stableMs
      if (Date.now() - lastNoiseAt >= stableMs) break;
    }
    process.stdout.write('. done\n');
  }

  /** Wait for exactly one non-noise agent message (used to capture the greeting). */
  private receiveOne(timeoutMs: number): Promise<AdapterMessage | null> {
    return this.receive(timeoutMs);
  }

  private async simulateTyping(text: string): Promise<void> {
    const wordCount = Math.max(1, text.split(/\s+/).length);
    const baseSecs = (wordCount / this.config.typingWpm) * 60;
    const jitter = (Math.random() * 0.4 - 0.15) * baseSecs;
    const delaySecs = Math.max(0.5, baseSecs + jitter);

    process.stdout.write(`    ✍  typing (${wordCount} words, ~${delaySecs.toFixed(1)}s)... `);

    try {
      await this.participantClient.send(
        new SendEventCommand({
          ContentType: 'application/vnd.amazonaws.connect.event.typing',
          ConnectionToken: this.connectionToken!,
        }),
      );
    } catch {
      // non-fatal
    }

    await sleep(delaySecs * 1000);
    process.stdout.write('↵\n');
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
