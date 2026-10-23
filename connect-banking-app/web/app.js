// Internet banking app (demo): one page with its own router, so the assistant (chat, call and the face) stays
// connected while the customer moves between pages. Each page module fills in its template and says what the
// assistant should know about it (its context). Every value is written as text, never as HTML.
import { $, api, forgetLink, readLink, text, whenExpired } from './lib.js';
import { hideHomeScreen, setupHomeScreen } from './homescreen.js';
import { setupTalk } from './widget/talk.js';

// Address -> page module. The mortgage stages keep the mortgage page's own paths (its assistant navigates by them).
// /cards/dispute is the Cards page on its "Your disputes" tab (the dispute form opens there).
const ROUTES = { '/': 'home', '/accounts': 'accounts', '/accounts/current': 'accounts', '/accounts/savings': 'accounts', '/cards': 'cards', '/cards/dispute': 'cards',
  '/money-hub': 'money-hub', '/mortgages': 'mortgages', '/help': 'help' };
const TITLES = { home: 'Home', accounts: 'Accounts', cards: 'Cards', 'money-hub': 'Money Hub',
  mortgages: 'Mortgages', apply: 'Mortgage application', help: 'Help' };
const NAV = { home: 'home', accounts: 'accounts', cards: 'cards', 'money-hub': 'money_hub',
  mortgages: 'mortgages', apply: 'mortgages', help: 'help' };
const DISPUTE_WATCH_MS = 4000;     // how often, during a conversation, the app looks for the dispute form being sent
const PAGE_SETTLE_MS = 1500;       // a page (or Money Hub tab) the customer stays on this long is told to the assistant
const routeOf = (path) => (path.startsWith('/apply/') ? 'apply' : ROUTES[path] || 'home');

// Shared between pages and the assistant while the app is open.
export const shared = {
  me: null,                // { firstName, talk, avatar, verified } from /app/home
  liveContact: null,       // the conversation going on now: { journey, contactId, kind }
  pendingDispute: '',      // a dispute form link the assistant posted in a chat, waiting for the Cards page
  pendingDisputeSession: '', // a dispute form the app opened itself, waiting for the Cards page
  disputePayment: null,    // the card payment the customer chose to dispute
};

let current = null;        // { name, handle }
let talk = null;
let rendering = Promise.resolve();

function navigate(path, { replace = false } = {}) {
  if (path !== location.pathname) history[replace ? 'replaceState' : 'pushState']({}, '', path);
  rendering = rendering.then(() => render()).catch(() => {});
  return rendering;
}

async function render() {
  const name = routeOf(location.pathname);
  if (current?.handle?.unmount) current.handle.unmount();
  const main = $('page');
  main.replaceChildren($('message'));
  text('message', '');
  const template = $(`t-${name}`);
  main.append(template.content.cloneNode(true));
  for (const link of document.querySelectorAll('[data-nav]')) {
    link.toggleAttribute('aria-current', link.dataset.nav === NAV[name]);
    if (link.dataset.nav === NAV[name]) link.setAttribute('aria-current', 'page');
  }
  document.title = `${TITLES[name]} — Nationwide internet banking (demo)`;
  const page = await import(`./pages/${name}.js`);
  current = { name, handle: null };
  current.handle = await page.mount({ main, navigate, shared, talk: () => talk, message: (words) => text('message', words) });
  talk?.contextChanged();
  pageMoved();
  window.scrollTo({ top: 0 });
  main.focus({ preventScroll: true });
}

// During any conversation: when the dispute assistant sends its form (texted on a call, posted in a chat), open it
// in the app, joined to this conversation, on the Cards page's "Your disputes" tab. Once per conversation.
let watch = null;              // { contactId, timer, opened }
function watchDisputes(contact) {
  stopWatching();
  watch = { contactId: contact.contactId, timer: 0, opened: false };
  const look = async () => {
    const current = watch;
    if (!current || current.opened) return;
    try {
      const live = await api('/disputes/live', { contactId: current.contactId });
      if (live.formSent && live.dispute && watch === current && !current.opened) {
        current.opened = true;
        const { sessionId } = await api('/disputes/open', { contactId: current.contactId, disputeId: live.dispute.disputeId });
        showDisputeForm({ sessionId });
        talk?.note('Your dispute is open on the Cards page, under Your disputes. Watch it fill in as you talk.');
        return;
      }
    } catch { /* disputes aren't set up, or not yet: look again */ }
    if (watch === current) current.timer = setTimeout(look, DISPUTE_WATCH_MS);
  };
  watch.timer = setTimeout(look, DISPUTE_WATCH_MS);
}
function stopWatching() { if (watch) clearTimeout(watch.timer); watch = null; }

