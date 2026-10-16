// The adviser page. Opened from the contact's screen pop with a link whose token sits after "#",
// the part of an address a browser never sends to a server. The token is taken out of the address
// bar at once and kept only for this tab.
import { api, $, show, text, drawRows } from './common.js';

const POLL_MS = 3000;
const KEY = 'disputeAdviser';
const FIELDS = ['disputeType', 'reason', 'cardInPossession', 'contactedMerchant', 'cardBlocked', 'narrative'];

let token = location.hash.slice(1) || sessionStorage.getItem(KEY) || '';
if (location.hash) { sessionStorage.setItem(KEY, token); history.replaceState(null, '', location.pathname); }
let last = null;

function options(select, choices, current) {
  const wanted = JSON.stringify(Object.keys(choices));
  if (select.dataset.keys !== wanted) {
    select.replaceChildren(new Option('Choose…', ''), ...Object.entries(choices).map(([value, words]) => new Option(words, value)));
    select.dataset.keys = wanted;
  }
  if (document.activeElement !== select) select.value = current ?? '';
}

function draw(reply) {
  const d = reply.dispute;
  const submitted = d.status === 'submitted';
  show('form', true); show('edit', !submitted); show('submit-box', !submitted); show('submitted', submitted);
  text('reference', d.disputeId); text('status', d.statusWords); text('submitted-reference', d.disputeId);
  $('status').className = submitted ? 'status submitted' : 'status';
  text('watching', reply.customerIsWatching
    ? 'The customer is watching this form on their own screen. Your changes appear there within a few seconds.'
    : 'The customer is not viewing this form. Read the details back to them before you submit.');
  drawRows($('rows'), d, last);

  options($('disputeType'), reply.choices.disputeType, d.disputeType);
  options($('reason'), reply.choices.reason[d.disputeType] ?? {}, d.reason);
  for (const name of ['cardInPossession', 'contactedMerchant', 'cardBlocked']) {
    if (document.activeElement !== $(name)) $(name).value = d[name] ?? '';
  }
  if (document.activeElement !== $('narrative')) $('narrative').value = d.narrative ?? '';
  const atRisk = d.disputeType === 'unauthorised' || d.disputeType === 'scam'; const merchant = d.disputeType === 'merchant';
  show('cardInPossession', atRisk); show('cardInPossession-label', atRisk);
  show('contactedMerchant', merchant); show('contactedMerchant-label', merchant);

  show('missing', d.missing.length > 0);
  text('missing', `Still needed: ${d.missing.join(', ')}.`);
  const byClick = d.customerConfirmed && d.confirmationSource === 'customer_click';
  text('confirm-state', byClick ? 'The customer has confirmed these details on their own screen.'
    : 'The customer has not confirmed on their own screen.');
  $('verbal').checked = d.customerConfirmed && !byClick;
  $('verbal').disabled = byClick || d.missing.length > 0;
  $('submit').disabled = !(d.customerConfirmed && d.missing.length === 0);
  last = d;
}

function closed(error) {
  for (const id of ['form', 'edit', 'submit-box', 'submitted']) show(id, false);
  show('closed', true);
  text('closed-why', error?.message ?? 'Open the dispute again from the contact\'s screen pop.');
}

async function call(path, body) {
  text('error', '');
  try { draw(await api(path, { token, ...body })); text('saved', 'Saved'); } catch (error) {
    if (error.code === 'link_expired') { closed(error); return; }
    text('error', error.message);
  }
}

for (const name of FIELDS) {
  $(name).addEventListener('change', () => {
    const value = $(name).value.trim();
    if (value) call('/adviser/update', { fields: { [name]: value } });
  });
}
$('verbal').addEventListener('change', (event) => {
  if (event.isTrusted) call('/adviser/confirm', { accepted: $('verbal').checked });
});
$('submit').addEventListener('click', (event) => {
  if (event.isTrusted) call('/adviser/submit', {});
});

async function refresh() {
  if (!token) { closed(); return; }
  try { draw(await api('/adviser/open', { token })); } catch (error) {
    if (error.code === 'link_expired') { closed(error); return; }
  }
  if (last?.status !== 'submitted') setTimeout(refresh, POLL_MS);
}
refresh();
