// Tests for the page's form-filling logic. Run from the repository root:
//   node --test connect-card-dispute/tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canFill, describeFields, optionValue, createInputHandler, createSaver } from '../web/formfill.js';

const analysis = {
  context: [
    { id: 'a1', name: 'Which payment is this about?', type: 'select', value: '',
      options: [{ value: '', text: 'Choose the payment…' }, { value: 'TXN-1', text: 'AMAZON.CO.UK, £89.99' }] },
    { id: 'a2', name: 'What happened, in your own words', type: 'textarea', value: '' },
    { id: 'a3', name: 'Search the site', type: 'text', value: '' },
    { id: 'a4', name: 'Confirm', type: 'checkbox', value: '' },
  ],
  formElements: {
    a1: { name: 'transactionId', form: 'dispute' }, a2: { name: 'narrative', form: 'dispute' },
    a3: { name: 'q', form: 'search' }, a4: { name: 'confirm', form: 'dispute', type: 'checkbox' },
  },
};
const isFillable = (el) => canFill({ inForm: el.form === 'dispute', disabled: false, readOnly: false, type: el.type ?? 'text' });

test('only the dispute form\'s own controls are offered to the agent, keyed by name', () => {
  const { fields, allowed } = describeFields(analysis, isFillable);
  assert.deepEqual(fields.map((f) => f.id), ['transactionId', 'narrative']);
  assert.deepEqual([...allowed.keys()], ['transactionId', 'narrative']);
  assert.equal(allowed.get('narrative'), null);
  assert.equal(fields[0].options[1].text.includes('£'), true); // option text is left as the page shows it
});
test('checkboxes, files, disabled and read-only controls are never fillable', () => {
  for (const type of ['checkbox', 'radio', 'file', 'hidden', 'submit', 'button']) assert.equal(canFill({ inForm: true, type }), false, type);
  assert.equal(canFill({ inForm: true, type: 'text', disabled: true }), false);
  assert.equal(canFill({ inForm: true, type: 'text', readOnly: true }), false);
  assert.equal(canFill({ inForm: false, type: 'text' }), false);
  assert.equal(canFill({ inForm: true, type: 'select-one' }), true);
});
test('a dropdown accepts an option\'s value or its visible text, and nothing else', () => {
  const options = [{ value: '', text: 'Choose…' }, { value: 'yes', text: 'Yes' }, { value: 'no', text: 'No' }];
  assert.equal(optionValue(options, 'yes'), 'yes');
  assert.equal(optionValue(options, ' YES '), 'yes');
  assert.equal(optionValue(options, 'maybe'), null);
  assert.equal(optionValue(options, 'Choose…'), null); // the placeholder is not an answer
});
test('the input hook rejects the whole request before touching the page', () => {
  const filled = [];
  const { allowed } = describeFields(analysis, isFillable);
  const input = createInputHandler({ fill: (id, value) => filled.push([id, value]), allowed: () => allowed });
  input([{ id: 'transactionId', value: 'AMAZON.CO.UK, £89.99' }, { id: 'narrative', value: 'Not me.' }]);
  assert.deepEqual(filled, [['transactionId', 'TXN-1'], ['narrative', 'Not me.']]);
  filled.length = 0;
  for (const bad of [
    [{ id: 'narrative', value: 'ok' }, { id: 'confirm', value: 'true' }],   // not a field the agent may fill
    [{ id: 'narrative', value: 'ok' }, { id: 'transactionId', value: 'TXN-9' }], // not one of the options
    [{ id: 'narrative', value: 42 }],
    'narrative=ok',
  ]) assert.throws(() => input(bad));
  assert.deepEqual(filled, [], 'nothing was filled by a rejected request');
});
test('several quick changes make one save with the latest state, and a failed save never throws', async () => {
  const sent = []; const timers = new Map(); let id = 0;
  const saver = createSaver({ send: async (s) => { sent.push(s); throw new Error('offline'); }, delayMs: 700,
    setTimer: (fn, ms) => { timers.set(++id, { fn, ms }); return id; }, clearTimer: (t) => timers.delete(t) });
  saver.changed(() => ({ v: 1 })); saver.changed(() => ({ v: 2 }));
  assert.equal(timers.size, 1); assert.equal(saver.pending(), true);
  const [[key, timer]] = timers; timers.delete(key); await timer.fn();
  assert.deepEqual(sent, [{ v: 2 }]); assert.equal(saver.pending(), false);
  assert.equal(await saver.now(() => ({ v: 3 })), null);
});
