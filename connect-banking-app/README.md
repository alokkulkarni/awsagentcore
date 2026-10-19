# Internet banking app (Nationwide Building Society demo)

A realistic, responsive internet banking app that brings three working journeys together behind **one
assistant**. The assistant is chat, a call, and on calls a real-looking face. It knows which page you're on, so
the right assistant helps:

| You're on | Chat or call reaches | What happens |
|---|---|---|
| **Money Hub** (any tab) | ARIA → the **Money Hub agent** | Exactly as on the Money Hub page: same figures, goals saved while you talk |
| **Mortgages** / the **application form** | The **mortgage assistant** (Agentic CX designer) | It fills in the form with you through Live Sync, moves between stages and highlights. Fields it fills are marked |
| **Cards** → "Dispute" on a payment | ARIA verifies you → the **card dispute assistant** | When it sends its form (texted on a call, posted in a chat), the app opens it itself on **Cards › Your disputes**, joined to your conversation, and it fills in as you talk |
| **Home, Accounts, Help** | **ARIA** on its own | |

> **Demo.** Sample data only (James, `CUST-001`), with a banner saying so on every page. There is no username or
> password screen: it opens from a link, and that link stands for James signed in to internet banking. So the
> link is verified (Level 2), and a chat or call from **any** page arrives verified, with that page's context:
> ARIA doesn't ask him to prove who he is again. Anyone holding the link is treated as James: sample data only.

## Contents

