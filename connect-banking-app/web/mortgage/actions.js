// Single source of truth for Live Sync custom actions (SDD §2, CLAUDE.md rule 8).
// Navigation and form fill are Touchpoint's built-in input/navigation actions (FR-02, FR-03), applied
// through the SDK's liveSync.input / liveSync.navigation hooks (FR-34, web/src/pageFields.js).
export const ACTIONS = [
  {
    action: 'apply_product_filter',
    description: 'Filter the mortgage products shown on screen when the customer asks for a fixed term length or products with no arrangement fee.',
    scopes: ['product_selection'],
    schema: {
      type: 'object',
      properties: {
        fixedTermYears: { type: 'number', enum: [2, 5] },
        feeFree: { type: 'boolean' },
      },
      additionalProperties: false,
    },
  },
  {
    action: 'select_product',
    description: 'Select the product the customer names from the products currently listed on screen. Use only an id from the input list. Never choose on the customer\'s behalf.',
    scopes: ['product_selection'],
    schema: { type: 'string', description: 'The id of a product visible on screen.' },
  },
  {
    action: 'open_document_upload',
    description: 'Open the upload panel for the document type the customer wants to provide now.',
    scopes: ['documents'],
    schema: { type: 'string', enum: ['payslips', 'bank_statement', 'photo_id'] },
  },
  {
    action: 'highlight_field',
    description: 'Draw the customer\'s attention to a field or section on the review page. This never changes a value.',
    scopes: ['review_submit'],
    schema: { type: 'string', enum: ['declaration', 'product_summary', 'loan_summary', 'documents_summary'] },
  },
  {
    action: 'show_affordability_breakdown',
    description: 'Expand the explanation of how the Decision in Principle amount was worked out when the customer asks why.',
    scopes: ['dip_result'],
  },
];
