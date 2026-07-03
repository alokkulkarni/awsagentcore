# Microsoft Teams Integration — Specification

**Status:** Phase 1 in progress · **Branch family:** `feature/teams-integration-*` · **Date:** 2026-07-03

## Goal

Embed a Microsoft Teams experience inside the Real-Time Command Centre the same way
the Amazon Connect CCP is embedded for supervisor monitor/barge: a panel the
supervisor opens from the dashboard, signed in with their own Microsoft 365
identity, without leaving the page. Primary use cases, in value order:

1. **Reachability** — see each agent's Teams presence directly in the Agent Roster
   (is the person actually available, in a call, DND?).
2. **Chat** — read and send Teams chats from a dashboard panel (e.g. nudge an agent
   who has been on a call for 25 minutes).
3. **Calls** — start a Teams call with an agent (deep-link first; in-panel calling
   is a later phase).

## Hard constraint (why this is not an iframe)

`teams.microsoft.com` refuses to be framed (CSP `frame-ancestors`) and Microsoft
ships no embeddable Teams client equivalent to Connect's `ccp-v2` +
`amazon-connect-streams`. The sanctioned approach is to build our own Teams
surface against Microsoft's APIs:

- **Auth:** MSAL.js in the browser (`@azure/msal-browser`), popup sign-in,
  delegated permissions. Tokens never touch our backend.
- **Chat + presence:** Microsoft Graph REST (`/me/chats`, `/chats/{id}/messages`,
  `/communications/getPresencesByUserId`), polled — consistent with the
  dashboard's existing polling model.
- **Calling (later):** Azure Communication Services UI Library (CallComposite)
  with Teams interop, or deep-links into the Teams client.

## Architecture

```
RealtimeCommandCenter ── "Teams" button (unread badge)
        │
        ▼
  TeamsPanel (slide-over, same pattern as Contact Detail)
        │ uses
        ▼
  services/teams.js  ──  provider selection at runtime:
        ├─ MockTeamsProvider    (dashboard mock mode ON — no network)
        ├─ GraphTeamsProvider   (VITE_TEAMS_CLIENT_ID + VITE_TEAMS_TENANT_ID set)
        └─ unconfigured         (real mode, no Entra IDs — setup hint shown)

  AgentRoster ── presence dots + "chat in Teams" deep-link per agent
                 (presence via the same provider)
```

Mock-first: every feature works fully in dummy-data mode with simulated chats and
presence derived from the fleet simulation, so the experience can be demoed and
tested with zero Microsoft configuration. Real mode lights up when the two Entra
IDs are provided at build time.

## Prerequisites (owner: you — cannot be automated from here)

Entra ID (Azure AD) **app registration** in your tenant:

| Setting | Value |
|---|---|
| Platform | Single-page application (SPA) |
| Redirect URIs | `http://localhost:5274`, `https://<cloudfront-domain>` |
| Delegated Graph permissions | `User.Read`, `Chat.ReadWrite`, `Presence.Read.All` |
| Consent | Admin consent for `Presence.Read.All` (others are user-consentable) |

Outputs → frontend env (config, not secrets): `VITE_TEAMS_CLIENT_ID`,
`VITE_TEAMS_TENANT_ID` (compose passes them through; Vite bakes at build).

## Security notes

- Delegated-only: the dashboard can do nothing in Teams the signed-in supervisor
  cannot do themselves. No app secrets exist in this design; client/tenant IDs are
  public identifiers.
- Tokens live in MSAL's session storage in the browser; sign-out clears them.
- No Teams message content is sent to our backend, logged, or stored.
- Mock mode makes zero Microsoft network calls.

## Phases

### Phase 1 — Panel + chat + roster presence, mock-first (PR: `feature/teams-integration-phase1`)

- `frontend/src/services/teams.js`: provider interface
  (`getState`, `signIn`, `signOut`, `listChats`, `listMessages`, `sendMessage`,
  `getPresence(names→state)`), Mock + Graph implementations, provider selection.
- `frontend/src/components/TeamsPanel.jsx`: slide-over with sign-in state, chat
  list (latest message + relative time), thread view, composer; 5s poll while
  open; unread count surfaced to the header button.
- `RealtimeCommandCenter`: header "Teams" button with unread badge.
- `AgentRoster`: Teams presence dot per agent + deep-link chat button
  (`https://teams.microsoft.com/l/chat/0/0?users=<email>`) when an email is known
  (mock: synthetic; real: agent username when it is an email).
- Graph provider implemented and env-gated but **untested against a real tenant**
  in this phase (no Entra app yet).

**Acceptance:** in mock mode — open panel, read/send simulated chats, see
presence dots in roster, unread badge updates; `npm run build` clean; no backend
changes required.

### Phase 2 — Real-tenant hardening (PR: `feature/teams-integration-phase2`)

Requires the Entra app registration. Token refresh + `interaction_required`
recovery, Graph throttling/backoff (429 `Retry-After`), delta queries for chat
messages, batched presence (`getPresencesByUserId` ≤ 650 IDs), agent→M365 user
mapping review, error surfaces, sign-out UX, optional backend `/config/teams` so
IDs can come from the server instead of build-time env.

### Phase 3 (optional) — In-panel calling

ACS resource + backend token service + CallComposite with Teams interop, or stay
with deep-links if the client-pop UX is acceptable. Decide after Phase 2 usage.

## Out of scope

Posting alerts INTO Teams channels (webhook/bot notification path), dashboard as
a Teams tab, and bot-based two-way AI chat — all valid, separately specced if
wanted; they share the Entra app registration.
