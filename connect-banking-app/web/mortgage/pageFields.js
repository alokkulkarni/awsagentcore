import { STAGES } from './context.js';

// Touchpoint 1.0.1 exports analyzePageForms() but never runs it, so it never tells the agent which
// fields exist and silently drops its input actions (FR-34). The page supplies both through the
// SDK's own hooks. Pure: the DOM is reached only through `isFillable` / `ui` (CLAUDE.md rule 18).

// The assistant saw "£" as the escape "\u00a3" and read it aloud on calls: labels go out in words.
const spoken = (t) => (typeof t === 'string' ? t.replace(/\(£\)/g, '(in pounds)').replace(/£\s*/g, 'pounds ') : t);

// Which fields the assistant may see and fill (FR-34), from plain facts the UI adapter reads off the
// element. The Decision in Principle result fields (assistantFill) can also be written from the
// stage just before theirs: the assistant runs the check there, before it moves on.
const NOT_FILLABLE = new Set(['file', 'radio', 'checkbox', 'hidden', 'submit', 'button']);
export function canFill(f) {
  if (!f.inStage || f.isDeclaration || f.disabled || NOT_FILLABLE.has(f.type)) return false;
  if (f.readOnly && !f.assistantFill) return false;
  return f.stageShowing || (f.assistantFill && f.previousStageShowing);
}

// analysis = analyzePageForms() → { context: [{ id, name, type, value, options? }], formElements }.
// Keeps only fillable elements (the UI adapter decides: visible stage, no declaration, no files,
// no read-only/disabled) and re-keys each field by the input's name, which is stable across stages.
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

// A dropdown value must be one of its options: its value, or its visible text in any case
// (the assistant hears "Employed", the option's value is `employed`).
function optionValue(options, v) {
  const t = v.trim().toLowerCase();
  const o = options.find((x) => x.value === v) ?? options.find((x) => x.value !== '' && x.text.trim().toLowerCase() === t);
  return o ? o.value : null;
}

// liveSync.input hook. Validates the whole action first and rejects it without touching the page
// if any field is unknown, not a string, or not one of a select's options (rule 10: reject, don't coerce).
export function createInputHandler({ ui, allowed }) {
  return (fields) => {
    if (!Array.isArray(fields)) throw new Error('input: expected a list of fields');
    const ok = allowed();
    const fills = [];
    for (const f of fields) {
      if (!f || !ok.has(f.id)) throw new Error('input: not a field on this stage');
      if (typeof f.value !== 'string') throw new Error('input: value must be a string');
      const options = ok.get(f.id);
      const value = options ? optionValue(options, f.value) : f.value;
      if (value === null) throw new Error('input: value is not an option of this field');
      fills.push([f.id, value]);
    }
    for (const [id, value] of fills) ui.fillField(id, value);
  };
}

// A destination may arrive as a path, a full URL, a scope, or a spoken stage name in any case,
// possibly with extra words ("Decision in principle stage").
const norm = (t) => String(t ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
function findStage(d) {
  const raw = String(d ?? '').trim();
  let path = raw;
  try { path = new URL(raw, 'https://page.invalid').pathname; } catch { /* not a URL */ }
  const n = norm(raw);
  return STAGES.find((s) => s.path === path || s.scope === raw)
    ?? STAGES.find((s) => norm(s.title) === n || norm(s.scope) === n)
    ?? STAGES.find((s) => n.includes(norm(s.title)));
}

// liveSync.navigation hook. Switches stage in place (no page load, so the call binding survives).
// Destinations outside the six stages are ignored and reported on the console (never a value the
// customer gave: destinations are page names).
// The action's name isn't relied on: ACXD's built-in Navigation action arrives named "Navigation"
// with only a destination, so the destination decides (a stage, or a step word).
const STEP = { next: 1, continue: 1, forward: 1, previous: -1, back: -1 };
export function createNavigationHandler({ onNavigate, current, warn = console.warn }) {
  return (action, destination) => {
    const i = STAGES.findIndex((s) => s.scope === current());
    const step = action === 'page_next' ? 1 : action === 'page_previous' ? -1 : STEP[norm(destination)];
    let target = null;
    if (step) target = i >= 0 ? STAGES[i + step] : null;
    else if (destination != null) target = findStage(destination);
    if (target) onNavigate(target.scope);
    else warn('[mortgage] navigation not applied:', action, destination);
  };
}