// Shows the dispute form: on the Cards page's "Your disputes" tab, going there if need be.
function showDisputeForm({ sessionId = '', token = '' }) {
  document.dispatchEvent(new CustomEvent('assistant', { detail: { type: 'dispute-form' } }));    // as talk.js tells
  if (routeOf(location.pathname) === 'cards' && current?.handle) {
    if (token) shared.pendingDispute = token;        // read by openLink
    if (sessionId) current.handle.openSession?.(sessionId); else current.handle.openLink?.();
    return;
  }
  if (sessionId) shared.pendingDisputeSession = sessionId;
  if (token) shared.pendingDispute = token;
  navigate('/cards/dispute');
}

// During a conversation, moving to another page (or Money Hub tab) is told to the assistant: the contact's page
// attributes and ARIA's known contact reason, so her next turn knows where they are and can bring in that page's
// specialist (the server's page_moved). Only a real change, once it has settled; never the page it started on.
const pageKey = (c) => [c.page, c.view || '', c.stage || '', c.applicationId || '', c.paymentId || ''].join('|');
let toldPage = { key: '', timer: 0 };
function pageMoved() {
  const contact = shared.liveContact;
  if (!contact) return;
  clearTimeout(toldPage.timer);
  toldPage.timer = setTimeout(async () => {
    const now = pageContext();
    if (shared.liveContact !== contact || pageKey(now) === toldPage.key) return;
    toldPage.key = pageKey(now);
    document.dispatchEvent(new CustomEvent('assistant', { detail: { type: 'page', label: now.label } }));   // as talk.js tells
    try {
      await api('/contact/page', { contactId: contact.contactId, page: now.page, view: now.view || '', stage: now.stage || '',
        applicationId: now.applicationId || '', paymentId: now.paymentId || '' });
    } catch { /* the conversation carries on; the next move tries again */ }
  }, PAGE_SETTLE_MS);
}
document.addEventListener('click', () => setTimeout(pageMoved));      // a tab or a payment chosen on the same page

// The assistant asks this whenever it needs to know where the customer is.
function pageContext() {
  const own = current?.handle?.context?.();
  return own || { page: 'home', label: TITLES[current?.name] || 'Home' };
}

function forget(words = 'This device has forgotten your internet banking. Open it from your link to see it again.') {
  forgetLink();
  hideHomeScreen();
  for (const id of ['forget', 'talk-launcher', 'talk-panel']) $(id).hidden = true;
  text('user-name', '');
  $('page').replaceChildren($('message'));
  text('message', words);
}

document.addEventListener('click', (event) => {
  const link = event.target.closest('a[data-link]');
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
  event.preventDefault();
  navigate(new URL(link.href).pathname);
});
window.addEventListener('popstate', () => { rendering = rendering.then(() => render()).catch(() => {}); });
$('forget').addEventListener('click', () => { if (talk) talk.end(); forget(); });
whenExpired(() => forget('That link no longer works. Open your internet banking from a new link.'));

async function start() {
  if (!readLink()) {
    $('page').replaceChildren($('message'));
    text('message', 'Open your internet banking from the link we gave you.');
    return;
  }
  $('forget').hidden = false;
  setupHomeScreen();
  try {
    shared.me = await api('/app/home');
  } catch (error) {
    text('message', error.message);
    return;
  }
  text('user-name', shared.me.firstName ? `Hello, ${shared.me.firstName}` : '');
  // A link that isn't signed in (not Level 2) still shows everything, but the assistant has to check who the
  // customer is: say so, rather than let it come as a surprise in the conversation.
  $('signed-out').hidden = Boolean(shared.me.verified);
  // The demo's "how it works" view, only when the server's setting has it on (it follows the assistant's events).
  if (shared.me.flowView) import('/assets/flowview/flowview.js').then((view) => view.setupFlowView({ api })).catch(() => {});
  if (shared.me.talk) {
    talk = setupTalk({
      api,
      context: pageContext,
      hasAvatar: () => Boolean(shared.me.avatar),
      onStarted(info) {
        shared.liveContact = info;
        toldPage = { key: pageKey(pageContext()), timer: 0 };        // where it started: nothing to tell yet
        watchDisputes(info);
        // A mortgage conversation fills the form: be on it (starting from the Mortgages page goes straight there).
        if (info.journey === 'mortgage' && routeOf(location.pathname) !== 'apply') {
          navigate(pageContext().formPath || '/apply/about-you');
        } else current?.handle?.contactStarted?.(info);
      },
      onActivity: () => current?.handle?.refresh?.(),
      onEnded: () => {
        const ended = shared.liveContact;
        shared.liveContact = null;
        stopWatching();
        current?.handle?.contactEnded?.(ended);
        current?.handle?.refresh?.();
      },
      onDisputeLink(token) {
        if (watch) watch.opened = true;          // this conversation's form, opened from the chat's link
        shared.pendingDispute = token;
        showDisputeForm({ token });
      },
      disputePagesUrl: shared.me.disputePagesUrl || '',
    });
  }
  await navigate(location.pathname, { replace: true });
}

start();
