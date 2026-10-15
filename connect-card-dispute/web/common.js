// Shared by the customer page and the adviser page. No inline script anywhere (the pages'
// content security policy forbids it), and every value is written as text, never as HTML.
export async function api(path, body) {
  const response = await fetch(`/api${path}`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}),
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(json.message ?? `HTTP ${response.status}`); error.code = json.error; throw error; }
  return json;
}

export const $ = (id) => document.getElementById(id);
export const show = (id, visible) => { $(id).hidden = !visible; };
export const text = (id, value) => { $(id).textContent = value; };

const WHO = { aria: 'Assistant', assistant: 'Assistant', adviser: 'Adviser', page: 'On your screen' };
const yesNo = (v) => ({ yes: 'Yes', no: 'No' }[v] ?? '');
const money = (d) => (d.amount ? `£${d.amount}` : '');

// The rows of a dispute, in the order both pages show them: [field, label, value].
export function rowsOf(d) {
  const rows = [
    ['transaction', 'Transaction', d.merchant ? `${d.merchant}, ${money(d)} on ${d.transactionDate}` : ''],
    ['card', 'Card', d.cardLastFour ? `${d.cardType} card ending ${d.cardLastFour}` : ''],
    ['disputeType', 'What happened', d.disputeTypeWords],
    ['reason', 'Reason', d.reasonWords],
  ];
  if (d.disputeType === 'unauthorised') rows.push(['cardInPossession', 'You still have the card', yesNo(d.cardInPossession)]);
  if (d.disputeType === 'merchant') rows.push(['contactedMerchant', 'You have contacted the retailer', yesNo(d.contactedMerchant)]);
  rows.push(['cardBlocked', 'Card blocked', yesNo(d.cardBlocked)], ['narrative', 'In your words', d.narrative]);
  return rows;
}

// Draws the rows into a <tbody>, and briefly highlights any whose value changed since last time.
export function drawRows(tbody, dispute, previous) {
  const before = new Map(previous ? rowsOf(previous).map(([k, , v]) => [k, v]) : []);
  tbody.replaceChildren(...rowsOf(dispute).map(([field, label, value]) => {
    const tr = document.createElement('tr');
    const th = document.createElement('th'); th.textContent = label;
    const td = document.createElement('td'); td.textContent = value || 'Not filled in yet';
    if (!value) td.className = 'empty';
    const by = dispute.filledBy?.[field === 'card' ? 'transaction' : field];
    if (value && WHO[by]) { const tag = document.createElement('span'); tag.className = 'by'; tag.textContent = WHO[by]; td.append(tag); }
    tr.append(th, td);
    if (previous && before.get(field) !== value) { tr.className = 'changed'; setTimeout(() => { tr.className = ''; }, 60); }
    return tr;
  }));
}
