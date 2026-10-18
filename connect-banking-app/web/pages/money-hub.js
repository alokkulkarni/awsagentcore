// Money Hub inside the internet banking app: the Money Hub page's own views (money out, money in, expected,
// transactions and goals), drawn from the same API and the same figures as the Money Hub page and its agent.
// Ported from connect-money-hub/web/app.js; the link, the "Forget this device" button and the assistant belong to
// the app around it here. Every value is written as text, never as HTML.
import { $, api, day, el, gbp, initialsTile, monthName, pounds, text } from '../lib.js';

const VIEWS = { out: 'Money out', in: 'Money in', expected: 'Expected', transactions: 'Transactions', goals: 'Goals' };
let choices = { in: [], out: [] };
let txPage = 1;
let txLastDay = '';          // the day heading last drawn, so "Show older" carries on under it
let lastDataDay = '';        // the Money Hub's today (the figures' as-of date)
let say = () => {};          // the app's status line

const avatar = (t) => initialsTile(t.merchantName || t.merchant);
function dayHeading(iso) {
  const date = new Date(`${iso}T12:00:00`);
  const label = date.toLocaleDateString('en-GB', { day: 'numeric', month: 'long' });
  if (iso === lastDataDay) return `Today, ${label}`;
  return `${date.toLocaleDateString('en-GB', { weekday: 'long' })}, ${label}`;
}

// How often, in words a customer would use: "about 5 payments a month", "about once every 3 months".
function howOften(perMonth) {
  if (perMonth < 0.75) return `About once every ${Math.max(2, Math.round(1 / perMonth))} months`;
  if (perMonth < 1.5) return 'About once a month';
  return `About ${Math.round(perMonth)} payments a month`;
}

// Bars per month (the totals are for `months` months), so they read the same way as the habits below them.

function bars(listId, rows, months = 1) {
  const perMonth = (r) => r.total / months;
  const top = Math.max(...rows.map(perMonth), 1);
  $(listId).replaceChildren(...rows.map((r) => {
    const li = el('li', r.discretionary ? 'flex' : '');
    const label = el('span', 'label', r.words);
    const track = el('span', 'track');
    const fill = el('span', 'fill');
    fill.style.width = `${Math.max(2, Math.round((100 * perMonth(r)) / top))}%`;
    track.append(fill);
    li.append(label, track, el('span', 'value', gbp(perMonth(r))));
    return li;
  }));
}

const shortMonth = (key) => new Date(`${key}-15T12:00:00`).toLocaleDateString('en-GB', { month: 'short' });

function drawOverview(o, d) {
  const avg = o.averageMonth;
  const period = `${monthName(o.months[0].month)} to ${monthName(o.months.at(-1).month)}`;
  text('as-of', `Figures up to ${day(o.asOf)}`);
  // Balance today: what's in the account now. A typical month: the average of the last three, as a sum.
  text('balance', gbp(o.balance));
  text('balance-note', `What's in your current account right now (${day(o.asOf)}). It goes up when money comes in and down when you spend.`);
  text('typical-period', `average of ${period}`);
  text('avg-in', gbp(avg.moneyIn));
  text('avg-out', gbp(avg.moneyOut));
  const leftOver = avg.moneyIn - avg.moneyOut;
  text('avg-left', gbp(leftOver));
  const biggest = Math.max(avg.moneyIn, avg.moneyOut, 1);
  $('in-bar').style.width = `${Math.round((100 * avg.moneyIn) / biggest)}%`;
  $('out-bar').style.width = `${Math.round((100 * avg.moneyOut) / biggest)}%`;
  text('avg-saved', leftOver >= 0
    ? `In a typical month you had ${gbp(leftOver)} left over after your spending${avg.movedToSavings ? `, and ${gbp(avg.movedToSavings)} of it went into your savings` : ''}. This is a monthly figure, not your balance.`
    : `In a typical month you spent ${gbp(-leftOver)} more than came in. This is a monthly figure, not your balance.`);
  text('out-period', period);
  $('habits').replaceChildren(...d.habits.filter((h) => h.discretionary).slice(0, 6).map((h) => {
    const li = el('li');
    li.append(el('strong', '', h.words), el('span', 'amount', `${gbp(h.perMonth)} a month`),
      el('span', 'hint', `${howOften(h.timesPerMonth)}, around ${pounds(h.averageEach)} each`));
    return li;
  }));
  $('months').replaceChildren(...o.months.map((m) => {
    const tr = el('tr');
    const month = el('td');
    month.append(el('span', 'long', monthName(m.month)), el('span', 'short', shortMonth(m.month)));
    tr.append(month, el('td', '', gbp(m.moneyIn)), el('td', '', gbp(m.moneyOut)),
      el('td', '', gbp(m.movedToSavings)), el('td', '', gbp(m.moneyIn - m.moneyOut)));
    return tr;
  }));
}

