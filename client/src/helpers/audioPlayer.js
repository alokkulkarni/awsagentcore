/**
 * Real AudioPlayer implementation using Web Audio API.
 * Receives 24 kHz 16-bit mono PCM chunks and plays them gaplessly.
 *
 * Accepts an optional shared AudioContext. When the same context is used for
 * both capture and playback, Chrome's AEC has full visibility of the playback
 * signal as its echo reference — critical for speaker (non-headphone) use.
 */
export class AudioPlayer {
  /**
   * @param {{ sampleRate?: number, audioContext?: AudioContext }} opts
   */
  constructor({ sampleRate = 24000, audioContext = null } = {}) {
    this.sourceSampleRate = sampleRate; // rate of incoming PCM from Nova Sonic
    this._externalContext = audioContext; // shared context passed in from useVoice
    this.context = null;
    this.nextPlayTime = 0;
    this.activeSources = [];
    this.isInitialized = false;
  }

  init() {
    if (this.isInitialized) return;

    if (this._externalContext) {
      // Use the shared context (same as AudioCapture) — ensures AEC reference matches
      this.context = this._externalContext;
    } else {
      try {
        // Fallback: create at browser native rate (NOT 24000) so OS AEC can track it
        this.context = new AudioContext();
      } catch {
        this.context = new AudioContext();
      }
    }

    this.nextPlayTime = 0;
    this.activeSources = [];
    this.isInitialized = true;
  }

  /**
   * Queue and play a chunk of 16-bit PCM audio.
   * Resamples from sourceSampleRate → context.sampleRate if they differ.
   * @param {Int16Array} int16Data - Raw 16-bit signed PCM at this.sourceSampleRate
   */
  playChunk(int16Data) {
    if (!this.context) return;

    if (this.context.state === 'suspended') {
      this.context.resume().catch(() => {});
    }

    const float32 = int16ToFloat32(int16Data);

    // Resample if the context rate differs from the incoming PCM rate
    const contextRate = this.context.sampleRate;
    const resampled = contextRate !== this.sourceSampleRate
      ? resampleLinear(float32, this.sourceSampleRate, contextRate)
      : float32;

    const buffer = this.context.createBuffer(1, resampled.length, contextRate);
    buffer.copyToChannel(resampled, 0);

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);

    const now = this.context.currentTime;
    const startTime = Math.max(now, this.nextPlayTime);

    source.start(startTime);
    this.nextPlayTime = startTime + buffer.duration;

    this.activeSources.push(source);
    source.onended = () => {
      const idx = this.activeSources.indexOf(source);
      if (idx !== -1) this.activeSources.splice(idx, 1);
    };
  }

  bargeIn() {
    for (const src of this.activeSources) {
      try { src.stop(); } catch {}
    }
    this.activeSources = [];
    if (this.context) {
      this.nextPlayTime = this.context.currentTime;
    }
  }

  stop() {
    for (const src of this.activeSources) {
      try { src.stop(); } catch {}
    }
    this.activeSources = [];
    this.nextPlayTime = 0;

    // Only close the context if we own it (i.e. it wasn't passed in externally)
    if (this.context && !this._externalContext) {
      const ctx = this.context;
      this.context = null;
      this.isInitialized = false;
      ctx.close().catch(() => {});
    } else {
      this.context = null;
      this.isInitialized = false;
    }
  }

  getState() {
    return this.context?.state;
  }
}

/**
 * Resample Float32 audio from inputRate to outputRate using linear interpolation.
 */
function resampleLinear(input, inputRate, outputRate) {
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const outputLength = Math.round(input.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    const pos = i * ratio;
    const idx = Math.floor(pos);
    const frac = pos - idx;
    const a = input[idx] ?? 0;
    const b = input[idx + 1] ?? 0;
    output[i] = a + frac * (b - a);
  }
  return output;
}

/**
 * Convert Int16Array PCM samples to Float32Array in [-1, 1] range.
 */
function int16ToFloat32(int16Array) {
  const float32 = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    float32[i] = int16Array[i] / (int16Array[i] < 0 ? 0x8000 : 0x7fff);
  }
  return float32;
}
