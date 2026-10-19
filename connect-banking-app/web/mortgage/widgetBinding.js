import { startLiveSync } from './touchpoint.js';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Binds Live Sync to a call your own Chime SDK widget already started (FR-29, FR-30).
// The widget owns the audio; Touchpoint runs headless ('external') and only syncs the page.
export function createWidgetBinder({ create, config, ui }) {
  let bound = null; // { contactId, session }

  async function bind({ contactId, stage, state = {} }) {
    if (!UUID.test(contactId ?? '')) throw new Error('Invalid contactId');
    if (bound?.contactId === contactId) return bound.session;
    const session = await startLiveSync({ create, config, ui, input: 'external', contactId });
    bound = { contactId, session };
    await session.enterStage(stage, state);
    return session;
  }

  async function enterStage(stage, state = {}) {
    if (bound) await bound.session.enterStage(stage, state);
  }

  return { bind, enterStage, current: () => bound?.contactId ?? null };
}

// Mobile WebView: the native calling layer tells the page which call it started (FR-31).
// iOS:     webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('mortgage:call-started',{detail:{contactId:'…'}}))")
// Android: webView.evaluateJavascript(same, null)
export function listenForNativeCall({ target = globalThis, onContactId }) {
  const handler = (e) => {
    const id = e?.detail?.contactId;
    if (typeof id === 'string' && UUID.test(id)) onContactId(id);
  };
  target.addEventListener('mortgage:call-started', handler);
  return () => target.removeEventListener('mortgage:call-started', handler);
}

// Mobile WebView: the web form's "Call us" button asks the native app to start the call (FR-32).
export function requestNativeCall({ win = globalThis, applicationId, stage }) {
  const msg = { applicationId, stage };
  if (win.webkit?.messageHandlers?.startCall) { win.webkit.messageHandlers.startCall.postMessage(msg); return 'ios'; }
  if (win.AndroidBridge?.startCall) { win.AndroidBridge.startCall(JSON.stringify(msg)); return 'android'; }
  return 'none'; // not in the app: use the web Chime widget
}