// Money out or in, by month: a column per month split in two, a picker (each month, or all three), then the
// chosen month's split and categories, with real amounts rather than an average.
const monthChoice = { out: '', in: '' };    // the month shown on each tab ('all' for the three together)

function drawMonthly(kind, months, cfg) {
  if (!months.length) return;
  if (monthChoice[kind] !== 'all' && !months.some((m) => m.month === monthChoice[kind])) monthChoice[kind] = months.at(-1).month;
  const choice = monthChoice[kind];
  const redraw = () => drawMonthly(kind, months, cfg);
  const top = Math.max(...months.map((m) => m.total), 1);
  $(cfg.chart).replaceChildren(...months.map((m) => {
    const col = el('button', 'month-col');
    col.type = 'button';
    col.setAttribute('aria-pressed', String(choice === m.month || choice === 'all'));
    col.setAttribute('aria-label', `${monthName(m.month)}: ${gbp(m.total)} ${cfg.word}`);
    const stack = el('span', 'col-stack');
    stack.style.height = `${Math.max(6, Math.round((100 * m.total) / top))}%`;
    const b = el('span', 'col-b');
    b.style.height = `${Math.round((100 * cfg.partB(m)) / (m.total || 1))}%`;
    stack.append(b, el('span', 'col-a'));
    const plot = el('span', 'col-plot');
    plot.append(stack);
    col.append(el('span', 'col-total', pounds(m.total)), plot, el('span', 'col-label', shortMonth(m.month)));
    col.addEventListener('click', () => { monthChoice[kind] = m.month; redraw(); });
    return col;
  }));
  const options = [...months.map((m) => [m.month, shortMonth(m.month)]), ['all', 'All three months']];
  $(cfg.pick).replaceChildren(...options.map(([key, label]) => {
    const button = el('button', '', label);
    button.type = 'button';
    button.setAttribute('aria-pressed', String(choice === key));
    button.addEventListener('click', () => { monthChoice[kind] = key; redraw(); });
    return button;
  }));

  const chosen = choice === 'all' ? months : months.filter((m) => m.month === choice);
  const total = chosen.reduce((sum, m) => sum + m.total, 0);
  const partB = chosen.reduce((sum, m) => sum + cfg.partB(m), 0);
  const byCat = new Map();
  for (const m of chosen) {
    for (const c of m.categories) {
      const row = byCat.get(c.category) || { ...c, total: 0 };
      row.total += c.total;
      byCat.set(c.category, row);
    }
  }
  const share = total ? Math.round((100 * partB) / total) : 0;
  text(cfg.scope, choice === 'all'
    ? `${monthName(months[0].month)} to ${monthName(months.at(-1).month)}: ${gbp(total)} ${cfg.word} altogether`
    : `${monthName(choice)}: ${gbp(total)} ${cfg.word}`);
  text(cfg.split, `${cfg.labelA} ${gbp(total - partB)} · ${cfg.labelB} ${gbp(partB)} (${share}%)`);
  $(cfg.splitA).style.width = `${100 - share}%`;
  $(cfg.splitB).style.width = `${share}%`;
  bars(cfg.bars, [...byCat.values()].sort((x, y) => y.total - x.total), 1);
}

function drawSpending(months) {
  drawMonthly('out', months, { chart: 'month-chart', pick: 'out-pick', scope: 'out-scope', split: 'split', splitA: 'split-ess',
    splitB: 'split-flex', bars: 'out-bars', word: 'out', labelA: 'Bills and essentials', labelB: 'spending you choose',
    partB: (m) => m.discretionary });
}

