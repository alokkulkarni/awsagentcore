// src/adapters/connect-voice.ts
// Playwright-based voice adapter: headless Chromium + Connect CCP page.
// Uses the same libwebrtc as a real browser — unlike Python aiortc.
//
// Audio flow:
//  TTS (Polly PCM 16kHz mono 16-bit) → frame.evaluate(injectAudio)
//  Chrome WebRTC out → ScriptProcessorNode → base64 PCM → exposeFunction → Deepgram WS → text
//
// Architecture note:
//  The Amazon Connect widget renders its UI inside a cross-origin iframe
//  (https://conversationalbot.my.connect.aws/...).  We use page.addInitScript
//  which Playwright injects into EVERY frame (including cross-origin iframes),
//  so getUserMedia interception, RTCPeerConnection tracking, and injectAudio
//  are all available in the widget iframe.  Audio must be injected into the
//  *frame that owns the WebRTC peer*, not just the top-level page.

import { chromium, type Browser, type BrowserContext, type Page, type Frame } from 'playwright';
import { createClient as createDeepgramClient } from '@deepgram/sdk';
import {
  PollyClient,
  SynthesizeSpeechCommand,
  Engine,
  VoiceId,
  OutputFormat,
  TextType,
} from '@aws-sdk/client-polly';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { BaseAdapter, AdapterMessage, ConnectOptions } from './base.js';
import { AdapterError } from './base.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

// The CCP page must be served from an origin on Amazon Connect's Approved Origins list.
// Approved origins: http://localhost:3001, http://localhost:4000, http://localhost:5173
// The main API server (port 3001) already serves public/ so no second server needed.
// Override with CCP_PORT env var if needed.
const CCP_PORT = parseInt(process.env['CCP_PORT'] ?? '3001', 10);
const CCP_URL = `http://localhost:${CCP_PORT}/evaluator-ccp.html`;

/** 400 ms of silence at 16 kHz, 16-bit, mono */
const SILENCE_400MS = Buffer.alloc(16000 * 0.4 * 2);

interface AudioSegment {
  role: 'customer' | 'agent';
  pcm: Buffer;
  timestampMs: number;
}

interface VoiceAdapterConfig {
  deepgramApiKey?: string;
  pollyVoiceId?: string;
  pollyRegion?: string;
  /** Seconds to wait for the agent to stop speaking after each turn */
  silenceTimeoutSecs?: number;
  headless?: boolean;
}

