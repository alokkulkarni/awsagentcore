// The customer page. It shows a code until a contact attaches a dispute to it, then shows that
// dispute and keeps it up to date. The page's secret (sessionId) never leaves this tab.
import { api, $, show, text, drawRows } from './common.js';

const POLL_MS = 2000;
const KEY = 'disputeScreen';
let sessionId = sessionStorage.getItem(KEY);
let last = null;

async function newCode() {
  show('new-code', false);
  text('code', '······'); text('code-note', 'Getting a code…');
  const screen = await api('/screen');
  sessionId = screen.sessionId;
  sessionStorage.setItem(KEY, sessionId);
}

function drawWaiting(status) {
  show('waiting', true); show('form', false);
  text('code', `${status.code.slice(0, 3)} ${status.code.slice(3)}`);
  const minutes = Math.max(1, Math.ceil(status.expiresInSeconds / 60));
  text('code-note', `This code works for about ${minutes} more minute${minutes === 1 ? '' : 's'}.`);
}

function drawDispute(status) {
  const d = status.dispute;
  show('waiting', false); show('form', true);
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

async function refresh() {
  try {
    if (!sessionId) await newCode();
    const status = await api('/screen/status', { sessionId });
    if (status.state === 'attached') drawDispute(status);
    else if (status.state === 'waiting') drawWaiting(status);
    else { // expired: an attached page stays as it was; a waiting page offers a new code
      sessionId = null; sessionStorage.removeItem(KEY);
      if (!last) { text('code', '······'); text('code-note', 'That code has expired.'); show('new-code', true); }
      return;
    }
  } catch { text('code-note', 'We could not reach the service. Trying again…'); }
  setTimeout(refresh, POLL_MS);
}

$('new-code').addEventListener('click', () => { refresh(); });
$('confirm').addEventListener('click', async (event) => {
  if (!event.isTrusted) return; // only the customer's own click counts
  $('confirm').disabled = true; text('error', '');
  try { drawDispute(await api('/screen/confirm', { sessionId })); } catch (error) { text('error', error.message); }
  $('confirm').disabled = false;
});

refresh();
