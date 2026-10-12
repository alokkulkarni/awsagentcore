"""
idv_test_data.py
================
Test data for the ARIA ID&V test harness.

The list of test customers is NOT defined here. It is imported from
session_injector_qconnect.py (_STUB_CUSTOMERS and _PHONE_TO_CUSTOMER) so the
harness menu always offers exactly the customers the session injector knows.
Add a customer to the injector and it appears in the harness automatically.

What IS defined here is the extra identity data the injector does not hold but
ID&V needs: date of birth, security number (for partial-PIN KBA), app enrolment
and the simulated telco signals for each customer's registered mobile.

ALL VALUES ARE FICTIONAL TEST DATA. Never put real customer data in this file.
"""

import hashlib

import session_injector_qconnect as injector

STUB_CUSTOMERS: dict[str, dict] = injector._STUB_CUSTOMERS
PHONE_TO_CUSTOMER: dict[str, str] = injector._PHONE_TO_CUSTOMER
normalise_phone = injector._normalise_phone

# ---------------------------------------------------------------------------
# ID&V profiles — keyed by the injector's customer IDs
# ---------------------------------------------------------------------------
# dob                    DDMMYYYY, keyed on the phone keypad for claimed identity.
#                        Kept identical to scripts/lambdas/mcp_tools/aria_auth_handler.py,
#                        which ARIA uses for its payment step-up (a unit test compares them).
# security_number        6 digits; KBA asks for the 2nd and 5th
# app_enrolled           customer has the bank app with a device-bound key
# app_on_second_device   app also on a tablet (reachable when the phone is not)
# device_bound_days_ago  age of the app's device binding
# sim_swap_days_ago      None = no recent SIM swap on the registered mobile
# call_forwarding        unconditional divert active on the registered mobile
# tenure_days            how long the number has been with this subscriber
IDV_TEST_PROFILES: dict[str, dict] = {
    "CUST-001": {
        "dob": "09091982", "security_number": "482916",
        "app_enrolled": True, "app_on_second_device": True, "device_bound_days_ago": 400,
        "sim_swap_days_ago": None, "call_forwarding": False, "tenure_days": 2100,
    },
    "CUST-002": {
        "dob": "14031990", "security_number": "305718",
        "app_enrolled": True, "app_on_second_device": False, "device_bound_days_ago": 250,
        "sim_swap_days_ago": None, "call_forwarding": False, "tenure_days": 900,
    },
    "CUST-003": {
        "dob": "09111958", "security_number": "661204",
        "app_enrolled": True, "app_on_second_device": True, "device_bound_days_ago": 620,
        "sim_swap_days_ago": None, "call_forwarding": False, "tenure_days": 3400,
    },
    # Daniel: the high-risk line. SIM swapped two days ago with divert on, but
    # his app was bound long before the swap (so a pre-swap device exists).
    "CUST-004": {
        "dob": "30051994", "security_number": "917342",
        "app_enrolled": True, "app_on_second_device": False, "device_bound_days_ago": 300,
        "sim_swap_days_ago": 2, "call_forwarding": True, "tenure_days": 1500,
    },
    # Ethel: no app at all, so OTP + KBA is her strongest route.
    "CUST-005": {
        "dob": "03021941", "security_number": "154873",
        "app_enrolled": False, "app_on_second_device": False, "device_bound_days_ago": 0,
        "sim_swap_days_ago": None, "call_forwarding": False, "tenure_days": 5200,
    },
}


def customer_ids() -> list[str]:
    """Every customer the session injector knows, in a stable order."""
    return sorted(STUB_CUSTOMERS.keys())


def profile_for(customer_id: str) -> dict:
    """
    ID&V profile for a customer. Customers added to the injector without an
    entry above get a deterministic default so they are still testable.
    """
    if customer_id in IDV_TEST_PROFILES:
        return IDV_TEST_PROFILES[customer_id]
    digest = hashlib.sha256(customer_id.encode()).hexdigest()
    digits = "".join(str(int(c, 16) % 10) for c in digest[:6])
    return {
        "dob": "01011970", "security_number": digits,
        "app_enrolled": True, "app_on_second_device": False, "device_bound_days_ago": 365,
        "sim_swap_days_ago": None, "call_forwarding": False, "tenure_days": 1000,
    }


def registered_mobile(customer_id: str) -> str:
    """The customer's registered mobile in E.164, or '' if the injector maps none."""
    for phone, cust in PHONE_TO_CUSTOMER.items():
        if cust == customer_id and phone.startswith("+"):
            return phone
    return ""


def preferred_name(customer_id: str) -> str:
    return (STUB_CUSTOMERS.get(customer_id) or {}).get("preferred_name", "")


def card_last_fours(customer_id: str) -> list[str]:
    return [c.get("last_four", "") for c in (STUB_CUSTOMERS.get(customer_id) or {}).get("cards", [])]


# ---------------------------------------------------------------------------
# Simulated lines — "which number is this call arriving from?"
# ---------------------------------------------------------------------------
# These special numbers are in Ofcom's reserved-for-drama ranges and are not
# mapped in the injector, so they can never collide with a real test customer.
SHARED_LANDLINE = "+441632960001"       # family landline registered to two customers
INTERNATIONAL_UNKNOWN = "+33199000001"  # presented, foreign, matches nobody


def shared_line_customers() -> list[str]:
    """The two customers who both list the shared landline (joint / household)."""
    return customer_ids()[:2]


def simulated_lines(real_cli: str) -> list[dict]:
    """
    The "which line are you calling from" menu, built from the injector's data.
    Each entry: key (keypad digits), label (spoken), cli, kind.
    """
    lines: list[dict] = []
    for i, cust in enumerate(customer_ids(), start=1):
        mobile = registered_mobile(cust)
        if mobile:
            lines.append({"key": str(i), "label": f"{preferred_name(cust)}'s registered mobile",
                          "cli": mobile, "kind": "customer"})
    n = len(customer_ids())
    lines.append({"key": str(n + 1), "label": "a landline shared by two customers",
                  "cli": SHARED_LANDLINE, "kind": "shared"})
    lines.append({"key": str(n + 2), "label": "a withheld number", "cli": "", "kind": "withheld"})
    lines.append({"key": str(n + 3), "label": "an unknown international number",
                  "cli": INTERNATIONAL_UNKNOWN, "kind": "international"})
    lines.append({"key": "0", "label": "the real number you are calling from",
                  "cli": normalise_phone(real_cli) if real_cli else "", "kind": "real"})
    return lines
