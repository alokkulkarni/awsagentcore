// Accounts: every account, and the chosen account's latest movements (/accounts/current, /accounts/savings).
// The saver shows only money moved to and from the current account: a savings account has no merchant payments.
import { $, api, day, el, text } from '../lib.js';
import { accountCard, paymentRow } from './home.js';

const SAVINGS_NOTE = 'Money only moves between your savings and your current account.';

export async function mount() {
  const wanted = location.pathname.split('/')[2] || 'current';
  const view = await api('/app/accounts', { account: wanted });
  $('accounts-list').replaceChildren(...view.accounts.map((a) => {
    const card = accountCard(a);
    if (a.id === view.selected) {
      card.classList.add('selected');
      card.setAttribute('aria-current', 'page');
    }
    return card;
  }));
  const chosen = view.accounts.find((a) => a.id === view.selected);
  text('accounts-title', chosen ? `${chosen.name}, ending ${chosen.ending}` : 'Current account');
  text('accounts-as-of', `up to ${day(view.asOf)}`);
  $('accounts-recent').replaceChildren(...(view.recent.length
    ? view.recent.map(paymentRow) : [el('li', 'tx-empty', 'Nothing has moved in or out yet.')]));
  $('accounts-note').hidden = view.selected !== 'savings';
  text('accounts-note', SAVINGS_NOTE);
  $('accounts-hub-hint').hidden = view.selected !== 'current';
  return { context: () => ({ page: 'accounts', label: chosen ? chosen.name : 'Accounts', launcher: 'Ask us anything' }) };
}