function drawIncome(months) {
  if (months.length) text('in-period', `${monthName(months[0].month)} to ${monthName(months.at(-1).month)}`);
  drawMonthly('in', months, { chart: 'in-chart', pick: 'in-pick', scope: 'in-scope', split: 'in-split', splitA: 'in-split-a',
    splitB: 'in-split-b', bars: 'in-bars', word: 'in', labelA: 'Salary', labelB: 'other money in',
    partB: (m) => m.other });
}

let chosenMonth = '';         // the month card selected on the Expected tab (kept across refreshes)

// The months ahead: a card per month; the chosen one shows what's expected in it, adding up to its card.
function drawForecast(f) {
  if (!f.months.some((m) => m.month === chosenMonth)) chosenMonth = f.months[0]?.month || '';
  $('forecast').replaceChildren(...f.months.map((m) => {
    const card = el('button', 'card month-card');
    card.type = 'button';
    card.setAttribute('aria-pressed', String(m.month === chosenMonth));
    card.append(el('h3', '', monthName(m.month)), el('p', 'in', `In ${gbp(m.expectedIn)}`),
      el('p', 'out', `Out ${gbp(m.expectedOut)}`), el('p', 'big', `Ends at ${gbp(m.endBalance)}`));
    card.addEventListener('click', () => { chosenMonth = m.month; drawForecast(f); });
    return card;
  }));
  const m = f.months.find((x) => x.month === chosenMonth);
  if (m) drawMonth(m);
  text('basis', f.basis);
}

function drawMonth(m) {
  text('month-title', `Expected in ${monthName(m.month)}`);
  text('month-totals', `In ${gbp(m.expectedIn)} · Out ${gbp(m.expectedOut)} · Ends at ${gbp(m.endBalance)}`);
  const items = [...m.regularIn.map((e) => ({ ...e, in: true })), ...m.regularOut.map((e) => ({ ...e, in: false }))]
    .sort((a, b) => a.date.localeCompare(b.date) || Number(b.in) - Number(a.in));
  const rows = [];
  let shownDay = '';
  for (const e of items) {
    if (e.date !== shownDay) { shownDay = e.date; rows.push(el('li', 'tx-day', dayHeading(e.date))); }
    const li = el('li', `tx-row${e.in ? ' in' : ''}`);
    const what = el('div', 'what');
    const meta = el('div', 'tx-meta');
    meta.append(el('span', 'tx-cat', e.words), el('span', 'tx-when', 'regular'));
    what.append(el('strong', '', e.merchantName || e.merchant), meta);
    li.append(avatar(e), what, el('span', 'value', `${e.in ? '+' : '−'}${gbp(e.amount)}`));
    rows.push(li);
  }
  if (m.sideIncome > 0) {
    const li = el('li', 'tx-row in');
    const what = el('div', 'what');
    what.append(el('strong', '', 'Other income'), el('span', 'hint', 'an estimate, at your recent monthly average'));
    li.append(avatar({ merchant: 'other income', merchantName: 'Other income' }), what, el('span', 'value', `+${gbp(m.sideIncome)}`));
    rows.push(li);
  }
  $('month-items').replaceChildren(...rows);
  $('month-everyday').replaceChildren(...m.everydaySpending.map((e) => {
    const li = el('li');
    li.append(el('span', '', e.words), el('span', 'value', `−${gbp(e.amount)}`));
    return li;
  }));
  const everydayTotal = m.everydaySpending.reduce((sum, e) => sum + e.amount, 0);
  $('month-everyday-title').hidden = !m.everydaySpending.length;
  if (m.everydaySpending.length) {
    const total = el('li', 'total');
    total.append(el('span', '', 'Everyday spending in all'), el('span', 'value', `−${gbp(everydayTotal)}`));
    $('month-everyday').append(total);
  }
}

function categorySelect(t) {
  const select = el('select', 'chip-select');
  select.setAttribute('aria-label', `Category for ${t.merchantName} on ${day(t.date)}`);
  const options = t.direction === 'in' ? choices.in : choices.out;
  for (const c of options) select.append(new Option(c.words, c.category, false, c.category === t.category));
  select.addEventListener('change', async () => {
    select.disabled = true;
    try {
      await api('/recategorise', { transactionId: t.transactionId, category: select.value });
      say(`Moved ${t.merchantName} to ${select.selectedOptions[0].text}.`);
      await load(false);
    } catch (error) { say(error.message); }
    select.disabled = false;
  });
  return select;
}

