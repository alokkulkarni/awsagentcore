"""How ARIA reaches her tools and the Money Hub agent, and who may use them.

    gateway     find the MCP gateway scripts/deploy_mcp_gateway.sh made (by name) and keep its ID and URL
    mock-data   MOCK_DATA=true on the auth, account and customer tool Lambdas: the demo's sample customers
                (the gateway script never sets it, and without it those tools answer "No data source configured")
    mcp-app     register the gateway with Connect as an MCP server (AppIntegrations MCP_SERVER) and associate it
    tool-grants let the Admin and Agent security profiles use every tool on the gateway (target___tool, as today):
                ARIA's tool calls run with the security profiles linked to her, and fail without these
    a2a-app     register the Money Hub bridge as an A2A server (API key in the bridge's own secret), associate it,
                and make the "ARIA AI agent collaborators" security profile that allows it
"""

from __future__ import annotations

from common import TAGS, cli, fail, ok, paged

GATEWAY_NAME = "aria-banking-mcp-gateway-prod"
MCP_APP = "aria-mcp-agentcore-gateway-server"
MONEY_HUB_APP = "aria-money-hub"
BRIDGE_FUNCTION = "aria-money-hub-bridge"
BRIDGE_SECRET = "aria-money-hub/a2a-api-key"
COLLABORATORS = "ARIA AI agent collaborators"
MOCK_FUNCTIONS = ("aria-banking-mcp-auth-prod", "aria-banking-mcp-account-prod", "aria-banking-mcp-customer-prod")


def gateway(ctx) -> None:
    ac = ctx.client("bedrock-agentcore-control")
    found = [g for g in paged(ac.list_gateways, "items", token="nextToken") if g["name"] == GATEWAY_NAME]
    if not found:
        fail(f"No gateway called {GATEWAY_NAME}: run the gateway step first.")
    gid = found[0]["gatewayId"]
    got = ac.get_gateway(gatewayIdentifier=gid)
    if got.get("authorizerType") != "CUSTOM_JWT":
        fail(f"The gateway's authorizer is {got.get('authorizerType')}, not CUSTOM_JWT, so Connect can't call it. "
             "It was made without the instance: tear it down (deploy_mcp_gateway.sh teardown) and run the gateway step again.")
    ctx.state.set("GATEWAY_ID", gid)
    ctx.state.set("GATEWAY_URL", got["gatewayUrl"])
    ok(f"Gateway {gid}: {got['gatewayUrl']}")


def mock_data(ctx) -> None:
    lam = ctx.client("lambda")
    for name in MOCK_FUNCTIONS:
        env = lam.get_function_configuration(FunctionName=name).get("Environment", {}).get("Variables", {})
        if env.get("MOCK_DATA") != "true":
            lam.update_function_configuration(FunctionName=name, Environment={"Variables": {**env, "MOCK_DATA": "true"}})
            lam.get_waiter("function_updated_v2").wait(FunctionName=name)
        ok(f"{name}: MOCK_DATA=true")


def _application(ctx, name: str, **create) -> tuple[str, str]:
    apps = ctx.client("appintegrations")
    have = [a for a in paged(apps.list_applications, "Applications") if a["Name"] == name]
    if have:
        return have[0]["Id"], have[0]["Arn"]
    made = apps.create_application(Name=name, Tags=TAGS, **create)
    return made["Id"], made["Arn"]


def _associate(ctx, arn: str) -> None:
    connect = ctx.client("connect")
    linked = paged(connect.list_integration_associations, "IntegrationAssociationSummaryList",
                   InstanceId=ctx.instance_id, IntegrationType="APPLICATION")
    if not any(link["IntegrationArn"] == arn for link in linked):
        connect.create_integration_association(InstanceId=ctx.instance_id, IntegrationType="APPLICATION",
                                               IntegrationArn=arn, Tags=TAGS)


