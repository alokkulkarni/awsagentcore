// The mortgage application form inside the banking app. The form, its rules and its Live Sync wiring are the
// mortgage page's own (connect-livesync-mortgage web/app/app.js and web/src, copied into ../mortgage unchanged);
// what differs is who starts the conversation: the app's assistant (chat or call, with the face on calls)
// instead of Touchpoint's own widget.
//
// When a conversation starts on this form, Connect's "conversation bot flow" passes it to the mortgage assistant
// (Point B, entry=web_widget). The page then binds Touchpoint to that same contact in its headless mode
// ("external": it draws nothing and opens no call), and the mortgage assistant's Live Sync fills, navigates and
// highlights here exactly as on the mortgage page. Help by phone (a code the caller quotes) binds the same way.
// A conversation that began elsewhere in the app and comes here binds too: ARIA brings the mortgage assistant in,
// and the page sends it the form's fields again when it takes over (watchAssistant).
import { $, api, text } from '../lib.js';
import { STAGES } from '../mortgage/context.js';
import { startLiveSync } from '../mortgage/touchpoint.js';
import { startScreenHelp } from '../mortgage/screenHelp.js';
import { reviewApplication, dipOutcome } from '../mortgage/review.js';
import { RESEND_AFTER_MS, resendContext } from '../mortgage/contextResend.js';
import { createUi } from '../mortgage/ui.js';
import { applicationId, saveForm, saveStage, savedForm, startAgain } from '../mortgage/state.js';

const TOUCHPOINT = '/vendor/touchpoint/index.js';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Live Sync outlives a page change (the customer can look at their accounts mid-call and come back): the session
// stays here, and reaches whichever form is showing through `form`.
let bound = null;            // { contactId, session, stopResend, watch }
let form = null;             // the mounted form: { ui, show, state, current }
// Re-send times for the form's context: the mortgage page's own, then on while ARIA hands over.
export const AFTER_ARIA_MS = [...RESEND_AFTER_MS, 45000, 60000, 90000, 120000];
const WATCH_MS = 4000;       // how often a bound form asks which assistant has the conversation
let touchpoint = null;       // { create, analyzePageForms }, loaded once
let config = null;           // the mortgage service's settings and Live Sync keys

// Handlers and hooks are created once per Live Sync session; they act on whichever form is mounted now.
const uiProxy = new Proxy({}, { get: (_, name) => (...args) => form?.ui?.[name]?.(...args) });

async function loadTouchpoint() {
  if (!touchpoint) touchpoint = await import(TOUCHPOINT);
  return touchpoint;
}

// The current stage's context, sent to the mortgage assistant.
async function sendContext() {
  if (bound && form) await bound.session.enterStage(form.current().scope, form.state());
}

// Binds Live Sync to a conversation this page (through the app's assistant) or a help-code call started.
async function bindLiveSync(contactId, { session } = {}) {
  if (!UUID.test(contactId || '')) return;
  if (bound?.contactId === contactId) { await sendContext().catch(() => {}); return; }
  if (!config?.configured) { form?.ui.setStatus('The assistant can talk with you, but it can\'t see this form yet (Live Sync isn\'t set up).'); return; }
  try {
    const live = session || await startLiveSync({ ...await loadTouchpoint(), ui: uiProxy, input: 'external', contactId,
      onNavigate: (scope) => form?.show(STAGES.find((s) => s.scope === scope), true),
      config: { ...config, languageCode: 'en-GB', launchIcon: false } });
    bound = { contactId, session: live, stopResend: () => {} };
    await sendContext();
    // The first context can arrive before the assistant's conversation exists: send it again a few times. In this
    // app ARIA greets first and then hands over, so the mortgage assistant can start well after the contact: keep
    // re-sending for up to two minutes (the same context each time, so harmless).
    bound.stopResend = resendContext({ send: () => sendContext(), delays: AFTER_ARIA_MS });
    watchAssistant(contactId);
    form?.ui.setStatus('The assistant can see this form and fill it in with you. Anything it fills is marked.');
  } catch {
    form?.ui.setStatus('The assistant can talk with you, but it couldn\'t connect to this form. You can fill it in yourself.');
  }
}

// ARIA brings the mortgage assistant in whenever she decides to (a conversation can begin anywhere in the app and come
// here minutes later), and the fields sent before it joined went to her. Each time it takes over, send them again
// on the mortgage page's own schedule (its conversation starts a moment after the hand-over).
function watchAssistant(contactId) {
  let was = '';
  const look = async () => {
    if (bound?.contactId !== contactId) return;
    try {
      const { assistant } = await api('/contact/assistant', { contactId });
      if (assistant === 'mortgage' && was !== 'mortgage' && bound?.contactId === contactId) {
        bound.stopResend();
        await sendContext().catch(() => {});
        bound.stopResend = resendContext({ send: () => sendContext(), delays: RESEND_AFTER_MS });
      }
      was = assistant || '';
    } catch { /* not answered this time: the next look, or the conversation's end, settles it */ }
    if (bound?.contactId === contactId) bound.watch = setTimeout(look, WATCH_MS);
  };
  bound.watch = setTimeout(look, WATCH_MS);
}

function unbind() {
  bound?.stopResend();
  clearTimeout(bound?.watch);
  bound = null;
  form?.ui.setStatus('');
}

