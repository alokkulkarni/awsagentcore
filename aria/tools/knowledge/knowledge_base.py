"""Meridian Bank knowledge base — searchable articles on products, processes, and policies."""

from strands import tool
from aria.models.knowledge import KnowledgeArticle, KnowledgeSearchResponse

# ---------------------------------------------------------------------------
# Knowledge base articles
# ---------------------------------------------------------------------------
_ARTICLES: list[KnowledgeArticle] = [

    # ── Digital Wallets ──────────────────────────────────────────────────────

    KnowledgeArticle(
        article_id="KB-DW-001",
        title="Replacement Card and Digital Wallets (Apple Pay / Google Pay)",
        category="digital_wallet",
        summary=(
            "When a card is blocked and a replacement ordered, the new card has a new card number "
            "and will NOT automatically appear in any digital wallet. The customer must add it manually."
        ),
        content=(
            "When a debit or credit card is blocked (whether lost, stolen, or due to fraud), "
            "Meridian Bank issues a replacement card with a NEW card number, expiry date, and CVV. "
            "Because the card number changes, the replacement card cannot be automatically provisioned "
            "to any digital wallet (Apple Pay, Google Pay, Samsung Pay, Garmin Pay, or similar). "
            "\n\n"
            "The customer will need to add the replacement card to their digital wallet manually once "
            "the physical card arrives (within 5 working days). They can do this in two ways:\n"
            "1. Via the Meridian Bank mobile app: go to Cards > [select card] > Add to Apple Wallet "
            "   or Add to Google Pay. This is the fastest method as it supports in-app provisioning.\n"
            "2. Directly through Apple Wallet or Google Pay: open the Wallet app, tap the + button, "
            "   and follow the on-screen prompts to add the new Meridian card.\n"
            "\n"
            "Important: the old card in the wallet will be deactivated automatically as soon as the "
            "block is confirmed. Any contactless or in-app payments attempted with the old card details "
            "will be declined. The customer should remove the old card from their wallet to avoid confusion.\n"
            "\n"
            "If the customer had the card registered in a third-party app (e.g., Uber, Netflix, Amazon), "
            "they will also need to update the card details there once the new card arrives."
        ),
        self_service_channels=["mobile"],
        related_article_ids=["KB-DW-002", "KB-DW-003", "KB-CM-003"],
    ),

    KnowledgeArticle(
        article_id="KB-DW-002",
        title="Setting Up Apple Pay with a Meridian Bank Card",
        category="digital_wallet",
        summary="How to add a Meridian debit or credit card to Apple Pay via the mobile app or Wallet app.",
        content=(
            "Apple Pay is available on iPhone (iPhone 6 and later), Apple Watch, iPad, and Mac with Touch ID.\n"
            "\n"
            "Method 1 — Via the Meridian Bank mobile app (recommended):\n"
            "1. Open the Meridian Bank app and log in.\n"
            "2. Tap 'Cards' from the bottom navigation.\n"
            "3. Select the card you want to add.\n"
            "4. Tap 'Add to Apple Wallet'.\n"
            "5. Follow the on-screen prompts. You may be asked to verify using Face ID, Touch ID, "
            "   or a one-time passcode sent to your registered mobile number.\n"
            "6. Your card will be ready to use in Apple Pay within seconds.\n"
            "\n"
            "Method 2 — Via the Apple Wallet app:\n"
            "1. Open the Wallet app on your iPhone.\n"
            "2. Tap the + button (top right).\n"
            "3. Select 'Debit or Credit Card' and tap 'Continue'.\n"
            "4. Position your Meridian card in frame to scan, or enter details manually.\n"
            "5. Accept the Meridian Bank terms and conditions.\n"
            "6. Verify via the Meridian app, SMS, or a call to our automated line.\n"
            "\n"
            "Eligible cards: All active Meridian debit and credit cards.\n"
            "Cards that are frozen, blocked, or expired cannot be added to Apple Pay.\n"
            "There is no limit to the number of devices you can add your card to."
        ),
        self_service_channels=["mobile"],
        related_article_ids=["KB-DW-001", "KB-DW-003"],
    ),

    KnowledgeArticle(
        article_id="KB-DW-003",
        title="Setting Up Google Pay with a Meridian Bank Card",
        category="digital_wallet",
        summary="How to add a Meridian debit or credit card to Google Pay.",
        content=(
            "Google Pay is available on Android devices running Android 5.0 or later with NFC capability.\n"
            "\n"
            "Method 1 — Via the Meridian Bank mobile app (recommended):\n"
            "1. Open the Meridian Bank app and log in.\n"
            "2. Tap 'Cards' from the bottom navigation.\n"
            "3. Select the card you want to add.\n"
            "4. Tap 'Add to Google Pay'.\n"
            "5. Follow the on-screen prompts and verify your identity as requested.\n"
            "6. Your card will be provisioned to Google Pay within seconds.\n"
            "\n"
            "Method 2 — Via the Google Pay / Google Wallet app:\n"
            "1. Open Google Wallet on your Android device.\n"
            "2. Tap '+ Add to Wallet' and select 'Payment card'.\n"
            "3. Select 'New credit or debit card' and scan or enter your Meridian card details.\n"
            "4. Accept the terms and verify via the Meridian app or SMS passcode.\n"
            "\n"
            "Eligible cards: All active Meridian debit and credit cards.\n"
            "Cards that are frozen, blocked, or expired cannot be added to Google Pay."
        ),
        self_service_channels=["mobile"],
        related_article_ids=["KB-DW-001", "KB-DW-002"],
    ),

    # ── Card Management ───────────────────────────────────────────────────────

    KnowledgeArticle(
        article_id="KB-CM-001",
        title="Freezing and Unfreezing a Debit or Credit Card",
        category="card_management",
        summary=(
            "Customers can temporarily freeze their card via the mobile app or online banking. "
            "A freeze is reversible; a block (lost/stolen) is permanent."
        ),
        content=(
            "Freezing a card temporarily prevents all new transactions but does not cancel the card. "
            "It is useful if the customer cannot locate their card but is not yet sure it is lost or stolen. "
            "A frozen card can be unfrozen at any time.\n"
            "\n"
            "To freeze or unfreeze via mobile app:\n"
            "1. Log in to the Meridian Bank app.\n"
            "2. Tap 'Cards' and select the card.\n"
            "3. Tap 'Freeze card' or 'Unfreeze card' and confirm.\n"
            "   The change takes effect immediately.\n"
            "\n"
            "To freeze or unfreeze via online banking:\n"
            "1. Log in at meridianbank.co.uk.\n"
            "2. Go to 'Manage cards' under your account.\n"
            "3. Toggle the freeze switch for the relevant card.\n"
            "\n"
            "A frozen card cannot be used for purchases, ATM withdrawals, or contactless payments. "
            "However, scheduled direct debits and standing orders linked to the card will continue.\n"
            "\n"
            "If the customer confirms the card is lost or stolen, proceed to block the card — "
            "this is a permanent action and cannot be reversed. A replacement will be issued automatically."
        ),
        self_service_channels=["mobile", "web"],
        related_article_ids=["KB-CM-002", "KB-DW-001"],
    ),

    KnowledgeArticle(
        article_id="KB-CM-002",
        title="Lost or Stolen Debit Card — Full Process",
        category="card_management",
        summary=(
            "Blocking a lost/stolen debit card is permanent. A replacement is automatically ordered "
            "and arrives within 5 working days. Digital wallets must be re-set up with the new card."
        ),
        content=(
            "Step 1: Block the card\n"
            "The card can be blocked via:\n"
            "- ARIA (this service) — confirm last-four digits and the reason; ARIA will request confirmation "
            "  before proceeding.\n"
            "- Meridian Bank mobile app: Cards > [select card] > Block card > Lost or Stolen.\n"
            "- Online banking: meridianbank.co.uk > Manage cards > Block card.\n"
            "- Phone: 0161 900 9000 (24/7 lost and stolen line).\n"
            "\n"
            "Step 2: Replacement card\n"
            "A replacement card is automatically ordered when a block is confirmed. "
            "The new card will be delivered to the registered address within 5 working days. "
            "Expedited delivery is not currently available.\n"
            "\n"
            "Step 3: PIN\n"
            "The replacement card will arrive with the same PIN as the blocked card. "
            "If the customer believes their PIN was compromised, they can change it via the mobile app "
            "(Cards > [select card] > Change PIN) after activating the replacement card.\n"
            "\n"
            "Step 4: Digital wallets\n"
            "Because the replacement card has a new card number, it will NOT automatically be available "
            "in Apple Pay, Google Pay, or any other digital wallet. The customer must add the new card "
            "manually once it arrives — see KB-DW-001 for instructions.\n"
            "\n"
            "Step 5: Suspicious transactions\n"
            "If the customer suspects fraudulent transactions, they should report them via:\n"
            "- Mobile app: Transactions > [select transaction] > Report as fraud.\n"
            "- Phone: 0161 900 9001 (fraud reporting line, 24/7).\n"
            "The bank will investigate and may issue a refund subject to the outcome."
        ),
        self_service_channels=["mobile", "web", "phone"],
        related_article_ids=["KB-CM-001", "KB-CM-003", "KB-DW-001"],
    ),

    KnowledgeArticle(
        article_id="KB-CM-003",
        title="Lost or Stolen Credit Card — Full Process",
        category="card_management",
        summary=(
            "Blocking a lost/stolen credit card is permanent. Replacement takes 5 working days. "
            "Existing direct debits and minimum payments continue uninterrupted."
        ),
        content=(
            "The process is the same as for debit cards (see KB-CM-002), with the following differences:\n"
            "\n"
            "Direct debits and minimum payments:\n"
            "Any direct debits or automated minimum payments set up against the credit card account "
            "will continue to be collected from the underlying credit account — they are not linked to "
            "the physical card number. The customer does not need to update them.\n"
            "\n"
            "Subscriptions charged to the card number:\n"
            "Any recurring charges set up using the credit card number (e.g., Netflix, Spotify, Amazon) "
            "will fail after the old card is blocked. The customer must update their card details with "
            "each provider once the replacement card arrives.\n"
            "\n"
            "Digital wallets:\n"
            "Same as debit card — the new card must be manually added to Apple Pay or Google Pay. "
            "See KB-DW-001 for instructions.\n"
            "\n"
            "Disputing transactions on a blocked card:\n"
            "If there are unauthorised transactions on the blocked credit card, report them via "
            "the mobile app (Transactions > Report as fraud) or call 0161 900 9001."
        ),
        self_service_channels=["mobile", "web", "phone"],
        related_article_ids=["KB-CM-002", "KB-DW-001"],
    ),

    KnowledgeArticle(
        article_id="KB-CM-004",
        title="Changing Your Card PIN",
        category="card_management",
        summary="Card PIN changes are only available via the mobile app. Online banking does not support PIN changes.",
        content=(
            "To change your debit or credit card PIN:\n"
            "1. Log in to the Meridian Bank mobile app.\n"
            "2. Tap 'Cards' and select the relevant card.\n"
            "3. Tap 'Change PIN'.\n"
            "4. Authenticate using Face ID, Touch ID, or your app passcode.\n"
            "5. Enter your current PIN, then enter and confirm your new PIN.\n"
            "6. The change takes effect within a few seconds and will work at ATMs and point-of-sale.\n"
            "\n"
            "PIN changes are NOT available via online banking (meridianbank.co.uk).\n"
            "If the customer does not have the mobile app, they can change their PIN at any Meridian "
            "Bank ATM or by visiting a branch with valid ID."
        ),
        self_service_channels=["mobile", "branch"],
        related_article_ids=["KB-CM-001", "KB-CM-002"],
    ),

    KnowledgeArticle(
        article_id="KB-CM-005",
        title="Card Spending Controls and Limits",
        category="card_management",
        summary=(
            "Customers can set custom spending limits and controls (e.g., block gambling, "
            "overseas transactions) via the mobile app only."
        ),
        content=(
            "Meridian Bank mobile app spending controls (mobile only — NOT available on web):\n"
            "- Set or adjust the daily ATM withdrawal limit (up to the account maximum).\n"
            "- Set or adjust the daily contactless / point-of-sale limit.\n"
            "- Block or unblock specific merchant categories: gambling, adult content, "
            "  premium-rate services.\n"
            "- Block or unblock overseas / foreign currency transactions.\n"
            "- Receive instant push notifications for every transaction (mobile only).\n"
            "\n"
            "To access: Cards > [select card] > Spending controls.\n"
            "\n"
            "Changes take effect immediately. Online banking (web) shows the current limits "
            "but does not allow changes."
        ),
        self_service_channels=["mobile"],
        related_article_ids=["KB-CM-001"],
    ),

    # ── Payments ──────────────────────────────────────────────────────────────

    KnowledgeArticle(
        article_id="KB-PAY-001",
        title="Setting Up and Managing Standing Orders",
        category="payments",
        summary="Standing orders can be set up, amended, or cancelled via both online banking and the mobile app.",
        content=(
            "To set up a new standing order:\n"
            "Via mobile app: Payments > Standing orders > New standing order > "
            "enter payee sort code, account number, amount, frequency, and start date > Confirm.\n"
            "Via online banking: Payments > Standing orders > Add standing order > same details.\n"
            "\n"
            "To amend or cancel an existing standing order:\n"
            "Both channels: navigate to Payments > Standing orders > select the standing order > "
            "Edit or Cancel.\n"
            "\n"
            "Note: changes made before 4pm on a working day take effect the same day. "
            "Changes after 4pm take effect the next working day."
        ),
        self_service_channels=["mobile", "web"],
        related_article_ids=["KB-PAY-002"],
    ),

    KnowledgeArticle(
        article_id="KB-PAY-002",
        title="Managing Direct Debits",
        category="payments",
        summary=(
            "Direct debits can be viewed and cancelled via both channels. "
            "New direct debits must be set up with the originating company."
        ),
        content=(
            "Viewing direct debits:\n"
            "Both mobile app and online banking: Payments > Direct debits.\n"
            "\n"
            "Cancelling a direct debit:\n"
            "Via mobile app: Payments > Direct debits > [select] > Cancel direct debit.\n"
            "Via online banking: Payments > Direct debits > [select] > Cancel.\n"
            "\n"
            "Setting up a new direct debit:\n"
            "Direct debits can ONLY be set up by the company taking payment (the originator), "
            "not by the customer via online banking or the mobile app. The customer must provide "
            "their sort code and account number to the company.\n"
            "\n"
            "Note: cancelling a direct debit does not cancel the underlying contract or subscription "
            "with the company. The customer must notify the company separately."
        ),
        self_service_channels=["mobile", "web"],
        related_article_ids=["KB-PAY-001"],
    ),

    KnowledgeArticle(
        article_id="KB-PAY-003",
        title="International Payments (SWIFT/SEPA Transfers)",
        category="payments",
        summary=(
            "International payments can be made via online banking only. "
            "The mobile app supports domestic payments only."
        ),
        content=(
            "International payments (including SEPA and SWIFT transfers) are available via "
            "online banking at meridianbank.co.uk only.\n"
            "\n"
            "The mobile app supports UK domestic payments (Faster Payments and CHAPS) only. "
            "International transfers are NOT available in the mobile app.\n"
            "\n"
            "To make an international payment via online banking:\n"
            "1. Log in at meridianbank.co.uk.\n"
            "2. Go to Payments > International transfer.\n"
            "3. Enter the beneficiary IBAN, SWIFT/BIC code, amount, and currency.\n"
            "4. Review the exchange rate (indicative) and fees.\n"
            "5. Confirm with your security details.\n"
            "\n"
            "Fees: £15 per SWIFT transfer; SEPA (EUR to EU) £5. "
            "Exchange rates are shown before confirmation."
        ),
        self_service_channels=["web"],
        related_article_ids=["KB-PAY-001"],
    ),

    # ── Statements & Documents ────────────────────────────────────────────────

    KnowledgeArticle(
        article_id="KB-ST-001",
        title="Downloading and Viewing Statements",
        category="statements",
        summary="Statements are available via both online banking and the mobile app for the past 7 years.",
        content=(
            "Via online banking (meridianbank.co.uk):\n"
            "1. Log in and select your account.\n"
            "2. Click 'Statements' from the account menu.\n"
            "3. Select the date range or specific month.\n"
            "4. Download as PDF.\n"
            "\n"
            "Via mobile app:\n"
            "1. Log in and select your account.\n"
            "2. Tap 'Statements' (bottom of account screen).\n"
            "3. Select the statement and tap to view or share as PDF.\n"
            "\n"
            "Statements are available for the past 7 years.\n"
            "Paper statements: if the customer has opted out of paper statements, they can re-enable "
            "via Settings > Statements > Paper statements in both channels."
        ),
        self_service_channels=["mobile", "web"],
        related_article_ids=[],
    ),

    # ── Mortgage ──────────────────────────────────────────────────────────────

    KnowledgeArticle(
        article_id="KB-MORT-001",
        title="Making Mortgage Overpayments",
        category="mortgage",
        summary=(
            "Overpayments can be submitted via online banking or the mobile app, "
            "subject to the annual 10% overpayment allowance."
        ),
        content=(
            "Most Meridian Bank fixed-rate mortgages allow overpayments of up to 10% of the "
            "outstanding balance per year without an early repayment charge (ERC). "
            "Tracker mortgages have no overpayment limit.\n"
            "\n"
            "To make a one-off overpayment:\n"
            "Via online banking: Mortgage > Make overpayment > enter amount > Confirm.\n"
            "Via mobile app: Mortgage > Overpayment > enter amount > Confirm.\n"
            "\n"
            "To set up a regular monthly overpayment:\n"
            "Via online banking or mobile app: Mortgage > Regular overpayment > set amount and start date.\n"
            "\n"
            "Overpayments above the annual allowance on a fixed-rate mortgage will incur an ERC. "
            "Check your current allowance under Mortgage > Overpayment allowance in either channel before submitting."
        ),
        self_service_channels=["mobile", "web"],
        related_article_ids=[],
    ),

    # ── Account Management ────────────────────────────────────────────────────

    KnowledgeArticle(
        article_id="KB-ACC-001",
        title="Updating Contact Details (Address, Mobile Number, Email)",
        category="account_management",
        summary="Contact details can be updated via online banking or the mobile app. Branch visit required for name changes.",
        content=(
            "Via online banking or mobile app:\n"
            "Settings > Personal details > edit address, mobile number, or email.\n"
            "A verification code will be sent to the existing mobile or email to confirm the change.\n"
            "\n"
            "Address changes: available on both web and mobile.\n"
            "Mobile number changes: available on both web and mobile. The old number receives a "
            "confirmation SMS before the change takes effect.\n"
            "Email changes: available on both web and mobile.\n"
            "\n"
            "Name changes (e.g., after marriage or deed poll): "
            "must be done in branch with original documentation (marriage certificate, deed poll, "
            "or court order). Name changes cannot be processed by phone or online."
        ),
        self_service_channels=["mobile", "web", "branch"],
        related_article_ids=[],
    ),

    KnowledgeArticle(
        article_id="KB-ACC-002",
        title="Biometric Login (Face ID / Fingerprint) — Mobile App Only",
        category="account_management",
        summary="Biometric login is available on the mobile app only. Online banking uses password + OTP.",
        content=(
            "The Meridian Bank mobile app supports Face ID (iOS) and fingerprint authentication (Android "
            "and iOS Touch ID) for secure login without entering a password.\n"
            "\n"
            "To enable biometric login:\n"
            "1. Log in to the Meridian Bank app with your password.\n"
            "2. Go to Settings > Security > Biometric login.\n"
            "3. Toggle on and authenticate with your device biometric to confirm.\n"
            "\n"
            "Biometric login is NOT available on online banking (meridianbank.co.uk), which uses "
            "username + password + one-time passcode (OTP) via SMS or authenticator app.\n"
            "\n"
            "If biometric login fails 3 times, the app falls back to the full password login."
        ),
        self_service_channels=["mobile"],
        related_article_ids=[],
    ),
]

