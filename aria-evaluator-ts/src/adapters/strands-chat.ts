import { SignatureV4 } from '@smithy/signature-v4';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import { Hash } from '@smithy/hash-node';
import type { AdapterMessage, BaseAdapter, ConnectOptions } from './base.js';
import { AdapterError, SessionEndedError } from './base.js';

export type StrandsAuthType = 'none' | 'bearer' | 'sigv4';

export interface StrandsChatAdapterConfig {
  endpoint: string;
  method?: 'POST' | 'PUT';
  /** Authentication mode.
   *  - `none`   — no auth header (open endpoints, local dev)
   *  - `bearer` — Authorization: Bearer <token>  (API Gateway + Cognito/custom authorizer)
   *  - `sigv4`  — AWS Signature V4 (Bedrock AgentCore, Lambda function URLs, private API GW)
   */
  authType?: StrandsAuthType;
  authBearerToken?: string;
  /** AWS region for SigV4 signing.  Defaults to AWS_REGION env var or 'us-east-1'. */
  sigv4Region?: string;
  /** AWS service name for SigV4.  Defaults to 'bedrock-agentcore'. */
  sigv4Service?: string;
  messageField?: string;
  responseField?: string;
  headersJson?: string;
  historyField?: string;
  sessionIdField?: string;
}

/**
 * Chat adapter for Strands/AgentCore style HTTP invoke endpoints.
 * Works with RAG/chat agents as long as request/response field paths are configured.
 */
export class StrandsChatAdapter implements BaseAdapter {
  private readonly config: Required<Omit<StrandsChatAdapterConfig, 'authBearerToken' | 'sigv4Region' | 'sigv4Service' | 'authType'>> & {
    authType: StrandsAuthType;
    authBearerToken: string;
    sigv4Region: string;
    sigv4Service: string;
  };
  private readonly queue: AdapterMessage[] = [];
  private readonly resolvers: Array<(msg: AdapterMessage | null) => void> = [];
  private readonly history: Array<{ role: 'customer' | 'agent'; content: string }> = [];
  private sessionId = '';
  private ended = false;
  private connectOptions: ConnectOptions | null = null;

  constructor(config: StrandsChatAdapterConfig) {
    this.config = {
      endpoint: config.endpoint,
      method: config.method ?? 'POST',
      authType: config.authType ?? (config.authBearerToken ? 'bearer' : 'none'),
      authBearerToken: config.authBearerToken ?? '',
      sigv4Region: config.sigv4Region ?? process.env['AWS_REGION'] ?? 'us-east-1',
      sigv4Service: config.sigv4Service ?? 'bedrock-agentcore',
      messageField: config.messageField ?? 'prompt',
      responseField: config.responseField ?? 'result',
      headersJson: config.headersJson ?? '',
      historyField: config.historyField ?? 'history',
      sessionIdField: config.sessionIdField ?? 'sessionId',
    };
  }

  get channel(): 'chat' {
    return 'chat';
  }

  get contactId(): string | null {
    return this.sessionId || null;
  }

  async connect(options: ConnectOptions): Promise<void> {
    this.sessionId = options.sessionId;
    this.connectOptions = options;
    this.ended = false;
    this.history.length = 0;
    this.queue.length = 0;
  }

  async sendMessage(content: string): Promise<void> {
    if (!this.sessionId) throw new AdapterError('sendMessage called before connect()');
    if (this.ended) throw new SessionEndedError('Strands chat session ended');

    this.history.push({ role: 'customer', content });

    const baseHeaders: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this.config.headersJson) {
      try {
        Object.assign(baseHeaders, JSON.parse(this.config.headersJson) as Record<string, string>);
      } catch {
        throw new AdapterError('STRANDS_HEADERS_JSON must be valid JSON');
      }
    }

    const body: Record<string, unknown> = {
      channel: 'chat',
      customerId: this.connectOptions?.customerId ?? null,
      authenticated: this.connectOptions?.authenticated ?? false,
      scenarioName: this.connectOptions?.scenarioName ?? '',
    };
    body[this.config.messageField] = content;
    body[this.config.historyField] = this.history;
    body[this.config.sessionIdField] = this.sessionId;

    const bodyStr = JSON.stringify(body);
    let finalHeaders: Record<string, string>;

    if (this.config.authType === 'sigv4') {
      finalHeaders = await this.signSigV4(baseHeaders, bodyStr);
    } else {
      finalHeaders = {
        ...baseHeaders,
        ...(this.config.authType === 'bearer' && this.config.authBearerToken
          ? { Authorization: `Bearer ${this.config.authBearerToken}` }
          : {}),
      };
    }

    const resp = await fetch(this.config.endpoint, {
      method: this.config.method,
      headers: finalHeaders,
      body: bodyStr,
    });
    if (!resp.ok) {
      throw new AdapterError(`Strands endpoint failed (${resp.status})`);
    }

    const data = await resp.json() as Record<string, unknown>;
    const reply = extractStringField(data, this.config.responseField)
      || extractStringField(data, 'response')
      || extractStringField(data, 'output')
      || extractStringField(data, 'message');
    if (!reply) throw new AdapterError('Strands response missing text output');

    this.history.push({ role: 'agent', content: reply });
    this.push({
      role: 'agent',
      content: reply,
      isNoise: false,
      timestampMs: Date.now(),
    });
  }

  /** Sign a request with AWS Signature V4 using the default credential chain. */
  private async signSigV4(
    baseHeaders: Record<string, string>,
    body: string,
  ): Promise<Record<string, string>> {
    const url = new URL(this.config.endpoint);
    const signer = new SignatureV4({
      service: this.config.sigv4Service,
      region: this.config.sigv4Region,
      credentials: defaultProvider(),
      sha256: Hash.bind(null, 'sha256'),
    });

    const signed = await signer.sign({
      method: this.config.method,
      hostname: url.hostname,
      path: url.pathname + url.search,
      protocol: url.protocol,
      headers: {
        ...baseHeaders,
        host: url.hostname,
        'x-amz-date': new Date().toISOString().replace(/[:-]|\.\d{3}/g, '').slice(0, 15) + 'Z',
      },
      body,
    });

    return signed.headers as Record<string, string>;
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

function extractStringField(obj: Record<string, unknown>, path: string): string {
  const value = path.split('.').reduce<unknown>((acc, key) => {
    if (acc && typeof acc === 'object' && key in (acc as Record<string, unknown>)) {
      return (acc as Record<string, unknown>)[key];
    }
    return undefined;
  }, obj);
  return typeof value === 'string' ? value.trim() : '';
}
