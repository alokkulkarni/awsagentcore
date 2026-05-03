import WebSocket from 'ws';
import type { AdapterMessage, BaseAdapter, ConnectOptions } from './base.js';
import { AdapterError, SessionEndedError } from './base.js';

type VoiceProtocol = 'deepgram' | 'agentcore' | 'generic-json';

export interface CustomWebSocketVoiceAdapterConfig {
  url: string;
  protocol?: VoiceProtocol;
  authHeaderName?: string;
  authHeaderValue?: string;
  deepgramSettingsJson?: string;
  genericInitJson?: string;
  genericSendTemplate?: string;
  genericAgentEventTypes?: string;
  genericMessagePath?: string;
}

export class CustomWebSocketVoiceAdapter implements BaseAdapter {
  private readonly config: Required<CustomWebSocketVoiceAdapterConfig>;
  private ws: WebSocket | null = null;
  private ended = false;
  private endReason = 'Session ended';
  private sessionId = '';
  private queue: AdapterMessage[] = [];
  private resolvers: Array<(msg: AdapterMessage | null) => void> = [];
  private controlEventQueue: Array<Record<string, unknown>> = [];
  private controlEventResolvers: Array<(event: Record<string, unknown> | null) => void> = [];

  constructor(config: CustomWebSocketVoiceAdapterConfig) {
    this.config = {
      url: config.url,
      protocol: config.protocol ?? 'deepgram',
      authHeaderName: config.authHeaderName ?? '',
      authHeaderValue: config.authHeaderValue ?? '',
      deepgramSettingsJson: config.deepgramSettingsJson ?? '',
      genericInitJson: config.genericInitJson ?? '',
      genericSendTemplate: config.genericSendTemplate ?? '{"type":"message","content":"{{message}}"}',
      genericAgentEventTypes: config.genericAgentEventTypes ?? 'agent,assistant,message,ConversationText',
      genericMessagePath: config.genericMessagePath ?? 'content',
    };
  }

  get channel(): 'voice' {
    return 'voice';
  }

  get contactId(): string | null {
    return this.sessionId || null;
  }

  async connect(options: ConnectOptions): Promise<void> {
    this.sessionId = options.sessionId;
    this.ended = false;
    this.endReason = 'Session ended';
    this.queue = [];
    this.resolvers = [];
    this.controlEventQueue = [];
    this.controlEventResolvers = [];

    const headers: Record<string, string> = {};
    if (this.config.authHeaderName && this.config.authHeaderValue) {
      headers[this.config.authHeaderName] = this.config.authHeaderValue;
    }

    this.ws = new WebSocket(this.config.url, { headers });
    await waitForSocketOpen(this.ws, 12_000);

    this.ws.on('message', (data, isBinary) => this.handleWsMessage(data, isBinary));
    this.ws.on('close', (_code, reasonBuffer) => {
      this.ended = true;
      const reason = typeof reasonBuffer === 'string'
        ? reasonBuffer
        : Buffer.isBuffer(reasonBuffer) ? reasonBuffer.toString('utf-8') : '';
      this.endReason = reason || 'WebSocket closed';
      this.flushResolvers(null);
      this.flushControlResolvers(null);
    });
    this.ws.on('error', (err) => {
      this.ended = true;
      this.endReason = `WebSocket error: ${err.message}`;
      this.flushResolvers(null);
      this.flushControlResolvers(null);
    });

    if (this.config.protocol === 'deepgram') {
      await this.initializeDeepgram();
      return;
    }

    if (this.config.genericInitJson.trim()) {
      this.ws.send(this.config.genericInitJson);
    }
  }

