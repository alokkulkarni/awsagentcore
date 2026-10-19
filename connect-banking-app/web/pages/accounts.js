// Accounts: every account, and the current account's latest payments.
import { $, api, day, text } from '../lib.js';
import { accountCard, paymentRow } from './home.js';

export async function mount() {
  const view = await api('/app/accounts');
  $('accounts-list').replaceChildren(...view.accounts.map(accountCard));
  text('accounts-as-of', `up to ${day(view.asOf)}`);
  $('accounts-recent').replaceChildren(...view.recent.map(paymentRow));
  return { context: () => ({ page: 'accounts', label: 'Accounts', launcher: 'Ask us anything' }) };
}
