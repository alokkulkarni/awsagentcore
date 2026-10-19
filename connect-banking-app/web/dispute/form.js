// The card dispute form, shown in the Cards page's "Your disputes" tab. It opens in two ways:
//   - during a call or chat, when the dispute assistant sends its form, the app opens it itself, joined to its own
//     conversation (openSession: a form session the app's Lambda opened with the dispute service's own code);
//   - in a chat, from the link the assistant posts ("Open the form here": openLink).
// From then on it is the dispute page's own behaviour (connect-card-dispute/web/customer.js): the assistant on the
// conversation fills the form through Live Sync, the customer can type in it too, and every change is saved to the
// dispute service. Once an adviser has the dispute the form becomes a view, and the customer confirms the details
// for the adviser to submit. The form's session secret stays in this tab's memory (and its storage, for a refresh).
import { $, api, store, text } from '../lib.js';
import { createSaver } from './formfill.js';
import { startLiveSync } from './livesync.js';
import { drawRows } from './rows.js';

const POLL_MS = 2000;
const KEY = 'disputeSession';
const FIELDS = ['transactionId', 'disputeType', 'reason', 'cardInPossession', 'contactedMerchant', 'narrative'];
const show = (id, visible) => { const node = $(id); if (node) node.hidden = !visible; };

export async function mountDisputeForm({ shared, onChange = () => {} }) {
  let sessionId = store.get(sessionStorage, KEY) || null;
  let alive = true;
  let timer = 0;
  let last = null;
  let lastForm = null;
  let liveSync = null;
  let liveSyncStarted = false;
  let config = null;

  const formValues = () => Object.fromEntries(FIELDS.map((name) => [name, $(name).value.trim()]));
  const saver = createSaver({ send: async (fields) => {
    const status = await api('/dispute/screen/save', { sessionId, fields });
    text('dispute-saved', 'Saved');
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

  // Fills the dropdowns' choices. Returns true if any list changed, so the assistant can be told.
  function drawChoices(status) {
    const type = $('disputeType').value;
    const changed = [
      options($('transactionId'), status.transactions.map((t) =>
        [t.transaction_id, `${t.merchant}, £${t.amount}, ${t.date}, ${t.card_type} card ending ${t.card_last_four}`]), 'Choose the payment…'),
      options($('disputeType'), [['unauthorised', 'No, I did not make it'], ['scam', 'Yes, but I was tricked into it'],
        ['merchant', 'Yes, but something went wrong']], 'Choose…'),
      options($('reason'), Object.entries(status.choices.reason[type] ?? {}), type ? 'Choose…' : 'Answer the question above first'),
    ].some(Boolean);
    const atRisk = type === 'unauthorised' || type === 'scam';
    show('cardInPossession', atRisk); show('cardInPossession-label', atRisk);
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

  // The assistant filled a field: put the value in, and treat it exactly like the customer changing it.
  function fillFromAgent(name, value) {
    const el = $(name);
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  async function drawForm(status) {
    lastForm = status;
    show('dispute-waiting', false);
    const editable = status.editable;
    show('dispute-edit', editable); show('dispute-view', !editable);
    if (!editable) { drawDispute(status); return; }
    drawSaved(status.dispute);
    let changed = drawChoices(status);
    drawSaved(status.dispute);
    changed = drawChoices(status) || changed;
    const missing = status.dispute?.missing ?? [];
    show('dispute-missing', missing.length > 0);
    text('dispute-missing', `Still to fill in: ${missing.join(', ')}.`);
    show('dispute-submit-box', Boolean(status.canSubmit) && !saver.pending());       // the customer may submit (R11)
    if (!liveSyncStarted) {
      liveSyncStarted = true;
      config = config || await api('/dispute/config').catch(() => ({ configured: false }));
      startLiveSync({ config, contactId: status.contactId, fill: fillFromAgent })
        .then((session) => { liveSync = session; text('dispute-sync', session ? 'Connected to your conversation: the assistant can fill this in with you.' : ''); })
        .catch(() => text('dispute-sync', 'You can fill this in yourself; we could not connect it to your conversation.'));
    } else if (changed) liveSync?.sendContext().catch(() => {});
  }

  function drawDispute(status) {
    const d = status.dispute;
    show('dispute-waiting', false); show('dispute-edit', false); show('dispute-view', true);
    text('dispute-reference', d.disputeId); text('dispute-status', d.statusWords);
    drawRows($('dispute-rows'), d, last);
    const submitted = d.status === 'submitted';
    show('dispute-view-missing', d.missing.length > 0 && !submitted);
    text('dispute-view-missing', `Still to fill in: ${d.missing.join(', ')}.`);
    show('dispute-confirm-box', status.canConfirm);
    show('dispute-confirmed', d.customerConfirmed && !submitted);
    show('dispute-submitted', submitted);
    text('dispute-submitted', `Your dispute has been submitted. Your reference is ${d.disputeId}.`);
    last = d;
  }

  function draw(status) {
    if (status.state === 'form') drawForm(status);
    else if (status.state === 'attached') drawDispute(status);
    onChange(status);
  }

  // A form session the app opened itself, joined to its own conversation.
  function openSession(id) {
    if (!id || id === sessionId) return;
    sessionId = id;
    store.set(sessionStorage, KEY, sessionId);
    liveSyncStarted = false;
    last = null;
    refresh();
  }

  // The link the assistant shared: swapped once for a form session joined to the conversation and the dispute.
  async function openLink() {
    const token = shared.pendingDispute;
    shared.pendingDispute = '';
    if (!token) return;
    try {
      sessionId = (await api('/dispute/screen/open', { linkToken: token })).sessionId;
      store.set(sessionStorage, KEY, sessionId);
      liveSyncStarted = false;
      refresh();
    } catch (error) { text('dispute-sync', error.message); }
  }

  async function refresh() {
    clearTimeout(timer);
    if (!alive || !sessionId) return;
    try {
      const status = await api('/dispute/screen/status', { sessionId });
      if (status.state === 'expired') { sessionId = null; store.remove(sessionStorage, KEY); return; }
      draw(status);
    } catch { text('dispute-sync', 'We could not reach the dispute service. Trying again…'); }
    if (alive) timer = setTimeout(refresh, POLL_MS);
  }

  $('dispute-form').addEventListener('change', () => {
    if (lastForm && drawChoices(lastForm)) liveSync?.sendContext().catch(() => {});
    text('dispute-saved', 'Saving…'); saver.changed(formValues);
  });
  $('dispute-form').addEventListener('submit', (event) => event.preventDefault());
  $('dispute-submit').addEventListener('click', async (event) => {
    if (!event.isTrusted) return; // only the customer's own click submits
    $('dispute-submit').disabled = true; text('dispute-submit-error', '');
    try { draw(await api('/dispute/screen/submit', { sessionId })); } catch (error) { text('dispute-submit-error', error.message); }
    $('dispute-submit').disabled = false;
  });
  $('dispute-confirm').addEventListener('click', async (event) => {
    if (!event.isTrusted) return; // only the customer's own click counts
    $('dispute-confirm').disabled = true; text('dispute-error', '');
    try { draw(await api('/dispute/screen/confirm', { sessionId })); } catch (error) { text('dispute-error', error.message); }
    $('dispute-confirm').disabled = false;
  });

  if (shared.pendingDispute) await openLink(); else refresh();

  if (shared.pendingDisputeSession) { openSession(shared.pendingDisputeSession); shared.pendingDisputeSession = ''; }
  return {
    openLink,
    openSession,
    showing: () => Boolean(sessionId),
    unmount() { alive = false; clearTimeout(timer); },
  };
}
