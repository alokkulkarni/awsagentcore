// src/adapters/base.ts
// BaseAdapter interface — implemented by ConnectChatAdapter and ConnectVoiceAdapter

import type { Turn } from '../types/index.js';

export interface AdapterMessage {
  role: 'agent' | 'system';
  content: string;
  displayName?: string;
  isNoise: boolean;
  timestampMs?: number;
}

export class SessionEndedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SessionEndedError';
  }
}

export class AdapterError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AdapterError';
  }
}

export interface ConnectOptions {
  sessionId: string;
  customerId?: string;
  authenticated?: boolean;
  channel?: 'chat' | 'voice';
  scenarioName?: string;
}

export interface BaseAdapter {
  /** Runtime channel implemented by this adapter */
  readonly channel?: 'chat' | 'voice';

  /** Establish a session with the contact centre (start contact + open transport) */
  connect(options: ConnectOptions): Promise<void>;

  /** Send a customer message (simulates human typing if simulate=true) */
  sendMessage(content: string, simulateTyping?: boolean): Promise<void>;

  /**
   * Wait for the next agent message.
   * Returns null on timeout, throws SessionEndedError when the session closes.
   */
  receive(timeoutMs?: number): Promise<AdapterMessage | null>;

  /** Close the session cleanly */
  disconnect(): Promise<void>;

  /** Contact ID returned by Amazon Connect (available after connect()) */
  readonly contactId: string | null;
}
