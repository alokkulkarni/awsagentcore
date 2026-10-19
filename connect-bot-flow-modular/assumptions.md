# Assumptions

1. **Modules can't read the calling flow's Lex or External attributes** (AWS: "Modules do not allow overriding flow
   local data of the invoking flow"). So the main flow copies ARIA's hand-back fields from Lex into contact
   attributes (`lexTool`, `lexNextStep`, `lexHandoverSummary`, `lexBuyerType`, `lexScreenCode`, `lexTopicCategory`,
   `lexEscalationReason`, `lexCustomerIntent`, `lexConversationSummary`) and sets `handbackOutcome` = `handback` or
   `error`. The decision module answers in `handbackRoute`. These are new contact attributes; the ones the
   destination flows read are set exactly as before.
2. **A Lex session attribute ARIA didn't send copies as an empty value**, as in the live flow's own Set blocks. If
   the copy fails, the turn is treated as a lost hand-back and the recovery Lambda is asked, as the live flow does
   on a Lex error.
3. **Disconnect works inside a module.** Contact setup and customer context hang up on a failure, as the live flow
   does.
4. **One Connect assistant block is enough.** The live flow's second one, before ARIA, had the same settings once
   the agent-assistance setting is gone. The session is created and saved on the contact before the injector, and
   ARIA's Lex block uses it. If ARIA doesn't greet with the customer's name in the first test, that's the place to
   look.
5. **Agent assist is set by the "ARIA agent assist" flow** on every route to a person (checked: card dispute
   assistant, Mortgage Live Sync handover and human handover all go through it).
6. **Module invocation failures are new paths.** Contact setup or customer context → disconnect (as any setup
   failure does today). The decision module → retry ARIA (as when the recovery Lambda fails after a Lex error).
7. **The live flow was read on 18 Oct 2026 at 06:57 UTC** (`reference/`). If you change the live flow, refresh it
   before trusting the equivalence test.
