// The customer's card disputes as a list (Cards' "Your disputes" tab and the Help page): the payment, the
// reference, where it's up to, and what's still missing. Every value is written as text.
// With actions (the Cards page): a complete draft can be submitted by the customer (after a confirm step), and an
// unfinished one finished with the dispute assistant.
import { day, el, tidyMerchant } from '../lib.js';

function button(label, className, onClick) {
  const b = el('button', className, label);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
}

// The row's actions: Submit (then "Yes, submit" / "Cancel"), or Finish with our assistant.
function actions(d, { onSubmit, onFinish }) {
  const box = el('div', 'dispute-actions');
  const error = el('p', 'error');
  error.setAttribute('role', 'alert');
  if (d.canSubmit && onSubmit) {
    const start = () => {
      const yes = button('Yes, submit', 'dispute-submit-yes', async (event) => {
        if (!event.isTrusted) return;
        yes.disabled = true;
        try { await onSubmit(d); } catch (e) { error.textContent = e.message; yes.disabled = false; }
      });
      box.replaceChildren(el('span', 'hint', 'Submit this dispute? You confirm the details are correct.'), yes,
        button('Cancel', 'link', () => box.replaceChildren(first, error)), error);
    };
    const first = button('Submit', 'dispute-submit-start', start);
    first.setAttribute('aria-label', `Submit dispute ${d.disputeId}`);
    box.append(first, error);
  } else if (d.status === 'draft' && d.missing?.length && !d.alreadyDisputedAs && onFinish) {
    const finish = button('Finish with our assistant', 'link', () => onFinish(d));
    finish.setAttribute('aria-label', `Finish dispute ${d.disputeId} with our assistant`);
    box.append(finish);
  }
  return box;
}

export function disputeRows(disputes, handlers = {}) {
  if (!disputes.length) return [el('li', 'hint dispute-empty', 'No disputes. If a card payment looks wrong, choose Dispute next to it.')];
  return disputes.map((d) => {
    const li = el('li', `dispute-row${d.open ? ' open' : ''}`);
    const what = el('div', 'what');
    what.append(el('strong', '', `${tidyMerchant(d.merchant)} · £${d.amount}`),
      el('span', 'hint', `${d.disputeId} · ${d.cardType === 'credit' ? 'Credit' : 'Debit'} card ••${d.cardLastFour}`
        + `${d.transactionDate ? ` · paid ${day(d.transactionDate)}` : ''}`));
    if (d.alreadyDisputedAs) what.append(el('span', 'hint', `This payment is already disputed as ${d.alreadyDisputedAs}: nothing more to do here.`));
    else if (d.open && d.missing?.length) what.append(el('span', 'hint', `Still to fill in: ${d.missing.join(', ')}`));
    if (d.canSubmit) what.append(el('span', 'hint', 'Everything is filled in: you can submit it.'));
    const right = el('div', 'dispute-right');
    right.append(el('span', `pill dispute-status ${d.status}`, d.statusWords), actions(d, handlers));
    li.append(what, right);
    return li;
  });
}
