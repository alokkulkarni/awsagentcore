/**
 * Real AudioCapture implementation using Web Audio API.
 * Captures microphone input, resamples to 16 kHz, emits Int16Array chunks.
 *
 * Accepts an optional shared AudioContext. When the same context is used for
 * both capture and playback (AudioPlayer), Chrome's AEC has full visibility of
 * the playback signal as its echo reference — essential for speaker use.
 */
export class AudioCapture {
  /**
   * @param {{ onChunk: function, onWaveform: function, targetSampleRate?: number, chunkSize?: number, audioContext?: AudioContext }} opts
   */
  constructor({ onChunk, onWaveform, targetSampleRate = 16000, chunkSize = 1024, audioContext = null }) {
    this.onChunk = onChunk;
    this.onWaveform = onWaveform;
    this.targetSampleRate = targetSampleRate;
    this.chunkSize = chunkSize;
    this._externalContext = audioContext; // shared context from useVoice

    this.audioContext = null;
    this.mediaStream = null;
    this.sourceNode = null;
    this.analyserNode = null;
    this.processorNode = null;
    this.isRunning = false;

    this._sampleBuffer = [];
  }

  async start() {
    if (this.isRunning) return;

    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
    });

    // Use the shared context if provided; otherwise create one at browser native rate.
    // Do NOT specify a sample rate — let the browser use its native rate so the OS
    // AEC reference aligns with the playback context sample rate.
    this.audioContext = this._externalContext ?? new AudioContext();
    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);

    // Analyser for waveform visualisation
    this.analyserNode = this.audioContext.createAnalyser();
    this.analyserNode.fftSize = 256;
    this.analyserNode.smoothingTimeConstant = 0.8;
    this.sourceNode.connect(this.analyserNode);

    // ScriptProcessor for raw PCM access (4096 frames, 1 in, 1 out)
    this.processorNode = this.audioContext.createScriptProcessor(4096, 1, 1);
    const nativeSampleRate = this.audioContext.sampleRate;
    const targetRate = this.targetSampleRate;
    const chunkSize = this.chunkSize;
    const onChunk = this.onChunk;
    const bufRef = this._sampleBuffer;

    this.processorNode.onaudioprocess = (event) => {
      if (!this.isRunning) return;

      const inputBuffer = event.inputBuffer.getChannelData(0);
      const resampled = resampleBuffer(inputBuffer, nativeSampleRate, targetRate);

      for (let i = 0; i < resampled.length; i++) {
        bufRef.push(resampled[i]);
      }

      while (bufRef.length >= chunkSize) {
        const chunk = bufRef.splice(0, chunkSize);
        const float32 = new Float32Array(chunk);
        const int16 = float32ToInt16(float32);
        onChunk(int16);
      }
    };

    this.sourceNode.connect(this.processorNode);
    // Connect to destination so the graph runs (output is silent)
    this.processorNode.connect(this.audioContext.destination);

    this.isRunning = true;
  }

  stop() {
    this.isRunning = false;
    this._sampleBuffer = [];

    if (this.processorNode) {
      this.processorNode.disconnect();
      this.processorNode.onaudioprocess = null;
      this.processorNode = null;
    }
    if (this.analyserNode) {
      this.analyserNode.disconnect();
      // Keep analyserNode ref briefly for last-frame reads, then null
      this.analyserNode = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    if (this.audioContext) {
      // Only close the context if we created it (not if it was shared externally)
      if (!this._externalContext) {
        this.audioContext.close().catch(() => {});
      }
      this.audioContext = null;
    }
  }

  getAnalyserNode() {
    return this.analyserNode;
  }
}

/**
 * Resample Float32 audio buffer from inputSampleRate to targetSampleRate
 * using linear interpolation.
 * @param {Float32Array} inputBuffer
 * @param {number} inputSampleRate
 * @param {number} targetSampleRate
 * @returns {Float32Array}
 */
function resampleBuffer(inputBuffer, inputSampleRate, targetSampleRate) {
  if (inputSampleRate === targetSampleRate) return inputBuffer;

  const ratio = inputSampleRate / targetSampleRate;
  const outputLength = Math.round(inputBuffer.length / ratio);
  const output = new Float32Array(outputLength);

  for (let i = 0; i < outputLength; i++) {
    const pos = i * ratio;
    const index = Math.floor(pos);
    const frac = pos - index;
    const a = inputBuffer[index] !== undefined ? inputBuffer[index] : 0;
    const b = inputBuffer[index + 1] !== undefined ? inputBuffer[index + 1] : 0;
    output[i] = a + frac * (b - a);
  }

  return output;
}

/**
 * Convert Float32Array samples to Int16Array (PCM 16-bit signed).
 * @param {Float32Array} float32Array
 * @returns {Int16Array}
 */
function float32ToInt16(float32Array) {
  const int16 = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return int16;
}
