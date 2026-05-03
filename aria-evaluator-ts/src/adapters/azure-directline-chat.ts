import type { AdapterMessage, BaseAdapter, ConnectOptions } from './base.js';
import { AdapterError, SessionEndedError } from './base.js';

interface DirectLineStartResponse {
  conversationId: string;
  token?: string;
  streamUrl?: string;
}

interface DirectLineActivitiesResponse {
  activities?: Array<{
    type?: string;
    text?: string;
    from?: { id?: string; role?: string };
    timestamp?: string;
  }>;
  watermark?: string;
}

export interface AzureDirectLineChatAdapterConfig {
  secret: string;
  endpoint?: string;
  userId?: string;
}

export class AzureDirectLineChatAdapter implements BaseAdapter {
  private readonly config: Required<AzureDirectLineChatAdapterConfig>;
  private conversationId: string | null = null;
  private watermark: string | undefined;
  private ended = false;

  constructor(config: AzureDirectLineChatAdapterConfig) {
    this.config = {
      secret: config.secret,
      endpoint: (config.endpoint ?? process.env['AZURE_DIRECT_LINE_ENDPOINT'] ?? 'https://directline.botframework.com/v3/directline').replace(/\/$/, ''),
      userId: config.userId ?? process.env['AZURE_DIRECT_LINE_USER_ID'] ?? 'aria-evaluator-user',
    };
  }

  get channel(): 'chat' {
    return 'chat';
  }

  get contactId(): string | null {
    return this.conversationId;
  }

  async connect(_options: ConnectOptions): Promise<void> {
    this.ended = false;
    this.watermark = undefined;

    const resp = await fetch(`${this.config.endpoint}/conversations`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${this.config.secret}`,
      },
    });
    if (!resp.ok) {
      throw new AdapterError(`Azure Direct Line start failed (${resp.status})`);
    }
    const data = await resp.json() as DirectLineStartResponse;
    if (!data.conversationId) throw new AdapterError('Azure Direct Line did not return conversationId');
    this.conversationId = data.conversationId;
  }

  async sendMessage(content: string): Promise<void> {
    if (!this.conversationId) throw new AdapterError('sendMessage called before connect()');
    if (this.ended) throw new SessionEndedError('Azure Direct Line session ended');

    const resp = await fetch(`${this.config.endpoint}/conversations/${this.conversationId}/activities`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${this.config.secret}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        type: 'message',
        from: { id: this.config.userId, role: 'user' },
        text: content,
      }),
    });
    if (!resp.ok) {
      throw new AdapterError(`Azure Direct Line send failed (${resp.status})`);
    }
  }

  async receive(timeoutMs = 40_000): Promise<AdapterMessage | null> {
    if (!this.conversationId) throw new AdapterError('receive called before connect()');
    if (this.ended) throw new SessionEndedError('Azure Direct Line session ended');

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const query = this.watermark ? `?watermark=${encodeURIComponent(this.watermark)}` : '';
      const resp = await fetch(`${this.config.endpoint}/conversations/${this.conversationId}/activities${query}`, {
        headers: {
          Authorization: `Bearer ${this.config.secret}`,
        },
      });
      if (!resp.ok) {
        throw new AdapterError(`Azure Direct Line receive failed (${resp.status})`);
      }
      const data = await resp.json() as DirectLineActivitiesResponse;
      if (data.watermark) this.watermark = data.watermark;

      const activity = (data.activities ?? []).find((a) =>
        a.type === 'message'
        && !!a.text
        && a.from?.id !== this.config.userId
      );

      if (activity?.text) {
        return {
          role: 'agent',
          content: activity.text,
          isNoise: false,
          timestampMs: activity.timestamp ? Date.parse(activity.timestamp) : Date.now(),
        };
      }
      await sleep(800);
    }

    return null;
  }

  async disconnect(): Promise<void> {
    this.ended = true;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