  async sendMessage(content: string): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new AdapterError('Voice WebSocket is not connected');
    }
    if (this.ended) throw new SessionEndedError(this.endReason);

    if (this.config.protocol === 'deepgram') {
      this.ws.send(JSON.stringify({ type: 'InjectUserMessage', content }));
      return;
    }

    const payload = this.config.genericSendTemplate.replaceAll('{{message}}', escapeJsonString(content));
    this.ws.send(payload);
  }

  async receive(timeoutMs = 40_000): Promise<AdapterMessage | null> {
    if (this.queue.length > 0) return this.queue.shift()!;
    if (this.ended) throw new SessionEndedError(this.endReason);

    return new Promise<AdapterMessage | null>((resolve) => {
      const timer = setTimeout(() => {
        const idx = this.resolvers.indexOf(resolve);
        if (idx >= 0) this.resolvers.splice(idx, 1);
        resolve(null);
      }, timeoutMs);
      this.resolvers.push((msg) => {
        clearTimeout(timer);
        resolve(msg);
      });
    });
  }

  async disconnect(): Promise<void> {
    this.ended = true;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.close();
    }
    this.ws = null;
    this.flushResolvers(null);
    this.flushControlResolvers(null);
  }

  private async initializeDeepgram(): Promise<void> {
    const welcome = await this.waitForJsonEvent(['Welcome'], 15_000);
    if (!welcome) throw new AdapterError('Deepgram voice did not send Welcome');

    const settings = this.config.deepgramSettingsJson.trim()
      ? this.config.deepgramSettingsJson
      : JSON.stringify({
          type: 'Settings',
          audio: {
            input: { encoding: 'linear16', sample_rate: 16000 },
            output: { encoding: 'linear16', sample_rate: 24000, container: 'none' },
          },
          agent: {
            listen: { model: 'nova-3' },
            think: { provider: { type: 'open_ai' }, model: 'gpt-4o-mini' },
            speak: { model: 'aura-2-thalia-en' },
          },
        });
    this.ws!.send(settings);

    const applied = await this.waitForJsonEvent(['SettingsApplied'], 15_000);
    if (!applied) throw new AdapterError('Deepgram voice did not acknowledge SettingsApplied');
  }

  private handleWsMessage(data: WebSocket.RawData, isBinary: boolean): void {
    if (isBinary) return;

    const text = Buffer.isBuffer(data) ? data.toString('utf-8') : String(data);
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      return;
    }

    const type = typeof payload['type'] === 'string' ? payload['type'] : '';
    if (type) this.pushControl(payload);
    if (this.config.protocol === 'deepgram') {
      this.handleDeepgramEvent(type, payload);
      return;
    }
    this.handleGenericEvent(type, payload);
  }

  private handleDeepgramEvent(type: string, payload: Record<string, unknown>): void {
    if (type !== 'ConversationText') return;
    const role = String(payload['role'] ?? payload['speaker'] ?? payload['source'] ?? '').toLowerCase();
    if (role && (role.includes('user') || role.includes('customer'))) return;
    const text =
      asString(payload['content'])
      || asString(payload['text'])
      || asString(payload['message']);
    if (!text) return;
    this.push({
      role: 'agent',
      content: text,
      isNoise: false,
      timestampMs: Date.now(),
    });
  }

  private handleGenericEvent(type: string, payload: Record<string, unknown>): void {
    const allow = new Set(this.config.genericAgentEventTypes.split(',').map((s) => s.trim()).filter(Boolean));
    if (allow.size > 0 && type && !allow.has(type)) return;
    const text = extractPath(payload, this.config.genericMessagePath);
    if (!text) return;
    this.push({
      role: 'agent',
      content: text,
      isNoise: false,
      timestampMs: Date.now(),
    });
  }

  private push(msg: AdapterMessage): void {
    if (this.resolvers.length > 0) {
      const resolve = this.resolvers.shift()!;
      resolve(msg);
      return;
    }
    this.queue.push(msg);
  }

  private flushResolvers(msg: AdapterMessage | null): void {
    while (this.resolvers.length > 0) {
      const resolve = this.resolvers.shift()!;
      resolve(msg);
    }
  }

  private async waitForJsonEvent(types: string[], timeoutMs: number): Promise<Record<string, unknown> | null> {
    if (this.controlEventQueue.length > 0) {
      const match = this.controlEventQueue.find((evt) => types.includes(asString(evt['type'])));
      if (match) return match;
    }
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const evt = await this.nextControlEvent(Math.min(1_500, deadline - Date.now()));
      if (!evt) continue;
      const type = asString(evt['type']);
      if (type && types.includes(type)) return evt;
    }
    return null;
  }

  private pushControl(event: Record<string, unknown>): void {
    if (this.controlEventResolvers.length > 0) {
      const resolve = this.controlEventResolvers.shift()!;
      resolve(event);
      return;
    }
    this.controlEventQueue.push(event);
  }

  private nextControlEvent(timeoutMs: number): Promise<Record<string, unknown> | null> {
    if (this.controlEventQueue.length > 0) return Promise.resolve(this.controlEventQueue.shift()!);
    if (this.ended) return Promise.resolve(null);
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        const idx = this.controlEventResolvers.indexOf(resolve);
        if (idx >= 0) this.controlEventResolvers.splice(idx, 1);
        resolve(null);
      }, timeoutMs);
      this.controlEventResolvers.push((event) => {
        clearTimeout(timer);
        resolve(event);
      });
    });
  }

  private flushControlResolvers(event: Record<string, unknown> | null): void {
    while (this.controlEventResolvers.length > 0) {
      const resolve = this.controlEventResolvers.shift()!;
      resolve(event);
    }
  }
}

function waitForSocketOpen(ws: WebSocket, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new AdapterError('WebSocket connect timeout')), timeoutMs);
    ws.once('open', () => {
      clearTimeout(timer);
      resolve();
    });
    ws.once('error', (err) => {
      clearTimeout(timer);
      reject(new AdapterError(`WebSocket connect failed: ${err.message}`));
    });
  });
}

function extractPath(payload: Record<string, unknown>, path: string): string {
  const value = path.split('.').reduce<unknown>((acc, key) => {
    if (acc && typeof acc === 'object' && key in (acc as Record<string, unknown>)) {
      return (acc as Record<string, unknown>)[key];
    }
    return undefined;
  }, payload);
  return asString(value);
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function escapeJsonString(input: string): string {
  return JSON.stringify(input).slice(1, -1);
}
