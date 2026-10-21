// "How it works": a view for demos that follows a chat or call from the assistant and shows, in words anyone can
// follow, where the conversation has got to: the app, the secure line, the contact centre, ARIA, a specialist
// assistant, a colleague. Separate from the assistant: it only listens to the 'assistant' events the widget sends
// on document (widget/talk.js) and asks the server where the contact is (/api/contact/journey, which reads
// Connect's own record of it: bankapp/flowview.py). It never touches the widget.
// It's loaded only when the server says the view is on (the SSM setting, so it turns off without a redeploy); if
// the setting goes off during a conversation, the server stops answering and the view takes itself away.
// "Show the technology" swaps in the AWS names for a technical audience. Every value is written as text.
// Whether it's minimised and the technology shown are remembered in this browser only.

const POLL_MS = 5000;     // with the call transcript also polling, keeps well inside Connect's DescribeContact rate
const STORE_KEY = 'bankingFlowView';
const SHOWN_EVENTS = 8;

// Each step on the line: its plain name, what it does, and the technology behind it.
const NODES = [
  { key: 'you', name: 'You', does: 'in your banking app', tech: 'Banking app in the browser' },
  { key: 'line', name: 'Secure line', does: 'over the internet, no phone number', tech: { chat: 'Amazon Connect chat (Participant Service, websocket)', call: 'Amazon Connect in-app calling (Amazon Chime SDK, WebRTC)' } },
  { key: 'centre', name: 'Our contact centre', does: 'knows who you are and where you were', tech: 'Amazon Connect contact flow' },
  { key: 'aria', name: 'ARIA', does: 'our AI assistant', tech: 'Amazon Connect AI agent (Amazon Q in Connect, Amazon Lex)' },
  { key: 'specialist', name: 'A specialist', does: 'brought in when needed', tech: 'Specialist AI agents' },
  { key: 'colleague', name: 'A colleague', does: 'a person, if you need one', tech: 'Amazon Connect queue and agent workspace' },
];
const SPECIALISTS = {
  money_hub: { name: 'Money Hub specialist', does: 'reads your spending and goals', tech: 'Strands agent on Amazon Bedrock AgentCore, over A2A' },
  card_dispute: { name: 'Disputes specialist', does: 'blocks the card and fills the form', tech: 'Amazon Connect agentic self-service, form by Live Sync' },
  mortgage: { name: 'Mortgage assistant', does: 'fills your application with you', tech: 'Amazon Connect agentic self-service, form by Live Sync' },
};
// What's happening now, in a sentence, and the line it adds to "What happened".
const SAY = {
  'starting-chat': ['You asked to chat. Your banking app is opening a secure line to our contact centre.', 'You started a chat'],
  'starting-call': ['You asked to call. Your browser is checking it can use your microphone.', 'You started a call'],
  microphone: ['Microphone ready. Asking our contact centre for a call.', 'Microphone ready'],
  started: ['Our contact centre has your request, with who you are and the page you were on, so you won\'t have to explain.', 'Contact centre has your request'],
  connecting: ['Opening a secure voice line over the internet. No phone number needed.', 'Opening the voice line'],
  'connected-chat': ['The chat line is open.', 'Chat line open'],
  'connected-call': ['Your call is through. The contact centre is getting ARIA ready.', 'Call connected'],
  aria: ['ARIA, our AI assistant, is with you. She answers questions and looks things up for you.', 'ARIA joined'],
  replied: ['Our assistant has answered. It keeps what you say in mind for the whole conversation.', 'First answer'],
  money_hub: ['ARIA has brought in our Money Hub specialist, an AI that reads your spending and goals, and passes on its answers.', 'Money Hub specialist brought in'],
  card_dispute: ['You\'re now with our disputes specialist, an AI that can block your card and fills in the dispute form with you.', 'Passed to the disputes specialist'],
  mortgage: ['You\'re now with our mortgage assistant, an AI that fills in your application with you as you talk.', 'Passed to the mortgage assistant'],
  'dispute-form': ['Your dispute form is open on the Cards page. Watch it fill in as you talk.', 'Dispute form opened for you'],
  'dispute-submitted': ['Your dispute has been submitted.', 'Dispute submitted'],
  'dispute-with_adviser': ['Your dispute has gone to one of our colleagues to finish.', 'Dispute passed to a colleague'],
  'colleague-waiting': ['ARIA is passing you to a colleague, with a summary, so you don\'t have to repeat yourself.', 'Passing to a colleague'],
  'colleague-joined': ['A colleague has joined. The AI has stepped back.', 'Colleague joined'],
  'video-starting': ['Starting the video: a digital face that speaks ARIA\'s words. It\'s an AI, not a person.', 'Video starting'],
  'video-on': ['The video is on. The face moves with ARIA\'s voice.', 'Video on'],
  'video-failed': ['The video couldn\'t start. The call carries on by voice.', 'Video not available'],
  'video-off': ['The video has stopped. The call carries on by voice.', 'Video stopped'],
  returned: ['Done there, the specialist has handed you back to ARIA, with a note of where things stand.', 'Back to ARIA'],
  trouble: ['ARIA had a problem. The contact centre is handling it, so you aren\'t left stranded.', 'ARIA had a problem'],
};
const TECH = {
  'starting-chat': 'Browser asks the app\'s Lambda to start a chat contact (StartChatContact)',
  'starting-call': 'Browser asks for the microphone (getUserMedia)',
  started: 'Contact started with the page\'s context as contact attributes',
  connecting: 'Amazon Chime SDK joins the call\'s meeting (WebRTC)',
  'connected-chat': 'Websocket subscribed to the chat (Participant Service)',
  'connected-call': 'Audio connected; the contact flow runs',
  aria: 'Amazon Q in Connect session created for the contact',
  money_hub: 'ARIA calls the Money Hub agent as a tool (A2A to AgentCore). Inferred: Connect doesn\'t record this hand-over',
  card_dispute: 'Contact flow transfers to the dispute assistant (handbackRoute card_dispute)',
  mortgage: 'Contact flow transfers to the mortgage assistant (Live Sync)',
  'dispute-form': 'Form opened in the app, joined to this contact by Live Sync',
  'colleague-waiting': 'Contact queued for an agent (handbackRoute human)',
  'colleague-joined': 'Agent connected (ConnectedToAgentTimestamp)',
  returned: 'Specialist escalated with back_to_aria; the flow transferred back to ARIA (entry returned, returnSummary)',
  'video-starting': 'Tavus digital human starting, lip-synced to the call audio',
};