- [What it reuses, unchanged](#what-it-reuses-unchanged)
- [How the assistant knows where you are](#how-the-assistant-knows-where-you-are)
- [Try it on your laptop](#try-it-on-your-laptop)
- [Deploy it](#deploy-it)
- [Test it](#test-it)
- [Things to know](#things-to-know)
- [What is in this folder](#what-is-in-this-folder)

## What it reuses, unchanged

Nothing in `connect-money-hub/`, `connect-card-dispute/` or the mortgage repo is changed by this app.

| From | What | How |
|---|---|---|
| `connect-money-hub` | The Money Hub API (`api/money_api.py`) and `moneyhub/` | Packaged with this app. The same DynamoDB table, so the app, the Money Hub page and the Money Hub agent always agree. Links, goals, call transcripts and the face work exactly as on the Money Hub page |
| Mortgage Live Sync (`connect-livesync-mortgage`) | Its form modules (`web/mortgage/`: actions, stages, field rules, review, help code, Touchpoint binding) | Copied unchanged. Its deployed backend is called for submit and help codes through its **IAM door**, and its Live Sync keys come from its own secret |
| `connect-card-dispute` | Its form's field rules, Live Sync binding and rows; its sample cards (`dispute_model.py`) | Copied or packaged unchanged. Its deployed service saves the form, exactly as its own page does |
| Connect | "conversation bot flow", ARIA, the ACXD applications | Nothing changes. Mortgage calls use the flow's existing **Point B** (`entry=web_widget`) |

## How the assistant knows where you are

Each page tells the widget its context. When you start a chat or call, the app's Lambda adds what that journey
expects to the contact (`bankapp/journeys.py`). **Who you are always comes from the link's record on the server,
never from the browser.**

```
Money Hub page    entry=money_hub, moneyHubView=<tab>            → session injector → ARIA → Money Hub agent
Mortgage form     entry=web_widget, applicationId, stage         → conversation bot flow, Point B → mortgage assistant
                  then Touchpoint binds headless ("external") to that contact: Live Sync fills the form
Card dispute      entry=card_dispute, handoverSummary, preferredName
                                                                 → conversation bot flow → dispute assistant
                  (needs the one flow change below; chat opens with "I'd like to dispute <the payment you chose>")
                  an unverified link sends entry=banking_app instead, so ARIA checks who you are first
Anything else     entry=banking_app, appPage=<page>              → ARIA
```

A link minted at Level 2 or above adds the verified fields (`customerId`, `authStatus`, `LoA` …), as the Money Hub
page does, and only then does a mortgage contact carry your `customerId`. The app's own demo link is always Level 2
(it's the signed-in session); `--unverified-demo` makes one that isn't, for testing ARIA's ID check.

### The one flow change disputes need

Choosing **Dispute** next to a card payment sends the contact straight to the card dispute assistant, the same way
the mortgage form reaches the mortgage assistant. It doesn't wait for ARIA to decide to hand over. The app
sends the payment you chose as `handoverSummary` (from the server's own record, never the browser's) and your first
name as `preferredName`, which are the two things the dispute assistant reads from ARIA's hand-over.

In the Connect admin website, open **Routing → Flows → conversation bot flow**:

1. Find the **Check contact attributes** block that checks `entry` (the one with the `web_widget` branch to
   "Mortgage Live Sync handover").
2. Add a condition: **Equals** `card_dispute`.
3. Add a **Set contact attributes** block after that new branch. Set one attribute: **Key** `entry`, **Value**
   `aria` (the value the dispute assistant expects). Don't set `handoverSummary` here: the app already sent it.
4. Connect its **Success** to the existing **Transfer to flow** block for "Card dispute assistant". Don't go
   through the Set contact attributes block that sits before it: it copies `handoverSummary` from Lex, which
   is empty here, and would wipe the app's.
5. Connect **Error** to the same Transfer to flow block. Then **Save** and **Publish**.

Until that's published, a dispute contact falls through to ARIA as before. The session injector tells her it's a
card dispute (`_banking_app_reason_vars` in `scripts/lambdas/session_injector_qconnect.py`, deployed as code
only: zip plus `update-function-code` for `aria-session-injector-qconnect`).

**Asking ARIA about a payment** from any page (or on the phone) works too: she verifies the customer and
hands over with her Complete tool (`nextStep` = `card_dispute`), and the flow sends them to the dispute
assistant. That needs the change in `connect-money-hub/docs/collaborator-setup.md`, "Hand-overs while ARIA has
collaborators": while ARIA has the Money Hub collaborator, her old `StartCardDispute` tool can't hand anyone
over. The dispute assistant can only find payments the card dispute service holds, which are the ones listed on
Cards.

## Try it on your laptop

```bash
python3 connect-banking-app/scripts/local_preview.py
```

Open the link it prints. Everything works on sample data except the assistant (no AWS is touched). Add
`--talk INSTANCE_ID FLOW_ID` for real chats and calls (and the face, using `connect-money-hub/.env`), and
`--partners` for the real mortgage and dispute services, both with your AWS credentials.

## Deploy it

You run this (it changes your AWS account; `--dry-run` first shows what it would do):

```bash
./connect-banking-app/scripts/deploy_banking_app.sh --approve-origin
```

It reads the Money Hub, mortgage and dispute settings from their own deployments and changes none of them. It:
1. creates the role `aria-banking-app-role` and the Lambda `aria-banking-app`;
2. creates the HTTP API `aria-banking-app-pages`;
3. with `--approve-origin`, adds the app's address to the Connect instance's approved origins (needed for chat
   and calls);
4. tests the app and prints a demo link.

The demo link is verified (signed in). Add `--unverified-demo` for one that isn't, to test ARIA's own ID check.

If the mortgage or dispute ACXD application limits which websites may use its Live Sync keys, add the app's
address there too.

## Test it

```bash
cd connect-banking-app && python3 -m unittest discover -s tests
```

Then, on the deployed app:

| Try | You should see |
|---|---|
| Home, Accounts, Cards, Money Hub on a phone | A tab bar at the bottom; "Ask us anything" above it, changing with the page |
| Money Hub → chat "where does my money go?" | The Money Hub agent answers with your figures |
| Mortgages → Call | The form opens; the mortgage assistant fills in fields as you answer, each marked "Filled by assistant"; the face on video |
| Cards → Dispute on a payment → Chat | ARIA, then the dispute assistant; when it shares the form, **Open the form here** opens it in the app and it fills in |
| Mortgage form → Get a help code, then phone the number | The call binds to your form, as on the mortgage page |

## Things to know

- **Live Sync on chat.** The mortgage docs only show headless Touchpoint on calls. The app binds on chats too;
  if Live Sync doesn't pick up a chat, the chat still works but only calls fill the form.
- **Captions on mortgage and dispute calls.** Call captions come from ARIA's session in Q in Connect. ACXD
  assistants' turns aren't stored there, so those calls may show no captions. Chats are unaffected.
- **Disputes.** Cards › **Your disputes** and Help list your disputes (from the dispute service's own table).
  During any conversation the app watches for the dispute assistant sending its form since that conversation
  began. When it does, the app opens the form itself, joined to its own call or chat, using the dispute service's
  own code (`mint_form_link`, `open_form_link`), as if you'd opened the texted link. It still texts the link too.
  A form sent before this conversation never opens by itself.
- **Security policy.** Scripts only from the app itself and Daily (the face's room), plus `'wasm-unsafe-eval'` for
  the Touchpoint SDK, as the mortgage page allows. Inline styles stay blocked; they belong to Touchpoint's own
  widget, which the headless binding never shows.

## What is in this folder

| Path | What it is |
|---|---|
| `api/banking_api.py` | The Lambda: the app, its API, and the reused Money Hub routes |
| `bankapp/journeys.py` | Which assistant a page reaches, and its contact attributes |
| `bankapp/home.py`, `products.py` | The account figures (from the Money Hub and dispute data) and the mortgage products |
| `bankapp/partners.py` | The mortgage and dispute services, and their Live Sync keys |
| `bankapp/disputes.py` | Your disputes, and opening a dispute's form joined to the app's own conversation |
| `web/index.html`, `app.js`, `lib.js`, `styles.css` | The app shell, router and page templates |
| `web/pages/` | One module per page |
| `web/widget/` | The assistant: chat, call, the face, message layout (from the Money Hub, made page-aware) |
| `web/mortgage/`, `web/dispute/` | The mortgage and dispute form code (copied unchanged), this app's mortgage UI adapter, and the dispute form and list as they appear in Cards |
| `scripts/` | `build_vendor.sh` (Chime, Daily, Touchpoint 1.0.1), `local_preview.py`, `deploy_banking_app.sh` |
| `tests/` | Which assistant each page reaches, identity, partner calls, the security policy |
