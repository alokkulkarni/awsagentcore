// src/adapters/connect-webrtc.ts
// ConnectWebRTCAdapter — AWS-native voice evaluation via StartWebRTCContact
//
// Architecture:
//   1. AWS Connect StartWebRTCContact → Chime Meeting + Attendee credentials
//   2. @roamhq/wrtc provides RTCPeerConnection in Node.js (no browser needed)
//   3. amazon-chime-sdk-js handles Chime WebSocket signaling + SDP negotiation
//   4. RTCAudioSource injects Polly TTS PCM → the agent hears the customer
//   5. RTCAudioSink captures the agent's PCM → Amazon Transcribe Streaming → text
//
// No Playwright, no widget, no approved origins, no getUserMedia headaches.

// ── Node.js shims BEFORE any Chime SDK import ─────────────────────────────────
// These globals must exist before amazon-chime-sdk-js is first evaluated.
import wrtcModule from '@roamhq/wrtc';
import WebSocket from 'ws';

const wrtc = wrtcModule as typeof import('@roamhq/wrtc') & {
  RTCRtpSender: typeof RTCRtpSender;
  RTCRtpReceiver: typeof RTCRtpReceiver;
  RTCRtpTransceiver: typeof RTCRtpTransceiver;
  RTCDtlsTransport: typeof RTCDtlsTransport;
  RTCIceTransport: typeof RTCIceTransport;
  RTCSctpTransport: typeof RTCSctpTransport;
  nonstandard?: {
    RTCAudioSource: new () => {
      createTrack(): MediaStreamTrack;
      onData(data: {
        samples: Int16Array;
        sampleRate: number;
        bitsPerSample: number;
        channelCount: number;
        numberOfFrames: number;
      }): void;
    };
    RTCAudioSink: new (track: MediaStreamTrack) => {
      ondata: ((data: {
        samples: Int16Array;
        sampleRate: number;
        bitsPerSample: number;
        channelCount: number;
        numberOfFrames: number;
      }) => void) | null;
      stop(): void;
    };
  };
};

// Capture the RTCPeerConnection created by Chime SDK so we can attach RTCAudioSink
let _chimePCCallback: ((pc: RTCPeerConnection) => void) | null = null;
const OriginalRTCPC = wrtc.RTCPeerConnection as unknown as new (
  config?: RTCConfiguration,
) => RTCPeerConnection;

class TrackedRTCPeerConnection extends OriginalRTCPC {
  constructor(config?: RTCConfiguration) {
    super(config);
    if (_chimePCCallback) _chimePCCallback(this as unknown as RTCPeerConnection);
  }
}

const g = globalThis as Record<string, unknown>;
g['RTCPeerConnection'] = TrackedRTCPeerConnection;
g['RTCSessionDescription'] = wrtc.RTCSessionDescription;
g['RTCIceCandidate'] = wrtc.RTCIceCandidate;
g['MediaStream'] = wrtc.MediaStream;
g['MediaStreamTrack'] = wrtc.MediaStreamTrack;
// Remaining WebRTC classes needed by the Chime SDK
g['RTCRtpSender'] = wrtc.RTCRtpSender;
g['RTCRtpReceiver'] = wrtc.RTCRtpReceiver;
g['RTCRtpTransceiver'] = wrtc.RTCRtpTransceiver;
g['RTCDtlsTransport'] = wrtc.RTCDtlsTransport;
g['RTCIceTransport'] = wrtc.RTCIceTransport;
g['RTCSctpTransport'] = wrtc.RTCSctpTransport;
// Use the ws implementation for Node; it's more battle-tested for Chime signaling
// than the built-in WHATWG WebSocket in newer Node runtimes.
g['WebSocket'] = WebSocket;

// window alias (Chime SDK checks window.RTCPeerConnection in some paths)
if (!g['window']) g['window'] = g;

// document stub — DefaultBrowserBehavior accesses document.createElement
if (!g['document']) {
  g['document'] = {
    createElement: () => ({ style: {} }),
    getElementById: () => null,
    addEventListener: () => {},
    removeEventListener: () => {},
    querySelectorAll: () => [],
    body: { appendChild: () => {}, removeChild: () => {} },
  };
}

// location stub
if (!g['location']) {
  g['location'] = { href: 'http://localhost/', hostname: 'localhost', protocol: 'http:' };
}

