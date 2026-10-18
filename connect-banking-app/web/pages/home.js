// Home: a greeting, the customer's accounts, shortcuts, and the latest payments.
import { $, api, day, el, gbp, initialsTile, text } from '../lib.js';

// An account as a card: its name and ending, then its balance (or, for a mortgage, the monthly payment).
export function accountCard(a) {
  const card = el('a', `account account-${a.kind}`);
  card.href = a.kind === 'mortgage' ? '/mortgages' : '/accounts';
  card.dataset.link = '';
  const head = el('div', 'account-head');
  head.append(el('strong', '', a.name), el('span', 'account-ending', `ending ${a.ending}`));
  card.append(head);
  if (a.kind === 'mortgage') {
    card.append(el('span', 'account-label', 'Monthly payment'), el('span', 'account-balance', gbp(a.monthly)));
  } else {
    card.append(el('span', 'account-label', 'Balance'), el('span', 'account-balance', gbp(a.balance)));
  }
  if (a.note) card.append(el('span', 'account-note', a.note));
  return card;
}

// A payment row: the merchant's tile, its name and category, the date, and the amount (green when money comes in).
export function paymentRow(t) {
  const li = el('li', `tx-row${t.in ? ' in' : ''}`);
  const what = el('div', 'what');
  const meta = el('div', 'tx-meta');
  meta.append(el('span', 'tx-cat', t.category), el('span', 'tx-when', day(t.date)));
  what.append(el('strong', '', t.merchantName), meta);
  li.append(initialsTile(t.merchantName), what, el('span', 'value', `${t.in ? '+' : '−'}${gbp(Math.abs(t.amount))}`));
  return li;
}

export async function mount({ shared }) {
  const me = shared.me || await api('/app/home');
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  text('hello', me.firstName ? `${greeting}, ${me.firstName}` : greeting);
  text('home-as-of', `Balances up to ${day(me.asOf)}`);
  $('home-accounts').replaceChildren(...me.accounts.map(accountCard));
  $('home-recent').replaceChildren(...me.recent.map(paymentRow));
  return { context: () => ({ page: 'home', label: 'Home', launcher: 'Ask us anything' }) };
}
