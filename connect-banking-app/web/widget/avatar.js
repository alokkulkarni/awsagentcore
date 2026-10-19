// The face on a call: a real-looking person (Tavus) who speaks the call's own voice, face moving in time.
// The Connect call doesn't change. Its audio (what Connect sends to the customer: ARIA's or the Money Hub agent's
// voice, never the customer's microphone) goes into a private Tavus room as "echo" messages; the face repeats it
// exactly, with matching video, and the page plays both. While the face is live the call's own audio element is
// muted, so the voice is heard once, in sync with the face. Anything going wrong unmutes the call: the face can
// never break a call. The room is closed when the face stops, so it stops counting minutes.
const START_WAIT_MS = 30000;     // longer than this for the face to appear, and the call carries on without it
const TRACK_WAIT_MS = 15000;     // how long to wait for the call's audio to arrive
const SAMPLE_RATE = 24000;       // what Tavus recommends for echo audio
const SPEAKING = 0.008;          // a 100 ms chunk this loud (RMS) or louder is speech
const QUIET_CHUNKS = 7;          // 0.7 s below it ends an utterance

function within(ms, promise, why) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(why)), ms); })])
    .finally(() => clearTimeout(timer));
}

// The call's remote audio track, once Chime has bound it to the call's audio element.
async function callTrack(callAudio) {
  const started = Date.now();
  while (Date.now() - started < TRACK_WAIT_MS) {
    const track = callAudio.srcObject && callAudio.srcObject.getAudioTracks && callAudio.srcObject.getAudioTracks()[0];
    if (track) return track;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error('no call audio');
}

function base64(buffer) {
  const bytes = new Uint8Array(buffer);
  let text = '';
  for (let i = 0; i < bytes.length; i += 0x2000) text += String.fromCharCode(...bytes.subarray(i, i + 0x2000));
  return btoa(text);
}

// Starts the face for this call. context: an AudioContext at 24 kHz, made when the customer pressed Call (browsers
// only let a page start audio from a tap or click). onGone(reason) runs once if the face stops by itself.
// Returns { stop }.
export async function startAvatar({ api, contactId, context, callAudio, video, audio, onGone, onStage = () => {} }) {
  // Each step in the console and on the overlay, so a face that never appears shows where it stopped.
  const began = performance.now();
  const stage = (words, step) => { onStage(words); console.info(`[video] ${step} +${Math.round(performance.now() - began)} ms`); };
  let call = null;
  let room = null;
  let source = null;
  let node = null;
  let stopped = false;

  function stop(reason = '') {
    if (stopped) return;
    stopped = true;
    callAudio.muted = false;                       // the call's own voice, straight away
    try { if (source) source.disconnect(); } catch { /* already gone */ }
    try { if (node) { node.port.onmessage = null; node.disconnect(); } } catch { /* already gone */ }
    if (call) call.leave().catch(() => {}).finally(() => call.destroy().catch(() => {}));
    if (room) api('/contact/avatar/end', { conversationId: room.conversationId }).catch(() => {});
    video.srcObject = null;
    audio.srcObject = null;
    if (reason) onGone(reason);
  }

  try {
    stage('Opening the video room…', 'asking for a room');
    room = await api('/contact/avatar', { contactId });
    stage('Connecting to the video…', 'room ready');
    const [{ default: Daily }] = await Promise.all([
      import('/assets/vendor/daily.js'), context.audioWorklet.addModule('/assets/widget/pcm-worklet.js'), context.resume()]);
    // No camera and no microphone of our own: the page only sends the call's audio, as messages.
    call = Daily.createCallObject({ audioSource: false, videoSource: false, subscribeToTracksAutomatically: true,
      dailyConfig: { avoidEval: true } });
    const faceShown = new Promise((resolve) => {
      call.on('track-started', ({ participant, track }) => {
        if (!participant || participant.local) return;
        if (track.kind === 'video') {
          video.addEventListener('loadeddata', () => resolve(), { once: true });       // her first frame is showing
          video.srcObject = new MediaStream([track]);
          video.play().catch(() => {});
        }
        if (track.kind === 'audio') { audio.srcObject = new MediaStream([track]); audio.play().catch(() => {}); }
      });
    });
    call.on('participant-left', ({ participant }) => { if (participant && !participant.local) stop('The video stopped.'); });
    call.on('left-meeting', () => stop('The video stopped.'));
    call.on('error', () => stop('The video stopped.'));
    await call.join({ url: room.conversationUrl, token: room.meetingToken, startAudioOff: true, startVideoOff: true });
    stage('Waiting for the assistant to appear…', 'joined the room, waiting for the face');
    await within(START_WAIT_MS, faceShown, 'video took too long');
    stage('', 'face showing');
    if (stopped) return { stop };

    // From here the call's voice reaches the customer through the face. Each stretch of speech is one utterance:
    // its chunks share an id, and a short silent chunk marked done closes it.
    const echo = (pcm, utterance, done) => call.sendAppMessage({
      message_type: 'conversation', event_type: 'conversation.echo', conversation_id: room.conversationId,
      properties: { modality: 'audio', inference_id: utterance, audio: base64(pcm), done, sample_rate: SAMPLE_RATE },
    }, '*');
    let utterance = null;
    let quiet = 0;
    let before = null;                             // the chunk before speech starts, so the first syllable isn't cut
    source = context.createMediaStreamSource(new MediaStream([await callTrack(callAudio)]));
    node = new AudioWorkletNode(context, 'pcm-chunks');
    node.port.onmessage = ({ data }) => {
      try {
        if (data.level >= SPEAKING) {
          if (!utterance) {
            utterance = crypto.randomUUID();
            if (before) echo(before, utterance, false);
          }
          echo(data.pcm, utterance, false);
          quiet = 0;
        } else if (utterance) {
          echo(data.pcm, utterance, false);        // pauses between words stay in
          quiet += 1;
          if (quiet >= QUIET_CHUNKS) {
            echo(new Int16Array(Math.round(SAMPLE_RATE / 25)).buffer, utterance, true);     // 40 ms of silence: done
            utterance = null;
            quiet = 0;
          }
        }
        before = data.pcm;
      } catch { stop('The video stopped.'); }
    };
    source.connect(node);
    callAudio.muted = true;
    return { stop };
  } catch (error) {
    console.info(`[video] stopped: ${error && error.message ? error.message : 'error'} +${Math.round(performance.now() - began)} ms`);
    stop();
    throw error;
  }
}