# Build lookup maps for fast search
_BY_ID: dict[str, KnowledgeArticle] = {a.article_id: a for a in _ARTICLES}
_BY_CATEGORY: dict[str, list[KnowledgeArticle]] = {}
for _a in _ARTICLES:
    _BY_CATEGORY.setdefault(_a.category, []).append(_a)

# Keyword → article ID mapping for soft search
_KEYWORDS: dict[str, list[str]] = {
    "apple pay": ["KB-DW-001", "KB-DW-002"],
    "apple wallet": ["KB-DW-001", "KB-DW-002"],
    "google pay": ["KB-DW-001", "KB-DW-003"],
    "google wallet": ["KB-DW-001", "KB-DW-003"],
    "digital wallet": ["KB-DW-001", "KB-DW-002", "KB-DW-003"],
    "wallet": ["KB-DW-001", "KB-DW-002", "KB-DW-003"],
    "contactless": ["KB-DW-001", "KB-CM-001"],
    "replacement card": ["KB-DW-001", "KB-CM-002"],
    "replaced card": ["KB-DW-001", "KB-CM-002"],
    "new card": ["KB-DW-001", "KB-CM-002"],
    "block card": ["KB-CM-002", "KB-CM-003"],
    "blocked card": ["KB-DW-001", "KB-CM-002"],
    "freeze": ["KB-CM-001"],
    "unfreeze": ["KB-CM-001"],
    "lost card": ["KB-CM-002"],
    "stolen card": ["KB-CM-002"],
    "lost debit": ["KB-CM-002"],
    "stolen debit": ["KB-CM-002"],
    "lost credit": ["KB-CM-003"],
    "stolen credit": ["KB-CM-003"],
    "pin": ["KB-CM-004"],
    "change pin": ["KB-CM-004"],
    "spending controls": ["KB-CM-005"],
    "limits": ["KB-CM-005"],
    "gambling block": ["KB-CM-005"],
    "standing order": ["KB-PAY-001"],
    "direct debit": ["KB-PAY-002"],
    "international payment": ["KB-PAY-003"],
    "international transfer": ["KB-PAY-003"],
    "swift": ["KB-PAY-003"],
    "sepa": ["KB-PAY-003"],
    "statement": ["KB-ST-001"],
    "statements": ["KB-ST-001"],
    "overpayment": ["KB-MORT-001"],
    "mortgage overpayment": ["KB-MORT-001"],
    "contact details": ["KB-ACC-001"],
    "update address": ["KB-ACC-001"],
    "change address": ["KB-ACC-001"],
    "change email": ["KB-ACC-001"],
    "change mobile": ["KB-ACC-001"],
    "biometric": ["KB-ACC-002"],
    "face id": ["KB-ACC-002"],
    "fingerprint": ["KB-ACC-002"],
    "touch id": ["KB-ACC-002"],
}


