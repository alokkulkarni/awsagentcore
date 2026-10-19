import { ACTIONS } from './actions.js';
import { validate } from './validate.js';

const schemaOf = (name) => ACTIONS.find((a) => a.action === name).schema;

function guarded(name, fn) {
  return (payload) => {
    if (!validate(schemaOf(name), payload)) {
      throw new Error(`${name}: payload does not match schema`); // NFR-02: reject, don't coerce
    }
    return fn(payload);
  };
}

// `ui` is a thin adapter over the DOM so handlers stay pure and testable.
export function createHandlers(ui) {
  return {
    apply_product_filter: guarded('apply_product_filter', (f) => ui.filterProducts(f)),
    select_product: guarded('select_product', (id) => {
      if (!ui.visibleProducts().some((p) => p.id === id)) {
        throw new Error(`select_product: ${id} is not on screen`);
      }
      ui.selectProduct(id);
    }),
    open_document_upload: guarded('open_document_upload', (t) => ui.openUpload(t)),
    highlight_field: guarded('highlight_field', (f) => ui.highlight(f)),
    show_affordability_breakdown: () => ui.expandAffordability(),
  };
}