function remembered() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { return {}; }
}
function keep(prefs) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(prefs)); } catch { /* private window: not remembered */ }
}
function el(tag, className, words) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (words !== undefined) node.textContent = words;
  return node;
}
const clock = (ms) => new Date(ms).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const after = (ms) => (ms < 60000 ? `+${(ms / 1000).toFixed(1)}s` : `+${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`);

export function setupFlowView({ api }) {
  const prefs = { minimised: false, tech: false, ...remembered() };
  const sheet = el('link');
  sheet.rel = 'stylesheet';
  sheet.href = '/assets/flowview/flowview.css';
  document.head.append(sheet);

  // ── The view ─────────────────────────────────────────────────────────────────────────────────────
  const box = el('aside', 'flow-view');
  box.setAttribute('aria-label', 'How it works');
  box.hidden = true;
  const head = el('header', 'flow-head');
  const titles = el('div');
  const title = el('h2', '', 'How it works');
  const sub = el('p', 'flow-sub');
  titles.append(title, sub);
  const techButton = el('button', 'flow-tech', 'Show the technology');
  techButton.type = 'button';
  const minButton = el('button', 'flow-icon', '–');
  minButton.type = 'button';
  minButton.setAttribute('aria-label', 'Minimise how it works');
  const closeButton = el('button', 'flow-icon', '×');
  closeButton.type = 'button';
  closeButton.setAttribute('aria-label', 'Close how it works');
  const actions = el('div', 'flow-actions');
  actions.append(techButton, minButton, closeButton);
  head.append(titles, actions);

  const lane = el('ol', 'flow-lane');
  lane.setAttribute('aria-hidden', 'true');          // the sentence below says it all; the line is a picture of it
  const nodes = {};
  for (const node of NODES) {
    const li = el('li', 'flow-node');
    li.dataset.key = node.key;
    const dot = el('span', 'flow-dot');
    const words = el('span', 'flow-words');
    const name = el('strong', 'flow-name', node.name);
    const does = el('span', 'flow-does', node.does);
    words.append(name, does);
    li.append(dot, words);
    lane.append(li);
    nodes[node.key] = { li, name, does, base: node };
  }
  const now = el('p', 'flow-now');
  now.setAttribute('role', 'status');
  const nowTech = el('p', 'flow-now-tech');
  const historyTitle = el('h3', 'flow-history-title', 'What happened');
  const history = el('ol', 'flow-history');
  const foot = el('p', 'flow-foot', 'For demos. It follows this page\'s own conversation only.');
  box.append(head, lane, now, nowTech, historyTitle, history, foot);

  const pill = el('button', 'flow-pill', 'How it works');
  pill.type = 'button';
  pill.hidden = true;
  pill.setAttribute('aria-label', 'Show how it works');
  document.body.append(box, pill);

  // On phones and tablets the view sits just under the app's (sticky) header, wherever the page is scrolled.
  const header = document.querySelector('.app-top');
  const place = () => {
    const bottom = header ? header.getBoundingClientRect().bottom : 0;
    document.documentElement.style.setProperty('--flow-top', `${Math.max(8, Math.round(bottom) + 8)}px`);
  };
  window.addEventListener('scroll', place, { passive: true });
  window.addEventListener('resize', place);
  place();

  // ── What we know about the conversation ──────────────────────────────────────────────────────────
  let run = null;     // { kind, journey, contactId, began, seen:Set, facts, status:{}, timer, ended, failed }

  function show() {
    const open = Boolean(run) && !prefs.minimised;
    box.hidden = !open;
    pill.hidden = !run || !prefs.minimised;
    box.classList.toggle('tech', prefs.tech);
    techButton.textContent = prefs.tech ? 'Hide the technology' : 'Show the technology';
    techButton.setAttribute('aria-pressed', String(prefs.tech));
    place();
  }

  function say(key) {
    if (!run || run.seen.has(key)) return;
    run.seen.add(key);
    const [sentence, line] = SAY[key] || [key, key];
    now.textContent = sentence;
    nowTech.textContent = TECH[key] || '';
    const at = Date.now();
    const li = el('li');
    li.append(el('span', 'flow-time', `${clock(at)} ${after(at - run.began)}`), el('span', 'flow-line', line));
    if (TECH[key]) li.append(el('span', 'flow-line-tech', TECH[key]));
    history.prepend(li);
    while (history.children.length > SHOWN_EVENTS) history.lastChild.remove();
    draw();
  }

  // Each step's state from what has happened: '' (not reached), 'active', 'done' or 'skipped'.
  function draw() {
    if (!run) return;
    const s = run.seen;
    const f = run.facts;
    // Connect's word first; until it comes, an opened dispute form means the disputes specialist is helping.
    const reported = f.specialist || (s.has('dispute-form') ? 'card_dispute' : run.journey === 'money_hub' ? 'money_hub' : '');
    // Back from the disputes specialist: ARIA is helping again, and the specialist's step stays done.
    const back = Boolean(f.returned) && !f.specialist;
    const who = back ? (f.returnedFrom === 'mortgage' ? 'mortgage' : 'card_dispute') : reported === 'money_hub' ? (s.has('money_hub') ? 'money_hub' : '') : reported;
    const handedOver = !back && (who === 'card_dispute' || who === 'mortgage');
    const colleague = f.colleague || (s.has('colleague-joined') ? 'joined' : '');
    const lineUp = s.has('connected-chat') || s.has('connected-call');
    const ariaIn = Boolean(f.aria);       // Connect's word only: some journeys go straight to a specialist
    const state = {
      you: 'done',
      line: run.failed ? 'failed' : lineUp ? 'done' : 'active',
      centre: !lineUp && !s.has('started') ? '' : ariaIn || who || colleague ? 'done' : 'active',
      aria: handedOver && !ariaIn ? 'skipped' : !ariaIn ? '' : handedOver || colleague ? 'done' : 'active',
      specialist: !who ? '' : colleague || back ? 'done' : 'active',
      colleague: colleague ? 'active' : '',
    };
    if (run.ended) for (const key of Object.keys(state)) if (state[key] === 'active') state[key] = 'done';
    for (const [key, value] of Object.entries(state)) {
      const node = nodes[key];
      node.li.className = `flow-node${value ? ` is-${value}` : ''}`;
      const base = key === 'specialist' && who ? SPECIALISTS[who] : node.base;
      node.name.textContent = base.name;
      const tech = typeof base.tech === 'object' ? base.tech[run.kind] : base.tech;
      node.does.textContent = prefs.tech ? tech : base.does;
      if (key === 'aria' && value === 'skipped') node.does.textContent = prefs.tech ? 'Not needed: the flow went straight to the specialist' : 'not needed this time';
      if (key === 'colleague' && colleague === 'waiting') node.does.textContent = prefs.tech ? 'Queued for an agent' : 'finding one for you';
    }
    sub.textContent = run.ended ? `This ${run.kind} has ended` : `Following your ${run.kind}`;
  }

  // Connect's record of the contact, every few seconds while it lasts (and once more when it ends).
  async function look() {
    const current = run;
    if (!current || !current.contactId) return;
    try {
      const facts = await api('/contact/journey', { contactId: current.contactId });
      if (run !== current) return;
      current.facts = facts;
      if (facts.aria) say('aria');
      if (facts.specialist && facts.basis === 'connect') say(facts.specialist);
      if (facts.dispute?.formSent) say('dispute-form');
      if (facts.dispute && facts.dispute.status !== 'started') say(`dispute-${facts.dispute.status}`);
      if (facts.colleague) say(`colleague-${facts.colleague}`);
      if (facts.trouble) say('trouble');
      if (facts.returned) say('returned');
      draw();
    } catch (error) {
      // Turned off on the server (or this link's conversation isn't found): take the view away.
      if (/turned off/i.test(error.message)) { stop(); run = null; show(); return; }
      // Not this link's conversation (or not one Connect knows): stop asking; the widget's own events carry on.
      if (/isn't available/i.test(error.message)) return;
    }
    if (run === current && !current.ended) current.timer = setTimeout(look, POLL_MS);
  }

  function stop() { if (run) clearTimeout(run.timer); }

  function begin(kind) {
    stop();
    run = { kind, journey: '', contactId: '', began: Date.now(), seen: new Set(), facts: {}, answers: 0, timer: 0, ended: false, failed: false };
    history.replaceChildren();
    show();
    say(`starting-${kind}`);
  }

  document.addEventListener('assistant', (event) => {
    const e = event.detail || {};
    if (e.type === 'starting') { begin(e.kind); return; }
    if (!run) return;
    switch (e.type) {
      case 'microphone': say('microphone'); break;
      case 'started':
        run.journey = e.journey || '';
        run.contactId = e.contactId || '';
        say('started');
        clearTimeout(run.timer);
        run.timer = setTimeout(look, 1000);
        break;
      case 'connecting': say('connecting'); break;
      case 'connected': say(`connected-${run.kind}`); break;
      case 'said':
        if (e.who === 'assistant') {
          // Whose answer it is comes from Connect (ARIA, or a specialist the flow went straight to), not from here.
          run.answers += 1;
          say('replied');
          // Started on the Money Hub page: ARIA greets, then brings in the Money Hub specialist, whose answer is
          // the next one. Connect doesn't record that hand-over, so this is the page's best reading of it.
          const startedOnHub = run.facts.specialist ? run.facts.specialist === 'money_hub' : run.journey === 'money_hub';
          if (startedOnHub && run.answers >= 2) say('money_hub');
        }
        break;
      case 'video': say(`video-${e.state}`); break;
      case 'colleague': say('colleague-joined'); break;
      case 'dispute-form': say('dispute-form'); break;
      case 'ended': {
        const current = run;
        current.failed = !current.seen.has('connected-chat') && !current.seen.has('connected-call');
        current.ended = true;
        stop();
        now.textContent = current.failed ? (e.words || 'The conversation couldn\'t start.')
          : `${e.words || 'The conversation has ended.'} From start to finish: ${after(Date.now() - current.began).slice(1)}.`;
        nowTech.textContent = '';
        draw();
        break;
      }
      default: break;
    }
  });

  techButton.addEventListener('click', () => { prefs.tech = !prefs.tech; keep(prefs); show(); draw(); });
  minButton.addEventListener('click', () => { prefs.minimised = true; keep(prefs); show(); pill.focus({ preventScroll: true }); });
  pill.addEventListener('click', () => { prefs.minimised = false; keep(prefs); show(); });
  // Closing puts it away until the next conversation starts.
  closeButton.addEventListener('click', () => { stop(); run = null; show(); });
  return { hide: () => { stop(); run = null; show(); } };
}
