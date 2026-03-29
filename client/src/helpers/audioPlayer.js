/**
 * Real AudioPlayer implementation using Web Audio API.
 * Receives 24 kHz 16-bit mono PCM chunks and plays them gaplessly.
 */
export class AudioPlayer {
  /**
   * @param {{ sampleRate?: number }} opts
   */
  constructor({ sampleRate = 24000 } = {}) {
    this.sampleRate = sampleRate;
    this.context = null;
    this.nextPlayTime = 0;
    this.activeSources = [];
    this.isInitialized = false;
  }

  init() {
    if (this.isInitialized) return;

    try {
      this.context = new AudioContext({ sampleRate: this.sampleRate });
    } catch {
      // Fallback: create without specific sample rate; resampling handled by browser
      this.context = new AudioContext();
    }

    this.nextPlayTime = 0;
    this.activeSources = [];
    this.isInitialized = true;
  }

  /**
   * Queue and play a chunk of 16-bit PCM audio.
   * @param {Int16Array} int16Data - Raw 16-bit signed PCM samples at this.sampleRate
   */
  playChunk(int16Data) {
    if (!this.context) return;

    // Resume AudioContext if suspended (browser autoplay policy)
    if (this.context.state === 'suspended') {
      this.context.resume().catch(() => {});
    }

    const float32 = int16ToFloat32(int16Data);
    const buffer = this.context.createBuffer(1, float32.length, this.sampleRate);
    buffer.copyToChannel(float32, 0);

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);

    const now = this.context.currentTime;
    const startTime = Math.max(now, this.nextPlayTime);

    source.start(startTime);
    this.nextPlayTime = startTime + buffer.duration;

    // Track active sources for cleanup
    this.activeSources.push(source);
    source.onended = () => {
      const idx = this.activeSources.indexOf(source);
      if (idx !== -1) this.activeSources.splice(idx, 1);
    };
  }

  stop() {
    // Stop all active sources immediately
    for (const src of this.activeSources) {
      try {
        src.stop();
      } catch {
        // Already stopped
      }
    }
    this.activeSources = [];
    this.nextPlayTime = 0;

    if (this.context) {
      // Don't close the context; just reset playback state so it can be reused
      const ctx = this.context;
      this.context = null;
      this.isInitialized = false;
      ctx.close().catch(() => {});
    }
  }

  getState() {
    return this.context?.state;
  }
}

/**
 * Convert Int16Array PCM samples to Float32Array in [-1, 1] range.
 * @param {Int16Array} int16Array
 * @returns {Float32Array}
 */
function int16ToFloat32(int16Array) {
  const float32 = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    float32[i] = int16Array[i] / (int16Array[i] < 0 ? 0x8000 : 0x7fff);
  }
  return float32;
}
