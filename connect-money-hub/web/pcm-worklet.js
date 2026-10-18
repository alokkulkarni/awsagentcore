// The call's audio as 16-bit PCM, mono, in chunks of 100 ms at the AudioContext's rate (avatar.js runs it at
// 24 kHz, so the browser resamples). Each chunk goes back to avatar.js with how loud it was, for telling speech from
// silence. Served from the page itself, so the page's script policy needs no blob: URLs.
class PcmChunks extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = Math.round(sampleRate / 10);       // 100 ms
    this.buffer = new Int16Array(this.size);
    this.used = 0;
    this.energy = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      for (let i = 0; i < channel.length; i += 1) {
        const sample = channel[i];
        this.energy += sample * sample;
        this.buffer[this.used] = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)));
        this.used += 1;
        if (this.used === this.size) {
          const full = this.buffer;
          this.port.postMessage({ pcm: full.buffer, level: Math.sqrt(this.energy / this.size) }, [full.buffer]);
          this.buffer = new Int16Array(this.size);
          this.used = 0;
          this.energy = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor('pcm-chunks', PcmChunks);
