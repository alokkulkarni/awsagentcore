"""Meridian Bank channel feature parity — which journeys are available on web vs mobile app."""

from strands import tool
from aria.models.knowledge import ChannelFeature, FeatureParityResponse

# ---------------------------------------------------------------------------
# Feature parity data
# ---------------------------------------------------------------------------
_FEATURES: list[ChannelFeature] = [

    # ── Account & Balance ─────────────────────────────────────────────────────
    ChannelFeature(
        feature_id="FP-ACC-001",
        feature_name="View account balance",
        feature_area="account",
        available_web=True,
        web_journey="Log in > select account > balance shown on account overview screen.",
        available_mobile=True,
        mobile_journey="Log in > tap account tile on home screen > balance shown immediately.",
    ),
    ChannelFeature(
        feature_id="FP-ACC-002",
        feature_name="View transaction history",
        feature_area="account",
        available_web=True,
        web_journey="Log in > select account > Transactions tab.",
        available_mobile=True,
        mobile_journey="Log in > tap account > scroll through transaction feed.",
    ),
    ChannelFeature(
        feature_id="FP-ACC-003",
        feature_name="Download / view statements",
        feature_area="account",
        available_web=True,
        web_journey="Log in > select account > Statements > choose date range > download PDF.",
        available_mobile=True,
        mobile_journey="Log in > tap account > Statements > select and view or share as PDF.",
    ),
    ChannelFeature(
        feature_id="FP-ACC-004",
        feature_name="Update contact details (address, email, mobile)",
        feature_area="account",
        available_web=True,
        web_journey="Log in > Settings > Personal details > edit field > verify via OTP.",
        available_mobile=True,
        mobile_journey="Log in > Settings > Personal details > edit field > verify via OTP.",
        notes="Name changes require a branch visit with original documentation.",
    ),
    ChannelFeature(
        feature_id="FP-ACC-005",
        feature_name="Biometric login (Face ID / fingerprint)",
        feature_area="account",
        available_web=False,
        available_mobile=True,
        mobile_journey="Log in > Settings > Security > Biometric login > toggle on and authenticate.",
        notes="Online banking uses username + password + one-time passcode (OTP) only.",
    ),
    ChannelFeature(
        feature_id="FP-ACC-006",
        feature_name="Push notifications for transactions",
        feature_area="account",
        available_web=False,
        available_mobile=True,
        mobile_journey="Settings > Notifications > toggle on transaction alerts.",
        notes="Email transaction alerts are available via online banking (web) as an alternative.",
    ),

    # ── Card Management ───────────────────────────────────────────────────────
    ChannelFeature(
        feature_id="FP-CM-001",
        feature_name="View card details (masked)",
        feature_area="card_management",
        available_web=True,
        web_journey="Log in > Cards > select card > card details shown masked.",
        available_mobile=True,
        mobile_journey="Log in > Cards > select card > card details shown masked; biometric to reveal full number.",
        notes="Full card number reveal via biometric is mobile app only.",
    ),
    ChannelFeature(
        feature_id="FP-CM-002",
        feature_name="Freeze / unfreeze card",
        feature_area="card_management",
        available_web=True,
        web_journey="Log in > Manage cards > select card > toggle Freeze.",
        available_mobile=True,
        mobile_journey="Log in > Cards > select card > Freeze card toggle.",
    ),
    ChannelFeature(
        feature_id="FP-CM-003",
        feature_name="Block card (lost or stolen)",
        feature_area="card_management",
        available_web=True,
        web_journey="Log in > Manage cards > select card > Block card > choose reason > confirm.",
        available_mobile=True,
        mobile_journey="Log in > Cards > select card > Block card > Lost or Stolen > confirm.",
        available_phone=True,
        notes="ARIA (this service) can also block cards after verbal confirmation.",
    ),
    ChannelFeature(
        feature_id="FP-CM-004",
        feature_name="Change card PIN",
        feature_area="card_management",
        available_web=False,
        available_mobile=True,
        mobile_journey="Log in > Cards > select card > Change PIN > authenticate with biometric or app passcode.",
        available_branch=True,
        notes=(
            "PIN changes are NOT available via online banking. "
            "Customers can also change PIN at any Meridian Bank ATM or by visiting a branch."
        ),
    ),
    ChannelFeature(
        feature_id="FP-CM-005",
        feature_name="Spending controls and merchant category blocks",
        feature_area="card_management",
        available_web=False,
        available_mobile=True,
        mobile_journey="Log in > Cards > select card > Spending controls > toggle controls.",
        notes=(
            "Online banking shows current limits but does not allow changes. "
            "Controls include: gambling block, adult content block, overseas transaction block, "
            "custom ATM and POS daily limits."
        ),
    ),
    ChannelFeature(
        feature_id="FP-CM-006",
        feature_name="Add card to Apple Pay",
        feature_area="card_management",
        available_web=False,
        available_mobile=True,
        mobile_journey=(
            "Log in > Cards > select card > Add to Apple Wallet > follow prompts and verify. "
            "Alternative: open Apple Wallet app > + > scan or enter card details > verify via Meridian app or SMS."
        ),
        notes="Apple Pay setup requires an active (non-frozen, non-blocked) card.",
    ),
    ChannelFeature(
        feature_id="FP-CM-007",
        feature_name="Add card to Google Pay",
        feature_area="card_management",
        available_web=False,
        available_mobile=True,
        mobile_journey=(
            "Log in > Cards > select card > Add to Google Pay > follow prompts and verify. "
            "Alternative: open Google Wallet app > + Add to Wallet > Payment card > enter card details > verify."
        ),
        notes="Google Pay requires an Android device with NFC. Card must be active.",
    ),
    ChannelFeature(
        feature_id="FP-CM-008",
        feature_name="Manage digital wallet (view / remove provisioned devices)",
        feature_area="card_management",
        available_web=False,
        available_mobile=True,
        mobile_journey="Log in > Cards > select card > Digital wallets > view or remove provisioned devices.",
        notes="Web shows a list of provisioned devices but does not allow removal.",
    ),

    # ── Payments ──────────────────────────────────────────────────────────────
    ChannelFeature(
        feature_id="FP-PAY-001",
        feature_name="Make a domestic payment (Faster Payments)",
        feature_area="payments",
        available_web=True,
        web_journey="Log in > Payments > New payment > enter payee details > confirm.",
        available_mobile=True,
        mobile_journey="Log in > Pay > New payment > enter or select payee > amount > confirm.",
    ),
    ChannelFeature(
        feature_id="FP-PAY-002",
        feature_name="Set up or cancel standing orders",
        feature_area="payments",
        available_web=True,
        web_journey="Log in > Payments > Standing orders > Add or manage.",
        available_mobile=True,
        mobile_journey="Log in > Pay > Standing orders > Add or manage.",
    ),
    ChannelFeature(
        feature_id="FP-PAY-003",
        feature_name="View and cancel direct debits",
        feature_area="payments",
        available_web=True,
        web_journey="Log in > Payments > Direct debits > view list > Cancel.",
        available_mobile=True,
        mobile_journey="Log in > Pay > Direct debits > view list > Cancel.",
        notes="New direct debits can only be set up by the originating company, not by the customer.",
    ),
    ChannelFeature(
        feature_id="FP-PAY-004",
        feature_name="International payments (SWIFT / SEPA)",
        feature_area="payments",
        available_web=True,
        web_journey="Log in > Payments > International transfer > enter IBAN and SWIFT/BIC > confirm.",
        available_mobile=False,
        notes=(
            "International transfers are NOT available in the mobile app. "
            "The mobile app supports UK domestic payments only. "
            "Fee: £15 SWIFT, £5 SEPA."
        ),
    ),
    ChannelFeature(
        feature_id="FP-PAY-005",
        feature_name="CHAPS same-day payment",
        feature_area="payments",
        available_web=True,
        web_journey="Log in > Payments > New payment > select CHAPS > enter details > confirm. Cutoff: 3pm.",
        available_mobile=False,
        notes="CHAPS payments are not available in the mobile app. Fee: £25 per CHAPS payment.",
    ),

    # ── Mortgage ──────────────────────────────────────────────────────────────
    ChannelFeature(
        feature_id="FP-MORT-001",
        feature_name="View mortgage balance and details",
        feature_area="mortgage",
        available_web=True,
        web_journey="Log in > Mortgage > overview shows balance, rate, term, next payment.",
        available_mobile=True,
        mobile_journey="Log in > Mortgage tile on home screen > balance and details.",
    ),
    ChannelFeature(
        feature_id="FP-MORT-002",
        feature_name="Make a mortgage overpayment",
        feature_area="mortgage",
        available_web=True,
        web_journey="Log in > Mortgage > Make overpayment > enter amount > confirm.",
        available_mobile=True,
        mobile_journey="Log in > Mortgage > Overpayment > enter amount > confirm.",
        notes="Check your annual overpayment allowance before submitting to avoid early repayment charges.",
    ),
    ChannelFeature(
        feature_id="FP-MORT-003",
        feature_name="Request a mortgage redemption statement",
        feature_area="mortgage",
        available_web=True,
        web_journey="Log in > Mortgage > Documents > Request redemption statement. Sent to registered email within 2 working days.",
        available_mobile=True,
        mobile_journey="Log in > Mortgage > Request redemption statement. Sent to registered email within 2 working days.",
    ),

    # ── Savings ───────────────────────────────────────────────────────────────
    ChannelFeature(
        feature_id="FP-SAV-001",
        feature_name="Open a new savings account",
        feature_area="savings",
        available_web=True,
        web_journey="Log in > Products > Savings > choose account > Apply now.",
        available_mobile=True,
        mobile_journey="Log in > Products > Savings > choose account > Apply.",
    ),
    ChannelFeature(
        feature_id="FP-SAV-002",
        feature_name="Transfer money to / from savings",
        feature_area="savings",
        available_web=True,
        web_journey="Log in > select savings account > Transfer > choose source/destination > amount > confirm.",
        available_mobile=True,
        mobile_journey="Log in > tap savings account > Transfer > choose source/destination > amount > confirm.",
    ),

    # ── Credit Card ───────────────────────────────────────────────────────────
    ChannelFeature(
        feature_id="FP-CC-001",
        feature_name="View credit card balance and available credit",
        feature_area="credit_card",
        available_web=True,
        web_journey="Log in > Credit card > overview.",
        available_mobile=True,
        mobile_journey="Log in > tap credit card tile > balance and available credit shown.",
    ),
    ChannelFeature(
        feature_id="FP-CC-002",
        feature_name="Make a credit card payment",
        feature_area="credit_card",
        available_web=True,
        web_journey="Log in > Credit card > Make payment > choose amount (minimum / full / custom) > confirm.",
        available_mobile=True,
        mobile_journey="Log in > Credit card > Pay > choose amount > confirm.",
    ),
    ChannelFeature(
        feature_id="FP-CC-003",
        feature_name="Report a fraudulent credit card transaction",
        feature_area="credit_card",
        available_web=True,
        web_journey="Log in > Credit card > Transactions > select transaction > Report as fraud.",
        available_mobile=True,
        mobile_journey="Log in > Credit card > tap transaction > Report as fraud.",
        available_phone=True,
        notes="For urgent fraud, call 0161 900 9001 (24/7 fraud line).",
    ),
]