export async function mount({ shared, talk }) {
  config = await api('/mortgage/config').catch(() => ({ configured: false, products: [] }));
  const ui = createUi({ products: config.products || [] });
  ui.renderProducts();
  const appId = applicationId();
  text('app-id', appId);
  if (config.helpPhoneNumber) text('help-number', config.helpPhoneNumber.replace(/^(\d{4})(\d{3})(\d+)$/, '$1 $2 $3'));

  // The answers so far, restored, and saved on every change.
  const restore = () => {
    for (const [k, v] of Object.entries(savedForm())) {
      for (const el of document.getElementsByName(k)) { if (el.type === 'radio') el.checked = el.value === v; else el.value = v; }
    }
  };
  const formState = () => {
    const values = savedForm();
    for (const el of document.querySelectorAll('form.stage [name]')) {
      if (el.type === 'radio') { if (el.checked) values[el.name] = el.value; } else if (el.type !== 'file') values[el.name] = el.value;
    }
    saveForm(values);
    return values;
  };
  restore();

  let current = STAGES.find((s) => s.path === location.pathname) ?? STAGES[0];
  const state = () => ({ ...formState(), products: ui.visibleProducts() });
  const nav = $('stages');
  STAGES.forEach((s, i) => {
    const li = document.createElement('li'); const a = document.createElement('a');
    a.href = s.path; a.textContent = `${i + 1} ${s.title}`; a.dataset.scope = s.scope;
    li.append(a); nav.append(li);
  });

  // The declaration can be ticked only when nothing is missing, and only by the customer's own click.
  let declaredByClick = false;
  function refreshReview() {
    const review = reviewApplication(formState(), ui.uploadedDocs());
    ui.renderReview(review);
    const declare = $('declare');
    declare.disabled = !review.complete;
    if (!review.complete) { declare.checked = false; declaredByClick = false; }
    $('submit').disabled = !(review.complete && declaredByClick && declare.checked);
  }

  function show(stage, push) {
    if (!stage) return;
    current = stage;
    saveStage(stage.scope);
    if (push && location.pathname !== stage.path) history.pushState({}, '', stage.path);
    for (const f of document.querySelectorAll('form.stage')) f.hidden = f.dataset.stage !== stage.scope;
    for (const a of nav.querySelectorAll('a')) a.toggleAttribute('aria-current', a.dataset.scope === stage.scope);
    $('back').disabled = STAGES.indexOf(stage) === 0;
    $('next').hidden = STAGES.indexOf(stage) === STAGES.length - 1;
    if (stage.scope === 'review_submit') refreshReview();
    sendContext().catch(() => {});
    form?.contextChanged();
  }

  form = { ui, show, state, current: () => current, contextChanged: () => talk()?.contextChanged() };
  nav.addEventListener('click', (e) => {
    const a = e.target.closest('a'); if (!a) return;
    e.preventDefault(); e.stopPropagation(); show(STAGES.find((s) => s.scope === a.dataset.scope), true);
  });
  const step = (d) => show(STAGES[Math.min(STAGES.length - 1, Math.max(0, STAGES.indexOf(current) + d))], true);
  $('back').addEventListener('click', () => step(-1));
  $('next').addEventListener('click', () => step(1));
  $('restart').addEventListener('click', () => { startAgain(); location.assign('/apply/about-you'); });
  document.querySelectorAll('form.stage').forEach((f) => {
    f.addEventListener('change', () => formState());
    f.addEventListener('submit', (e) => e.preventDefault());
  });
  $('declare').addEventListener('change', (e) => {
    declaredByClick = e.isTrusted && e.target.checked;
    $('submit').disabled = !declaredByClick;
  });
  $('submit').addEventListener('click', async () => {
    const v = formState();
    const button = $('submit'); button.disabled = true;
    const r = await api('/mortgage/submit', { applicationId: appId, productId: v.productId, dipDecision: dipOutcome(v.dipDecision),
      documents: ui.uploadedDocs(), declared: declaredByClick }).catch((err) => ({ ok: false, errors: [err.message] }));
    ui.showSubmitResult(r);
    if (!r.ok) button.disabled = !declaredByClick;
  });

  // Help by phone: a code the caller quotes binds this form to their call (the mortgage page's own route).
  $('help-start').hidden = !config.helpCode;
  $('help-start').addEventListener('click', async () => {
    $('help-start').hidden = true;
    try {
      const tp = config.configured ? await loadTouchpoint() : {};
      const session = await startScreenHelp({
        api: { createHelpCode: (p) => api('/mortgage/help-code', p), helpCodeStatus: (id) => api('/mortgage/help-code/status', { helpSessionId: id }) },
        ...tp, ui: uiProxy, applicationId: appId, stage: current.scope, state: state(),
        onNavigate: (scope) => form?.show(STAGES.find((s) => s.scope === scope), true),
        config: { ...config, languageCode: 'en-GB', launchIcon: false } });
      ui.showHelpClaimed(true);
      bound = { contactId: 'help-code', session, stopResend: () => {} };
    } catch (err) {
      if (/Missing Live Sync|create is not a function/.test(String(err?.message))) ui.showHelpClaimed(false);
      else if (!/expired/.test(String(err?.message))) { ui.showError('Something went wrong — try again.'); $('help-start').hidden = false; }
    }
  });

  show(current, true);       // the browser's back and forward re-open this page at their stage (the app's router)

  // A conversation already going on (started here, on the Mortgages page, or anywhere else and brought here): bind to
  // it now, so whenever the mortgage assistant has it, it sees this form.
  if (shared.liveContact) bindLiveSync(shared.liveContact.contactId);

  const handle = {
    context: () => ({ page: 'mortgage', stage: current.scope, applicationId: appId, formPath: current.path,
      label: `Mortgage application · ${current.title}`, launcher: 'Help with your application',
      note: 'The assistant fills in the form with you as you talk, and you can change anything. Choosing a product is up to you.' }),
    contactStarted(info) { bindLiveSync(info.contactId); },
    contactEnded(info) { if (bound && (!info || info.contactId === bound.contactId)) unbind(); },
    unmount() { ui.stop(); form = null; },
  };
  return handle;
}
