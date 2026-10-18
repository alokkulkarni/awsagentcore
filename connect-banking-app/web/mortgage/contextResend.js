// FR-37: Touchpoint posts the page context once, as soon as the contact exists. Connect starts the
// assistant's conversation a moment later, so that first post can arrive too early and be lost; the
// assistant then asks for a help code on a call the page itself started. Sending the context again
// a few times is harmless (it is the same context) and closes that gap.
export const RESEND_AFTER_MS = [3000, 8000, 15000, 30000];

// `send()` sends the context of whichever stage is showing now. Returns a function that cancels
// the re-sends still to come.
export function resendContext({ send, delays = RESEND_AFTER_MS, timer = setTimeout, clear = clearTimeout }) {
  const ids = delays.map((ms) => timer(async () => {
    try { await send(); } catch { /* the next re-send, or the next stage change, tries again */ }
  }, ms));
  return () => ids.forEach((id) => clear(id));
}
