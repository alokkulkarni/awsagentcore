// Local avatar check: the same avatar.js a call uses, fed a sample voice instead of the call's audio.
// The sample plays into a stream on the hidden "call" audio element, just as Chime's audio would arrive.
import { startAvatar } from '/assets/avatar.js';

const $ = (id) => document.getElementById(id);
const status = (words) => { $('talk-status').textContent = words; };
let handle = null;
let voice = null;          // { context, buffer, destination }

// The page's own routes stand in for the call's: /contact/avatar opens the room, /contact/avatar/end closes it.
async function api(path, body = {}) {
  const response = await fetch(`/api${path.replace('/contact/avatar', '/avatar-demo')}`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const json = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(json.message || `HTTP ${response.status}`);
  return json;
}

$('demo-start').addEventListener('click', async () => {
  $('demo-start').disabled = true;
  status('Starting the face…');
  const context = new AudioContext({ sampleRate: 24000 });        // made on the click, as on a call
  const sampleContext = new AudioContext();
  const buffer = await fetch('/avatar-demo.wav').then((r) => r.arrayBuffer()).then((b) => sampleContext.decodeAudioData(b));
  const destination = sampleContext.createMediaStreamDestination();
  voice = { context: sampleContext, buffer, destination };
  $('talk-audio').srcObject = destination.stream;
  $('avatar').hidden = false;
  try {
    const started = performance.now();
    handle = await startAvatar({ api, contactId: 'demo', context, callAudio: $('talk-audio'), video: $('avatar-video'),
      audio: $('avatar-audio'), onGone: (why) => status(why) });
    status(`The face is live (${Math.round(performance.now() - started)} ms to start). Play the sample voice.`);
    $('demo-speak').disabled = false;
    $('demo-stop').disabled = false;
  } catch (error) {
    status(`The face didn't start: ${error.message || error}`);
    $('demo-start').disabled = false;
  }
});

$('demo-speak').addEventListener('click', () => {
  const source = voice.context.createBufferSource();
  source.buffer = voice.buffer;
  source.connect(voice.destination);
  source.start();
});

$('demo-stop').addEventListener('click', () => {
  if (handle) handle.stop();
  handle = null;
  $('avatar').hidden = true;
  $('demo-speak').disabled = true;
  $('demo-stop').disabled = true;
  $('demo-start').disabled = false;
  status('Stopped.');
});
