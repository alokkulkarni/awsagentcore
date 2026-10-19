import { startLiveSync } from './touchpoint.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// "Get help by phone" on a page that already has the form open (FR-21, FR-24).
// The page shows a help code; when a caller quotes it, this tab binds to that call.
// `api` calls your web backend, which invokes the Lambda directly (IAM door) with
// { operation: 'createHelpCode' | 'helpCodeStatus' }. The agent endpoint refuses page operations (NFR-12).
export async function startScreenHelp({ api, create, analyzePageForms, onNavigate, config, ui, applicationId, stage, state = {},
  pollMs = 2000, maxPolls = 300 }) {
  const { code, helpSessionId } = await api.createHelpCode({ applicationId, stage });
  ui.showHelpCode(code);

  for (let i = 0; i < maxPolls; i++) {
    const s = await api.helpCodeStatus(helpSessionId); // secret session id, never the code
    if (s.claimed) {
      const ls = await startLiveSync({ create, analyzePageForms, onNavigate, config, ui, input: 'external', contactId: s.contactId });
      await ls.enterStage(stage, state); // the agent sees exactly where the customer is
      return ls;
    }
    if (s.expired) { ui.showHelpExpired(); throw new Error('Help code expired'); }
    await sleep(pollMs);
  }
  ui.showHelpExpired();
  throw new Error('Help code expired');
}
