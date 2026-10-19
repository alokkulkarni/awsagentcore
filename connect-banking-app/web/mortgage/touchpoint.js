import { buildContext } from './context.js';
import { createHandlers } from './handlers.js';
import { describeFields, createInputHandler, createNavigationHandler } from './pageFields.js';

// `create` and `analyzePageForms` are injected: in the browser pass the real ones from
//   import { create, analyzePageForms } from '@amazon-connect-touchpoint/web';
// `onNavigate(scope)` switches stage in place (FR-34); without it the SDK default applies.
export async function startLiveSync({ create, config, ui, input = 'text', contactId, analyzePageForms, onNavigate, onContactEnded }) {
  for (const k of ['deploymentKey', 'apiKey']) {
    if (!config[k]) throw new Error(`Missing Live Sync ${k} in runtime config`);
  }
  let allowed = new Map(); let current = null;
  const pageHooks = {
    ...(analyzePageForms && { input: createInputHandler({ ui, allowed: () => allowed }) }),
    ...(onNavigate && { navigation: createNavigationHandler({ onNavigate, current: () => current }) }),
  };
  const touchpoint = await create({
    config: {
      chatEndpoint: config.chatEndpoint,
      voiceEndpoint: config.voiceEndpoint,
      instanceId: config.instanceId,
      contactFlowId: config.contactFlowId,
      region: config.region,
      // Sent to the start-contact endpoint, which re-validates them (FR-33, NFR-15).
      ...(config.contactAttributes && { contactAttributes: config.contactAttributes }),
      ...(config.participantDisplayName && { participantDisplayName: config.participantDisplayName }),
    },
    input, // 'text' | 'voice' | 'voiceMini' | 'external' (phone call driving the page)
    // Live Sync connects on the channel `connect-<languageCode>`; the SDK defaults to en-US,
    // so set the application's language explicitly.
    languageCode: config.languageCode ?? 'en-GB',
    ...(config.theme && { theme: config.theme }),
    ...(config.colorMode && { colorMode: config.colorMode }),
    ...(config.windowSize && { windowSize: config.windowSize }),
    // FR-37: the page draws its own launcher, so Touchpoint's is hidden and the panel sits above it.
    ...(config.launchIcon !== undefined && { launchIcon: config.launchIcon }),
    ...(config.containerStyle && { containerStyle: config.containerStyle }),
    ...(onContactEnded && { onContactEnded }),
    liveSync: { deploymentKey: config.deploymentKey, apiKey: config.apiKey, ...(contactId && { contactId }), ...pageHooks },
  });
  const handlers = createHandlers(ui);

  async function enterStage(scope, state) {
    const ctx = buildContext(scope, state);
    ctx.actions = ctx.actions.map((a) => ({ ...a, handler: handlers[a.action] }));
    current = scope;
    if (analyzePageForms) { // FR-34: the visible stage's fields, from the same scan the input hook checks
      const d = describeFields(analyzePageForms(), ui.isFillable);
      ctx.fields = d.fields; allowed = d.allowed;
    }
    await touchpoint.sendContext(ctx);
  }
  return { touchpoint, enterStage };
}
