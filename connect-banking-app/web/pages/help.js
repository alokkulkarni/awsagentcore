// Help: how to reach us, the customer's disputes at a glance, and common questions. The assistant helps with
// anything from here.
import { $, api } from '../lib.js';
import { disputeRows } from '../dispute/list.js';

export async function mount() {
  try {
    const { disputes } = await api('/disputes');
    if (disputes.length) {
      $('help-disputes-list').replaceChildren(...disputeRows(disputes.slice(0, 4)));
      $('help-disputes').hidden = false;
    }
  } catch { /* disputes aren't set up: Help still works */ }
  return { context: () => ({ page: 'help', label: 'Help', launcher: 'Ask us anything' }) };
}
