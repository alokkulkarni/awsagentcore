// Cards: the customer's cards, their payments, and their disputes.
//   Card payments   the card dispute service's own list, so the payment the customer picks is the one the dispute
//                   assistant finds. "Dispute" points the assistant at it and opens the assistant: the contact goes
//                   straight to the dispute assistant with that payment (entry=card_dispute).
//   Your disputes   every dispute and where it's up to, and the dispute form. When the dispute assistant sends its
//                   form during a call or chat, the app opens it here (at /cards/dispute) and it fills in as they talk.
import { $, api, day, el, gbp, initialsTile, text, tidyMerchant } from '../lib.js';
import { mountDisputeForm } from '../dispute/form.js';
import { disputeRows } from '../dispute/list.js';

let filter = 'all';
const LIST_EVERY_MS = 5000;     // the list follows a dispute being filled in

function cardFace(c) {
  const face = el('div', `bank-card bank-card-${c.type}`);
  face.append(el('span', 'bank-card-brand', 'Nationwide'), el('span', 'bank-card-name', c.name),
    el('span', 'bank-card-number', `•••• •••• •••• ${c.ending}`));
  return face;
}

export async function mount({ shared, talk }) {
  const view = await api('/app/cards');
  let chosen = shared.disputePayment || null;       // the payment being disputed, while it's this page's context
  let form = null;
  let listTimer = 0;
  let alive = true;

  $('cards-list').replaceChildren(...view.cards.map(cardFace));

  function drawFilter() {
    const options = [['all', 'All cards'], ...view.cards.map((c) => [c.type, `${c.type === 'debit' ? 'Debit' : 'Credit'} ••${c.ending}`])];
    $('cards-filter').replaceChildren(...options.map(([key, label]) => {
      const button = el('button', '', label);
      button.type = 'button';
      button.setAttribute('aria-pressed', String(filter === key));
      button.addEventListener('click', () => { filter = key; drawFilter(); drawPayments(); });
      return button;
    }));
  }

  function drawPayments() {
    $('cards-payments').replaceChildren(...view.payments.filter((p) => filter === 'all' || p.card === filter).map((p) => {
      const li = el('li', `tx-row${chosen?.id === p.id ? ' chosen' : ''}`);
      const what = el('div', 'what');
      const meta = el('div', 'tx-meta');
      meta.append(el('span', 'tx-cat', `${p.card === 'debit' ? 'Debit' : 'Credit'} card ••${p.ending}`), el('span', 'tx-when', day(p.date)));
      what.append(el('strong', '', tidyMerchant(p.merchant)), meta);
      const dispute = el('button', 'link dispute-button', 'Dispute');
      dispute.type = 'button';
      dispute.setAttribute('aria-label', `Dispute ${tidyMerchant(p.merchant)}, ${gbp(p.amount)} on ${day(p.date)}`);
      dispute.addEventListener('click', () => {
        chosen = p;
        shared.disputePayment = p;
        drawPayments();
        talk()?.contextChanged();
        talk()?.open();
      });
      const right = el('div', 'tx-right');
      right.append(el('span', 'value', `−${gbp(p.amount)}`), dispute);
      li.append(initialsTile(p.merchant), what, right);
      return li;
    }));
  }

  async function drawDisputes() {
    clearTimeout(listTimer);
    if (!alive) return;
    try {
      const { disputes } = await api('/disputes');
      $('disputes-list').replaceChildren(...disputeRows(disputes));
      const open = disputes.filter((d) => d.open).length;
      text('disputes-count', open ? String(open) : '');
    } catch { /* disputes aren't set up: the tab still holds the form */ }
    if (alive && tab === 'disputes') listTimer = setTimeout(drawDisputes, LIST_EVERY_MS);
  }

  let tab = location.pathname === '/cards/dispute' ? 'disputes' : 'payments';
  async function showTab(next, push = true) {
    tab = next;
    for (const button of document.querySelectorAll('.cards-tabs [role=tab]')) button.setAttribute('aria-selected', String(button.dataset.tab === tab));
    $('cards-payments-panel').hidden = tab !== 'payments';
    $('cards-disputes-panel').hidden = tab !== 'disputes';
    const path = tab === 'disputes' ? '/cards/dispute' : '/cards';
    if (push && location.pathname !== path) history.pushState({}, '', path);
    if (tab === 'disputes') {
      if (!form) form = await mountDisputeForm({ shared, onChange: () => {} });
      drawDisputes();
    }
  }
  for (const button of document.querySelectorAll('.cards-tabs [role=tab]')) {
    button.addEventListener('click', () => showTab(button.dataset.tab));
  }

  drawFilter();
  drawPayments();
  drawDisputes();
  await showTab(tab, false);

  return {
    context: () => (chosen
      ? { page: 'card_dispute', paymentId: chosen.id, launcher: 'Help with a payment',
          label: `Disputing ${tidyMerchant(chosen.merchant)} ${gbp(chosen.amount)}` }
      : { page: 'cards', label: 'Cards', launcher: 'Help with a payment' }),
    // The dispute assistant posted its form in the chat ("Open the form here").
    async openLink() { await showTab('disputes'); form?.openLink(); },
    // The app opened the form itself, joined to the conversation.
    async openSession(sessionId) { await showTab('disputes'); form?.openSession(sessionId); },
    unmount() { alive = false; clearTimeout(listTimer); form?.unmount(); },
  };
}