async function loadTransactions(reset = true) {
  if (reset) { txPage = 1; txLastDay = ''; $('tx').replaceChildren(); }
  const listed = await api('/transactions', {
    page: txPage, direction: $('f-direction').value, category: $('f-category').value, merchant: $('f-merchant').value,
  });
  const rows = [];
  for (const t of listed.transactions) {
    if (t.date !== txLastDay) {
      txLastDay = t.date;
      rows.push(el('li', 'tx-day', dayHeading(t.date)));
    }
    const li = el('li', `tx-row${t.amount > 0 ? ' in' : ''}`);
    const what = el('div', 'what');
    const meta = el('div', 'tx-meta');
    meta.append(categorySelect(t));
    if (t.recategorised) meta.append(el('span', 'tx-mine', 'your category'));
    what.append(el('strong', '', t.merchantName), meta);
    li.append(avatar(t), what, el('span', 'value', `${t.amount > 0 ? '+' : '−'}${gbp(Math.abs(t.amount))}`));
    rows.push(li);
  }
  $('tx').append(...rows);
  if (!rows.length && reset) $('tx').append(el('li', 'tx-empty', 'No payments match. Try another search or category.'));
  text('tx-count', listed.total ? `${listed.total} ${listed.total === 1 ? 'payment' : 'payments'}` : '');
  $('more').hidden = !listed.hasMore;
}

const monthYear = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
const openGoals = new Set();   // goals the customer has opened, kept open when the page refreshes

// A goal card: name, target and date, progress and status; opens to show the plan behind it.
function goalCard(g) {
  const li = el('li', 'goal');
  const box = el('details');
  box.open = openGoals.has(g.name);
  box.addEventListener('toggle', () => { if (box.open) openGoals.add(g.name); else openGoals.delete(g.name); });
  const plan = g.plan;
  const share = Math.min(100, Math.round((100 * (g.saved || 0)) / g.target));

  const summary = el('summary');
  const head = el('div', 'goal-head');
  head.append(el('strong', '', g.name), el('span', `goal-status ${plan ? (plan.onTrack ? 'ok' : 'gap') : 'past'}`,
    plan ? (plan.onTrack ? 'On track' : 'Needs changes') : 'Date passed'));
  const line = el('div', 'goal-line');
  line.append(el('span', 'goal-target', `${gbp(g.target)} by ${day(g.byDate)} ${g.byDate.slice(0, 4)}`),
    el('span', 'hint', `${gbp(g.neededPerMonth)} a month`));
  const bar = el('div', 'goal-bar');
  const fill = el('span');
  fill.style.width = `${share}%`;
  bar.append(fill);
  summary.append(head, line, bar, el('span', 'hint goal-saved', `${gbp(g.saved || 0)} saved so far (${share}%)`));
  box.append(summary);

  const details = el('div', 'goal-details');
  if (plan) {
    const facts = el('dl', 'goal-facts');
    const fact = (label, value) => { facts.append(el('dt', '', label), el('dd', '', value)); };
    fact('Needed each month', `${gbp(plan.neededPerMonth)} for ${plan.months} ${plan.months === 1 ? 'month' : 'months'}`);
    fact('Left over now', `${gbp(plan.leftOverPerMonth)} a month${plan.alreadyMovingToSavings ? `, ${gbp(plan.alreadyMovingToSavings)} of it to savings` : ''}`);
    if (plan.otherGoalsPerMonthNow > 0) {
      fact('Your other goals need', `${gbp(plan.otherGoalsPerMonthNow)} a month of that now`);
      fact('Free for this goal', plan.freeForThisGoalPerMonth > 0 ? `about ${gbp(plan.freeForThisGoalPerMonth)} a month, on average to its date` : 'Nothing for now: your other goals need it all');
    }
    fact('Gap', plan.onTrack ? `None: what you have left over covers it${plan.otherGoalsPerMonthNow > 0 ? ', alongside your other goals' : ''}` : `${gbp(plan.gapPerMonth)} a month`);
    if (plan.reachedAtCurrentRate) fact('At your current rate', `reached in ${monthYear(plan.reachedAtCurrentRate.date)}`);
    if (!plan.onTrack && plan.reachedWithMix) fact('With the changes below', `reached in ${monthYear(plan.reachedWithMix.date)}`);
    details.append(facts);
    if (!plan.onTrack && plan.changes.length) {
      details.append(el('p', 'goal-sub', 'Changes that would help (examples, your choice):'));
      const list = el('ul', 'goal-changes');
      for (const c of plan.changes) {
        const item = el('li');
        item.append(el('span', '', c.change), el('span', 'value', `+${gbp(c.savesPerMonth)} a month`));
        list.append(item);
      }
      details.append(list);
    }
  } else {
    details.append(el('p', 'hint', 'This date has passed. Remove the goal, or add it again with a later date.'));
  }
  const remove = el('button', 'link', 'Remove goal');
  remove.type = 'button';
  remove.addEventListener('click', async () => { await api('/goal/delete', { name: g.name }); await load(false); });
  details.append(remove);
  box.append(details);
  li.append(box);
  return li;
}

