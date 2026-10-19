// Form filling for the Live Sync route, kept free of the page so it can be tested on its own.
// The pattern (and the reasons in the comments) come from the mortgage Live Sync page, where each
// was found on live contacts.

// Touchpoint 1.0.1 exports analyzePageForms() but never runs it, so by itself it never tells the
// agent which fields exist and silently drops the agent's attempts to fill them. The page supplies
// both through the SDK's own hooks.

// The agent saw "£" as an escape sequence and read it aloud: labels go out in words.
const spoken = (t) => (typeof t === 'string' ? t.replace(/£\s*/g, 'pounds ') : t);

const NOT_FILLABLE = new Set(['file', 'radio', 'checkbox', 'hidden', 'submit', 'button']);
// Plain facts about one form control, read off the element by the page.
export const canFill = (f) => f.inForm && !f.disabled && !f.readOnly && !NOT_FILLABLE.has(f.type);

// analysis = analyzePageForms() → { context: [{ id, name, type, value, options? }], formElements }.
// Keeps only the dispute form's fillable controls and re-keys each by its `name`.
export function describeFields(analysis, isFillable) {
  const fields = []; const allowed = new Map();
  for (const info of analysis?.context ?? []) {
    const element = analysis.formElements?.[info.id];
    if (!element || !element.name || !isFillable(element)) continue;
    fields.push({ ...info, id: element.name, name: spoken(info.name), ...(info.description && { description: spoken(info.description) }) });
    allowed.set(element.name, Array.isArray(info.options)
      ? info.options.map((o) => ({ value: String(o.value), text: String(o.text ?? '') })) : null);
  }
  return { fields, allowed };
}

// A dropdown's value must be one of its options: its value, or its visible text in any case
// (the agent hears "Yes", the option's value is `yes`).
export function optionValue(options, v) {
  const t = v.trim().toLowerCase();
  const o = options.find((x) => x.value === v) ?? options.find((x) => x.value !== '' && x.text.trim().toLowerCase() === t);
  return o ? o.value : null;
}

// The liveSync.input hook. Checks the whole request first and rejects it without touching the page
// if any field is unknown, not text, or not one of a dropdown's options. Reject, never coerce.
export function createInputHandler({ fill, allowed }) {
  return (fields) => {
    if (!Array.isArray(fields)) throw new Error('input: expected a list of fields');
    const ok = allowed();
    const fills = [];
    for (const f of fields) {
      if (!f || !ok.has(f.id)) throw new Error('input: not a field on this form');
      if (typeof f.value !== 'string') throw new Error('input: value must be text');
      const options = ok.get(f.id);
      const value = options ? optionValue(options, f.value) : f.value;
      if (value === null) throw new Error('input: value is not an option of this field');
      fills.push([f.id, value]);
    }
    for (const [id, value] of fills) fill(id, value);
  };
}

// One save a moment after the last change, carrying the latest state. A failed save never throws
// to the page: the next change tries again.
export function createSaver({ send, delayMs = 700, setTimer = setTimeout, clearTimer = clearTimeout }) {
  let timer = null;
  const cancel = () => { if (timer !== null) { clearTimer(timer); timer = null; } };
  const save = async (getState) => { try { return await send(getState()); } catch { return null; } };
  return {
    changed(getState) { cancel(); timer = setTimer(() => { timer = null; return save(getState); }, delayMs); },
    now(getState) { cancel(); return save(getState); },
    pending: () => timer !== null,
  };
}
