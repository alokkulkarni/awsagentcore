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
 *      ("ARIA - Nationwide" while bot is active; agent name when transferred).
 *
 * Why MutationObserver?
 *   The Connect hosted widget injects chat message DOM nodes dynamically.
 *   A MutationObserver catches every new node the widget adds and renames
 *   participant labels before the customer sees them.
 *
 * The primary rename is done via `amazon_connect('customDisplayNames', ...)` in
 * index.html. This component's MutationObserver acts as a belt-and-braces catch
 * for any bubbles that appear before the SDK has applied the customDisplayNames setting.
 *
 * If the chat button does not appear, check:
 *   1. Browser console for CSP violations.
 *   2. That the snippetId in index.html matches your Connect instance's widget config.
 *   3. That this page's origin is on the Approved origins list in your Connect instance:
 *      Connect console → Instance → Approved origins → add http://localhost:4001
 */

import { useEffect } from 'react';

const PARTICIPANT_NAMES = {
  BOT:    'ARIA',
  SYSTEM: 'Nationwide',
};

const NAME_SELECTORS = [
  '[class*="participantName"]',
  '[class*="participant-name"]',
  '[class*="ParticipantName"]',
  '[data-testid="participant-name"]',
  '[class*="displayName"]',
  '[class*="senderName"]',
  '[class*="sender-name"]',
].join(',');

function renameParticipants(root = document.body) {
  root.querySelectorAll(NAME_SELECTORS).forEach(el => {
    const current = el.textContent.trim();
    if (PARTICIPANT_NAMES[current]) {
      el.textContent = PARTICIPANT_NAMES[current];
    }
  });

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const trimmed = node.textContent.trim();
    if (PARTICIPANT_NAMES[trimmed]) {
      node.textContent = node.textContent.replace(trimmed, PARTICIPANT_NAMES[trimmed]);
    }
  }
}

export default function ConnectChatWidget() {
  useEffect(() => {
    renameParticipants();

    const observer = new MutationObserver(mutations => {
      for (const mutation of mutations) {
        if (mutation.addedNodes.length > 0) {
          renameParticipants(document.body);
          break;
        }
      }
    });

    observer.observe(document.body, {
      subtree:   true,
      childList: true,
    });

    if (typeof window.amazon_connect === 'function') {
      window.amazon_connect('onChatConnected', () => { renameParticipants(); });
      window.amazon_connect('onAgentConnect',  () => { renameParticipants(); });
      window.amazon_connect('onChatDisconnected', () => {});
    }

    return () => observer.disconnect();
  }, []);

  return null;
}
