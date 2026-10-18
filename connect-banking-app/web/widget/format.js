// How an assistant message is laid out in the conversation, for reading on a phone: one sentence per line, lists
// as lists, the closing question on its own, the advice disclaimer small. Works on whatever arrives: the agent's
// chat replies (written with line breaks and "- " lists), ARIA's replies, and a call's transcript (spoken, so one
// paragraph). Returns plain data; talk.js turns it into elements as text, never HTML.
//   [{ kind: 'line' | 'ask' | 'note', text }, { kind: 'list', lead, items: [text], ordered }]

const BULLET = /^\s*(?:[-*•–]|(\d+)[.)])\s+(.*)$/;
// A sentence ends at . ! or ? followed by a space and a capital, a £ amount, a digit or a quote.
const SENTENCE_END = /(?<=[.!?])\s+(?=[A-Z£0-9"'‘“(])/;
const NOTE = /^this is guidance based on your past spending/i;
// "The biggest three are shopping at £300, holidays at £296, and eating out at £161." -> a lead and its items.
const LEAD = /^(.*?\b(?:are|were|is|was|include|includes|including)\b)\s+(.+?)[.!]?$/i;

const tidy = (text) => text.replace(/(\*\*|__)(.+?)\1/g, '$2').replace(/^#+\s*/, '').trim();
const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);

// A sentence naming three or more amounts, as a list; otherwise null.
function asList(sentence) {
  if ((sentence.match(/£/g) || []).length < 3) return null;
  const found = sentence.match(LEAD);
  if (!found) return null;
  const items = found[2].split(/,\s*(?:and\s+)?|\s+and\s+(?=[^,]*£[^,]*$)/).map((item) => item.trim()).filter(Boolean);
  if (items.length < 3 || !items.every((item) => item.includes('£'))) return null;
  const lead = found[1].replace(/\s+(?:are|were|is|was)$/i, '');
  return { kind: 'list', lead: `${lead}:`, ordered: false,
    items: items.map((item) => capital(item.replace(/\s+at\s+(£[\d,]+(?:\.\d{2})?)/, ': $1'))) };
}

export function layout(words) {
  const blocks = [];
  let list = null;
  for (const raw of String(words || '').split(/\n/)) {
    const line = tidy(raw);
    if (!line) { list = null; continue; }
    const bullet = line.match(BULLET);
    if (bullet) {
      if (!list) {
        // "The biggest three:" just before a list is the list's lead.
        const before = blocks.at(-1);
        const lead = before && before.kind === 'line' && before.text.endsWith(':') ? blocks.pop().text : '';
        list = { kind: 'list', lead, items: [], ordered: Boolean(bullet[1]) };
        blocks.push(list);
      }
      list.items.push(tidy(bullet[2]));
      continue;
    }
    list = null;
    for (const sentence of line.split(SENTENCE_END).map((s) => s.trim()).filter(Boolean)) {
      const asItems = asList(sentence);
      if (asItems) blocks.push(asItems);
      else if (NOTE.test(sentence)) blocks.push({ kind: 'note', text: sentence });
      else blocks.push({ kind: 'line', text: sentence });
    }
  }
  // The question that closes a message stands on its own.
  const last = blocks.findLast((b) => b.kind !== 'note');
  if (last && last.kind === 'line' && last.text.endsWith('?')) last.kind = 'ask';
  return blocks;
}

// Splits text into plain parts and £ amounts, so amounts can be shown in bold: [{ text, amount }].
export function amounts(text) {
  return String(text).split(/(£[\d,]+(?:\.\d{1,2})?)/).filter(Boolean).map((part) => ({ text: part, amount: part.startsWith('£') }));
}