def mcp_app(ctx) -> None:
    gid, url = ctx.state.need("GATEWAY_ID"), ctx.state.need("GATEWAY_URL")
    app_id, arn = _application(ctx, MCP_APP, Namespace=gid, ApplicationType="MCP_SERVER",
                               Description="ARIA banking tools (AgentCore MCP gateway)",
                               ApplicationSourceConfig={"ExternalUrlConfig": {"AccessUrl": url}})
    _associate(ctx, arn)
    ctx.state.set("APP_MCP_ID", app_id)
    ok(f"MCP server {MCP_APP} ({app_id}) is on the instance")


def _tools(ctx) -> list[str]:
    ac = ctx.client("bedrock-agentcore-control")
    gid = ctx.state.need("GATEWAY_ID")
    out = []
    for target in paged(ac.list_gateway_targets, "items", token="nextToken", gatewayIdentifier=gid):
        got = ac.get_gateway_target(gatewayIdentifier=gid, targetId=target["targetId"])
        schema = got.get("targetConfiguration", {}).get("mcp", {}).get("lambda", {}).get("toolSchema", {})
        out += [f"{got['name']}___{tool['name']}" for tool in schema.get("inlinePayload", [])]
    return sorted(out)


def tool_grants(ctx) -> None:
    connect = ctx.client("connect")
    gid = ctx.state.need("GATEWAY_ID")
    tools = _tools(ctx)
    if not tools:
        fail("The gateway has no tools yet.")
    for key in ("SP_ADMIN", "SP_AGENT"):
        sp = ctx.state.need(key)
        current = paged(connect.list_security_profile_applications, "Applications",
                        InstanceId=ctx.instance_id, SecurityProfileId=sp)
        apps = [a for a in current if a["Namespace"] != gid]
        apps.append({"Namespace": gid, "ApplicationPermissions": tools, "Type": "MCP"})
        connect.update_security_profile(InstanceId=ctx.instance_id, SecurityProfileId=sp, Applications=apps)
    ok(f"Admin and Agent may use the gateway's {len(tools)} tools")


def a2a_app(ctx) -> None:
    lam, sm, connect = ctx.client("lambda"), ctx.client("secretsmanager"), ctx.client("connect")
    url = lam.get_function_url_config(FunctionName=BRIDGE_FUNCTION)["FunctionUrl"]
    secret_arn = sm.describe_secret(SecretId=BRIDGE_SECRET)["ARN"]
    app_id, arn = _application(ctx, MONEY_HUB_APP, Namespace=MONEY_HUB_APP, ApplicationType="A2A_SERVER",
                               Description="ARIA Money Hub (Strands on AgentCore, via A2A bridge)",
                               ApplicationSourceConfig={"ExternalUrlConfig": {"AccessUrl": url}},
                               AuthConfig={"AuthType": "API_KEY", "CredentialProviderIdentifier": secret_arn})
    _associate(ctx, arn)
    ctx.state.set("APP_MONEY_HUB_ID", app_id)
    ctx.state.set("APP_MONEY_HUB_ARN", arn)
    profiles = {s["Name"]: s["Id"] for s in paged(connect.list_security_profiles, "SecurityProfileSummaryList",
                                                  InstanceId=ctx.instance_id)}
    allowed = [{"Arn": arn, "Type": "THIRD_PARTY"}]
    if COLLABORATORS in profiles:
        sp = profiles[COLLABORATORS]
        connect.update_security_profile(InstanceId=ctx.instance_id, SecurityProfileId=sp, AllowedAIAgents=allowed,
                                        Permissions=["BasicAgentAccess"])
    else:
        sp = connect.create_security_profile(InstanceId=ctx.instance_id, SecurityProfileName=COLLABORATORS,
                                             Description="Lets ARIA hand over to the Money Hub agent (A2A)",
                                             Permissions=["BasicAgentAccess"], AllowedAIAgents=allowed,
                                             Tags=TAGS)["SecurityProfileId"]
    ctx.state.set("SP_COLLABORATORS", sp)
    ok(f"A2A server {MONEY_HUB_APP} ({app_id}) on the instance; '{COLLABORATORS}' allows it")


if __name__ == "__main__":
    cli(__doc__, {"gateway": gateway, "mock-data": mock_data, "mcp-app": mcp_app, "tool-grants": tool_grants,
                  "a2a-app": a2a_app})
