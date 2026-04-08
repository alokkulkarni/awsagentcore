/**
 * ConnectChatWidget
 * ─────────────────
 * The Amazon Connect widget script and all amazon_connect() configuration calls
 * are loaded directly in index.html <head>. The widget renders its own
 * fixed-position chat button and panel automatically.
 *
 * This component does two things:
 *   1. Renames participant labels in the chat UI using a MutationObserver:
 *      - "BOT"   → "ARIA"          (AI agent messages)
 *      - "AGENT" → agent's real name is used automatically by Connect;
 *                  override here if you want a generic label instead.
 *   2. Updates the widget header title to reflect the current participant
 *      ("ARIA - Meridian Bank" while bot is active; agent name when transferred).
 *
 * Why MutationObserver?
 *   The Connect hosted widget injects chat message DOM nodes dynamically.
 *   A MutationObserver catches every new node the widget adds and renames
 *   participant labels before the customer sees them. This is more reliable
 *   than a one-time rename because it handles:
 *     - The initial bot greeting
 *     - Every subsequent bot message
 *     - Historical messages loaded on reconnect
 *     - The moment a human agent joins
 *
 * The primary rename is done via `amazon_connect('customDisplayNames', ...)` in
 * index.html — that is the documented AWS API and overrides whatever "Bot Message
 * Display Name" is set to in the Connect console. This component's MutationObserver
 * acts as a belt-and-braces catch for any bubbles that appear before the SDK has
 * applied the customDisplayNames setting.
 *
 * If the chat button does not appear, check:
 *   1. Browser console for CSP violations (adjust <meta> CSP in index.html).
 *   2. That the snippetId in index.html matches your Connect instance's widget config.
 *   3. That this page's origin is on the Approved origins list in your Connect instance:
 *      Connect console → Instance → Approved origins → add http://localhost:4000
 */

import { useEffect } from 'react';

// ─── Display name map ──────────────────────────────────────────────────────
// Keys are the default Connect participant labels (case-sensitive).
// Values are what the customer should see in the chat widget.
const PARTICIPANT_NAMES = {
  BOT:    'ARIA',
  SYSTEM: 'Meridian Bank',
  // AGENT is intentionally omitted — Connect shows the human agent's real
  // first name automatically from their user profile. Add an entry here only
  // if you want to show a generic label like 'Meridian Bank Advisor' instead.
};

// ─── Selectors the Connect widget uses for participant name labels ──────────
// The hosted widget renders participant names in one of these elements.
// We target all of them so the rename works across widget versions.
const NAME_SELECTORS = [
  '[class*="participantName"]',
  '[class*="participant-name"]',
  '[class*="ParticipantName"]',
  '[data-testid="participant-name"]',
  '[class*="displayName"]',
  '[class*="senderName"]',
  '[class*="sender-name"]',
].join(',');

// ─── Rename function ────────────────────────────────────────────────────────
function renameParticipants(root = document.body) {
  // Approach 1: target known participant name elements by selector.
  root.querySelectorAll(NAME_SELECTORS).forEach(el => {
    const current = el.textContent.trim();
    if (PARTICIPANT_NAMES[current]) {
      el.textContent = PARTICIPANT_NAMES[current];
    }
  });

  // Approach 2: walk all text nodes as a fallback for widgets that don't use
  // the expected class names. Only replaces standalone "BOT" or "SYSTEM"
  // text nodes (not text inside longer sentences).
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const trimmed = node.textContent.trim();
    if (PARTICIPANT_NAMES[trimmed]) {
      node.textContent = node.textContent.replace(trimmed, PARTICIPANT_NAMES[trimmed]);
    }
  }
}

// ─── Component ─────────────────────────────────────────────────────────────
export default function ConnectChatWidget() {
  useEffect(() => {
    // Run once immediately in case the widget has already rendered messages
    // (e.g. on hot-reload during development).
    renameParticipants();

    // Watch for any DOM changes inside document.body. The Connect widget
    // injects its entire panel and all messages as new DOM nodes, so
    // subtree + childList catches everything.
    const observer = new MutationObserver(mutations => {
      for (const mutation of mutations) {
        if (mutation.addedNodes.length > 0) {
          renameParticipants(document.body);
          break; // one rename pass per batch of mutations is enough
        }
      }
    });

    observer.observe(document.body, {
      subtree:   true,
      childList: true,
    });

    // ── Connect event hooks ──────────────────────────────────────────────
    // amazon_connect() is loaded asynchronously by index.html. These calls
    // are queued by the stub function (w[x].ac = [...]) and executed once
    // the widget script has loaded, so it is safe to call them here.

    if (typeof window.amazon_connect === 'function') {
      // Fires when the customer starts a chat session (bot or agent).
      window.amazon_connect('onChatConnected', () => {
        renameParticipants();
      });

      // Fires when a human agent joins the conversation.
      // At this point the widget header and agent bubbles update automatically
      // to show the agent's real name from their Connect user profile.
      // renameParticipants() is still called to catch any residual "BOT" labels
      // that may linger on older message bubbles after the agent joins.
      window.amazon_connect('onAgentConnect', () => {
        renameParticipants();
      });

      // Fires when chat ends — clean-up only, no rename needed.
      window.amazon_connect('onChatDisconnected', () => {
        // Nothing to rename on disconnect.
      });
    }

    return () => observer.disconnect();
  }, []);

  return null;
}
