// Chat or call with ARIA from the Money Hub page.
// The page Lambda starts the contact (it alone knows who this is); the browser then joins it:
//   chat  through the Amazon Connect Participant Service (HTTPS + a websocket), with the participant token
//   call  through the Amazon Chime SDK (loaded only when a call starts), with the meeting and attendee
// The participant and connection tokens live only in this module's memory. Every message is written as text.
// Where it sits on the page (the bottom tag and the overlay) is dock.js.
import { TABS, setupDock } from './dock.js';

const PARTICIPANT = (region) => `https://participant.connect.${region}.amazonaws.com/participant`;
const HEARTBEAT_MS = 10000;
const CHAT_ENDED = 'application/vnd.amazonaws.connect.event.chat.ended';
// ARIA only hears messages sent after its bot block has joined. The flow announces that with a (blank)
// message; if none arrives, the opener is sent anyway after this long.
const READY_WAIT_MS = 20000;
// Markdown emphasis shown as plain text (every message is written as text, never HTML).
const plain = (words) => words.replace(/(\*\*|__)(.+?)\1/g, '$2');

export function setupTalk({ api, currentView, onEnded }) {
  const $ = (id) => document.getElementById(id);
  const dock = setupDock({ currentView });
  let live = null;          // { kind, region, participantToken, connectionToken, socket, heartbeat, session, stream }
  const seen = new Set();

  const status = (words) => { $('talk-status').textContent = words; };

  async function participant(region, path, bearer, body) {
    const response = await fetch(`${PARTICIPANT(region)}/${path}`, {
      method: 'POST', headers: { 'content-type': 'application/json', 'X-Amz-Bearer': bearer }, body: JSON.stringify(body),
      keepalive: true,                  // so leaving the page still ends the contact
    });
    if (!response.ok) {
      // Connect's own reason, for the browser console only (it never contains a token).
      const reason = await response.json().then((j) => j.Message || j.message || '').catch(() => '');
      console.warn(`Connect participant ${path} failed: ${response.status} ${reason}`);
      throw new Error(`We couldn't connect the conversation (${response.status}). Please try again.`);
    }
    return response.json().catch(() => ({}));
  }

  function show(role, words) {
    const li = document.createElement('li');
    li.className = role === 'CUSTOMER' ? 'me' : role === 'SYSTEM' ? 'system' : 'them';
    li.textContent = plain(words);
    $('chat-log').append(li);
    $('talk-body').scrollTop = $('talk-body').scrollHeight;     // the overlay scrolls, never the page
  }

  function onChatItem(item) {
    if (!item || (item.Id && seen.has(item.Id))) return;
    if (item.Id) seen.add(item.Id);
    if (item.Type === 'MESSAGE') {
      if ((item.Content || '').trim()) show(item.ParticipantRole, item.Content);    // the flow's blank line isn't shown
      if (item.ParticipantRole !== 'CUSTOMER') sendOpener();                       // ARIA is listening now
    }
    if (item.Type === 'EVENT' && item.ContentType === CHAT_ENDED) finish('The chat has ended.');
  }

  function begin(kind) {
    $('chat-log').replaceChildren();
    seen.clear();
    $('talk-start').hidden = true;
    $('talk-foot').hidden = false;
    $('chat-form').hidden = kind !== 'chat';
    $('call-controls').hidden = kind !== 'call';
    $('call-mute').textContent = 'Mute';
    $('call-mute').setAttribute('aria-pressed', 'false');
    $('talk-end').textContent = kind === 'call' ? 'End call' : 'End chat';
    dock.live(kind);               // remembers the tab it started from
  }

  // The first thing the customer says: which tab they're on. Sent as an ordinary message once ARIA is
  // listening, so ARIA can let the Money Hub agent take over straight away. Until then the input stays off,
  // so nothing the customer types is lost.
  function sendOpener() {
    if (!live || live.kind !== 'chat' || live.opened || !live.connectionToken) return;
    live.opened = true;
    clearTimeout(live.openerTimer);
    const tab = TABS[live.view] || TABS.out;
    participant(live.region, 'message', live.connectionToken, { ContentType: 'text/plain', ClientToken: crypto.randomUUID(),
      Content: `I'm on my Money Hub page, on the ${tab} tab, and I'd like some help understanding my money.` })
      .catch((error) => status(error.message));
    typing(true);
    status('Connected.');
  }

  function typing(on) {
    $('chat-input').disabled = !on;
    $('chat-form').querySelector('button').disabled = !on;
    if (on) $('chat-input').focus({ preventScroll: true });
  }

  async function startChat() {
    begin('chat'); status('Connecting you…');
    try {
      const view = currentView();
      const started = await api('/contact/chat', { view });
      live = { kind: 'chat', region: started.region, participantToken: started.participantToken, view };
      const joined = await participant(started.region, 'connection', started.participantToken,
        { Type: ['WEBSOCKET', 'CONNECTION_CREDENTIALS'] });     // no ConnectParticipant: that's for streaming and agents
      live.connectionToken = joined.ConnectionCredentials.ConnectionToken;
      const socket = new WebSocket(joined.Websocket.Url);
      live.socket = socket;
      socket.addEventListener('open', async () => {
        socket.send(JSON.stringify({ topic: 'aws/subscribe', content: { topics: ['aws/chat'] } }));
        live.heartbeat = setInterval(() => socket.send(JSON.stringify({ topic: 'aws/heartbeat' })), HEARTBEAT_MS);
        status('Connecting you to our assistant…');
        typing(false);
        // Anything said before the websocket was listening (your first message, the greeting).
        const transcript = await participant(live.region, 'transcript', live.connectionToken,
          { MaxResults: 100, ScanDirection: 'FORWARD', SortOrder: 'ASCENDING' }).catch(() => ({}));
        (transcript.Transcript || []).forEach(onChatItem);
        if (live && !live.opened) live.openerTimer = setTimeout(sendOpener, READY_WAIT_MS);
      });
      socket.addEventListener('message', (event) => {
        let frame;
        try { frame = JSON.parse(event.data); } catch { return; }
        if (frame.topic !== 'aws/chat' || !frame.content) return;
        try { onChatItem(JSON.parse(frame.content)); } catch { /* not a chat item */ }
      });
      socket.addEventListener('close', () => { if (live && live.kind === 'chat') finish('The chat has ended.'); });
    } catch (error) {
      finish(error.message);
    }
  }

  async function sendChat(event) {
    event.preventDefault();
    const words = $('chat-input').value.trim();
    if (!words || !live || !live.connectionToken) return;
    $('chat-input').value = '';
    try {
      await participant(live.region, 'message', live.connectionToken,
        { ContentType: 'text/plain', Content: words, ClientToken: crypto.randomUUID() });
    } catch (error) { status(error.message); }
  }

  async function startCall() {
    begin('call'); status('Starting your call…');
    try {
      // Ask for the microphone first, so a refusal costs nothing.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const started = await api('/contact/call', { view: currentView() });
      const chime = await import('/assets/chime.js');
      const logger = new chime.ConsoleLogger('call', chime.LogLevel.WARN);
      const devices = new chime.DefaultDeviceController(logger);
      const config = new chime.MeetingSessionConfiguration({ Meeting: started.meeting }, { Attendee: started.attendee });
      const session = new chime.DefaultMeetingSession(config, logger, devices);
      live = { kind: 'call', region: started.region, participantToken: started.participantToken, session, stream };
      const av = session.audioVideo;
      av.addObserver({
        audioVideoDidStart: () => status('Connected. Speak when you\'re ready.'),
        audioVideoDidStop: () => { if (live && live.kind === 'call') finish('The call has ended.'); },
      });
      await av.startAudioInput(stream);
      await av.bindAudioElement($('talk-audio'));
      av.start();
    } catch (error) {
      const words = error && error.name === 'NotAllowedError'
        ? 'To call, allow this page to use your microphone.' : (error.message || 'The call could not start.');
      finish(words);
    }
  }

  function toggleMute() {
    if (!live || !live.session) return;
    const av = live.session.audioVideo;
    const muted = av.realtimeIsLocalAudioMuted();
    if (muted) av.realtimeUnmuteLocalAudio(); else av.realtimeMuteLocalAudio();
    $('call-mute').textContent = muted ? 'Mute' : 'Unmute';
    $('call-mute').setAttribute('aria-pressed', String(!muted));
  }

  // Leave properly, so Connect ends the contact rather than waiting for a timeout.
  async function hangUp() {
    if (!live) return;
    const current = live;
    try {
      const token = current.connectionToken || (await participant(current.region, 'connection',
        current.participantToken, { Type: ['CONNECTION_CREDENTIALS'] })).ConnectionCredentials.ConnectionToken;
      await participant(current.region, 'disconnect', token, { ClientToken: crypto.randomUUID() });
    } catch { /* the contact may already have ended */ }
    finish(current.kind === 'call' ? 'You ended the call.' : 'You ended the chat.');
  }

  function finish(words) {
    const current = live;
    live = null;
    if (current) {
      clearInterval(current.heartbeat);
      clearTimeout(current.openerTimer);
      try { current.socket && current.socket.close(); } catch { /* already closed */ }
      try { current.session && current.session.audioVideo.stop(); } catch { /* already stopped */ }
      (current.stream ? current.stream.getTracks() : []).forEach((track) => track.stop());
    }
    $('talk-foot').hidden = true;
    $('talk-start').hidden = false;
    // A finished conversation leaves the page: only a one-line note of how it ended stays.
    $('chat-log').replaceChildren();
    seen.clear();
    $('chat-input').value = '';
    dock.live('');
    status(words);
    if (current) onEnded();       // the assistant may have changed categories or goals
  }

  $('talk-chat').addEventListener('click', startChat);
  $('talk-call').addEventListener('click', startCall);
  $('chat-form').addEventListener('submit', sendChat);
  $('call-mute').addEventListener('click', toggleMute);
  $('talk-end').addEventListener('click', hangUp);
  // Closing ends any conversation; minimising (in dock.js) keeps it going behind the bottom tag.
  $('talk-close').addEventListener('click', () => { if (live) hangUp(); dock.hide(); });
  window.addEventListener('pagehide', () => { if (live) hangUp(); });
}