function drawGoals(goals) {
  $('goals').replaceChildren(...goals.map(goalCard));
  if (!goals.length) $('goals').append(el('li', 'hint goal-empty', 'No goals yet. Add one above, or ask the assistant to help you set one.'));
}

let knownGoals = null;      // goal names last drawn, to announce one the assistant adds

async function load(all = true) {
  const view = await api('/hub');
  lastDataDay = view.overview.asOf;
  const names = view.goals.map((g) => g.name);
  const added = knownGoals ? names.filter((n) => !knownGoals.includes(n)) : [];
  knownGoals = names;
  if (added.length) say(`Your goal "${added.join('", "')}" is now on the Goals tab.`);
  choices = view.choices;
  drawOverview(view.overview, view.discretionary);
  drawSpending(view.monthlySpending || []);
  drawIncome(view.monthlyIncome || []);
  drawForecast(view.forecast);
  drawGoals(view.goals);
  if (all) {
    const known = new Set();
    for (const c of [...choices.out, ...choices.in]) {
      if (!known.has(c.category)) { known.add(c.category); $('f-category').append(new Option(c.words, c.category)); }
    }
    await loadTransactions();
  }
  $('hub').hidden = false;
}

export async function mount({ message }) {
  say = message;
  knownGoals = null;
  txPage = 1;
  for (const tab of document.querySelectorAll('[role=tab]')) {
    tab.addEventListener('click', () => {
      for (const t of document.querySelectorAll('[role=tab]')) {
        t.setAttribute('aria-selected', String(t === tab));
        $(`view-${t.dataset.view}`).hidden = t !== tab;
      }
    });
  }
  $('filters').addEventListener('input', () => { loadTransactions().catch((e) => say(e.message)); });
  $('filters').addEventListener('submit', (e) => e.preventDefault());
  $('more').addEventListener('click', () => { txPage += 1; loadTransactions(false).catch((e) => say(e.message)); });
  $('goal-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const saved = await api('/goal', { name: $('g-name').value, target: Number($('g-target').value),
        byDate: $('g-date').value, saved: Number($('g-saved').value || 0) });
      const p = saved.plan;
      text('g-result', p.onTrack
        ? `On track: ${gbp(p.neededPerMonth)} a month, and you have about ${gbp(p.leftOverPerMonth)} left over.`
        : `${gbp(p.neededPerMonth)} a month needed; about ${gbp(p.gapPerMonth)} a month more than you have left over now. Open the goal below for ideas.`);
      $('goal-form').reset();
      await load(false);
    } catch (error) { text('g-result', error.message); }
  });
  await load();
  let timer = 0;
  const view = () => document.querySelector('[role=tab][aria-selected=true]')?.dataset.view || 'out';
  return {
    context: () => ({ page: 'money_hub', view: view(), label: `Money Hub · ${VIEWS[view()]}`, launcher: 'Ask about your money',
      note: 'This is guidance based on your past spending, not financial advice.' }),
    // While a conversation is going, the assistant can save goals or move payments: refresh shortly after it speaks.
    refresh() { clearTimeout(timer); timer = setTimeout(() => load(false).catch(() => {}), 1500); },
    unmount() { clearTimeout(timer); },
  };
}
