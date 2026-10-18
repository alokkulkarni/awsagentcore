import { canFill } from './pageFields.js';

// UI adapter for the mortgage form in the banking app: the only mortgage module that touches the DOM, as on the
// mortgage page (its web/app/ui.js, without its own launcher: the app's assistant replaces it). Handlers in this
// folder call these methods; they never set the declaration or submit.
const $ = (id) => document.getElementById(id);

function flag(el) { // "Filled by assistant" marker so the customer knows who changed what
  if (!el) return;
  el.classList.add('by-assistant');
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// Which elements the assistant may fill: reads the facts off the element; pageFields.js decides.
function isFillable(el) {
  const form = el?.closest?.('form.stage');
  const before = form?.previousElementSibling;
  return canFill({ inStage: !!form, stageShowing: !!form && !form.hidden,
    previousStageShowing: !!before?.matches?.('form.stage') && !before.hidden,
    isDeclaration: el?.id === 'declare', type: el?.type, readOnly: !!el?.readOnly,
    assistantFill: !!el?.hasAttribute?.('data-assistant-fill'), disabled: !!el?.disabled });
}

export function createUi({ products }) {
  let filter = {};
  let timer = null;

  function renderProducts() {
    const list = $('products');
    if (!list) return;
    const chosen = list.querySelector('input:checked')?.value;
    list.replaceChildren();
    for (const p of products) {
      if (filter.fixedTermYears !== undefined && p.fixedTermYears !== filter.fixedTermYears) continue;
      if (filter.feeFree && p.fee !== 0) continue;
      const card = document.createElement('label');
      card.className = 'product'; card.setAttribute('role', 'listitem'); card.dataset.id = p.id;
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'productId'; radio.value = p.id; radio.checked = p.id === chosen;
      const name = document.createElement('strong'); name.textContent = p.name;
      const facts = document.createElement('span'); facts.className = 'product-facts';
      facts.textContent = `${p.rate}% · fee £${p.fee} · max LTV ${p.maxLtv}%`;
      card.append(radio, name, facts);
      list.append(card);
    }
  }

  return {
    renderProducts,
    visibleProducts: () => [...document.querySelectorAll('#products .product')]
      .map((c) => products.find((p) => p.id === c.dataset.id)).filter(Boolean),
    filterProducts(f) { filter = { ...f }; renderProducts(); flag($('products')); },
    selectProduct(id) {
      const radio = document.querySelector(`#products input[value="${CSS.escape(id)}"]`);
      if (radio) { radio.checked = true; radio.dispatchEvent(new Event('change', { bubbles: true })); flag(radio.closest('.product')); }
    },
    openUpload(type) { const box = document.querySelector(`.upload[data-doc="${CSS.escape(type)}"]`); flag(box); box?.querySelector('input')?.focus(); },
    highlight(field) { flag($(field)); }, // draws attention only; never ticks or changes a value
    expandAffordability() { $('affordability').open = true; flag($('affordability')); },

    // Review and submit: read-only answers, missing items, the result. Text only, no HTML.
    renderReview(review) {
      const boxes = { 'About you': 'loan_summary', 'Property and loan': 'loan_summary', 'Decision in Principle': 'loan_summary',
        Product: 'product_summary', Documents: 'documents_summary' };
      for (const id of new Set(Object.values(boxes))) $(id).replaceChildren();
      let last = null;
      for (const row of review.rows) {
        const box = $(boxes[row.group]);
        if (row.group !== last) { const h = document.createElement('h3'); h.textContent = row.group; box.append(h); last = row.group; }
        const line = document.createElement('div'); line.className = row.missing ? 'review-row missing-row' : 'review-row';
        const k = document.createElement('span'); k.className = 'review-label'; k.textContent = row.label;
        const v = document.createElement('span'); v.className = 'review-value';
        v.textContent = row.missing ? (row.value ? `${row.value} (needs attention)` : 'Missing') : row.value;
        line.append(k, v); box.append(line);
      }
      const m = $('review-missing');
      m.hidden = review.complete;
      m.textContent = review.complete ? '' : `Before you can confirm and submit, complete: ${review.missing.join(', ')}.`;
    },
    uploadedDocs: () => [...document.querySelectorAll('.upload[data-doc]')]
      .filter((u) => u.querySelector('input[type=file]')?.files?.length > 0).map((u) => u.dataset.doc),
    showSubmitResult(r) {
      const el = $('submit-result'); el.hidden = false;
      el.textContent = r.ok ? `Application submitted. Your reference is ${r.reference}.`
        : `We couldn't submit yet: ${(r.errors ?? ['please try again']).join('; ')}.`;
      el.className = r.ok ? 'submit-result ok' : 'submit-result error';
    },

    // Live Sync form fill. Values arrive already checked by pageFields.js.
    isFillable,
    fillField(name, value) {
      const el = [...document.querySelectorAll(`form.stage [name="${CSS.escape(name)}"]`)].find(isFillable);
      if (!el) return false;
      el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true })); // the page saves the form on change
      flag(el);
      return true;
    },

    // Help-code panel
    showHelpCode(code) {
      $('help').hidden = false;
      $('help-code').textContent = `${code.slice(0, 3)} ${code.slice(3)}`;
      $('help-state').textContent = 'Waiting for your call…';
      const end = Date.now() + 10 * 60 * 1000;
      clearInterval(timer);
      timer = setInterval(() => {
        const s = Math.max(0, Math.round((end - Date.now()) / 1000));
        if ($('help-timer')) $('help-timer').textContent = `Valid for ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
      }, 1000);
    },
    showHelpClaimed(liveSync) {
      clearInterval(timer);
      $('help').hidden = true;
      $('help-state').textContent = liveSync
        ? 'Connected to your call. The assistant can now see this page.'
        : 'Connected to your call. The assistant can\'t see this page yet.';
      $('help-start').hidden = true;
    },
    showHelpExpired() {
      clearInterval(timer);
      $('help').hidden = true;
      $('help-state').textContent = 'Code expired — get a new one.';
      $('help-start').hidden = false;
    },
    showError(msg) { $('help-state').textContent = msg; },
    setStatus(text) { if ($('livesync-state')) $('livesync-state').textContent = text; },
    stop() { clearInterval(timer); },
  };
}
