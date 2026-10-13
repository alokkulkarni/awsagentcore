// Binds this page to the customer's phone call so the CX designer agent can fill the form
// (Touchpoint in `external` mode). Used only on the Live Sync route, after a call has attached to
// the page. If Live Sync is not configured, or fails to start, the page is still a form the
// customer can fill in by hand.
import { describeFields, createInputHandler, canFill } from './formfill.js';

const TOUCHPOINT = '/vendor/touchpoint-1.0.1/index.js';
const FORM_ID = 'dispute-form';
// The first context can reach the agent before its conversation exists, so it is sent again.
const RESEND_AFTER_MS = [1500, 4000, 9000];

const isFillable = (el) => canFill({
  inForm: el.form?.id === FORM_ID, disabled: el.disabled, readOnly: el.readOnly === true, type: el.type,
});

export async function startLiveSync({ config, contactId, fill }) {
  if (!config?.configured) return null;
  const { create, analyzePageForms } = await import(TOUCHPOINT);
  let allowed = new Map();
  const touchpoint = await create({
    config: { region: config.region },
    input: 'external',                 // the phone call drives the page; the page opens no call of its own
    languageCode: 'en-GB',             // Live Sync connects on `connect-<language>`; the SDK defaults to en-US
    launchIcon: false,
    liveSync: {
      deploymentKey: config.deploymentKey, apiKey: config.apiKey, contactId,
      input: createInputHandler({ fill, allowed: () => allowed }),
    },
  });

  async function sendContext() {
    const described = describeFields(analyzePageForms(), isFillable);
    allowed = described.allowed;
    // One page, so no navigation; and no custom actions: nothing here can confirm or submit.
    await touchpoint.sendContext({ uri: '/dispute', scopes: ['dispute_form'], destinations: ['/dispute'],
      actions: [], fields: described.fields });
  }
  await sendContext();
  for (const ms of RESEND_AFTER_MS) setTimeout(() => { sendContext().catch(() => {}); }, ms);
  return { sendContext };
}
