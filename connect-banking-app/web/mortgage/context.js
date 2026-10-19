import { ACTIONS } from './actions.js';

export const STAGES = [
  { scope: 'about_you', path: '/apply/about-you', title: 'About you' },
  { scope: 'property_loan', path: '/apply/property', title: 'Property and loan' },
  { scope: 'dip_result', path: '/apply/decision', title: 'Decision in Principle' },
  { scope: 'product_selection', path: '/apply/products', title: 'Choose a product' },
  { scope: 'documents', path: '/apply/documents', title: 'Documents' },
  { scope: 'review_submit', path: '/apply/review', title: 'Review and submit' },
];

// Builds the payload for touchpoint.sendContext() for one stage (FR-01, FR-03).
export function buildContext(scope, state = {}) {
  const stage = STAGES.find((s) => s.scope === scope);
  if (!stage) throw new Error(`Unknown stage: ${scope}`);
  const actions = ACTIONS.filter((a) => a.scopes.includes(scope)).map((a) =>
    a.action === 'select_product' ? { ...a, input: { products: state.products ?? [] } } : { ...a });
  return { uri: stage.path, scopes: [scope], destinations: STAGES.map((s) => s.path), actions };
}
