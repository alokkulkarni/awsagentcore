// Chat or call from any page of the internet banking app. The page the customer is on decides who helps
// (the server's bankapp/journeys.py): the Money Hub agent, the mortgage assistant (which fills the form through
// Live Sync), the card dispute assistant, or ARIA itself. The app's Lambda starts the contact (it alone knows who
// this is); the browser then joins it:
//   chat  through the Amazon Connect Participant Service (HTTPS + a websocket), with the participant token
//   call  through the Amazon Chime SDK (loaded only when a call starts), with the meeting and attendee
// The participant and connection tokens live only in this module's memory. Every message is written as text.
// Where it sits on the page (the bottom tag and the overlay) is dock.js. On a call, a real-looking face can speak
// the call's voice (avatar.js); the call itself never depends on it.
import { setupDock } from './dock.js';
import { startAvatar } from './avatar.js';
import { amounts, layout } from './format.js';

const PARTICIPANT = (region) => `https://participant.connect.${region}.amazonaws.com/participant`;
const HEARTBEAT_MS = 10000;
const CHAT_ENDED = 'application/vnd.amazonaws.connect.event.chat.ended';
// ARIA only hears messages sent after its bot block has joined. The flow announces that with a (blank)
// message; if none arrives, the opener is sent anyway after this long.
const READY_WAIT_MS = 20000;
// A call is audio only: what's said on it is read back from the page Lambda this often, to show as text.
const TRANSCRIPT_EVERY_MS = 2000;
// A call whose audio hasn't connected by now never will (Connect gives up at 90 s, as "customer never arrived"):
// the page hangs up and says so, rather than showing "Starting your call…" for ever.
const CONNECT_WAIT_MS = 25000;
// After the face fails to start, later calls in this page don't try it by themselves for a while (Tavus refusing,
// for example out of credit, refuses every time). The customer can still press Show video.
const VIDEO_REST_MS = 10 * 60 * 1000;
// What happens in a conversation, for anything on the page that wants to follow it (the demo's "how it works" view,
// flowview/): an 'assistant' event on document, { type, ... }. The widget doesn't know or care who listens.
const tell = (type, detail = {}) => document.dispatchEvent(new CustomEvent('assistant', { detail: { type, ...detail } }));
// Markdown emphasis shown as plain text (every message is written as text, never HTML).
const plain = (words) => words.replace(/(\*\*|__)(.+?)\1/g, '$2');

// Text with its £ amounts in bold, as text nodes and <strong> elements.
function withAmounts(parent, text) {
  for (const part of amounts(text)) {
    if (part.amount) {
      const strong = document.createElement('strong');
      strong.textContent = part.text;
      parent.append(strong);
    } else parent.append(document.createTextNode(part.text));
  }
  return parent;
}

// An assistant message laid out for reading (format.js): lines, lists, the closing question, the disclaimer.
function laidOut(words) {
  const box = document.createElement('div');
  box.className = 'said';
  for (const block of layout(words)) {
    if (block.kind === 'list') {
      if (block.lead) box.append(withAmounts(Object.assign(document.createElement('p'), { className: 'lead' }), block.lead));
      const list = document.createElement(block.ordered ? 'ol' : 'ul');
      for (const item of block.items) list.append(withAmounts(document.createElement('li'), item));
      box.append(list);
    } else {
      const line = document.createElement('p');
      if (block.kind !== 'line') line.className = block.kind;
      box.append(withAmounts(line, block.text));
    }
  }
  return box;
}

// What the server needs to know about the page: which page, and on it the tab, the mortgage stage and
// application, or the card payment being disputed. Nothing here says who the customer is.
const pageFields = (c) => ({ page: c.page, view: c.view || '', stage: c.stage || '', applicationId: c.applicationId || '',
  paymentId: c.paymentId || '' });

