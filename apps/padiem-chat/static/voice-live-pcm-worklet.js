/* apps/padiem-chat/static/voice-live-pcm-worklet.js
 *
 * Audio render thread: convert microphone floats into transferable 16-bit PCM.
 *
 * Port of skerishKang/global-classroom public/worklets/interview-pcm-processor.js
 * (the reviewed capture path of the Global Classroom live transcription).
 * The processor name is PADIEM's own so this module never collides with the
 * reference one.
 */
class PadiemVoiceLivePcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Int16Array(2048);
    this.offset = 0;
    this.port.onmessage = (event) => {
      if (event.data === 'stop') this.offset = 0;
    };
  }
  process(inputs, outputs) {
    const input = inputs[0]?.[0];
    for (const channel of outputs[0] || []) channel.fill(0);
    if (!input) return true;
    for (let i = 0; i < input.length; i++) {
      const v = Math.max(-1, Math.min(1, input[i]));
      this.buffer[this.offset++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.offset === this.buffer.length) {
        this.port.postMessage(this.buffer.buffer, [this.buffer.buffer]);
        this.buffer = new Int16Array(2048);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor('padiem-voice-live-pcm', PadiemVoiceLivePcmProcessor);
