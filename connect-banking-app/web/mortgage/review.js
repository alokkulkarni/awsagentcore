// Review and submit stage (FR-36): every answer read-only, grouped by stage, and what's missing.
// Pure: values come from the saved form, uploaded document types from the UI adapter.
const OPTIONS = {
  employmentStatus: { employed: 'Employed', self_employed: 'Self-employed', other: 'Other' },
  buyerType: { first_time: 'First-time buyer', home_mover: 'Home mover', remortgage: 'Remortgage' },
};
const FIELDS = [
  ['About you', 'fullName', 'Full name'], ['About you', 'dateOfBirth', 'Date of birth'],
  ['About you', 'employmentStatus', 'Employment'], ['About you', 'annualIncome', 'Annual income before tax'],
  ['About you', 'commitmentsMonthly', 'Monthly credit commitments'],
  ['Property and loan', 'propertyValue', 'Property value'], ['Property and loan', 'deposit', 'Deposit'],
  ['Property and loan', 'termYears', 'Mortgage term (years)'], ['Property and loan', 'buyerType', 'Buyer type'],
  ['Decision in Principle', 'dipDecision', 'Decision in Principle'], ['Product', 'productId', 'Product'],
];
export const DOCUMENTS = [['payslips', 'Payslips'], ['bank_statement', 'Bank statement'], ['photo_id', 'Photo ID']];

// The assistant writes the Decision in Principle result: accept it in any case or punctuation.
const DIP_WORDS = { accept: 'accept', accepted: 'accept', refer: 'refer', referred: 'refer', decline: 'decline', declined: 'decline' };
export const dipOutcome = (v) => DIP_WORDS[String(v ?? '').toLowerCase().replace(/[^a-z]/g, '')] ?? null;
const DIP_LABEL = { accept: 'Accept', refer: 'Refer', decline: 'Decline' };

const filled = (v) => v !== undefined && v !== null && String(v).trim() !== '';

export function reviewApplication(values = {}, uploaded = []) {
  const rows = []; const missing = [];
  for (const [group, name, label] of FIELDS) {
    const raw = values[name];
    const dip = name === 'dipDecision' ? dipOutcome(raw) : null;
    const value = filled(raw) ? (dip ? DIP_LABEL[dip] : (OPTIONS[name]?.[raw] ?? String(raw))) : '';
    let problem = !filled(raw);
    if (name === 'dipDecision' && filled(raw) && dip !== 'accept') {
      problem = true; missing.push('Decision in Principle (must be accept)');
    } else if (problem) missing.push(label);
    rows.push({ group, name, label, value, missing: problem });
  }
  for (const [type, label] of DOCUMENTS) {
    const has = uploaded.includes(type);
    rows.push({ group: 'Documents', name: type, label, value: has ? 'Uploaded' : '', missing: !has });
    if (!has) missing.push(label);
  }
  return { rows, missing, complete: missing.length === 0 };
}