// AudioContext stub — DefaultDeviceController(enableWebAudio:false) normally skips
// this, but we provide a safe stub for any code path that checks for its existence.
if (!g['AudioContext']) {
  g['AudioContext'] = class StubAudioContext {
    state = 'running';
    sampleRate = 48_000;
    destination = {};
    close(): Promise<void> { return Promise.resolve(); }
    resume(): Promise<void> { return Promise.resolve(); }
    suspend(): Promise<void> { return Promise.resolve(); }
    createAnalyser() { return { getFloatTimeDomainData() {}, fftSize: 256, frequencyBinCount: 128 }; }
    createGain() { return { connect() {}, disconnect() {}, gain: { value: 1 } }; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createMediaStreamDestination() { return { stream: new (wrtc.MediaStream as unknown as new () => MediaStream)() }; }
    createOscillator() { return { connect() {}, start() {}, stop() {}, frequency: { value: 440 } }; }
    createDynamicsCompressor() { return { connect() {}, disconnect() {}, threshold: { value: -24 }, knee: { value: 30 }, ratio: { value: 12 }, attack: { value: 0.003 }, release: { value: 0.25 } }; }
  };
}

// navigator.mediaDevices — Node.js 25 has navigator as a getter-only property;
// use Object.defineProperty to add mediaDevices without reassigning navigator itself.
{
  const mediaDevicesStub = {
    getUserMedia: async () => new (wrtc.MediaStream as unknown as new () => MediaStream)(),
    enumerateDevices: async () => [],
    getSupportedConstraints: () => ({}),
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  };
  try {
    if (typeof navigator !== 'undefined' && !navigator.mediaDevices) {
      Object.defineProperty(navigator, 'mediaDevices', {
        value: mediaDevicesStub, writable: true, configurable: true,
      });
    } else if (typeof navigator === 'undefined') {
      g['navigator'] = { userAgent: 'Node.js', mediaDevices: mediaDevicesStub };
    } else if (navigator.mediaDevices && !navigator.mediaDevices.getSupportedConstraints) {
      (navigator.mediaDevices as unknown as Record<string, unknown>)['getSupportedConstraints'] = () => ({});
    }
  } catch {
    // navigator is fully frozen — ignore, Chime SDK will work without it
  }
}

// ── AWS SDK imports ────────────────────────────────────────────────────────────
import {
  ConnectClient,
  StartWebRTCContactCommand,
  DescribeContactCommand,
} from '@aws-sdk/client-connect';
import type { Meeting, Attendee } from '@aws-sdk/client-connect';
import type { EscalationEvent, EscalationReason } from '../types/index.js';
import {
  PollyClient,
  SynthesizeSpeechCommand,
} from '@aws-sdk/client-polly';
import type { VoiceId } from '@aws-sdk/client-polly';
import {
  TranscribeStreamingClient,
  StartStreamTranscriptionCommand,
} from '@aws-sdk/client-transcribe-streaming';
import { randomUUID } from 'node:crypto';
import { PassThrough } from 'node:stream';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

// ── Chime SDK (CJS, imported after globals are set) ───────────────────────────
import {
  DefaultMeetingSession,
  MeetingSessionConfiguration,
  DefaultDeviceController,
  ConsoleLogger,
  LogLevel,
} from 'amazon-chime-sdk-js';

import type { BaseAdapter, AdapterMessage, ConnectOptions } from './base.js';
import { AdapterError, SessionEndedError } from './base.js';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface WebRTCAdapterConfig {
  instanceId: string;
  contactFlowId: string;
  region?: string;
  displayName?: string;
}

interface AudioDataFrame {
  samples: Int16Array;
  sampleRate: number;
  bitsPerSample: number;
  channelCount: number;
  numberOfFrames: number;
}

interface RecordedAudioSlice {
  startMs: number;
  samples: Int16Array;
  sampleRate: number;
}

// ── Filtered Chime logger ─────────────────────────────────────────────────────
// Suppress noisy health-check WARNs that don't affect functionality.
class FilteredChimeLogger extends ConsoleLogger {
  override warn(msg: string): void {
    if (
      msg.includes('Sending Audio is unhealthy') ||
      msg.includes('SendingAudioFailure health policy') ||
      msg.includes('browser is not currently supported') ||
      msg.includes('will reconnect due to status code TaskFailed') ||
      msg.includes('[AudioRed] Encoded insertable streams not supported')
    ) {
      return; // suppress
    }
    super.warn(msg);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function buildWavHeader(dataByteLength: number, sampleRate: number): Buffer {
  const header = Buffer.alloc(44);
  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = sampleRate * numChannels * (bitsPerSample / 8);
  const blockAlign = numChannels * (bitsPerSample / 8);

  header.write('RIFF', 0, 'ascii');
  header.writeUInt32LE(36 + dataByteLength, 4);
  header.write('WAVE', 8, 'ascii');
  header.write('fmt ', 12, 'ascii');
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(numChannels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write('data', 36, 'ascii');
  header.writeUInt32LE(dataByteLength, 40);
  return header;
}

function pcmBufferToInt16Copy(pcmBuffer: Buffer): Int16Array {
  const view = new Int16Array(
    pcmBuffer.buffer,
    pcmBuffer.byteOffset,
    Math.floor(pcmBuffer.byteLength / 2),
  );
  return new Int16Array(view);
}

function resamplePcmInt16(input: Int16Array, inRate: number, outRate: number): Int16Array {
  if (input.length === 0) return input;
  if (inRate === outRate) return new Int16Array(input);

  const outputLength = Math.max(1, Math.round((input.length * outRate) / inRate));
  const out = new Int16Array(outputLength);
  const ratio = inRate / outRate;
  for (let i = 0; i < outputLength; i++) {
    const srcPos = i * ratio;
    const idx = Math.floor(srcPos);
    const frac = srcPos - idx;
    const s0 = input[idx] ?? input[input.length - 1] ?? 0;
    const s1 = input[idx + 1] ?? s0;
    out[i] = Math.round(s0 + (s1 - s0) * frac);
  }
  return out;
}

function applyNoiseGateInt16(input: Int16Array, thresholdPcm: number): Int16Array {
  if (input.length === 0 || thresholdPcm <= 0) return new Int16Array(input);
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const v = input[i] ?? 0;
    out[i] = Math.abs(v) < thresholdPcm ? 0 : v;
  }
  return out;
}

// Convenience types to avoid complex ReturnType<Constructor> gymnastics
interface AudioSource {
  createTrack(): MediaStreamTrack;
  onData(data: AudioDataFrame): void;
}

interface AudioSink {
  ondata: ((data: AudioDataFrame) => void) | null;
  stop(): void;
}

export class ConnectWebRTCAdapter implements BaseAdapter {
  private readonly connectClient: ConnectClient;
  private readonly pollyClient: PollyClient;
  private readonly transcribeClient: TranscribeStreamingClient;
  private readonly config: Required<WebRTCAdapterConfig>;

  private _contactId: string | null = null;
  private sessionEnded = false;
  private sessionEndReason: string | null = null;
  private meetingSession: DefaultMeetingSession | null = null;

  // Audio pipeline
  private audioSource: AudioSource | null = null;
  private audioSink: AudioSink | null = null;
  private transcribeInput: PassThrough | null = null;

  // Transcript delivery
  private receiveQueue: AdapterMessage[] = [];
  private receiveResolvers: Array<(msg: AdapterMessage | null) => void> = [];

  // Speech detection state
  private speechState: 'idle' | 'speaking' = 'idle';
  private speechText = '';
  private speechPartialText = '';
  private speechStartMs = 0;
  private speechLastActiveMs = 0;
  private silenceTimer: ReturnType<typeof setTimeout> | null = null;
  private audioSinkPollTimer: ReturnType<typeof setInterval> | null = null;

  private readonly SPEECH_THRESHOLD = 0.008; // ~-42dBFS
  private readonly SILENCE_GAP_MS = 1_800;
  private readonly MIN_SPEECH_MS = 300;
  private readonly SAVED_AUDIO_SAMPLE_RATE = 16_000;
  private readonly AUDIO_NOISE_GATE_PCM = (() => {
    const raw = Number.parseInt(process.env['VOICE_AUDIO_NOISE_GATE_PCM'] ?? '180', 10);
    return Number.isFinite(raw) && raw > 0 ? raw : 180;
  })();
  private readonly MIX_TRACK_GAIN = 0.6;

  // Call recording (agent inbound + customer outbound)
  private readonly recordedAgentSlices: RecordedAudioSlice[] = [];
  private readonly recordedCustomerSlices: RecordedAudioSlice[] = [];

  // Escalation detection
  private _escalationEvent: EscalationEvent | null = null;

  /** Opening greeting captured during connect() — exposed so runner can record it as turn 0 */
  private _openingGreeting: AdapterMessage | null = null;

  // Phrases the agent uses when transferring to a human agent (case-insensitive)
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

  constructor(config: WebRTCAdapterConfig) {
    this.config = {
      instanceId: config.instanceId,
      contactFlowId: config.contactFlowId,
      region: config.region ?? 'eu-west-2',
      displayName: config.displayName ?? 'Customer',
    };
    this.connectClient = new ConnectClient({ region: this.config.region });
    this.pollyClient = new PollyClient({ region: this.config.region });
    this.transcribeClient = new TranscribeStreamingClient({ region: this.config.region });
  }

  get channel(): 'voice' {
    return 'voice';
  }

  get contactId(): string | null { return this._contactId; }
  get escalationEvent(): EscalationEvent | null { return this._escalationEvent; }
  get openingGreeting(): AdapterMessage | null { return this._openingGreeting; }
  get lastSessionEndReason(): string | null { return this.sessionEndReason; }
  hasAudio(): boolean {
    return this.recordedAgentSlices.length > 0 || this.recordedCustomerSlices.length > 0;
  }

  saveAudio(outputPath: string): string {
    if (!this.hasAudio()) {
      throw new AdapterError('No audio captured');
    }

    const normalizedSlices: RecordedAudioSlice[] = [
      ...this.recordedAgentSlices,
      ...this.recordedCustomerSlices,
    ].map((slice) => ({
      startMs: slice.startMs,
      sampleRate: this.SAVED_AUDIO_SAMPLE_RATE,
      samples: resamplePcmInt16(slice.samples, slice.sampleRate, this.SAVED_AUDIO_SAMPLE_RATE),
    }));

    const allSlices: RecordedAudioSlice[] = normalizedSlices.filter((slice) => slice.samples.length > 0);
    if (allSlices.length === 0) {
      throw new AdapterError('No audio captured');
    }

    const firstStartMs = Math.min(...allSlices.map((slice) => slice.startMs));
    const totalSamples = Math.max(
      1,
      ...allSlices.map((slice) => {
        const offset = Math.max(
          0,
          Math.round(((slice.startMs - firstStartMs) * this.SAVED_AUDIO_SAMPLE_RATE) / 1000),
        );
        return offset + slice.samples.length;
      }),
    );
    const mix = new Float32Array(totalSamples);
    const gainPerTrack = this.MIX_TRACK_GAIN;

    for (const slice of allSlices) {
      const offset = Math.max(
        0,
        Math.round(((slice.startMs - firstStartMs) * this.SAVED_AUDIO_SAMPLE_RATE) / 1000),
      );
      for (let i = 0; i < slice.samples.length; i++) {
        const idx = offset + i;
        if (idx >= mix.length) break;
        const current = mix[idx] ?? 0;
        mix[idx] = current + (slice.samples[i] ?? 0) * gainPerTrack;
      }
    }

    const mixedInt16 = new Int16Array(mix.length);
    for (let i = 0; i < mix.length; i++) {
      const sample = Math.round(mix[i] ?? 0);
      const v = Math.abs(sample) < this.AUDIO_NOISE_GATE_PCM ? 0 : sample;
      mixedInt16[i] = v > 32767 ? 32767 : v < -32768 ? -32768 : v;
    }
    const pcmData = Buffer.from(mixedInt16.buffer);
    const wav = Buffer.concat([
      buildWavHeader(pcmData.byteLength, this.SAVED_AUDIO_SAMPLE_RATE),
      pcmData,
    ]);
    mkdirSync(dirname(outputPath), { recursive: true });
    writeFileSync(outputPath, wav);
    return outputPath;
  }

  // ── connect ────────────────────────────────────────────────────────────────

  async connect(options: ConnectOptions): Promise<void> {
    const rawMaxAttempts = Number.parseInt(process.env['CONNECT_WEBRTC_CONNECT_ATTEMPTS'] ?? '2', 10);
    const maxAttempts = Number.isFinite(rawMaxAttempts) && rawMaxAttempts > 0 ? rawMaxAttempts : 2;
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        await this.connectOnce(options);
        return;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        lastError = error;
        const canRetry = attempt < maxAttempts && this.shouldRetryConnectError(error);
        if (!canRetry) throw error;

        console.warn(`  ⚠  WebRTC connect attempt ${attempt}/${maxAttempts} failed: ${error.message}`);
        this.resetAfterFailedConnect();
        const backoffMs = attempt * 1_500;
        console.log(`  ↻ Retrying with a new WebRTC contact in ${(backoffMs / 1000).toFixed(1)}s…`);
        await sleep(backoffMs);
      }
    }

    throw (lastError ?? new AdapterError('WebRTC connect failed'));
  }

  private async connectOnce(options: ConnectOptions): Promise<void> {
    const {
      customerId,
      authenticated = false,
      channel = 'voice',
      scenarioName = '',
    } = options;

    this.sessionEnded = false;
    this.sessionEndReason = null;
    this._openingGreeting = null;
    this._escalationEvent = null;
    this.receiveQueue = [];
    this.clearAudioSinkPoll();
    this.speechState = 'idle';
    this.speechText = '';
    this.speechPartialText = '';
    this.speechStartMs = 0;
    this.speechLastActiveMs = 0;
    this.recordedAgentSlices.length = 0;
    this.recordedCustomerSlices.length = 0;
    for (const r of this.receiveResolvers) r(null);
    this.receiveResolvers = [];

    console.log(`  📡 Starting WebRTC contact…`);
    console.log(`     Flow   : ${this.config.contactFlowId}`);
    console.log(`     Customer: ${customerId ?? 'anonymous'} (auth=${authenticated})`);

    // 1. Create the WebRTC contact — returns Chime meeting + attendee credentials
    const startResp = await this.connectClient.send(
      new StartWebRTCContactCommand({
        InstanceId: this.config.instanceId,
        ContactFlowId: this.config.contactFlowId,
        ClientToken: randomUUID(),
        ParticipantDetails: { DisplayName: this.config.displayName },
        Attributes: {
          customerId: customerId ?? '',
          authStatus: authenticated ? 'authenticated' : 'unauthenticated',
          evaluationScenario: scenarioName,
          channel,
          locale: 'en-GB',
          ...(authenticated && customerId
            ? {
                // SESSION_START equivalent for voice — tells the agent the customer is authed
                sessionStart: `SESSION_START authenticated ${customerId}`,
              }
            : {}),
        },
      }),
    );

    this._contactId = startResp.ContactId!;
    const connectionData = startResp.ConnectionData!;
    console.log(`  ✓  Contact created | contactId=${this._contactId}`);

    // 2. Prepare the Chime RTCAudioSource (our microphone)
    const { RTCAudioSource, RTCAudioSink } = wrtc.nonstandard!;
    this.audioSource = new RTCAudioSource();
    const micTrack = this.audioSource.createTrack();
    const micStream = new (wrtc.MediaStream as unknown as new (
      tracks: MediaStreamTrack[],
    ) => MediaStream)([micTrack]);

    // 3. Set up RTCPeerConnection intercept so we can attach RTCAudioSink later
    let capturedPC: RTCPeerConnection | null = null;
    _chimePCCallback = (pc) => { capturedPC = pc; };
    const attachAudioSink = (phase: 'initial' | 'reconnected' | 'delayed') => {
      if (!capturedPC) return false;
      const audioRx = capturedPC
        .getReceivers()
        .find((r: RTCRtpReceiver) => r.track?.kind === 'audio');
      if (!audioRx) return false;

      if (this.audioSink) {
        try {
          this.audioSink.stop();
        } catch (err) {
          console.debug(`  ℹ  audioSink.stop() during reattach: ${this.formatUnknownError(err)}`);
        }
      }

      this.audioSink = new RTCAudioSink(audioRx.track);
      this.audioSink.ondata = (frame: AudioDataFrame) => {
        this.onAudioData(frame);
      };
      this.clearAudioSinkPoll();
      const tag = phase === 'reconnected' ? ' (reconnected)' : phase === 'delayed' ? ' (delayed)' : '';
      console.log(`  ✓  RTCAudioSink attached${tag} — listening for agent speech`);
      return true;
    };
    const ensureAudioSinkAttached = (phase: 'initial' | 'reconnected') => {
      if (attachAudioSink(phase)) return;
      console.warn(`  ⚠  No audio receiver found — waiting for track`);
      this.clearAudioSinkPoll();
      this.audioSinkPollTimer = setInterval(() => {
        void attachAudioSink('delayed');
      }, 500);
      setTimeout(() => this.clearAudioSinkPoll(), 10_000);
    };

    // 4. Build Chime meeting session
    const logger = new FilteredChimeLogger('ARIA-Chime', LogLevel.WARN);
    const deviceController = new DefaultDeviceController(logger, { enableWebAudio: false } as never);

    // Log what Connect returned so we can verify the structure
    console.log(`  ℹ  Meeting data: ${JSON.stringify({
      MeetingId: (connectionData.Meeting as Record<string, unknown>)?.['MeetingId'],
      SignalingUrl: ((connectionData.Meeting as Record<string, unknown>)?.['MediaPlacement'] as Record<string, unknown>)?.['SignalingUrl'],
      TurnControlUrl: ((connectionData.Meeting as Record<string, unknown>)?.['MediaPlacement'] as Record<string, unknown>)?.['TurnControlUrl'],
    })}`);

    const meetingResp = { Meeting: connectionData.Meeting as unknown as Meeting };
    const attendeeResp = { Attendee: connectionData.Attendee as unknown as Attendee };

    const configuration = new MeetingSessionConfiguration(
      meetingResp as never,
      attendeeResp as never,
    );

    const session = new DefaultMeetingSession(configuration, logger, deviceController);
    this.meetingSession = session;

    // 5. Set microphone input to our custom stream (Polly audio)
    session.audioVideo.setDeviceLabelTrigger(() => Promise.resolve(micStream));
    await session.audioVideo.startAudioInput(micStream as never);

    // 6. Wait for connection + capture remote audio track
    let resolved = false;
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        if (!resolved) reject(new AdapterError('Chime audioVideoDidStart timed out after 60s'));
      }, 60_000);

      session.audioVideo.addObserver({
        audioVideoDidStartConnecting: (reconnecting: boolean) => {
          console.log(`  ✓  Chime signaling connecting (reconnecting=${reconnecting})`);
        },

        audioVideoDidStart: () => {
          const reconnecting = resolved;
          if (!resolved) {
            resolved = true;
            clearTimeout(timeout);
            console.log(`  ✓  Chime meeting connected (contactId=${this._contactId})`);
          } else {
            console.log(`  ✓  Chime media reconnected`);
          }

          ensureAudioSinkAttached(reconnecting ? 'reconnected' : 'initial');

          if (!reconnecting) resolve();
        },

        audioVideoDidStop: (status) => {
          const statusInfo = status as {
            statusCode?: () => unknown;
            isTerminal?: () => boolean;
          };
          const statusText = String(status);
          const statusCode = typeof statusInfo.statusCode === 'function'
            ? String(statusInfo.statusCode())
            : statusText;
          const isTerminal = typeof statusInfo.isTerminal === 'function'
            ? statusInfo.isTerminal()
            : true;
          if (statusText && statusText !== statusCode) {
            console.log(`  ℹ  Chime session stopped: ${statusText} (code=${statusCode})`);
          } else {
            console.log(`  ℹ  Chime session stopped: ${statusCode}`);
          }

          if (resolved && !isTerminal) {
            console.warn(`  ⚠  Chime stop was non-terminal; waiting for reconnect`);
            return;
          }

          this.flushPendingSpeech('session stop');
          this.sessionEndReason = statusText && statusText !== 'undefined'
            ? statusText
            : `status_code_${statusCode}`;
          this.sessionEnded = true;
          if (!resolved) {
            resolved = true;
            clearTimeout(timeout);
            reject(new AdapterError(`Chime session stopped before connecting: ${statusText}`));
          }
          for (const r of this.receiveResolvers) r(null);
          this.receiveResolvers = [];
        },

        connectionDidBecomeGood: () => console.log(`  ✓  Chime connection good`),
        connectionDidBecomePoor: () => console.warn(`  ⚠  Chime connection poor`),
      });

      try {
        session.audioVideo.start();
        console.log(`  ⏳ Waiting for Chime connection…`);
      } catch (err) {
        resolved = true;
        clearTimeout(timeout);
        reject(new AdapterError(`session.audioVideo.start() threw: ${(err as Error).message}`));
      }
    });

    // 7. Start Transcribe Streaming (runs in background for whole conversation)
    this.transcribeInput = new PassThrough();
    void this.runTranscribeLoop();

    // 8. Wait for the agent's opening greeting before allowing the runner to send
    //    the first customer message. For this flow, greeting-first is preferred
    //    but no longer hard-required by default.
    const rawGreetingTimeoutMs = Number.parseInt(
      process.env['VOICE_INITIAL_GREETING_TIMEOUT_MS'] ?? '120000',
      10,
    );
    const greetingTimeoutMs = Number.isFinite(rawGreetingTimeoutMs) && rawGreetingTimeoutMs > 0
      ? rawGreetingTimeoutMs
      : 120_000;
    const rawGreetingFollowupMs = Number.parseInt(
      process.env['VOICE_GREETING_FOLLOWUP_TIMEOUT_MS'] ?? '6000',
      10,
    );
    const greetingFollowupMs = Number.isFinite(rawGreetingFollowupMs) && rawGreetingFollowupMs > 0
      ? rawGreetingFollowupMs
      : 6_000;
    const requireOpeningGreeting = process.env['VOICE_REQUIRE_OPENING_GREETING'] === 'true';

    console.log(`  ⏳ Waiting for agent opening greeting…`);
    const opening = await this.receive(greetingTimeoutMs);
    if (!opening) {
      if (this.sessionEnded) {
        throw new AdapterError(`Session ended before agent greeting: ${this.sessionEndReason ?? 'unknown'}`);
      }
      if (requireOpeningGreeting) {
        throw new AdapterError(
          `No agent opening greeting received within ${Math.round(greetingTimeoutMs / 1000)}s`,
        );
      }
      console.log('  ℹ  No immediate greeting — agent will greet after first customer message');
      await sleep(200);
      return;
    }

    let greetingContent = opening.content;
    while (true) {
      const extra = await this.receive(greetingFollowupMs);
      if (!extra) break;
      greetingContent += `\n${extra.content}`;
    }
    this._openingGreeting = { ...opening, content: greetingContent };
    console.log(
      `  ✓  Opening greeting: "${greetingContent.slice(0, 80)}${greetingContent.length > 80 ? '…' : ''}"`,
    );
    await sleep(400);
  }

  private shouldRetryConnectError(error: Error): boolean {
    const msg = error.message.toLowerCase();
    return (
      msg.includes('chime session stopped before connecting') ||
      msg.includes('meeting ended') ||
      msg.includes('meeting unavailable') ||
      msg.includes('websocket') ||
      msg.includes('timed out')
    );
  }

  private resetAfterFailedConnect(): void {
    if (this.silenceTimer) {
      clearTimeout(this.silenceTimer);
      this.silenceTimer = null;
    }
    this.clearAudioSinkPoll();
    if (this.audioSink) {
      try {
        this.audioSink.stop();
      } catch (err) {
        console.debug(`  ℹ  audioSink.stop() during retry cleanup: ${(err as Error).message}`);
      }
      this.audioSink = null;
    }
    if (this.transcribeInput) {
      try {
        this.transcribeInput.destroy();
      } catch (err) {
        console.debug(`  ℹ  transcribeInput.destroy() during retry cleanup: ${(err as Error).message}`);
      }
      this.transcribeInput = null;
    }
    if (this.meetingSession) {
      try {
        this.meetingSession.audioVideo.stop();
      } catch (err) {
        console.debug(`  ℹ  meetingSession.stop() during retry cleanup: ${(err as Error).message}`);
      }
      this.meetingSession = null;
    }
    this.audioSource = null;
    this.sessionEnded = false;
    this.sessionEndReason = null;
    this._contactId = null;
    this._openingGreeting = null;
    this._escalationEvent = null;
    this.speechState = 'idle';
    this.speechText = '';
    this.speechPartialText = '';
    this.speechStartMs = 0;
    this.speechLastActiveMs = 0;
    this.recordedAgentSlices.length = 0;
    this.recordedCustomerSlices.length = 0;
    this.clearAudioSinkPoll();
    this.receiveQueue = [];
    for (const r of this.receiveResolvers) r(null);
    this.receiveResolvers = [];
    _chimePCCallback = null;
  }

  private clearAudioSinkPoll(): void {
    if (this.audioSinkPollTimer) {
      clearInterval(this.audioSinkPollTimer);
      this.audioSinkPollTimer = null;
    }
  }

  private formatUnknownError(err: unknown): string {
    if (err instanceof Error) {
      return err.message || err.name;
    }
    try {
      const json = JSON.stringify(err);
      if (json && json !== '{}') return json;
    } catch {
      // fall through
    }
    return String(err);
  }

  // ── sendMessage ────────────────────────────────────────────────────────────

  async sendMessage(text: string, simulateTyping = true): Promise<void> {
    if (this.sessionEnded) {
      const reason = this.sessionEndReason ? `: ${this.sessionEndReason}` : '';
      throw new SessionEndedError(`WebRTC session has ended${reason}`);
    }
    if (!this.audioSource) throw new AdapterError('sendMessage called before connect()');

    if (simulateTyping) {
      const wordCount = Math.max(1, text.split(/\s+/).length);
      // Speaking rate: ~130 wpm for a realistic human phone call
      const baseSecs = (wordCount / 130) * 60;
      const jitter = (Math.random() * 0.3 - 0.1) * baseSecs;
      const delaySecs = Math.max(0.5, baseSecs + jitter);
      process.stdout.write(
        `  🎤 Speaking "${text.substring(0, 50)}${text.length > 50 ? '…' : ''}" (~${delaySecs.toFixed(1)}s)… `,
      );
      await sleep(delaySecs * 1000);
      process.stdout.write('✓\n');
    }

    const pcm = await this.synthesize(text);
    this.recordedCustomerSlices.push({
      startMs: Date.now(),
      sampleRate: 16_000,
      samples: pcmBufferToInt16Copy(pcm),
    });
    await this.injectAudio(pcm);

    // Inject a silence tail so Connect's VAD gets a clean speech→silence
    // transition. On ECS (same AWS region as Connect), audio arrives with
    // near-zero latency; without a silence tail the audio ends abruptly,
    // Transcribe finalises early on a partial utterance, and the Lambda is
    // called twice (acknowledgment + filler) instead of once with the full
    // customer request. Default 700ms; tune via VOICE_POST_SPEECH_SILENCE_MS.
    const silenceMs = Number.parseInt(process.env['VOICE_POST_SPEECH_SILENCE_MS'] ?? '700', 10);
    if (silenceMs > 0) await this.injectSilence(silenceMs);
  }

  // ── receive ────────────────────────────────────────────────────────────────

  async receive(timeoutMs = 45_000): Promise<AdapterMessage | null> {
    // Check pre-queued messages
    const queued = this.receiveQueue.shift();
    if (queued) return queued;
    if (this.sessionEnded) return null;

    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        const idx = this.receiveResolvers.indexOf(resolve);
        if (idx !== -1) this.receiveResolvers.splice(idx, 1);
        resolve(null);
      }, timeoutMs);

      const wrapped = (msg: AdapterMessage | null) => {
        clearTimeout(timer);
        resolve(msg);
      };

      this.receiveResolvers.push(wrapped);
    });
  }

  // ── disconnect ─────────────────────────────────────────────────────────────

  async disconnect(): Promise<void> {
    this.sessionEnded = true;

    if (this.silenceTimer) {
      clearTimeout(this.silenceTimer);
      this.silenceTimer = null;
    }
    this.clearAudioSinkPoll();
    if (this.audioSink) {
      try { this.audioSink.stop(); } catch { /* ignore */ }
      this.audioSink = null;
    }
    if (this.transcribeInput) {
      try { this.transcribeInput.destroy(); } catch { /* ignore */ }
      this.transcribeInput = null;
    }
    if (this.meetingSession) {
      try { this.meetingSession.audioVideo.stop(); } catch { /* ignore */ }
      this.meetingSession = null;
    }

    // Fetch contact attributes from Connect — the Contact Flow may have set
    // escalation metadata (e.g. escalationReason, escalationType).
    if (this._contactId) {
      try {
        const desc = await this.connectClient.send(
          new DescribeContactCommand({
            InstanceId: this.config.instanceId,
            ContactId: this._contactId,
          }),
        );
        const attrs = desc.Contact?.Attributes ?? {};
        if (Object.keys(attrs).length > 0) {
          if (this._escalationEvent) {
            this._escalationEvent.contactAttributes = attrs;
            // Refine reason from contact attributes if available
            const attrReason = (attrs['escalationReason'] ?? attrs['escalation_reason'] ?? '').toLowerCase();
            if (attrReason) {
              this._escalationEvent.reason = this.normaliseContactReason(attrReason);
            }
          } else {
            // Contact attributes indicate escalation even if we missed the keyword
            const attrReason = attrs['escalationReason'] ?? attrs['escalation_reason'] ?? '';
            if (attrReason) {
              this._escalationEvent = {
                detectedAtTurn: -1,
                trigger: 'contact_attribute',
                reason: this.normaliseContactReason(attrReason.toLowerCase()),
                contactAttributes: attrs,
              };
            }
          }
        }
      } catch (err) {
        // DescribeContact is best-effort — ignore errors (e.g. insufficient IAM perms)
        console.debug(`  ℹ  DescribeContact skipped: ${(err as Error).message}`);
      }
    }
    this._contactId = null;

    for (const r of this.receiveResolvers) r(null);
    this.receiveResolvers = [];
  }

  private normaliseContactReason(raw: string): EscalationReason {
    if (raw.includes('vulnerable')) return 'vulnerable_customer';
    if (raw.includes('auth')) return 'auth_failure';
    if (raw.includes('compliance') || raw.includes('regulat') || raw.includes('complaint')) return 'compliance_blocked';
    if (raw.includes('customer_requested') || raw.includes('human_requested')) return 'customer_requested';
    if (raw.includes('unresolvable') || raw.includes('unable')) return 'unresolvable';
    if (raw.includes('scope')) return 'out_of_scope';
    return 'unknown';
  }

  // ── Private: TTS synthesis ─────────────────────────────────────────────────

  private async synthesize(text: string): Promise<Buffer> {
    const voiceId = (process.env['POLLY_VOICE_ID'] ?? 'Amy') as VoiceId;
    const resp = await this.pollyClient.send(
      new SynthesizeSpeechCommand({
        Engine: 'neural',
        LanguageCode: 'en-GB',
        OutputFormat: 'pcm',
        SampleRate: '16000',
        Text: text,
        TextType: 'text',
        VoiceId: voiceId,
      }),
    );

    const chunks: Buffer[] = [];
    for await (const chunk of resp.AudioStream as AsyncIterable<Uint8Array>) {
      chunks.push(Buffer.from(chunk));
    }
    return Buffer.concat(chunks);
  }

  // ── Private: audio injection ───────────────────────────────────────────────

  private injectAudio(pcmBuffer: Buffer): Promise<void> {
    return new Promise((resolve) => {
      if (!this.audioSource) { resolve(); return; }

      // Polly output: 16kHz, 16-bit, mono (PCM signed little-endian)
      const sampleRate = 16_000;
      const frameSize = 160; // 10ms @ 16kHz — RTCAudioSource requires EXACTLY this
      const pcm = new Int16Array(
        pcmBuffer.buffer,
        pcmBuffer.byteOffset,
        pcmBuffer.byteLength / 2,
      );

      // Pad to a multiple of frameSize so every chunk is exactly 160 samples
      const padded = pcm.length % frameSize === 0
        ? pcm
        : (() => {
            const p = new Int16Array(Math.ceil(pcm.length / frameSize) * frameSize);
            p.set(pcm);
            return p;
          })();

      let offset = 0;
      let frameIndex = 0;
      const startMs = Date.now();

      // Drift-compensating scheduler: compute when each frame *should* fire
      // based on wall-clock time rather than accumulating setTimeout delays.
      // On ECS Fargate, setTimeout(10) can fire 15–25ms late, stretching the
      // injected audio and creating silence gaps that confuse Connect's VAD.
      const sendFrame = () => {
        if (offset >= padded.length) { resolve(); return; }

        // slice() creates an independent copy with its own buffer so that
        // samples.buffer.byteLength === 320 exactly (wrtc validates this).
        const samples = padded.slice(offset, offset + frameSize);

        this.audioSource!.onData({
          samples,
          sampleRate,
          bitsPerSample: 16,
          channelCount: 1,
          numberOfFrames: frameSize,
        });

        offset += frameSize;
        frameIndex++;

        // Schedule the next frame relative to the absolute start time so
        // accumulated timer drift doesn't stretch the audio stream.
        const nextMs = startMs + frameIndex * 10;
        const delay = Math.max(0, nextMs - Date.now());
        setTimeout(sendFrame, delay);
      };

      sendFrame();
    });
  }

  // Inject silent PCM frames for `durationMs` milliseconds.
  // Called after each customer speech injection to give Connect's VAD a clean
  // speech→silence transition, ensuring Transcribe finalises the COMPLETE
  // utterance before invoking the Lambda. Without this, ECS's near-zero
  // network latency to Connect causes an abrupt audio cutoff that triggers
  // early Transcribe partials and splits one utterance into two Lambda calls.
  private injectSilence(durationMs: number): Promise<void> {
    return new Promise((resolve) => {
      if (!this.audioSource) { resolve(); return; }

      const sampleRate = 16_000;
      const frameSize = 160; // 10ms @ 16kHz
      const totalFrames = Math.ceil(durationMs / 10);
      const startMs = Date.now();
      let frameIndex = 0;

      const sendFrame = () => {
        if (frameIndex >= totalFrames) { resolve(); return; }
        // Fresh zero-filled Int16Array per frame (byteLength === 320 exactly)
        const samples = new Int16Array(frameSize);
        this.audioSource!.onData({
          samples,
          sampleRate,
          bitsPerSample: 16,
          channelCount: 1,
          numberOfFrames: frameSize,
        });
        frameIndex++;
        const nextMs = startMs + frameIndex * 10;
        const delay = Math.max(0, nextMs - Date.now());
        setTimeout(sendFrame, delay);
      };

      sendFrame();
    });
  }

  // ── Private: audio capture + silence detection ────────────────────────────

  private onAudioData(frame: AudioDataFrame): void {
    const { samples, sampleRate } = frame;
    const gatedForRecording = applyNoiseGateInt16(samples, this.AUDIO_NOISE_GATE_PCM);
    const resampled = resamplePcmInt16(gatedForRecording, sampleRate, this.SAVED_AUDIO_SAMPLE_RATE);
    if (resampled.length > 0) {
      this.recordedAgentSlices.push({
        startMs: Date.now(),
        sampleRate: this.SAVED_AUDIO_SAMPLE_RATE,
        samples: resampled,
      });
    }

    // Write raw PCM to Transcribe's input stream
    if (this.transcribeInput?.writable) {
      this.transcribeInput.write(Buffer.from(samples.buffer, samples.byteOffset, samples.byteLength));
    }

    // Amplitude detection
    let maxAmp = 0;
    for (let i = 0; i < samples.length; i++) {
      const v = Math.abs(samples[i] ?? 0) / 32_768;
      if (v > maxAmp) maxAmp = v;
    }

    const now = Date.now();

    if (maxAmp > this.SPEECH_THRESHOLD) {
      // Voice activity detected
      if (this.speechState === 'idle') {
        this.speechState = 'speaking';
        this.speechStartMs = now;
        this.speechText = '';
        this.speechPartialText = '';
      }
      this.speechLastActiveMs = now;

      if (this.silenceTimer) {
        clearTimeout(this.silenceTimer);
        this.silenceTimer = null;
      }
    } else if (this.speechState === 'speaking') {
      // Silence while we were tracking speech
      if (!this.silenceTimer) {
        this.silenceTimer = setTimeout(() => {
          this.silenceTimer = null;
          const duration = this.speechLastActiveMs - this.speechStartMs;
          const candidateText = (this.speechText || this.speechPartialText).trim();

          if (duration > this.MIN_SPEECH_MS && candidateText) {
            this.speechState = 'idle';
            this.speechText = '';
            this.speechPartialText = '';
            this.deliverMessage({
              role: 'agent',
              content: candidateText,
              isNoise: false,
              timestampMs: Date.now(),
            });
          } else {
            this.speechState = 'idle';
            this.speechText = '';
            this.speechPartialText = '';
          }
        }, this.SILENCE_GAP_MS);
      }
    }

    void sampleRate; // used above, suppress lint
  }

  private flushPendingSpeech(trigger: string): void {
    if (this.silenceTimer) {
      clearTimeout(this.silenceTimer);
      this.silenceTimer = null;
    }

    const candidateText = (this.speechText || this.speechPartialText).trim();
    this.speechState = 'idle';
    this.speechText = '';
    this.speechPartialText = '';

    if (!candidateText) return;
    this.deliverMessage({
      role: 'agent',
      content: candidateText,
      isNoise: false,
      timestampMs: Date.now(),
    });
    console.log(
      `  ℹ  Flushed pending speech on ${trigger}: "${candidateText.slice(0, 80)}${candidateText.length > 80 ? '…' : ''}"`,
    );
  }

  // ── Private: Transcribe Streaming ─────────────────────────────────────────

  private async runTranscribeLoop(): Promise<void> {
    const SAMPLE_RATE = 48_000; // wrtc delivers 48kHz PCM from WebRTC
    let restartCount = 0;

    while (!this.sessionEnded && this.transcribeInput) {
      const input = this.transcribeInput;

      const audioGenerator = async function* () {
        for await (const chunk of input as AsyncIterable<Buffer>) {
          yield { AudioEvent: { AudioChunk: new Uint8Array(chunk) } };
        }
      };

      try {
        const response = await this.transcribeClient.send(
          new StartStreamTranscriptionCommand({
            LanguageCode: 'en-GB',
            MediaSampleRateHertz: SAMPLE_RATE,
            MediaEncoding: 'pcm',
            AudioStream: audioGenerator(),
          }),
        );

        restartCount = 0;
        for await (const event of response.TranscriptResultStream!) {
          const results = event.TranscriptEvent?.Transcript?.Results;
          if (!results) continue;

          for (const result of results) {
            const text = result.Alternatives?.[0]?.Transcript?.trim();
            if (text) this.appendTranscript(text, !!result.IsPartial);
          }
        }

        if (!this.sessionEnded && this.transcribeInput === input) {
          throw new AdapterError('Transcribe stream ended unexpectedly');
        }
      } catch (err) {
        if (this.sessionEnded || this.transcribeInput !== input) break;
        restartCount += 1;
        const delayMs = Math.min(restartCount, 3) * 1_000;
        console.error(`  ⚠  Transcribe loop error: ${this.formatUnknownError(err)} (retrying)`);
        await sleep(delayMs);
      }
    }
  }

  private appendTranscript(text: string, isPartial: boolean): void {
    if (isPartial) {
      if (this.speechState === 'speaking' || this.speechState === 'idle') {
        // Partial transcripts are snapshots of the current utterance; keep latest.
        this.speechPartialText = text;
      }
      return;
    }

    if (this.speechState === 'speaking') {
      this.speechText += (this.speechText ? ' ' : '') + text;
      this.speechPartialText = '';
    } else if (this.speechState === 'idle' && text) {
      // Transcript arrived slightly after silence timer fired — re-open window
      this.speechText += (this.speechText ? ' ' : '') + text;
      this.speechPartialText = '';
    }
  }

  // ── Private: message delivery ─────────────────────────────────────────────

  private deliverMessage(msg: AdapterMessage): void {
    // Escalation keyword detection — scan every agent turn
    if (msg.role === 'agent' && !this._escalationEvent) {
      for (const { re, reason } of ConnectWebRTCAdapter.ESCALATION_PATTERNS) {
        if (re.test(msg.content)) {
          this._escalationEvent = {
            detectedAtTurn: this.receiveQueue.length + this.receiveResolvers.length,
            trigger: 'text_keyword',
            detectedFrom: msg.content,
            reason,
          };
          console.log(`  ⚡ Escalation detected (${reason}): "${msg.content.substring(0, 80)}…"`);
          // Mark session ended — no more customer turns needed after transfer
          this.sessionEnded = true;
          break;
        }
      }
    }

    if (this.receiveResolvers.length > 0) {
      const resolver = this.receiveResolvers.shift()!;
      resolver(msg);
    } else {
      this.receiveQueue.push(msg);
    }
  }
}