def _search(query: str) -> list[KnowledgeArticle]:
    """Return articles matching the query by keyword, then category."""
    q = query.lower().strip()
    matched_ids: list[str] = []

    # Keyword scan (longest match first to prefer specific phrases)
    for kw in sorted(_KEYWORDS.keys(), key=len, reverse=True):
        if kw in q:
            for aid in _KEYWORDS[kw]:
                if aid not in matched_ids:
                    matched_ids.append(aid)

    # Category fallback
    for cat in _BY_CATEGORY:
        if cat.replace("_", " ") in q or cat in q:
            for art in _BY_CATEGORY[cat]:
                if art.article_id not in matched_ids:
                    matched_ids.append(art.article_id)

    return [_BY_ID[aid] for aid in matched_ids if aid in _BY_ID]


@tool
def search_knowledge_base(query: str) -> dict:
    """
    Search the Meridian Bank internal knowledge base for policies, processes, and how-to guidance.

    ALWAYS call this tool BEFORE telling a customer "I cannot help with that" for any
    service-related question. Use it to find official guidance on:
    - Digital wallets: Apple Pay, Google Pay, wallet setup after card replacement
    - Card management: freeze/unfreeze, lost/stolen process, PIN changes, spending controls
    - Payments: standing orders, direct debits, international transfers
    - Statements and documents
    - Mortgage overpayments
    - Account management: updating contact details, biometric login

    Pass a natural-language query (e.g. "replacement card apple pay", "freeze card",
    "standing order setup", "PIN change", "international payment").

    The response includes:
    - matched: bool — whether any articles were found
    - articles: list of relevant articles, each with title, summary, content, and self_service_channels
    - suggestion: guidance hint if no articles matched

    If matched is True:
    - Use the article content to answer the customer's question accurately.
    - Tell the customer which self_service_channels they can use (web, mobile, branch, phone).
    - Be specific about which channel supports the journey — do not say "online banking or the app"
      if the feature is only available on one of them.

    If matched is False:
    - Do NOT fabricate an answer.
    - On voice channel: offer to connect the customer with a colleague.
    - On chat channel: direct the customer to online banking, the mobile app, or the support number.
    """
    articles = _search(query)
    if articles:
        return KnowledgeSearchResponse(
            query=query,
            matched=True,
            articles=articles,
        ).model_dump()

    return KnowledgeSearchResponse(
        query=query,
        matched=False,
        articles=[],
        suggestion=(
            "No knowledge base article matched this query. "
            "If this is a service or product question, consider whether it falls under card management, "
            "payments, digital wallets, statements, mortgage, or account management. "
            "If genuinely out of scope, apply the channel-appropriate out-of-scope response."
        ),
    ).model_dump()
