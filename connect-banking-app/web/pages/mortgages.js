// Mortgages: what the application involves, the products, and a way in. Chatting or calling from here starts the
// mortgage journey: the app opens the form, and the mortgage assistant fills it in with the customer.
import { $, api, el, text } from '../lib.js';
import { STAGES } from '../mortgage/context.js';
import { applicationId, savedStage } from '../mortgage/state.js';

export async function mount() {
  const reached = savedStage();
  const start = $('mortgage-start');
  if (reached) {
    start.textContent = 'Continue your application';
    start.href = reached.path;
    text('mortgage-progress', `You've started an application: you were on "${reached.title}".`);
  }
  const config = await api('/mortgage/config').catch(() => ({ products: [] }));
  $('mortgage-products').replaceChildren(...(config.products || []).map((p) => {
    const li = el('li', 'product-row');
    const what = el('div', 'what');
    what.append(el('strong', '', p.name), el('span', 'hint', `Fee £${p.fee.toLocaleString('en-GB')} · up to ${p.maxLtv}% of the property's value`));
    li.append(what, el('span', 'product-rate', `${p.rate.toFixed(2)}%`));
    return li;
  }));
  const stage = reached || STAGES[0];
  return {
    context: () => ({ page: 'mortgage', stage: stage.scope, applicationId: applicationId(), formPath: stage.path,
      label: 'Mortgage application', launcher: 'Help with a mortgage',
      note: 'The assistant fills in the application with you as you talk. Choosing a product is up to you.' }),
  };
}
