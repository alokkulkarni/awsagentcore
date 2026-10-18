// The customer's card disputes as a list (Cards' "Your disputes" tab and the Help page): the payment, the
// reference, where it's up to, and what's still missing. Every value is written as text.
import { day, el, tidyMerchant } from '../lib.js';

export function disputeRows(disputes) {
  if (!disputes.length) return [el('li', 'hint dispute-empty', 'No disputes. If a card payment looks wrong, choose Dispute next to it.')];
  return disputes.map((d) => {
    const li = el('li', `dispute-row${d.open ? ' open' : ''}`);
    const what = el('div', 'what');
    what.append(el('strong', '', `${tidyMerchant(d.merchant)} · £${d.amount}`),
      el('span', 'hint', `${d.disputeId} · ${d.cardType === 'credit' ? 'Credit' : 'Debit'} card ••${d.cardLastFour}`
        + `${d.transactionDate ? ` · paid ${day(d.transactionDate)}` : ''}`));
    if (d.open && d.missing?.length) what.append(el('span', 'hint', `Still to fill in: ${d.missing.join(', ')}`));
    li.append(what, el('span', `pill dispute-status ${d.status}`, d.statusWords));
    return li;
  });
}
