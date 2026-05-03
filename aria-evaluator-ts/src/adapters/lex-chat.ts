import {
  LexRuntimeV2Client,
  RecognizeTextCommand,
} from '@aws-sdk/client-lex-runtime-v2';
import type { AdapterMessage, BaseAdapter, ConnectOptions } from './base.js';
import { AdapterError, SessionEndedError } from './base.js';

export interface LexChatAdapterConfig {
  botId: string;
  botAliasId: string;
  localeId: string;
  region?: string;
}

export class LexChatAdapter implements BaseAdapter {
  private readonly client: LexRuntimeV2Client;
  private readonly config: Required<LexChatAdapterConfig>;
  private readonly queue: AdapterMessage[] = [];
  private readonly resolvers: Array<(msg: AdapterMessage | null) => void> = [];
  private sessionId = '';
  private ended = false;

  constructor(config: LexChatAdapterConfig) {
    this.config = {
      botId: config.botId,
      botAliasId: config.botAliasId,
      localeId: config.localeId,
      region: config.region ?? process.env['LEX_REGION'] ?? process.env['AWS_REGION'] ?? 'eu-west-2',
    };
    this.client = new LexRuntimeV2Client({ region: this.config.region });
  }

  get channel(): 'chat' {
    return 'chat';
  }

  get contactId(): string | null {
    return null;
  }

  async connect(options: ConnectOptions): Promise<void> {
    this.sessionId = options.sessionId;
    this.ended = false;
    this.queue.length = 0;
  }

  async sendMessage(content: string): Promise<void> {
    if (!this.sessionId) throw new AdapterError('sendMessage called before connect()');
    if (this.ended) throw new SessionEndedError('Lex session has ended');

    const resp = await this.client.send(new RecognizeTextCommand({
      botId: this.config.botId,
      botAliasId: this.config.botAliasId,
      localeId: this.config.localeId,
      sessionId: this.sessionId,
      text: content,
    }));

    const messages = (resp.messages ?? [])
      .map((m) => m.content?.trim())
      .filter((m): m is string => !!m);
    const payload = messages.join('\n').trim();
    if (!payload) {
      this.push({
        role: 'agent',
        content: '[Lex returned no text response]',
        isNoise: false,
        timestampMs: Date.now(),
      });
      return;
    }
    this.push({
      role: 'agent',
      content: payload,
      isNoise: false,
      timestampMs: Date.now(),
    });
  }

  async receive(timeoutMs = 40_000): Promise<AdapterMessage | null> {
    if (this.queue.length > 0) return this.queue.shift()!;

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
    this.queue.length = 0;
    while (this.resolvers.length > 0) {
      const resolver = this.resolvers.shift()!;
      resolver(null);
    }
  }

  private push(msg: AdapterMessage): void {
    if (this.resolvers.length > 0) {
      const resolve = this.resolvers.shift()!;
      resolve(msg);
      return;
    }
    this.queue.push(msg);
  }
}