/** Build a 44-byte WAV file header for mono 16 kHz 16-bit PCM. */
function buildWavHeader(dataByteLength: number): Buffer {
  const header = Buffer.alloc(44);
  const sampleRate = 16000;
  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = sampleRate * numChannels * (bitsPerSample / 8);
  const blockAlign = numChannels * (bitsPerSample / 8);

  header.write('RIFF', 0, 'ascii');
  header.writeUInt32LE(36 + dataByteLength, 4);
  header.write('WAVE', 8, 'ascii');
  header.write('fmt ', 12, 'ascii');
  header.writeUInt32LE(16, 16);            // PCM sub-chunk size
  header.writeUInt16LE(1, 20);             // audio format: PCM
  header.writeUInt16LE(numChannels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write('data', 36, 'ascii');
  header.writeUInt32LE(dataByteLength, 40);
  return header;
}

export class ConnectVoiceAdapter implements BaseAdapter {
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private readonly polly: PollyClient;
  private readonly config: Required<VoiceAdapterConfig>;
  private readonly messageQueue: AdapterMessage[] = [];
  private resolveNextMessage: ((m: AdapterMessage) => void) | null = null;
  private deepgramClient: ReturnType<typeof createDeepgramClient> | null = null;
  private currentTranscript = '';

  /** Ordered list of PCM segments captured during the conversation */
  private readonly audioSegments: AudioSegment[] = [];

  readonly contactId: string | null = null;

  get channel(): 'voice' {
    return 'voice';
  }

  constructor(config: VoiceAdapterConfig = {}) {
    this.config = {
      deepgramApiKey: config.deepgramApiKey ?? process.env['DEEPGRAM_API_KEY'] ?? '',
      pollyVoiceId: config.pollyVoiceId ?? process.env['POLLY_VOICE_ID'] ?? 'Amy',
      pollyRegion: config.pollyRegion ?? process.env['AWS_REGION'] ?? 'eu-west-2',
      silenceTimeoutSecs: config.silenceTimeoutSecs ?? 5,
      headless: config.headless ?? (process.env['VOICE_HEADLESS'] !== 'false'),
    };
    this.polly = new PollyClient({ region: this.config.pollyRegion });

    if (!this.config.deepgramApiKey) {
      console.warn('  ⚠  DEEPGRAM_API_KEY not set — voice STT will not work');
    }
  }

  async connect(options: ConnectOptions): Promise<void> {
    const instanceId = process.env['CONNECT_INSTANCE_ID']  ?? '(not set)';
    const region     = process.env['AWS_REGION'] ?? process.env['CONNECT_REGION'] ?? 'eu-west-2';
    const snippetId  = process.env['CONNECT_SNIPPET_ID']   ?? '17638a13-f2b0-4371-a593-1f81f86548e8';
    const widgetHost = process.env['CONNECT_WIDGET_HOST']  ?? 'conversationalbot.my.connect.aws';
    const dgKeySet   = !!(process.env['DEEPGRAM_API_KEY'] && !process.env['DEEPGRAM_API_KEY'].startsWith('<'));

    console.log(`  🌐 Launching ${this.config.headless ? 'headless' : 'visible'} Chrome for voice...`);
    console.log(`     CCP URL  : ${CCP_URL}`);
    console.log(`     Instance : ${instanceId}`);
    console.log(`     Region   : ${region}`);
    console.log(`     Widget   : ${widgetHost}`);
    console.log(`     Snippet  : ${snippetId}`);
    console.log(`     Customer : ${options.customerId ?? 'CUST-001'} (auth=${options.authenticated ?? false})`);
    console.log(`     Deepgram : ${dgKeySet ? '✓ key set' : '⚠ KEY NOT SET — STT disabled'}`);

    this.browser = await chromium.launch({
      headless: this.config.headless,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--autoplay-policy=no-user-gesture-required',
        // NOTE: --disable-web-security was removed. It suppresses the Origin header
        // which breaks Amazon Connect's approved-origins check (StartChatContact → 400).
        // Cross-origin iframe access works via Playwright CDP without this flag.
        '--use-fake-device-for-media-stream',  // fallback fake device; overridden by getUserMedia intercept
        '--use-fake-ui-for-media-stream',      // auto-approve media permission dialogs
        '--disable-features=IsolateOrigins,site-per-process',  // allow cross-origin frame JS injection
      ],
    });

    this.context = await this.browser.newContext({
      permissions: ['microphone', 'camera'],
      userAgent:
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    });

    this.page = await this.context.newPage();

    // ── addInitScript: runs in EVERY frame (including cross-origin widget iframes).
    // IMPORTANT: must use { content: 'raw JS string' } — NOT a function reference.
    // esbuild transforms function callbacks and injects __name() helpers which crash
    // in the browser context because they're never defined there.
    //
    // KEY DESIGN DECISIONS:
    // • Do NOT intercept getUserMedia return value — Chrome's --use-fake-device-for-media-stream
    //   provides a working fake audio track.  Our earlier interception was returning a
    //   MediaStreamDestination stream that, combined with the sandbox iframe missing
    //   allow="microphone", caused getUserMedia to fail silently → no WebRTC.
    // • Iframe createElement is patched to add allow="microphone *" before Connect SDK
    //   creates its renderer iframe.  Without this attr Chrome's Permissions Policy
    //   blocks getUserMedia inside the sandboxed iframe even with fake-ui flag set.
    // • getUserMedia is LOGGED (not intercepted) so we can see if/when it is called.
    // • RTCPeerConnection is proxied in ALL frames (detects voice connection).
    // • injectAudio creates AudioContext lazily and uses replaceTrack on the RTC sender
    //   rather than feeding into an intercepted mic stream.
    await this.page.addInitScript({ content: `(function() {
  var g = globalThis;

  // 1. Patch document.createElement so every iframe gets allow="microphone *".
  //    Chrome's Permissions Policy blocks getUserMedia in sandboxed iframes unless
  //    the iframe element has an explicit allow attribute — even with fake-ui flag.
  //    This runs in the MAIN PAGE frame before the Connect widget creates its iframes.
  try {
    if (g.document && g.document.createElement) {
      var _origCreate = g.document.createElement.bind(g.document);
      g.document.createElement = function(tag, opts) {
        var el = _origCreate(tag, opts);
        if (typeof tag === 'string' && tag.toLowerCase() === 'iframe') {
          el.setAttribute('allow', 'microphone *; camera *; autoplay *');
        }
        return el;
      };
    }
  } catch (e) { console.log('[eval] iframe patch err: ' + e); }

  // 2. Log getUserMedia calls — both new and old/vendor-prefixed APIs.
  //    Do NOT intercept the return value; let the native fake device work.
  try {
    var _gumLog = function(src, constraints) {
      g._gumCallCount = (g._gumCallCount || 0) + 1;
      var loc = g.location ? g.location.href : '?';
      console.log('[eval] getUserMedia #' + g._gumCallCount + ' [' + src + '] at ' + loc + ' constraints=' + JSON.stringify(constraints));
    };
    g._gumCallCount = 0;
    if (g.navigator && g.navigator.mediaDevices && g.navigator.mediaDevices.getUserMedia) {
      var _origGUM = g.navigator.mediaDevices.getUserMedia.bind(g.navigator.mediaDevices);
      g.navigator.mediaDevices.getUserMedia = function(c) {
        _gumLog('mediaDevices', c);
        return _origGUM(c).then(
          function(s) { console.log('[eval] getUserMedia OK track=' + (s.getAudioTracks()[0] ? s.getAudioTracks()[0].label : 'none')); return s; },
          function(e) { console.log('[eval] getUserMedia FAILED: ' + e); throw e; }
        );
      };
    }
    if (g.navigator && g.navigator.getUserMedia) {
      var _origLegacy = g.navigator.getUserMedia.bind(g.navigator);
      g.navigator.getUserMedia = function(c, ok, fail) {
        _gumLog('navigator.getUserMedia(legacy)', c);
        return _origLegacy(c, ok, fail);
      };
    }
    if (g.navigator && g.navigator.webkitGetUserMedia) {
      var _origWebkit = g.navigator.webkitGetUserMedia.bind(g.navigator);
      g.navigator.webkitGetUserMedia = function(c, ok, fail) {
        _gumLog('webkitGetUserMedia', c);
        return _origWebkit(c, ok, fail);
      };
    }
  } catch (e) { console.log('[eval] GUM log patch err: ' + e); }

  // 2b. Log postMessage traffic between frames (renderer → parent voice initiation).
  //     Only log messages that look SDK-related (not noise from all extensions/widgets).
  try {
    if (g.window) {
      var _origPM = g.window.postMessage.bind(g.window);
      g.window.postMessage = function(data, targetOrigin, transfer) {
        try {
          var s = typeof data === 'string' ? data : JSON.stringify(data);
          if (s && s.length < 500) console.log('[eval] postMessage OUT to=' + targetOrigin + ' data=' + s.slice(0, 200));
        } catch(pe) {}
        return _origPM(data, targetOrigin, transfer);
      };
      g.window.addEventListener('message', function(evt) {
        try {
          var s = typeof evt.data === 'string' ? evt.data : JSON.stringify(evt.data);
          if (s && s.length < 500) console.log('[eval] postMessage IN from=' + evt.origin + ' data=' + s.slice(0, 200));
        } catch(pe) {}
      }, true);
    }
  } catch (e) { console.log('[eval] postMessage patch err: ' + e); }

  // 2c. Log microphone permissions query result so we can see if SDK checks permissions.
  try {
    if (g.navigator && g.navigator.permissions && g.navigator.permissions.query) {
      var _origPQ = g.navigator.permissions.query.bind(g.navigator.permissions);
      g.navigator.permissions.query = function(desc) {
        return _origPQ(desc).then(function(r) {
          if (desc && (desc.name === 'microphone' || desc.name === 'camera')) {
            console.log('[eval] permissions.query(' + desc.name + ')=' + r.state);
          }
          return r;
        });
      };
    }
  } catch (e) { console.log('[eval] perms patch err: ' + e); }

  // 3. Track RTCPeerConnection via Proxy
  try {
    g._rtcPeers = g._rtcPeers || [];
    var _OrigRTC = g.RTCPeerConnection;
    if (_OrigRTC && !_OrigRTC.__evalPatched) {
      g.RTCPeerConnection = new Proxy(_OrigRTC, {
        construct: function(Target, args) {
          var pc = Reflect.construct(Target, args);
          g._rtcPeers.push(pc);
          console.log('[eval] RTCPeerConnection created at ' + (g.location ? g.location.href : 'unknown'));
          return pc;
        }
      });
      g.RTCPeerConnection.__evalPatched = true;
    }
  } catch (e) { console.log('[eval] RTC patch err: ' + e); }

  // 4. injectAudio — create AudioContext lazily, schedule PCM buffer, then use
  //    replaceTrack() on the RTC sender so Polly TTS audio is transmitted to Connect.
  //    replaceTrack is idempotent: subsequent calls keep routing audio through the
  //    same MediaStreamDestination track already installed on the sender.
  g.injectAudio = function(base64pcm) {
    return new Promise(function(resolve) {
      try {
        var AudioCtx = g.AudioContext || g.webkitAudioContext;
        if (!AudioCtx) { console.log('[eval] injectAudio: no AudioContext'); resolve(undefined); return; }
        if (!g._evalAudioCtx) {
          g._evalAudioCtx = new AudioCtx({ sampleRate: 16000 });
          g._evalMicDest  = g._evalAudioCtx.createMediaStreamDestination();
          console.log('[eval] injectAudio: AudioContext created');
        }
        var ctx = g._evalAudioCtx;
        var dest = g._evalMicDest;
        if (ctx.state === 'suspended') ctx.resume();
        var raw = atob(base64pcm);
        var buf = new ArrayBuffer(raw.length);
        var u8 = new Uint8Array(buf);
        for (var i = 0; i < raw.length; i++) u8[i] = raw.charCodeAt(i);
        var i16 = new Int16Array(buf);
        var f32 = new Float32Array(i16.length);
        for (var j = 0; j < i16.length; j++) f32[j] = (i16[j] || 0) / 32768.0;
        var abuf = ctx.createBuffer(1, f32.length, 16000);
        abuf.copyToChannel(f32, 0);
        var src = ctx.createBufferSource();
        src.buffer = abuf;
        src.connect(dest);
        src.start();
        // Replace the RTC sender's audio track so our TTS goes through WebRTC.
        // We only need to do this once per RTCPeerConnection.
        if (!g._trackReplaced) {
          var peers = g._rtcPeers || [];
          for (var p = 0; p < peers.length; p++) {
            var pc = peers[p];
            if (!pc.getSenders) continue;
            var senders = pc.getSenders();
            for (var s = 0; s < senders.length; s++) {
              var sender = senders[s];
              if (sender.track && sender.track.kind === 'audio') {
                var tracks = dest.stream.getAudioTracks();
                if (tracks.length > 0) {
                  g._trackReplaced = true;
                  sender.replaceTrack(tracks[0]).then(
                    function() { console.log('[eval] replaceTrack OK'); },
                    function(e2) { console.log('[eval] replaceTrack err: ' + e2); g._trackReplaced = false; }
                  );
                }
                break;
              }
            }
          }
        }
        resolve(undefined);
      } catch (e3) { console.log('[eval] injectAudio err: ' + e3); resolve(undefined); }
    });
  };

  // 5. Status reporter (used by _waitForRtcPeer and frame status logging)
  g.getStatus = function() {
    return {
      rtcPeers:      (g._rtcPeers || []).length,
      gumCalls:      g._gumCallCount || 0,
      captureActive: !!(g._captureNode),
      audioCtxState: g._evalAudioCtx ? g._evalAudioCtx.state : 'none',
      trackReplaced: !!(g._trackReplaced),
      url:           g.location ? g.location.href : ''
    };
  };
})();` });

    // Inject ARIA_CONFIG so CCP HTML can read it
    await this.page.addInitScript((cfg: Record<string, string>) => {
      (globalThis as unknown as Record<string, unknown>)['ARIA_CONFIG'] = cfg;
    }, {
      snippetId,
      customerId: options.customerId ?? 'CUST-001',
      authStatus: options.authenticated ? 'authenticated' : 'unauthenticated',
      locale: 'en-GB',
      botName: 'ARIA',
    });

    // Expose audio chunk callback — Playwright exposes it only in the main frame;
    // the CCP HTML uses postMessage to relay agent audio from the widget iframe.
    await this.page.exposeFunction('__onAgentAudio', (base64chunk: string) => {
      this.onAgentAudioChunk(base64chunk);
    });

    // Forward ALL browser console to terminal
    this.page.on('console', (msg) => {
      console.log(`  [browser:${msg.type()}] ${msg.text().slice(0, 200)}`);
    });
    this.page.on('pageerror', (err) => {
      console.error(`  [browser:error] ${err.message}`);
    });

    // Intercept ALL HTTP responses — log 4xx/5xx with URL and body for diagnosis
    this.page.on('response', async (response) => {
      const status = response.status();
      if (status >= 400) {
        const url = response.url();
        let body = '';
        try { body = (await response.text()).slice(0, 300); } catch { /* ignore */ }
        console.log(`  [net:${status}] ${url}`);  // full URL, no truncation
        if (body) console.log(`  [net:${status}:body] ${body}`);
      }
    });

    // Log ALL requests to Amazon Connect — full URL + key headers to diagnose 400
    this.page.on('request', (request) => {
      const url = request.url();
      if (url.includes('connect.aws')) {
        const h = request.headers();
        const method = request.method();
        console.log(`  [net:req:${method}] ${url}`);
        // Log every header that might carry the credential
        const interesting = ['origin', 'referer', 'authorization', 'x-api-key',
          'x-amz-snippet-id', 'x-amz-security-token', 'x-amz-active-chat', 'content-type'];
        const hlog = interesting
          .filter(k => h[k])
          .map(k => `${k}=${(h[k] ?? '').slice(0, 60)}`)
          .join(' | ');
        console.log(`  [net:req:hdrs] ${hlog || '(no interesting headers)'}`);
        const body = request.postData();
        if (body) console.log(`  [net:req:body] ${body.slice(0, 200)}`);
      }
    });

    // Load the CCP page over HTTP — widget requires a real origin (not file://)
    console.log(`  ⏳ Loading CCP page...`);
    await this.page.goto(CCP_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });

    // Wait for widget script to initialise
    console.log(`  ⏳ Waiting for amazon_connect() to be available...`);
    await this.page.waitForFunction(
      () => typeof (globalThis as unknown as Record<string, unknown>)['amazon_connect'] === 'function',
      { timeout: 20_000 },
    );
    console.log(`  ✓ Widget script loaded`);

    // Give the widget SDK time to finish processing the queued amazon_connect() calls
    // before clicking the toggle. Do NOT call openChatWidget here — clicking the button
    // is the only action needed; calling the API first creates a race / double-trigger.
    await this.page.waitForTimeout(2000);

    // Open the widget panel and click the voice button
    console.log(`  🖱  Opening widget panel...`);
    const opened = await this._openWidget();
    if (!opened) {
      console.log(`  ⚠  Widget panel could not be opened — voice call will not connect`);
    }

    // Wait for a WebRTC peer to appear in ANY frame — extended to 60s
    console.log(`  ⏳ Waiting for WebRTC peer connection...`);
    const rtcConnected = await this._waitForRtcPeer(60_000);
    if (rtcConnected) {
      const vf = await this._getVoiceFrame();
      console.log(`  ✓ WebRTC peer connected (frame: ${vf?.url()?.slice(0, 80) ?? 'main page'})`);
    } else {
      console.log(`  ⚠  No WebRTC peer after 60s`);
    }

    console.log(`  ✓ Connect voice session ready`);
  }

  /** Try multiple strategies to open the widget panel and start a voice call. */
  private async _openWidget(): Promise<boolean> {
    if (!this.page) return false;

    // Click the floating toggle button — the widget creates iframes AFTER this click.
    const toggleSelectors = [
      '[id*="amazon-connect"] button',
      '[class*="widget-btn"]', '[class*="widgetBtn"]', '[class*="widget-button"]',
      '[class*="amazon-connect"] button',
      'div[style*="position: fixed"] button',
      'button[style*="position: fixed"]',
    ];

    let clicked = false;
    for (const sel of toggleSelectors) {
      try {
        const el = await this.page.$(sel);
        if (el) {
          console.log(`  🖱  Clicking toggle button: ${sel}`);
          await el.click();
          clicked = true;
          break;
        }
      } catch { /* try next selector */ }
    }

    if (!clicked) {
      clicked = await this.page.evaluate(() => {
        /* eslint-disable @typescript-eslint/no-explicit-any */
        const g = globalThis as any;
        const btns = Array.from(g.document.querySelectorAll('button, [role="button"]')) as any[];
        const btn = btns.find((b: any) =>
          g.getComputedStyle(b).position === 'fixed' || b.closest('[style*="fixed"]') != null,
        );
        if (btn) { btn.click(); return true; }
        return false;
        /* eslint-enable @typescript-eslint/no-explicit-any */
      });
      if (clicked) console.log(`  🖱  Clicked fixed-position button via JS scan`);
    }

    if (!clicked) {
      await this.page.evaluate(() => {
        const g = globalThis as unknown as Record<string, (...a: unknown[]) => void>;
        try { g['amazon_connect']?.('openChatWidget'); console.log('[eval] openChatWidget called'); } catch { /* ignore */ }
      });
      clicked = true;
    }

    // Wait for chat to be established: "Customer has joined" or the agent's first message
    // The "Start a Call" button only appears AFTER the chat session is connected.
    console.log(`  ⏳ Waiting for chat session to connect (agent first message)...`);
    const chatReady = await this._waitForChatConnected(30_000);
    if (!chatReady) {
      console.log(`  ⚠  Chat connection not confirmed within 30s — trying voice button anyway`);
    }

    // Find the renderer frame (about:blank iframe with the widget UI)
    const rendererFrame = await this._waitForRendererFrame(5_000);

    // Take a post-connect screenshot to see the "Start a Call" button
    const ssPath = join(__dirname, `../../debug-widget-open-${Date.now()}.png`);
    await this.page.screenshot({ path: ssPath, fullPage: true }).catch(() => {});
    console.log(`  📸 Widget-open screenshot: ${ssPath}`);

    // Click "Start a Call" across all frames (primary strategy: native click by testid)
    const voiceClicked = await this._clickStartCallButton();
    if (!voiceClicked && rendererFrame) {
      await this._inspectAndClickVoice(rendererFrame);
    } else if (!voiceClicked) {
      console.log(`  ⚠  Could not find "Start a Call" button`);
    }

    // Give the SDK 2s to react to the click, then check if voice started.
    // If gumCalls is still 0, try the programmatic amazon_connect('startVoiceCall') API.
    await this.page.waitForTimeout(2000);
    const gumAfterClick: number = await this.page.evaluate(
      () => (globalThis as unknown as Record<string, number>)['_gumCallCount'] ?? 0,
    ).catch(() => 0);
    console.log(`  ℹ  gumCalls after click: ${gumAfterClick}`);

    if (gumAfterClick === 0) {
      console.log(`  🔄 getUserMedia not called — trying programmatic amazon_connect('startVoiceCall')...`);
      await this.page.evaluate(() => {
        /* eslint-disable @typescript-eslint/no-explicit-any */
        const g = globalThis as any;
        const ac = g.amazon_connect;
        if (typeof ac === 'function') {
          try { ac('startVoiceCall'); console.log('[eval] amazon_connect(startVoiceCall) called'); }
          catch(e) { console.log('[eval] startVoiceCall err: ' + e); }
          // Also try alternate API names used by different widget versions
          try { ac('openVoiceCall'); } catch { /* ignore */ }
          try { ac('startCall'); } catch { /* ignore */ }
        } else {
          console.log('[eval] amazon_connect not available as function');
        }
        /* eslint-enable @typescript-eslint/no-explicit-any */
      });
      // Wait another 2s to see if the programmatic call worked
      await this.page.waitForTimeout(2000);
      const gumAfterApi: number = await this.page.evaluate(
        () => (globalThis as unknown as Record<string, number>)['_gumCallCount'] ?? 0,
      ).catch(() => 0);
      console.log(`  ℹ  gumCalls after programmatic API: ${gumAfterApi}`);
    }

    return true;
  }

  /**
   * Wait until any frame contains "Customer has joined" or "Start a Call"
   * text — confirming the chat session is live and the voice button is visible.
   */
  private async _waitForChatConnected(timeoutMs: number): Promise<boolean> {
    if (!this.page) return false;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      for (const frame of this.page.frames()) {
        try {
          /* eslint-disable @typescript-eslint/no-explicit-any */
          const ready: boolean = await frame.evaluate(() => {
            const g = globalThis as any;
            const body = (g.document?.body?.textContent ?? '').toLowerCase();
            return body.includes('customer has joined') ||
                   body.includes('start a call') ||
                   body.includes('start call');
          });
          /* eslint-enable @typescript-eslint/no-explicit-any */
          if (ready) {
            console.log(`  ✓ Chat ready signal found in frame: ${frame.url().slice(0, 60)}`);
            return true;
          }
        } catch { /* cross-origin — skip */ }
      }
      await this.page.waitForTimeout(500);
    }
    return false;
  }

  /**
   * Find and click the "Start a Call" button across ALL frames.
   * CRITICAL: Must use Playwright native el.click() — NOT frame.evaluate(() => btn.click()).
   * JS-dispatched clicks have event.isTrusted=false. The Connect widget SDK checks isTrusted
   * before starting the voice session and silently ignores untrusted clicks.
   * Playwright native clicks go via CDP Input.dispatchMouseEvent which sets isTrusted=true.
   */
  private async _clickStartCallButton(): Promise<boolean> {
    if (!this.page) return false;

    for (const frame of this.page.frames()) {
      // Log non-emoji buttons for diagnostics (evaluate is fine here — not a click)
      try {
        /* eslint-disable @typescript-eslint/no-explicit-any */
        await frame.evaluate(() => {
          const g = globalThis as any;
          const all = Array.from(g.document.querySelectorAll('button, [role="button"]')) as any[];
          all.filter((b: any) => !(b.className ?? '').includes('emoji'))
            .forEach((b: any) => console.log('[eval] button: text="' +
              (b.textContent?.trim().slice(0, 50) ?? '') +
              '" aria="' + (b.getAttribute('aria-label') ?? '') +
              '" data-testid="' + (b.getAttribute('data-testid') ?? '') + '"'));
        });
        /* eslint-enable @typescript-eslint/no-explicit-any */
      } catch { /* cross-origin or detached — skip logging */ }

      // Native Playwright click selectors (TRUSTED user gesture via CDP)
      const selectors = [
        '[data-testid="start-call-button"]',
        '[aria-label="Start a call"]',
        '[aria-label="Start a Call"]',
      ];

      for (const sel of selectors) {
        try {
          const el = await frame.$(sel);
          if (el) {
            await el.click();   // ← Playwright native click, isTrusted=true
            console.log(`  ✓ "Start a Call" native-clicked (${sel}) in frame: ${frame.url().slice(0, 60)}`);
            await this.page.waitForTimeout(500);
            const ssPath2 = join(__dirname, `../../debug-post-call-${Date.now()}.png`);
            await this.page.screenshot({ path: ssPath2, fullPage: true }).catch(() => {});
            console.log(`  📸 Post-call screenshot: ${ssPath2}`);
            return true;
          }
        } catch { /* try next */ }
      }

      // Fallback: locator by accessible name (also native click)
      try {
        const locator = frame.getByRole('button', { name: /start.*(a )?call/i });
        if (await locator.count() > 0) {
          await locator.first().click();  // ← also trusted
          console.log(`  ✓ "Start a Call" clicked via role locator in frame: ${frame.url().slice(0, 60)}`);
          await this.page.waitForTimeout(500);
          const ssPath2 = join(__dirname, `../../debug-post-call-${Date.now()}.png`);
          await this.page.screenshot({ path: ssPath2, fullPage: true }).catch(() => {});
          console.log(`  📸 Post-call screenshot: ${ssPath2}`);
          return true;
        }
      } catch { /* cross-origin or no match */ }
    }
    return false;
  }

  /**
   * Wait for the Connect renderer iframe (at conversationalbot.my.connect.aws).
   * This is distinct from the emoji-picker iframe (about:blank) which appears first.
   */
  private async _waitForRendererFrame(timeoutMs: number): Promise<Frame | null> {
    if (!this.page) return null;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      for (const frame of this.page.frames()) {
        if (frame === this.page.mainFrame()) continue;
        const url = frame.url();
        // The renderer iframe loads from the Connect widget host
        if (url && url.includes('connect.aws') && !url.includes('about:blank')) {
          console.log(`  ℹ  Renderer iframe: ${url.slice(0, 100)}`);
          return frame;
        }
      }
      await this.page.waitForTimeout(300);
    }

    // Fallback: return the first non-main non-blank frame if renderer didn't load
    const anyFrame = this.page.frames().find(f =>
      f !== this.page!.mainFrame() && f.url() !== 'about:blank' && f.url() !== ''
    ) ?? null;
    if (anyFrame) {
      console.log(`  ℹ  Fallback iframe: ${anyFrame.url().slice(0, 100)}`);
      return anyFrame;
    }

    // Last resort: return any non-main frame
    const lastResort = this.page.frames().find(f => f !== this.page!.mainFrame()) ?? null;
    if (lastResort) console.log(`  ℹ  Last-resort iframe: ${lastResort.url().slice(0, 60)}`);
    return lastResort;
  }

  /** Inspect all buttons in the renderer frame, then attempt to click the voice one (fallback). */
  private async _inspectAndClickVoice(frame: Frame): Promise<void> {
    await frame.page().waitForTimeout(1000);

    // Log ALL non-emoji buttons for diagnostics
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const btns = await frame.evaluate(() => {
        const g = globalThis as any;
        return Array.from(g.document.querySelectorAll('button, [role="button"]'))
          .filter((b: any) => !(b.className ?? '').includes('emoji'))
          .map((b: any) => ({
            text:     b.textContent?.trim().slice(0, 60),
            aria:     b.getAttribute('aria-label'),
            testid:   b.getAttribute('data-testid'),
            cls:      b.className?.slice?.(0, 60),
            tag:      b.tagName,
          }));
      });
      /* eslint-enable @typescript-eslint/no-explicit-any */
      console.log(`  ℹ  Non-emoji buttons in renderer frame (${frame.url().slice(0, 60)}): ${btns.length}`);
      for (const b of btns) {
        console.log(`     • "${b.text}" aria="${b.aria}" testid="${b.testid}" cls="${b.cls?.slice(0, 30)}"`);
      }
    } catch (e) { console.log(`  ℹ  Could not read buttons: ${e}`); }

    // Try CSS selectors first (avoiding emoji selectors)
    const voiceSelectors = [
      '[aria-label*="voice" i]', '[aria-label*="call" i]', '[aria-label*="phone" i]',
      '[title*="voice" i]', '[title*="call" i]', '[title*="phone" i]',
      'button[class*="voice"]', 'button[class*="Voice"]',
      'button[class*="phone"]', 'button[class*="call" i]',
    ];
    for (const sel of voiceSelectors) {
      try {
        const el = await frame.$(sel);
        if (el) {
          await el.click();
          console.log(`  ✓ Voice button clicked via selector: ${sel}`);
          return;
        }
      } catch { /* try next */ }
    }

    // Text-based fallback
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const clicked: boolean = await frame.evaluate(() => {
        const g = globalThis as any;
        const btns = Array.from(g.document.querySelectorAll('button, [role="button"]')) as any[];
        const btn = btns.find((b: any) => {
          const t = (b.textContent?.trim() ?? '').toLowerCase();
          const a = (b.getAttribute('aria-label') ?? '').toLowerCase();
          return t.includes('voice') || t.includes('call') || t.includes('phone')
              || a.includes('voice') || a.includes('call') || a.includes('phone');
        });
        if (btn) { btn.click(); return true; }
        return false;
      });
      /* eslint-enable @typescript-eslint/no-explicit-any */
      if (clicked) console.log(`  ✓ Voice button clicked via text scan`);
    } catch { /* cross-origin */ }
  }

  /** Click the "..." or "more options" menu button in a frame. */
  private async _clickMoreOptionsMenu(frame: Frame): Promise<boolean> {
    const moreSelectors = [
      '[aria-label*="more" i]', '[aria-label*="option" i]', '[aria-label*="menu" i]',
      '[title*="more" i]', '[title*="option" i]',
      'button[class*="more"]', 'button[class*="More"]',
      'button[class*="option"]', 'button[class*="menu"]',
    ];

    // Also match buttons whose text is exactly "..." or "⋯"
    for (const sel of moreSelectors) {
      try {
        const el = await frame.$(sel);
        if (el) {
          await el.click();
          console.log(`  🖱  Clicked options menu: ${sel}`);
          return true;
        }
      } catch { /* try next */ }
    }

    // Text-based fallback for the literal "..." button
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const clicked: boolean = await frame.evaluate(() => {
        const g = globalThis as any;
        const btns = Array.from(g.document.querySelectorAll('button, [role="button"]')) as any[];
        const btn = btns.find((b: any) => {
          const t = b.textContent?.trim();
          return t === '...' || t === '⋯' || t === '•••' || (t?.length <= 3 && t?.includes('•'));
        });
        if (btn) { btn.click(); return true; }
        return false;
      });
      /* eslint-enable @typescript-eslint/no-explicit-any */
      if (clicked) { console.log(`  🖱  Clicked "..." button via text match`); return true; }
    } catch { /* ignore */ }

    return false;
  }

  /** Click the voice/phone call button in a given frame or page. Returns true if clicked. */
  private async _clickVoiceButtonIn(frame: Frame | Page): Promise<boolean> {
    const voiceSelectors = [
      '[aria-label*="voice" i]', '[aria-label*="call" i]', '[aria-label*="phone" i]',
      '[title*="voice" i]',     '[title*="call" i]',     '[title*="phone" i]',
      'button[class*="voice"]', 'button[class*="Voice"]',
      'button[class*="phone"]', 'button[class*="call"]',
      'button[class*="Phone"]', 'button[class*="Call"]',
      '[data-testid*="voice" i]', '[data-testid*="call" i]',
    ];
    for (const sel of voiceSelectors) {
      try {
        const isPage = 'mainFrame' in frame;
        const el = isPage ? await (frame as Page).$(sel) : await (frame as Frame).$(sel);
        if (el) {
          await el.click();
          console.log(`  ✓ Voice button clicked: ${sel}`);
          return true;
        }
      } catch { /* try next */ }
    }

    // Text-based fallback: buttons with voice/call text
    try {
      /* eslint-disable @typescript-eslint/no-explicit-any */
      const evalTarget = 'mainFrame' in frame ? (frame as Page) : (frame as Frame);
      const clicked: boolean = await evalTarget.evaluate(() => {
        const g = globalThis as any;
        const btns = Array.from(g.document.querySelectorAll('button, [role="button"], li, [role="menuitem"]')) as any[];
        const btn = btns.find((b: any) => {
          const t = (b.textContent?.trim() ?? '').toLowerCase();
          const a = (b.getAttribute('aria-label') ?? '').toLowerCase();
          return t.includes('voice') || t.includes('call') || t.includes('phone')
              || a.includes('voice') || a.includes('call') || a.includes('phone');
        });
        if (btn) { btn.click(); return true; }
        return false;
      });
      /* eslint-enable @typescript-eslint/no-explicit-any */
      if (clicked) { console.log(`  ✓ Voice button clicked via text scan`); return true; }
    } catch { /* cross-origin */ }

    return false;
  }

  /** Return the first frame (across all frames) that has an active RTCPeerConnection. */
  private async _getVoiceFrame(): Promise<Frame | null> {
    if (!this.page) return null;
    for (const frame of this.page.frames()) {
      try {
        const peers: number = await frame.evaluate(
          () => ((globalThis as unknown as Record<string, unknown[]>)['_rtcPeers'] ?? []).length,
        );
        if (peers > 0) return frame;
      } catch { /* cross-origin — skip */ }
    }
    return null;
  }

  /** Poll ALL frames until any has an RTCPeerConnection, or timeout. Logs diagnostics every 10s. */
  private async _waitForRtcPeer(timeoutMs: number): Promise<boolean> {
    if (!this.page) return false;
    const deadline = Date.now() + timeoutMs;
    let nextDiag = Date.now() + 10_000;
    while (Date.now() < deadline) {
      const found = await this._getVoiceFrame();
      if (found) return true;
      if (Date.now() >= nextDiag) {
        nextDiag = Date.now() + 10_000;
        for (const frame of this.page.frames()) {
          try {
            /* eslint-disable @typescript-eslint/no-explicit-any */
            const st: any = await frame.evaluate(() =>
              (globalThis as any)['getStatus']?.() ?? null,
            );
            /* eslint-enable @typescript-eslint/no-explicit-any */
            if (st) console.log(`  📡 [${Math.round((deadline - Date.now()) / 1000)}s left] ${frame.url().slice(0, 60)}: rtcPeers=${st.rtcPeers} gumCalls=${st.gumCalls} audioCtx=${st.audioCtxState} trackReplaced=${st.trackReplaced}`);
          } catch { /* cross-origin — skip */ }
        }
      }
      await this.page.waitForTimeout(500);
    }
    // Final frame status dump
    for (const frame of this.page.frames()) {
      try {
        /* eslint-disable @typescript-eslint/no-explicit-any */
        const st: any = await frame.evaluate(() =>
          (globalThis as any)['getStatus']?.() ?? null,
        );
        /* eslint-enable @typescript-eslint/no-explicit-any */
        if (st) console.log(`  📊 Frame status [${frame.url().slice(0, 60)}]: ${JSON.stringify(st)}`);
      } catch { /* cross-origin — skip */ }
    }
    return false;
  }

  async sendMessage(text: string, typing?: boolean): Promise<void> {
    if (!this.page) throw new AdapterError('Not connected');
    void typing;  // not used for voice

    console.log(`  🎤 Speaking: "${text.slice(0, 80)}${text.length > 80 ? '…' : ''}"`);

    // Synthesise speech with Polly
    const pcmBuffer = await this.synthesise(text);

    // Capture for call recording
    this.audioSegments.push({ role: 'customer', pcm: pcmBuffer, timestampMs: Date.now() });

    // Inject audio into the frame that owns the WebRTC peer, falling back to main page
    const base64pcm = pcmBuffer.toString('base64');
    const voiceFrame = await this._getVoiceFrame();
    const target = voiceFrame ?? this.page;

    await target.evaluate((b64: string) => {
      return (globalThis as unknown as Record<string, (b: string) => Promise<void>>)['injectAudio']?.(b64);
    }, base64pcm);

    if (voiceFrame) {
      console.log(`  ℹ  Audio injected into voice frame`);
    } else {
      console.log(`  ⚠  No voice frame — audio injected into main page (WebRTC not yet connected)`);
    }
  }

  async receive(timeoutMs = 40_000): Promise<AdapterMessage | null> {
    // Start capturing in the frame that has the WebRTC peer
    const voiceFrame = await this._getVoiceFrame();
    const captureTarget = voiceFrame ?? this.page;
    if (captureTarget) {
      await captureTarget.evaluate(() => {
        (globalThis as unknown as Record<string, () => void>)['startAgentAudioCapture']?.();
      }).catch(() => {});
    }

    // Reset transcript for new turn
    this.currentTranscript = '';

    // Return the next queued message or wait for one
    if (this.messageQueue.length > 0) {
      return this.messageQueue.shift()!;
    }

    return new Promise<AdapterMessage | null>((resolve) => {
      const timer = setTimeout(() => {
        this.resolveNextMessage = null;
        resolve(null);
      }, timeoutMs);

      this.resolveNextMessage = (m) => {
        clearTimeout(timer);
        resolve(m);
      };
    });
  }

  async disconnect(): Promise<void> {
    const voiceFrame = await this._getVoiceFrame();
    const captureTarget = voiceFrame ?? this.page;
    if (captureTarget) {
      await captureTarget.evaluate(() => {
        (globalThis as unknown as Record<string, () => void>)['stopAgentAudioCapture']?.();
      }).catch(() => {});
    }
    await this.context?.close();
    await this.browser?.close();
    this.page = null;
    this.context = null;
    this.browser = null;
    this.deepgramClient = null;
  }

  // ── Audio processing ────────────────────────────────────────────────────────

  private onAgentAudioChunk(base64chunk: string): void {
    // Send to Deepgram
    this.sendToDeepgram(base64chunk);
  }

  private async sendToDeepgram(base64chunk: string): Promise<void> {
    if (!this.config.deepgramApiKey) return;

    // Use Deepgram live transcription
    if (!this.deepgramClient) {
      this.deepgramClient = createDeepgramClient(this.config.deepgramApiKey);
    }

    // We use a simple approach: buffer chunks and periodically transcribe.
    // For production use, this would use the live streaming API.
    // For now, this detects utterance completion via silence.
    this.bufferAudio(base64chunk);
  }

  private audioBuffer: Buffer[] = [];
  private silenceTimer: NodeJS.Timeout | null = null;

  private bufferAudio(base64chunk: string): void {
    const chunk = Buffer.from(base64chunk, 'base64');
    this.audioBuffer.push(chunk);

    // Reset silence timer
    if (this.silenceTimer) clearTimeout(this.silenceTimer);
    this.silenceTimer = setTimeout(() => {
      this.flushAudioBuffer();
    }, this.config.silenceTimeoutSecs * 1000);
  }

  private async flushAudioBuffer(): Promise<void> {
    if (this.audioBuffer.length === 0) return;
    const combined = Buffer.concat(this.audioBuffer);
    this.audioBuffer = [];

    // Capture for call recording (agent side)
    if (combined.length >= 1000) {
      this.audioSegments.push({ role: 'agent', pcm: combined, timestampMs: Date.now() });
    }

    if (!this.config.deepgramApiKey || combined.length < 1000) return;

    try {
      const dg = createDeepgramClient(this.config.deepgramApiKey);
      const { result } = await dg.listen.prerecorded.transcribeFile(
        combined,
        {
          model: 'nova-2',
          smart_format: true,
          language: 'en-GB',
          encoding: 'linear16',
          sample_rate: 16000,
          channels: 1,
        },
      );

      const transcript = result?.results?.channels?.[0]?.alternatives?.[0]?.transcript ?? '';
      if (transcript.trim()) {
        console.log(`  🤖 agent (voice): "${transcript.trim().slice(0, 100)}"`);
        const msg: AdapterMessage = {
          role: 'agent',
          content: transcript.trim(),
          isNoise: false,
          timestampMs: Date.now(),
        };
        if (this.resolveNextMessage) {
          const fn = this.resolveNextMessage;
          this.resolveNextMessage = null;
          fn(msg);
        } else {
          this.messageQueue.push(msg);
        }
      }
    } catch (err) {
      console.error('  ⚠  Deepgram transcription error:', err);
    }
  }

  // ── TTS ─────────────────────────────────────────────────────────────────────

  private async synthesise(text: string): Promise<Buffer> {
    // Polly supports raw PCM output directly — no ffmpeg needed
    const resp = await this.polly.send(
      new SynthesizeSpeechCommand({
        Text: text,
        TextType: TextType.TEXT,
        VoiceId: this.config.pollyVoiceId as VoiceId,
        Engine: Engine.NEURAL,
        OutputFormat: OutputFormat.PCM,  // raw signed 16-bit little-endian PCM
        SampleRate: '16000',
      }),
    );

    if (!resp.AudioStream) throw new AdapterError('Polly returned no audio stream');

    const chunks: Buffer[] = [];
    for await (const chunk of resp.AudioStream as AsyncIterable<Uint8Array>) {
      chunks.push(Buffer.from(chunk));
    }
    return Buffer.concat(chunks);
  }

  // ── Call recording ───────────────────────────────────────────────────────────

  /** True when audio segments were captured during the run */
  hasAudio(): boolean {
    return this.audioSegments.length > 0;
  }

  /**
   * Build a WAV file from captured audio segments and save to outputPath.
   * Segments are written in timestamp order, separated by 400 ms of silence.
   * Format: mono, 16 kHz, 16-bit signed little-endian PCM.
   * Returns the output path.
   */
  saveAudio(outputPath: string): string {
    if (this.audioSegments.length === 0) {
      throw new AdapterError('No audio segments captured');
    }

    // Sort by capture time (should already be in order, but be safe)
    const sorted = [...this.audioSegments].sort((a, b) => a.timestampMs - b.timestampMs);

    // Concatenate PCM with 400 ms silence between segments
    const parts: Buffer[] = [];
    for (let i = 0; i < sorted.length; i++) {
      if (i > 0) parts.push(SILENCE_400MS);
      parts.push(sorted[i]!.pcm);
    }
    const pcmData = Buffer.concat(parts);

    // Build WAV file
    const wav = Buffer.concat([buildWavHeader(pcmData.byteLength), pcmData]);

    mkdirSync(dirname(outputPath), { recursive: true });
    writeFileSync(outputPath, wav);
    return outputPath;
  }
}
