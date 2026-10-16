// Money Hub page. Opened from a link whose secret is after "#" (never sent to a server or in a Referer).
// The secret is read once, wiped from the address bar, and sent only in the body of this page's own calls.
// Every value is written as text, never as HTML.
import { setupTalk } from './talk.js';

const $ = (id) => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };
const gbp = (n) => `£${Number(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const day = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
const monthName = (key) => new Date(`${key}-15T12:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });

let token = new URLSearchParams(location.hash.slice(1)).get('k') || sessionStorage.getItem('moneyHub') || '';
if (location.hash) history.replaceState(null, '', location.pathname);
if (token) sessionStorage.setItem('moneyHub', token);

let choices = { in: [], out: [] };
let txPage = 1;

async function api(path, body = {}) {
  const response = await fetch(`/api${path}`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ...body, token }),
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(json.message || `Something went wrong (${response.status}).`);
  return json;
}

function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

function bars(listId, rows) {
  const top = Math.max(...rows.map((r) => r.total), 1);
  $(listId).replaceChildren(...rows.map((r) => {
    const li = el('li', r.discretionary ? 'flex' : '');
    const label = el('span', 'label', r.words);
    const track = el('span', 'track');
    const fill = el('span', 'fill');
    fill.style.width = `${Math.max(2, Math.round((100 * r.total) / top))}%`;
    track.append(fill);
    li.append(label, track, el('span', 'value', gbp(r.total)));
    return li;
  }));
}

function drawOverview(o, d) {
  text('as-of', `Figures up to ${day(o.asOf)}`);
  text('balance', gbp(o.balance));
  text('avg-in', gbp(o.averageMonth.moneyIn));
  text('avg-out', gbp(o.averageMonth.moneyOut));
  text('avg-left', gbp(o.averageMonth.moneyIn - o.averageMonth.moneyOut));
  text('out-period', `${monthName(o.months[0].month)} to ${monthName(o.months.at(-1).month)}`);
  text('split', `Essentials ${gbp(d.essentialPerMonth)} a month · Discretionary ${gbp(d.discretionaryPerMonth)} a month (${d.discretionaryShare}%)`);
  bars('out-bars', o.topSpending);
  bars('in-bars', o.moneyInSources);
  $('habits').replaceChildren(...d.habits.filter((h) => h.discretionary).slice(0, 6).map((h) => {
    const li = el('li');
    li.append(el('strong', '', h.words), el('span', '', `${gbp(h.perMonth)} a month · ${h.timesPerMonth} ${h.timesPerMonth === 1 ? 'time' : 'times'} · ${gbp(h.averageEach)} each`));
    return li;
  }));
  $('months').replaceChildren(...o.months.map((m) => {
    const tr = el('tr');
    tr.append(el('td', '', monthName(m.month)), el('td', '', gbp(m.moneyIn)), el('td', '', gbp(m.moneyOut)),
      el('td', '', gbp(m.movedToSavings)), el('td', '', gbp(m.net)));
    return tr;
  }));
}

function drawForecast(f, regular) {
  $('forecast').replaceChildren(...f.months.map((m) => {
    const card = el('article', 'card');
    card.append(el('h3', '', monthName(m.month)), el('p', 'in', `In ${gbp(m.expectedIn)}`),
      el('p', 'out', `Out ${gbp(m.expectedOut)}`), el('p', 'big', `Ends at ${gbp(m.endBalance)}`));
    return card;
  }));
  $('regular').replaceChildren(...regular.map((r) => {
    const li = el('li', r.direction === 'in' ? 'in' : '');
    li.append(el('span', '', r.merchantName || r.merchant), el('span', 'hint', `${r.words} · next ${day(r.nextExpected)}`),
      el('span', 'value', `${r.direction === 'in' ? '+' : '−'}${gbp(r.amount)}`));
    return li;
  }));
  text('basis', f.basis);
}

