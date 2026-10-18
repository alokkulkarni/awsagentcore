// The mortgage application in progress, kept in this browser tab only (as the mortgage page does): its id, the
// answers so far and the stage reached. A convenience; the form works without it.
import { STAGES } from './context.js';

const KEY = { id: 'mortgageApplicationId', form: 'mortgageForm', stage: 'mortgageStage' };
const read = (key) => { try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; } };
const write = (key, value) => { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* not kept */ } };

// The mortgage page's own id format: "MA-" and eight characters with no I, O, 0 or 1.
export function applicationId() {
  let id = read(KEY.id);
  if (!/^MA-[A-HJ-NP-Z2-9]{8}$/.test(id || '')) {
    const abc = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    id = `MA-${[...crypto.getRandomValues(new Uint8Array(8))].map((b) => abc[b % abc.length]).join('')}`;
    write(KEY.id, id);
  }
  return id;
}

export const savedForm = () => read(KEY.form) ?? {};
export const saveForm = (values) => write(KEY.form, values);
export const savedStage = () => STAGES.find((s) => s.scope === read(KEY.stage)) ?? null;
export const saveStage = (scope) => write(KEY.stage, scope);
export const startAgain = () => { for (const key of Object.values(KEY)) { try { sessionStorage.removeItem(key); } catch { /* none */ } } };
