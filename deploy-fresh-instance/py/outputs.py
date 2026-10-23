"""Reads back what the repo's deploy scripts made, by name, so later steps get it from AWS rather than from screen
output.

    web     the banking app's, Money Hub's and dispute pages' addresses (their HTTP APIs), and the dispute
            service's Data request address (…/acxd/ops) the card dispute designer app calls
    mortgage the mortgage stack's outputs: its Data request address, Lambda names and secret names
"""

from __future__ import annotations

from common import cli, fail, ok, paged

APIS = {"BANKING_APP_URL": "aria-banking-app-pages", "MONEY_HUB_URL": "aria-money-hub-pages",
        "DISPUTE_PAGES_URL": "aria-card-dispute-pages"}
MORTGAGE_STACK = "mortgage-livesync-api"


def web(ctx) -> None:
    gw = ctx.client("apigatewayv2")
    apis = {a["Name"]: a["ApiEndpoint"] for a in paged(gw.get_apis, "Items")}
    for key, name in APIS.items():
        if name in apis:
            ctx.state.set(key, apis[name].rstrip("/") + "/")
            ok(f"{name}: {apis[name]}")
    if "aria-card-dispute-pages" in apis:
        ctx.state.set("DISPUTE_ACXD_URL", apis["aria-card-dispute-pages"].rstrip("/") + "/acxd/ops")


def mortgage(ctx) -> None:
    cfn = ctx.client("cloudformation")
    try:
        stack = cfn.describe_stacks(StackName=MORTGAGE_STACK)["Stacks"][0]
    except cfn.exceptions.ClientError:
        fail(f"No {MORTGAGE_STACK} stack: run the mortgage backend step first.")
    out = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    for key, name in (("MORTGAGE_ENDPOINT_URL", "EndpointUrl"), ("MORTGAGE_FUNCTION", "FunctionName"),
                      ("MORTGAGE_ACXD_SYNC_FUNCTION", "AcxdSyncFunctionName"),
                      ("MORTGAGE_ACXD_ACCESS_SECRET", "AcxdAccessSecretName"),
                      ("MORTGAGE_TOUCHPOINT_SECRET", "TouchpointSecretName"),
                      ("MORTGAGE_AGENT_TOKEN_SECRET", "AgentTokenSecretArn")):
        if out.get(name):
            ctx.state.set(key, out[name])
    ok(f"Mortgage service: {out.get('EndpointUrl')}")


if __name__ == "__main__":
    cli(__doc__, {"web": web, "mortgage": mortgage})