function categorySelect(t) {
  const select = el('select');
  select.setAttribute('aria-label', `Category for ${t.merchantName} on ${day(t.date)}`);
  const options = t.direction === 'in' ? choices.in : choices.out;
  for (const c of options) select.append(new Option(c.words, c.category, false, c.category === t.category));
  select.addEventListener('change', async () => {
    select.disabled = true;
    try {
      await api('/recategorise', { transactionId: t.transactionId, category: select.value });
      text('message', `Moved ${t.merchantName} to ${select.selectedOptions[0].text}.`);
      await load(false);
    } catch (error) { text('message', error.message); }
    select.disabled = false;
  });
  return select;
}

async function loadTransactions(reset = true) {
  if (reset) { txPage = 1; $('tx').replaceChildren(); }
  const listed = await api('/transactions', {
    page: txPage, direction: $('f-direction').value, category: $('f-category').value, merchant: $('f-merchant').value,
  });
  $('tx').append(...listed.transactions.map((t) => {
    const li = el('li', t.amount > 0 ? 'in' : '');
    const what = el('div', 'what');
    what.append(el('strong', '', t.merchantName), el('span', 'hint', `${day(t.date)}${t.recategorised ? ' · your category' : ''}`));
    li.append(what, categorySelect(t), el('span', 'value', `${t.amount > 0 ? '+' : '−'}${gbp(Math.abs(t.amount))}`));
    return li;
  }));
  $('more').hidden = !listed.hasMore;
}

function drawGoals(goals) {
  $('goals').replaceChildren(...goals.map((g) => {
    const li = el('li');
    const remove = el('button', 'link', 'Remove');
    remove.addEventListener('click', async () => { await api('/goal/delete', { name: g.name }); await load(false); });
    li.append(el('strong', '', `${g.name}: ${gbp(g.target)} by ${day(g.byDate)}`),
      el('span', '', `${gbp(g.neededPerMonth)} a month · ${g.onTrack ? 'on track at your current rate' : 'needs changes to reach'}`), remove);
    return li;
  }));
  if (!goals.length) $('goals').append(el('li', 'hint', 'No goals yet.'));
}

async function load(all = true) {
  const view = await api('/hub');
  choices = view.choices;
  drawOverview(view.overview, view.discretionary);
  drawForecast(view.forecast, view.recurring);
  drawGoals(view.goals);
  if (all && view.talk) {
    setupTalk({
      api,
      currentView: () => document.querySelector('[role=tab][aria-selected=true]').dataset.view,
      onEnded: () => load(false).catch(() => {}),
    });
  }
  if (all) {
    const known = new Set();
    for (const c of [...choices.out, ...choices.in]) {
      if (!known.has(c.category)) { known.add(c.category); $('f-category').append(new Option(c.words, c.category)); }
    }
    await loadTransactions();
  }
  $('hub').hidden = false;
}

for (const tab of document.querySelectorAll('[role=tab]')) {
  tab.addEventListener('click', () => {
    for (const t of document.querySelectorAll('[role=tab]')) {
      t.setAttribute('aria-selected', String(t === tab));
      $(`view-${t.dataset.view}`).hidden = t !== tab;
    }
  });
}
$('filters').addEventListener('input', () => { loadTransactions().catch((e) => text('message', e.message)); });
$('filters').addEventListener('submit', (e) => e.preventDefault());
$('more').addEventListener('click', () => { txPage += 1; loadTransactions(false).catch((e) => text('message', e.message)); });
$('goal-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const saved = await api('/goal', { name: $('g-name').value, target: Number($('g-target').value),
      byDate: $('g-date').value, saved: Number($('g-saved').value || 0) });
    const p = saved.plan;
    text('g-result', p.onTrack
      ? `On track: ${gbp(p.neededPerMonth)} a month, and you have about ${gbp(p.leftOverPerMonth)} left over.`
      : `${gbp(p.neededPerMonth)} a month needed; about ${gbp(p.gapPerMonth)} a month more than you have left over now. Ask the assistant for ideas.`);
    await load(false);
  } catch (error) { text('g-result', error.message); }
});

if (!token) text('message', 'Open your Money Hub from the link we gave you.');
else load().catch((error) => text('message', error.message));