export function setupTalk({ api, context, onEnded = () => {}, onActivity = () => {}, hasAvatar = () => false,
  onStarted = () => {}, onDisputeLink = () => {}, disputePagesUrl = '' }) {
  const $ = (id) => document.getElementById(id);
  const dock = setupDock({ context });
  $('avatar-hint').hidden = !hasAvatar();
  let live = null;          // { kind, region, participantToken, connectionToken, socket, heartbeat, session, stream }
  let videoFailedAt = 0;    // when the face last failed to start
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

  // The dispute assistant shares its form as a link (its page, with the form's secret after "#k="). Here the form
  // opens inside the app instead: the link's secret goes to the app's own dispute page, never to a new tab.
  function disputeToken(words) {
    if (!disputePagesUrl) return '';
    const at = words.indexOf(disputePagesUrl);
    if (at < 0) return '';
    const found = words.slice(at).match(/#k=([A-Za-z0-9_-]{16,128})/);
    return found ? found[1] : '';
  }

  // role: CUSTOMER (the customer) or anything else (the assistant: whichever assistant is helping, one voice to them).
  function show(role, words) {
    const li = document.createElement('li');
    const me = role === 'CUSTOMER';
    li.className = me ? 'me' : 'them';
    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = me ? 'You' : 'Assistant';
    li.append(who, me ? document.createTextNode(plain(words)) : laidOut(words));
    const token = me ? '' : disputeToken(words);
    if (token) {
      const open = document.createElement('button');
      open.type = 'button';
      open.className = 'open-form';
      open.textContent = 'Open the form here';
      open.addEventListener('click', () => onDisputeLink(token));
      li.append(open);
    }
    $('chat-log').append(li);
    tell('said', { who: me ? 'customer' : 'assistant' });
    if (!me) onActivity();          // the assistant may have just saved a goal or moved a payment
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
    $('call-video').hidden = !(kind === 'call' && hasAvatar());
    showVideo(false);
    $('talk-end').textContent = kind === 'call' ? 'End call' : 'End chat';
    dock.live(kind);               // remembers the tab it started from
    tell('starting', { kind });
  }

  // The first thing the customer says: where they are (the server words it for the page). Sent as an ordinary
  // message once the assistant is listening, so ARIA can pass them to the right assistant straight away. Pages with
  // nothing to say send nothing. Until then the input stays off, so nothing the customer types is lost.
  function sendOpener() {
    if (!live || live.kind !== 'chat' || live.opened || !live.connectionToken) return;
    live.opened = true;
    clearTimeout(live.openerTimer);
    if (live.opener) {
      participant(live.region, 'message', live.connectionToken, { ContentType: 'text/plain', ClientToken: crypto.randomUUID(),
        Content: live.opener }).catch((error) => status(error.message));
    }
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
      const started = await api('/contact/chat', pageFields(context()));
      live = { kind: 'chat', region: started.region, participantToken: started.participantToken, opener: started.opener,
        contactId: started.contactId, journey: started.journey };
      onStarted({ journey: started.journey, contactId: started.contactId, kind: 'chat' });
      tell('started', { kind: 'chat', journey: started.journey, contactId: started.contactId });
      const joined = await participant(started.region, 'connection', started.participantToken,
        { Type: ['WEBSOCKET', 'CONNECTION_CREDENTIALS'] });     // no ConnectParticipant: that's for streaming and agents
      live.connectionToken = joined.ConnectionCredentials.ConnectionToken;
      const socket = new WebSocket(joined.Websocket.Url);
      live.socket = socket;
      socket.addEventListener('open', async () => {
        socket.send(JSON.stringify({ topic: 'aws/subscribe', content: { topics: ['aws/chat'] } }));
        live.heartbeat = setInterval(() => socket.send(JSON.stringify({ topic: 'aws/heartbeat' })), HEARTBEAT_MS);
        status('Connecting you to our assistant…');
        tell('connected', { kind: 'chat' });
        typing(false);
        // Anything said before the websocket was listening (your first message, the greeting): the latest 100,
        // oldest first. (FORWARD needs a StartPosition, and Connect refused it with a 400.)
        const transcript = await participant(live.region, 'transcript', live.connectionToken,
          { MaxResults: 100, ScanDirection: 'BACKWARD', SortOrder: 'ASCENDING' }).catch(() => ({}));
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

  // The face area: shown while the face is starting or live. note: a line over the video ('' for none).
  function showVideo(on, note = '') {
    $('avatar').hidden = !on;
    $('avatar-note').textContent = note;
    $('avatar-note').hidden = !note;
    $('call-video').textContent = on ? 'Hide video' : 'Show video';
    $('call-video').setAttribute('aria-pressed', String(!on));
  }

  // Starts the face for the live call. Any failure leaves the call as it is, voice only.
  async function videoOn() {
    if (!live || live.kind !== 'call' || live.avatar || !live.contactId || !live.connected) return;
    const current = live;
    const run = {};                   // this attempt: a later Hide (or a newer attempt) makes it stale
    current.avatar = 'starting';
    current.avatarRun = run;
    showVideo(true, 'Starting video…');
    tell('video', { state: 'starting' });
    try {
      const handle = await startAvatar({
        api, contactId: current.contactId, context: current.audioContext, callAudio: $('talk-audio'),
        video: $('avatar-video'), audio: $('avatar-audio'),
        onStage: (words) => { if (live === current && current.avatarRun === run) showVideo(true, words); },
        onGone: (why) => {
          if (live !== current || current.avatarRun !== run) return;
          current.avatar = null;
          showVideo(false);
          tell('video', { state: 'off' });
          status(`${why} Your call carries on.`);
        },
      });
      if (live !== current || current.avatarRun !== run) { handle.stop(); return; }     // ended or hidden meanwhile
      current.avatar = handle;
      showVideo(true);
      tell('video', { state: 'on' });
    } catch (error) {
      if (live !== current || current.avatarRun !== run) return;
      current.avatar = null;
      videoFailedAt = Date.now();
      showVideo(false);
      tell('video', { state: 'failed' });
      if (!current.withPerson) status('The video couldn\'t start. You\'re still on the call, by voice.');
    }
  }

  function videoOff() {
    if (!live) return;
    if (live.avatar && live.avatar !== 'starting') live.avatar.stop();
    live.avatar = null;
    live.avatarRun = null;
    showVideo(false);
  }

  async function startCall() {
    begin('call'); status('Starting your call…');
    // Each step's time since Call was pressed, in the browser console: shows where a slow or failed call stalls.
    const began = performance.now();
    const mark = (step) => console.info(`[call] ${step} +${Math.round(performance.now() - began)} ms`);
    // Browsers only let a page start audio from a tap or click: the face's audio context is made now.
    const audioContext = hasAvatar() ? new AudioContext({ sampleRate: 24000 }) : null;
    try {
      // Ask for the microphone first, so a refusal costs nothing. Echo cancellation keeps the assistant's voice from
      // the speakers out of the microphone: otherwise Connect hears it as the customer interrupting.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      mark('microphone ready');
      tell('microphone');
      const started = await api('/contact/call', pageFields(context()));
      mark('contact started');
      const chime = await import('/assets/vendor/chime.js');
      mark('call library loaded');
      const logger = new chime.ConsoleLogger('call', chime.LogLevel.WARN);
      const devices = new chime.DefaultDeviceController(logger);
      const config = new chime.MeetingSessionConfiguration({ Meeting: started.meeting }, { Attendee: started.attendee });
      const session = new chime.DefaultMeetingSession(config, logger, devices);
      const current = { kind: 'call', region: started.region, participantToken: started.participantToken, session, stream,
        devices, contactId: started.contactId, audioContext, journey: started.journey, connected: false };
      live = current;
      onStarted({ journey: started.journey, contactId: started.contactId, kind: 'call' });
      tell('started', { kind: 'call', journey: started.journey, contactId: started.contactId });
      const av = session.audioVideo;
      if (started.transcript) live.transcript = setInterval(() => readTranscript(started.contactId), TRANSCRIPT_EVERY_MS);
      av.addObserver({
        audioVideoDidStart: () => {
          if (live !== current) return;
          mark('audio connected');
          tell('connected', { kind: 'call' });
          current.connected = true;
          clearTimeout(current.connecting);
          $('call-video').hidden = !(audioContext && !current.withPerson);       // Show/Hide video, once there's a call
          status(`Connected. Speak when you're ready${started.transcript ? '; what\'s said appears below' : ''}.`
            + ' Headphones give the clearest call.');
          // The face starts once the call is connected, so it never competes with the call for the network, and a
          // call that doesn't connect never opens (and pays for) a face.
          if (audioContext && Date.now() - videoFailedAt > VIDEO_REST_MS) videoOn();
        },
        audioVideoDidStop: (why) => {
          if (live !== current) return;
          const code = why && why.statusCode ? why.statusCode() : '';
          mark(`stopped (${current.connected ? 'after connecting' : 'before connecting'})`);
          if (code !== '') console.warn('call stopped, Chime status', code);
          finish(current.connected ? 'The call has ended.' : 'The call couldn\'t connect. A VPN or work network can block calls: try another network, or use Chat.');
        },
      });
      await av.startAudioInput(stream);
      await av.bindAudioElement($('talk-audio'));
      av.start();
      mark('connecting');
      tell('connecting');
      status('Connecting your call…');
      $('call-video').hidden = true;                // nothing to show or hide until the call connects
      current.connecting = setTimeout(() => {
        if (live === current && !current.connected) mark('gave up: audio never connected');
        if (live === current && !current.connected) hangUp('The call couldn\'t connect. A VPN or work network can block calls: try another network, or use Chat.');
      }, CONNECT_WAIT_MS);
    } catch (error) {
      const words = error && error.name === 'NotAllowedError'
        ? 'To call, allow this page to use your microphone.' : (error.message || 'The call could not start.');
      if (audioContext && !live) audioContext.close().catch(() => {});
      finish(words);
    }
  }

  // New lines of the call's transcript, each shown once, oldest first.
  async function readTranscript(contactId) {
    if (!live || live.kind !== 'call' || live.reading) return;
    live.reading = true;
    try {
      const said = await api('/contact/transcript', { contactId });
      if (said.unavailable) clearInterval(live.transcript);      // this deployment can't read transcripts
      if (said.withPerson && !live.withPerson) {                 // an adviser joined: they're heard as themselves
        live.withPerson = true;
        videoOff();
        $('call-video').hidden = true;
        status('A colleague has joined the call.');
        tell('colleague');
      }
      for (const line of said.lines || []) {
        const key = `${line.at}|${line.who}|${line.text}`;
        if (seen.has(key)) continue;
        seen.add(key);
        show(line.who === 'customer' ? 'CUSTOMER' : 'ASSISTANT', line.text);
      }
    } catch { /* try again on the next tick */ }
    if (live) live.reading = false;
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
  async function hangUp(words = '') {
    if (!live) return;
    const current = live;
    try {
      const token = current.connectionToken || (await participant(current.region, 'connection',
        current.participantToken, { Type: ['CONNECTION_CREDENTIALS'] })).ConnectionCredentials.ConnectionToken;
      await participant(current.region, 'disconnect', token, { ClientToken: crypto.randomUUID() });
    } catch { /* the contact may already have ended */ }
    finish(typeof words === 'string' && words ? words : current.kind === 'call' ? 'You ended the call.' : 'You ended the chat.');
  }

  function finish(words) {
    const current = live;
    live = null;
    if (current) {
      clearInterval(current.heartbeat);
      clearInterval(current.transcript);
      clearTimeout(current.connecting);
      clearTimeout(current.openerTimer);
      if (current.avatar && current.avatar !== 'starting') current.avatar.stop();
      current.avatar = null;
      if (current.audioContext) current.audioContext.close().catch(() => {});
      try { current.socket && current.socket.close(); } catch { /* already closed */ }
      try { current.session && current.session.audioVideo.stop(); } catch { /* already stopped */ }
      // Release the call library's audio devices too, so the next call in this tab starts clean (each call made a
      // new device controller and none was ever released).
      try { current.devices && current.devices.destroy().catch(() => {}); } catch { /* already released */ }
      (current.stream ? current.stream.getTracks() : []).forEach((track) => track.stop());
    }
    $('talk-foot').hidden = true;
    $('talk-start').hidden = false;
    showVideo(false);
    $('talk-audio').muted = false;
    // A finished conversation leaves the page: only a one-line note of how it ended stays.
    $('chat-log').replaceChildren();
    seen.clear();
    $('chat-input').value = '';
    dock.live('');
    status(words);
    tell('ended', { words });       // also when it never got going (microphone refused, contact not started)
    if (current) onEnded();       // the assistant may have changed categories or goals
  }

  $('talk-chat').addEventListener('click', startChat);
  $('talk-call').addEventListener('click', startCall);
  $('chat-form').addEventListener('submit', sendChat);
  $('call-mute').addEventListener('click', toggleMute);
  $('call-video').addEventListener('click', () => { if (live && live.avatar) videoOff(); else videoOn(); });
  $('talk-end').addEventListener('click', hangUp);
  // Closing ends any conversation; minimising (in dock.js) keeps it going behind the bottom tag.
  $('talk-close').addEventListener('click', () => { if (live) hangUp(); dock.hide(); });
  window.addEventListener('pagehide', () => { if (live) hangUp(); });
  return { contextChanged: dock.refresh, open: dock.open, note: status, end: () => { if (live) hangUp(); dock.hide(); } };
}