_BY_AREA: dict[str, list[ChannelFeature]] = {}
for _f in _FEATURES:
    _BY_AREA.setdefault(_f.feature_area, []).append(_f)

_AREA_ALIASES: dict[str, str] = {
    "account": "account",
    "balance": "account",
    "transaction": "account",
    "card": "card_management",
    "card management": "card_management",
    "debit card": "card_management",
    "credit card": "credit_card",
    "apple pay": "card_management",
    "google pay": "card_management",
    "digital wallet": "card_management",
    "wallet": "card_management",
    "pin": "card_management",
    "freeze": "card_management",
    "block": "card_management",
    "payments": "payments",
    "payment": "payments",
    "standing order": "payments",
    "direct debit": "payments",
    "international": "payments",
    "chaps": "payments",
    "mortgage": "mortgage",
    "overpayment": "mortgage",
    "savings": "savings",
    "saver": "savings",
}


@tool
def get_feature_parity(feature_area: str) -> dict:
    """
    Returns the full list of features available on Meridian Bank's digital channels
    (online banking web and mobile app) for a given area, including journey descriptions
    for each available channel.

    feature_area can be: account, card_management, payments, mortgage, savings, credit_card.
    Common aliases are accepted (e.g. "digital wallet", "apple pay", "standing order", "pin").

    Use this tool when:
    - The customer asks how to do something (e.g. "how do I change my PIN?", "can I set up a
      standing order online?", "is Apple Pay available in the app?")
    - You need to direct a customer to the right self-service channel
    - You want to confirm whether a feature is available on web, mobile, or both

    The response includes:
    - features: list of features with available_web, web_journey, available_mobile,
      mobile_journey, and notes
    - Counts: web_only_count, mobile_only_count, both_count, neither_count

    How to use the response:
    - If a feature is available on BOTH: tell the customer they can use either the
      Meridian Bank mobile app or online banking at meridianbank.co.uk.
    - If available on MOBILE ONLY: tell the customer to use the Meridian Bank mobile app.
      Do NOT say they can use online banking.
    - If available on WEB ONLY: tell the customer to use online banking at meridianbank.co.uk.
      Do NOT say they can use the mobile app.
    - If available on NEITHER: apply the channel-appropriate out-of-scope response
      (voice: offer to transfer; chat: provide branch/phone contact).
    - Always include the specific journey steps if the customer asks how to do something.
    """
    canonical = _AREA_ALIASES.get(feature_area.lower().strip())
    if not canonical:
        # Try partial match
        for key in _BY_AREA:
            if key in feature_area.lower():
                canonical = key
                break

    if not canonical or canonical not in _BY_AREA:
        return {
            "error": (
                f"Unknown feature area '{feature_area}'. "
                "Valid areas: account, card_management, payments, mortgage, savings, credit_card."
            ),
            "features": [],
        }

    features = _BY_AREA[canonical]
    web_only = sum(1 for f in features if f.available_web and not f.available_mobile)
    mob_only = sum(1 for f in features if f.available_mobile and not f.available_web)
    both = sum(1 for f in features if f.available_web and f.available_mobile)
    neither = sum(1 for f in features if not f.available_web and not f.available_mobile)

    return FeatureParityResponse(
        feature_area=canonical,
        features=features,
        total_features=len(features),
        web_only_count=web_only,
        mobile_only_count=mob_only,
        both_count=both,
        neither_count=neither,
    ).model_dump()
