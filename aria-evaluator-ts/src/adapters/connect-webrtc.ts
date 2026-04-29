// src/adapters/connect-webrtc.ts
// ConnectWebRTCAdapter — AWS-native voice evaluation via StartWebRTCContact
//
// Architecture:
//   1. AWS Connect StartWebRTCContact → Chime Meeting + Attendee credentials
//   2. @roamhq/wrtc provides RTCPeerConnection in Node.js (no browser needed)
//   3. amazon-chime-sdk-js handles Chime WebSocket signaling + SDP negotiation
//   4. RTCAudioSource injects Polly TTS PCM → ARIA hears the customer
//   5. RTCAudioSink captures ARIA's PCM → Amazon Transcribe Streaming → text
//
// No Playwright, no widget, no approved origins, no getUserMedia headaches.

// ── Node.js shims BEFORE any Chime SDK import ─────────────────────────────────
// These globals must exist before amazon-chime-sdk-js is first evaluated.
import wrtcModule from '@roamhq/wrtc';

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
import { PassThrough } from 'node:stream';

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
  private speechStartMs = 0;
  private speechLastActiveMs = 0;
  private silenceTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly SPEECH_THRESHOLD = 0.008; // ~-42dBFS
  private readonly SILENCE_GAP_MS = 1_800;
  private readonly MIN_SPEECH_MS = 300;

  // Escalation detection
  private _escalationEvent: EscalationEvent | null = null;

  /** Opening greeting captured during connect() — exposed so runner can record it as turn 0 */
  private _openingGreeting: AdapterMessage | null = null;

  // Phrases ARIA uses when transferring to a human agent (case-insensitive)
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

  get contactId(): string | null { return this._contactId; }
  get escalationEvent(): EscalationEvent | null { return this._escalationEvent; }
  get openingGreeting(): AdapterMessage | null { return this._openingGreeting; }

  // ── connect ────────────────────────────────────────────────────────────────

  async connect(options: ConnectOptions): Promise<void> {
    const {
      sessionId,
      customerId,
      authenticated = false,
      channel = 'voice',
      scenarioName = '',
    } = options;

    console.log(`  📡 Starting WebRTC contact…`);
    console.log(`     Flow   : ${this.config.contactFlowId}`);
    console.log(`     Customer: ${customerId ?? 'anonymous'} (auth=${authenticated})`);

    // 1. Create the WebRTC contact — returns Chime meeting + attendee credentials
    const startResp = await this.connectClient.send(
      new StartWebRTCContactCommand({
        InstanceId: this.config.instanceId,
        ContactFlowId: this.config.contactFlowId,
        ParticipantDetails: { DisplayName: this.config.displayName },
        Attributes: {
          customerId: customerId ?? '',
          authStatus: authenticated ? 'authenticated' : 'unauthenticated',
          evaluationScenario: scenarioName,
          channel,
          locale: 'en-GB',
          ...(authenticated && customerId
            ? {
                // SESSION_START equivalent for voice — tells ARIA the customer is authed
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
          if (resolved) return;
          resolved = true;
          clearTimeout(timeout);
          console.log(`  ✓  Chime meeting connected (contactId=${this._contactId})`);

          // Attach RTCAudioSink to the remote audio track
          if (capturedPC) {
            const audioRx = capturedPC
              .getReceivers()
              .find((r: RTCRtpReceiver) => r.track?.kind === 'audio');

            if (audioRx) {
              this.audioSink = new RTCAudioSink(audioRx.track);
              this.audioSink.ondata = (frame: AudioDataFrame) => {
                this.onAudioData(frame);
              };
              console.log(`  ✓  RTCAudioSink attached — listening for ARIA speech`);
            } else {
              console.warn(`  ⚠  No audio receiver found — waiting for track`);
              // Poll for receiver — it may arrive after audioVideoDidStart
              const poll = setInterval(() => {
                const rx = capturedPC!
                  .getReceivers()
                  .find((r: RTCRtpReceiver) => r.track?.kind === 'audio');
                if (rx) {
                  clearInterval(poll);
                  this.audioSink = new RTCAudioSink(rx.track);
                  this.audioSink.ondata = (f: AudioDataFrame) => this.onAudioData(f);
                  console.log(`  ✓  RTCAudioSink attached (delayed)`);
                }
              }, 500);
              setTimeout(() => clearInterval(poll), 10_000);
            }
          } else {
            console.warn(`  ⚠  RTCPeerConnection was not captured`);
          }

          resolve();
        },

        audioVideoDidStop: (status) => {
          console.log(`  ℹ  Chime session stopped: ${String(status)}`);
          // If the meeting ended while we had received at least one agent turn and no
          // escalation has been detected by keyword yet, treat it as a possible
          // escalation (ARIA transferred the call → Chime meeting ends).
          if (!this._escalationEvent && this.receiveQueue.length === 0 && !resolved) {
            // Pre-connect stop → not an escalation, handled as error below
          } else if (!this._escalationEvent) {
            this._escalationEvent = {
              detectedAtTurn: -1, // populated in disconnect() after we know turn count
              trigger: 'meeting_ended',
              reason: 'unknown',
            };
          }
          this.sessionEnded = true;
          if (!resolved) {
            resolved = true;
            clearTimeout(timeout);
            reject(new AdapterError(`Chime session stopped before connecting: ${String(status)}`));
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

    // 8. On voice, ARIA typically waits for the customer to speak first before
    //    greeting — so we do a short opportunistic check for any immediate IVR
    //    prompt (e.g. hold music, queue messages).  If nothing arrives quickly we
    //    proceed: the ARIA greeting will arrive as part of the first agent response.
    const earlyGreeting = await this.receive(3_000);
    if (earlyGreeting) {
      this._openingGreeting = earlyGreeting;
      console.log(`  ✓  Early greeting: "${earlyGreeting.content.slice(0, 80)}${earlyGreeting.content.length > 80 ? '…' : ''}"`);
      await sleep(400);
    } else {
      console.log(`  ℹ  No immediate greeting — ARIA will greet after first customer message`);
    }
  }

  // ── sendMessage ────────────────────────────────────────────────────────────

  async sendMessage(text: string, simulateTyping = true): Promise<void> {
    if (this.sessionEnded) throw new SessionEndedError('WebRTC session has ended');
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
    await this.injectAudio(pcm);
  }

  // ── receive ────────────────────────────────────────────────────────────────

  async receive(timeoutMs = 45_000): Promise<AdapterMessage | null> {
    if (this.sessionEnded) return null;

    // Check pre-queued messages
    const queued = this.receiveQueue.shift();
    if (queued) return queued;

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
        setTimeout(sendFrame, 10); // 10ms per frame
      };

      sendFrame();
    });
  }

  // ── Private: audio capture + silence detection ────────────────────────────

  private onAudioData(frame: AudioDataFrame): void {
    const { samples, sampleRate } = frame;

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

          if (duration > this.MIN_SPEECH_MS && this.speechText.trim()) {
            const text = this.speechText.trim();
            this.speechState = 'idle';
            this.speechText = '';
            this.deliverMessage({
              role: 'agent',
              content: text,
              isNoise: false,
              timestampMs: Date.now(),
            });
          } else {
            this.speechState = 'idle';
            this.speechText = '';
          }
        }, this.SILENCE_GAP_MS);
      }
    }

    void sampleRate; // used above, suppress lint
  }

  // ── Private: Transcribe Streaming ─────────────────────────────────────────

  private async runTranscribeLoop(): Promise<void> {
    const input = this.transcribeInput!;
    const SAMPLE_RATE = 48_000; // wrtc delivers 48kHz PCM from WebRTC

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

      for await (const event of response.TranscriptResultStream!) {
        const results = event.TranscriptEvent?.Transcript?.Results;
        if (!results) continue;

        for (const result of results) {
          if (result.IsPartial) continue;
          const text = result.Alternatives?.[0]?.Transcript?.trim();
          if (text) this.appendTranscript(text);
        }
      }
    } catch (err) {
      if (!this.sessionEnded) {
        console.error('  ⚠  Transcribe loop error:', (err as Error).message);
      }
    }
  }

  private appendTranscript(text: string): void {
    if (this.speechState === 'speaking') {
      this.speechText += (this.speechText ? ' ' : '') + text;
    } else if (this.speechState === 'idle' && text) {
      // Transcript arrived slightly after silence timer fired — re-open window
      this.speechText += (this.speechText ? ' ' : '') + text;
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
