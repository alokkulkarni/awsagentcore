# One copy of the sample bank's data

Every assistant and page now reads the same customers, accounts, cards and payments from one file:
**`connect-money-hub/moneyhub/data.py`**. Ask ARIA, the card dispute assistant, the Money Hub or the internet
banking app about James, and you get the same card endings, balances and payments.

Before this change, James's data was held in six places that disagreed. ARIA's customer tool gave him cards
ending 8901 and 3456, her credit card tool listed an M&S payment from March, and the dispute service listed
different payments again.

## What the file holds

| Data | Where it comes from |
|---|---|
| Current account | Six months of generated transactions (the Money Hub's own). The balance is the last row's. |
| Debit card payments | The current account's card payments (shopping, groceries, coffee, travel, subscriptions…). Never direct debits, salary or transfers. The 25 most recent are listed. |
| Credit card | Its own payments, limit, balance (the sum of its payments) and minimum payment. |
| Saver | Its opening balance, plus what the current account moves in, minus what comes back out. |
| Customers | Names, account and card endings, card BINs, mortgages. |

CUST-001 (James) and CUST-002 (Sarah) have generated current accounts. CUST-003 to CUST-005 have a fixed balance
and a fixed list of card payments.

**James, as everyone now sees him:**

| | |
|---|---|
| Current account | ending **0617**, £2,828.80 on 15 Oct 2026 |
| Instant access saver | ending **3390**, £5,150.00 |
| Visa debit card | ending **4821** (BIN 414900). Latest payment: AMAZON.CO.UK £32.45, 15 Oct |
| Mastercard credit card | ending **2291** (BIN 531908). Balance £1,406.59 of £5,000 |
| Mortgage | MR-\*\*\*\*-**8842**, £1,050 a month |

Payment IDs keep the dispute service's format, `TXN-<card ending>-<date>-<pence>`, so ARIA can name a payment and
the dispute assistant finds it.

## Which value won where they disagreed

- **Card endings 4821 / 2291:** ARIA's greeting, the dispute service and the app already agreed.
- **Account endings 0617 / 3390 / 8842:** the app's. A current account ending in the same digits as the debit card
  (ARIA's greeting said 4821 for both) was confusing.
- **Names:** the session injector's (CUST-003 is Margaret, not Michael).
- **Mortgage payment £1,050:** what the current account actually pays.
- **Credit card payments:** the dispute service's list, unchanged, because its scam and retailer scenarios use them.
- **Debit card payments:** the current account's own, so the Money Hub and the dispute assistant always agree.

## Who reads it

| Service | Lambda | How it gets the file |
|---|---|---|
| Money Hub page, agent, bridge | `aria-money-hub-*` | Already part of `moneyhub/`. Nothing it shows has changed. |
| Internet banking app | `connect-banking-app` | Already part of `moneyhub/` |
| Card dispute service | `aria-card-dispute` | `deploy_card_dispute.sh` copies it in |
| ARIA's account, card, customer, mortgage and spending tools | `aria-banking-mcp-*-prod` | `scripts/deploy_mcp_gateway.sh` copies it into each zip |
| Session injector (ARIA's greeting) | `aria-session-injector-qconnect` | `scripts/build_injector_zip.sh` |
| ID&V test harness, agent assist | their own Lambdas | Their deploy scripts copy it (they package the injector) |

`connect-money-hub/tests/test_bank_data.py` pins every figure the Money Hub shows, so adding to the bank can never
move them. `connect-banking-app/tests/test_one_bank.py` asks every service about James and checks they agree.

## Deploying it

All code-only. Nothing else about any function changes.

ARIA's card, mortgage and spending tools now take the customer's ID, and answer only for that customer's own cards,
accounts and mortgage. Before, they looked a card up by its digits alone, so naming another customer's card would
have shown their payments. ARIA must be sending the ID before the new tool code goes live, so do these in this order:

1. **The gateway's tool schemas** (adds `customer_id` to the four tools; today's Lambdas ignore it):
   `./scripts/deploy_mcp_gateway.sh update-targets --env prod --region eu-west-2`. It re-sends all ten targets'
   schemas, but I compared them with what's live: only these four tools change.
2. **ARIA**, if you haven't yet done the hand-over change
   (`connect-money-hub/docs/collaborator-setup.md`, "Hand-overs while ARIA has collaborators"):
   - publish the prompt;
   - add the flow's `nextStep` check;
   - run `connect_collaborator.sh --apply`. Her new version also has `customer_id` on the four tools.
   - Point the flow at the version it prints.
3. **ARIA's tools.** Update only the six that read the data:
   ```bash
   ./scripts/deploy_mcp_gateway.sh update-lambdas --env prod --region eu-west-2 \
       --only "account customer debit-card credit-card mortgage products"
   ```
   Without `--only` it would also redeploy the auth tool, whose local copy is newer than the one that's live.
   If you do this before step 2, ARIA's card, mortgage and spending questions get "customer_id is required"
   until her new version is in the flow.
4. **The dispute service:** `./connect-card-dispute/scripts/deploy_card_dispute.sh`.
5. **The session injector:** run `./scripts/build_injector_zip.sh`, then the `update-function-code` command it
   prints. Don't use the injector's old deploy script: it drops `CLI_MATCH_LOA=3`.
6. **The banking app:** `./connect-banking-app/scripts/deploy_banking_app.sh`.
7. **If you use them:** `deploy_idv_test_harness.sh` and `deploy_agent_assist.sh`. They package the injector, so
   they need the new copy too.
8. **The keypad card registry:** `python3 scripts/sync_customer_cards.py` shows the differences; add `--apply` to
   make them. Today it would:
   - add Sarah, Margaret, Daniel and Ethel's debit cards;
   - remove James's old card 8901;
   - remove the "fallback test record" `deploy_dtmf_lambda.sh` seeded: Sarah with a credit card ending 4821, a
     second customer with James's digits but a different BIN. Keep that row (don't use `--apply`, or add it back)
     if you still test the BIN check with it.

The Money Hub itself needs no redeploy.

## Things to know

- **Demo disputes made before this change** (4 in `aria-card-disputes`, on James's old Amazon £89.99 and Tesco
  £42.50 payments) still show, because each keeps its own payment details. Those payments no longer exist, so
  delete the drafts and start new ones.
- **ARIA's mortgage tool** finds the mortgage of the customer ARIA names. If she also gives a reference with
  digits (`MR-****-8842`, from the injector once step 5 is deployed), it must be that customer's.
- **Who the customer is** still comes from ARIA, as it always has for her account and customer tools. Connect can
  only fill a tool's inputs with fixed values, not session values. So the tools stop one customer naming another's
  card digits, but they rely on ARIA passing the right customer ID from her session context.
- **Not changed:**
  - `aria_auth_handler.py`: its names already match, and its dates of birth and mobiles are its own.
  - `scripts/lambdas/session_injector.py`: the older injector, not the one the flow uses.
  - `aria/tools/*`: the original Strands version of ARIA, not deployed.
  - The `deploy_dtmf_lambda.sh` seed, which only runs when it creates the table. Use the sync script instead.

## How to check it live

Start a chat from internet banking and ask ARIA:

1. "Show me my recent credit card transactions." She should list NETFLIX.COM £10.99, ELECTROWORLD ONLINE £349.00…,
   the same as the credit card on the Cards page.
2. "What's my current account balance?" She should say £2,828.80, the same as the Accounts page and the Money Hub.
3. "I don't recognise the £32.45 Amazon payment." The dispute assistant should find it straight away.
