// The customer page. It shows a code until a contact attaches to it, then one of two things:
//   - a dispute being filled in elsewhere, which it shows and keeps up to date (a view), or
//   - on the Live Sync route, a form: the agent on the call fills it in, the customer can type in
//     it too, and the page saves it. Once an adviser has the dispute the form becomes a view.
// The page's secret (sessionId) never leaves this tab.
import { api, $, show, text, drawRows } from './common.js';
import { createSaver } from './formfill.js';
import { startLiveSync } from './livesync.js';

const POLL_MS = 2000;
const KEY = 'disputeScreen';
const FIELDS = ['transactionId', 'disputeType', 'reason', 'cardInPossession', 'contactedMerchant', 'narrative'];
let sessionId = sessionStorage.getItem(KEY);
let last = null;
let liveSync = null; let liveSyncStarted = false;
let lastForm = null;       // the last form status, so a change can redraw the choices at once

const formValues = () => Object.fromEntries(FIELDS.map((name) => [name, $(name).value.trim()]));
const saver = createSaver({ send: async (fields) => {
  const status = await api('/screen/save', { sessionId, fields });
  text('edit-saved', 'Saved');
  return status;
} });

function options(select, entries, placeholder) {
  const wanted = JSON.stringify(entries);
  if (select.dataset.options === wanted) return false;
  const current = select.value;
  select.replaceChildren(new Option(placeholder, ''), ...entries.map(([value, words]) => new Option(words, value)));
  select.dataset.options = wanted;
  select.value = entries.some(([value]) => value === current) ? current : '';
  return true;
}

// Fills the dropdowns' choices. Returns true if any list changed, so the agent can be told.
function drawChoices(status) {
  const type = $('disputeType').value;
  const changed = [
    options($('transactionId'), status.transactions.map((t) =>
      [t.transaction_id, `${t.merchant}, £${t.amount}, ${t.date}, ${t.card_type} card ending ${t.card_last_four}`]), 'Choose the payment…'),
    options($('disputeType'), [['unauthorised', 'No, I did not make it'], ['merchant', 'Yes, but something went wrong']], 'Choose…'),
    options($('reason'), Object.entries(status.choices.reason[type] ?? {}), type ? 'Choose…' : 'Answer the question above first'),
  ].some(Boolean);
  show('cardInPossession', type === 'unauthorised'); show('cardInPossession-label', type === 'unauthorised');
  show('contactedMerchant', type === 'merchant'); show('contactedMerchant-label', type === 'merchant');
  return changed;
}

// Puts the saved dispute's values into the form, leaving alone whatever the customer is typing in.
function drawSaved(d) {
  if (!d || saver.pending()) return;
  for (const name of FIELDS) {
    const el = $(name);
    if (document.activeElement !== el && el.value !== (d[name] ?? '')) el.value = d[name] ?? '';
  }
}

function drawForm(status) {
  lastForm = status;
  show('waiting', false);
  const editable = status.editable;
  show('edit', editable); show('form', !editable);
  if (!editable) { drawDispute(status); return; }
  drawSaved(status.dispute);
  let changed = drawChoices(status);
  drawSaved(status.dispute);                       // the reason list may only now hold the saved reason
  changed = drawChoices(status) || changed;
  const missing = status.dispute?.missing ?? [];
  show('edit-missing', missing.length > 0);
  text('edit-missing', `Still to fill in: ${missing.join(', ')}.`);
  if (!liveSyncStarted) {
    liveSyncStarted = true;
    fetch('/api/config').then((r) => r.json()).then((config) => startLiveSync({ config, contactId: status.contactId, fill: fillFromAgent }))
      .then((session) => { liveSync = session; text('edit-sync', session ? 'Connected to your call.' : ''); })
      .catch(() => text('edit-sync', 'You can fill this in yourself; we could not connect it to your call.'));
  } else if (changed) liveSync?.sendContext().catch(() => {});
}

// The agent filled a field: put the value in, and treat it exactly like the customer changing it.
function fillFromAgent(name, value) {
  const el = $(name);
  el.value = value;
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

async function newCode() {
  show('new-code', false);
  text('code', '······'); text('code-note', 'Getting a code…');
  const screen = await api('/screen');
  sessionId = screen.sessionId;
  sessionStorage.setItem(KEY, sessionId);
}

function drawWaiting(status) {
  show('waiting', true); show('form', false); show('edit', false);
  text('code', `${status.code.slice(0, 3)} ${status.code.slice(3)}`);
  const minutes = Math.max(1, Math.ceil(status.expiresInSeconds / 60));
  text('code-note', `This code works for about ${minutes} more minute${minutes === 1 ? '' : 's'}.`);
}

function drawDispute(status) {
  const d = status.dispute;
  show('waiting', false); show('edit', false); show('form', true);
  text('reference', d.disputeId); text('status', d.statusWords);
  $('status').className = d.status === 'submitted' ? 'status submitted' : 'status';
  drawRows($('rows'), d, last);
  const submitted = d.status === 'submitted';
  show('intro', !submitted);
  show('missing', d.missing.length > 0 && !submitted);
  text('missing', `Still to fill in: ${d.missing.join(', ')}.`);
  show('confirm-box', status.canConfirm);
  show('confirmed', d.customerConfirmed && !submitted);
  show('submitted', submitted);
  text('submitted', `Your dispute has been submitted. Your reference is ${d.disputeId}.`);
  last = d;
}

function draw(status) {
  if (status.state === 'form') drawForm(status);
  else if (status.state === 'attached') drawDispute(status);
  else if (status.state === 'waiting') drawWaiting(status);
}

async function refresh() {
  try {
    if (!sessionId) await newCode();
    const status = await api('/screen/status', { sessionId });
    if (status.state === 'expired') { // an attached page stays as it was; a waiting page offers a new code
      sessionId = null; sessionStorage.removeItem(KEY);
      if (!last && !liveSyncStarted) { text('code', '······'); text('code-note', 'That code has expired.'); show('new-code', true); }
      return;
    }
    draw(status);
  } catch { text('code-note', 'We could not reach the service. Trying again…'); }
  setTimeout(refresh, POLL_MS);
}

$('dispute-form').addEventListener('change', () => {
  // "Did you make this payment?" decides which reasons are offered: show them, and tell the agent.
  if (lastForm && drawChoices(lastForm)) liveSync?.sendContext().catch(() => {});
  text('edit-saved', 'Saving…'); saver.changed(formValues);
});
$('dispute-form').addEventListener('submit', (event) => event.preventDefault());
$('new-code').addEventListener('click', () => { refresh(); });
$('confirm').addEventListener('click', async (event) => {
  if (!event.isTrusted) return; // only the customer's own click counts
  $('confirm').disabled = true; text('error', '');
  try { draw(await api('/screen/confirm', { sessionId })); } catch (error) { text('error', error.message); }
  $('confirm').disabled = false;
});

refresh();
