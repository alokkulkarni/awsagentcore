"""The branch finder, appointment and queue-status tools, from the branchtransfercalldesign project (BRANCH_REPO).
ARIA uses the branch-info and branch-appointments tools; the advisers' agent-assist agent uses all three.

    tools   the tables branches and branch-appointments (branches seeded with the project's sample branches), a role
            and a Lambda for each tool (python3.12, arm64, 256 MB, 10 s, as today), and each Lambda as a target on
            the MCP gateway (branch-info, branch-appointments, queue-status) that the gateway may call; then waits
            until the targets are READY and asks find_branches for Leeds. Create-only: what exists is kept.
            The project's Teams transfer pieces (lease bridge, its API and tables, the Azure side) aren't part of
            this system and aren't made.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from decimal import Decimal
from pathlib import Path

from common import TAGS, cli, fail, info, ok, paged, wait

TAG_LIST = [{"Key": k, "Value": v} for k, v in TAGS.items()]
BRANCHES, APPOINTMENTS, ROUTING = "branches", "branch-appointments", "aria-routing-config"
TABLES = {BRANCHES: ("branch_id", None), APPOINTMENTS: ("branch_id", "slot")}
LAMBDA = {"Runtime": "python3.12", "Architectures": ["arm64"], "MemorySize": 256, "Timeout": 10}
TRUST = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                                                 "Action": "sts:AssumeRole"}]}
BASIC = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"


def _table(ctx, name: str) -> str:
    return f"arn:aws:dynamodb:{ctx.region}:{ctx.account}:table/{name}"


# target on the gateway | Lambda | its one source file | its tool schemas | role | environment | what it may do
TOOLS = (
    {"target": "branch-info", "function": "branch-info-tool", "file": "branch_info_tool.py",
     "schemas": "branch_info_tool_schemas.json", "role": "branch-info-role",
     "env": lambda ctx: {"BRANCHES_TABLE": BRANCHES},
     "allow": lambda ctx: [{"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:Scan"],
                            "Resource": _table(ctx, BRANCHES)}]},
    {"target": "branch-appointments", "function": "branch-appointment-tool", "file": "branch_appointment_tool.py",
     "schemas": "branch_appointment_tool_schemas.json", "role": "branch-appointment-role",
     "env": lambda ctx: {"BRANCHES_TABLE": BRANCHES, "APPOINTMENTS_TABLE": APPOINTMENTS},
     "allow": lambda ctx: [{"Effect": "Allow", "Action": ["dynamodb:GetItem"], "Resource": _table(ctx, BRANCHES)},
                           {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"],
                            "Resource": _table(ctx, APPOINTMENTS)}]},
    {"target": "queue-status", "function": "queue-status-tool", "file": "queue_status_tool.py",
     "schemas": "queue_status_tool_schemas.json", "role": "queue-status-role",
     "env": lambda ctx: {"ROUTING_TABLE": ROUTING, "CONNECT_INSTANCE_ID": ctx.instance_id},
     "allow": lambda ctx: [{"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:Scan"],
                            "Resource": _table(ctx, ROUTING)},
                           {"Effect": "Allow", "Resource": [ctx.instance_arn, f"{ctx.instance_arn}/*"],
                            "Action": ["connect:DescribeQueue", "connect:DescribeHoursOfOperation",
                                       "connect:GetCurrentMetricData"]}]},
)


def _backend(ctx) -> Path:
    backend = Path(ctx.state.need("BRANCH_REPO")) / "backend"
    if not (backend / "branch_info_tool.py").exists():
        fail(f"{backend} isn't the branchtransfercalldesign backend (BRANCH_REPO in your config).")
    return backend


def plain(node):
    """AgentCore's inline tool schema takes type, properties, required, items and description only: drop enum, minimum
    and maximum, as the project's own register script does (each description already states its values)."""
    if isinstance(node, dict):
        return {k: plain(v) for k, v in node.items() if k not in ("enum", "minimum", "maximum")}
    if isinstance(node, list):
        return [plain(v) for v in node]
    return node


def _tables(ctx, backend: Path) -> None:
    ddb = ctx.client("dynamodb")
    have = {t for page in ddb.get_paginator("list_tables").paginate() for t in page["TableNames"]}
    for name, (hash_key, range_key) in TABLES.items():
        if name not in have:
            keys = [(hash_key, "HASH")] + ([(range_key, "RANGE")] if range_key else [])
            ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST", Tags=TAG_LIST,
                             AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k, _ in keys],
                             KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in keys])
            ddb.get_waiter("table_exists").wait(TableName=name)
        ok(f"Table {name}")
    if not ddb.scan(TableName=BRANCHES, Limit=1).get("Items"):
        import boto3
        table = boto3.resource("dynamodb", region_name=ctx.region).Table(BRANCHES)
        branches = json.loads((backend / "data" / "branches-seed.json").read_text(), parse_float=Decimal)
        with table.batch_writer() as batch:
            for branch in branches:
                batch.put_item(Item=branch)
        ok(f"Seeded {len(branches)} sample branches")


def _role(ctx, tool: dict) -> str:
    iam = ctx.client("iam")
    try:
        arn = iam.get_role(RoleName=tool["role"])["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=tool["role"], AssumeRolePolicyDocument=json.dumps(TRUST), Tags=TAG_LIST,
                              Description=f"{tool['function']} (deploy-fresh-instance)")["Role"]["Arn"]
    # Both every time (they're idempotent): a run stopped between create_role and here would leave the Lambda
    # unable to reach its table.
    iam.attach_role_policy(RoleName=tool["role"], PolicyArn=BASIC)
    iam.put_role_policy(RoleName=tool["role"], PolicyName="inline",
                        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": tool["allow"](ctx)}))
    ok(f"Role {tool['role']}")
    return arn


def _lambda(ctx, tool: dict, backend: Path, role_arn: str) -> str:
    lam = ctx.client("lambda")
    try:
        return lam.get_function(FunctionName=tool["function"])["Configuration"]["FunctionArn"]
    except lam.exceptions.ResourceNotFoundException:
        pass
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(backend / tool["file"], tool["file"])
    params = dict(FunctionName=tool["function"], Role=role_arn, Handler=f"{tool['file'][:-3]}.lambda_handler",
                  Code={"ZipFile": buf.getvalue()}, Environment={"Variables": tool["env"](ctx)}, Tags=TAGS, **LAMBDA)
    for attempt in range(12):                  # a new role takes a few seconds before Lambda may assume it
        try:
            arn = lam.create_function(**params)["FunctionArn"]
            break
        except lam.exceptions.InvalidParameterValueException as err:
            if "assume" not in str(err) or attempt == 11:
                raise
            info("Waiting for the new role to reach Lambda...")
            time.sleep(5)
    lam.get_waiter("function_active_v2").wait(FunctionName=tool["function"])
    ok(f"Lambda {tool['function']}")
    return arn


def _target(ctx, tool: dict, backend: Path, lambda_arn: str, gateway: dict, existing: dict) -> str:
    ac, lam, iam = ctx.client("bedrock-agentcore-control"), ctx.client("lambda"), ctx.client("iam")
    gid = gateway["gatewayId"]
    # The gateway calls the Lambda with its execution role (CreateGatewayTarget checks that role up front)...
    iam.put_role_policy(RoleName=gateway["roleArn"].split("/")[-1], PolicyName=f"invoke-{tool['function']}",
                        PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
                            {"Effect": "Allow", "Action": "lambda:InvokeFunction",
                             "Resource": [lambda_arn, f"{lambda_arn}:*"]}]}))
    # ...and the Lambda lets the gateway in.
    try:
        lam.add_permission(FunctionName=tool["function"], StatementId="agentcore-gateway-invoke",
                           Action="lambda:InvokeFunction", Principal="bedrock-agentcore.amazonaws.com",
                           SourceArn=gateway["gatewayArn"])
    except lam.exceptions.ResourceConflictException:
        pass
    target_id = existing.get(tool["target"])
    if not target_id:
        schemas = plain(json.loads((backend / tool["schemas"]).read_text()))
        for attempt in range(12):              # the role policy just written takes a few seconds to apply
            try:
                target_id = ac.create_gateway_target(
                    gatewayIdentifier=gid, name=tool["target"],
                    description=f"{tool['function']} (branchtransfercalldesign)",
                    targetConfiguration={"mcp": {"lambda": {"lambdaArn": lambda_arn,
                                                            "toolSchema": {"inlinePayload": schemas}}}},
                    credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])["targetId"]
                break
            except ac.exceptions.ValidationException as err:
                # Only the not-yet-applied role policy is worth waiting for; a schema problem shows straight away.
                if not any(w in str(err).lower() for w in ("role", "invoke", "permission", "access")) or attempt == 11:
                    raise
                info(f"Gateway not ready to add {tool['target']} yet ({str(err)[:120]}); retrying...")
                time.sleep(10)

    def ready():
        got = ac.get_gateway_target(gatewayIdentifier=gid, targetId=target_id)
        if got["status"] == "FAILED" or got["status"].endswith("_UNSUCCESSFUL"):
            fail(f"Gateway target {tool['target']} failed: {got.get('statusReasons')}")
        return got["status"] == "READY"

    wait(ready, f"gateway target {tool['target']}", timeout=300, every=10)
    names = ", ".join(t["name"] for t in json.loads((backend / tool["schemas"]).read_text()))
    ok(f"Gateway target {tool['target']} ({names})")
    return target_id


def tools(ctx) -> None:
    backend = _backend(ctx)
    ac = ctx.client("bedrock-agentcore-control")
    gateway = ac.get_gateway(gatewayIdentifier=ctx.state.need("GATEWAY_ID"))
    existing = {t["name"]: t["targetId"] for t in paged(ac.list_gateway_targets, "items", token="nextToken",
                                                        gatewayIdentifier=gateway["gatewayId"])}
    _tables(ctx, backend)
    for tool in TOOLS:
        arn = _lambda(ctx, tool, backend, _role(ctx, tool))
        _target(ctx, tool, backend, arn, gateway, existing)
    # The call the gateway makes, straight to the Lambda: proves the table, the seed and the role together.
    reply = ctx.client("lambda").invoke(FunctionName="branch-info-tool", Payload=json.dumps(
        {"jsonrpc": "2.0", "method": "tools/call",
         "params": {"name": "branch-info___find_branches", "arguments": {"query": "Leeds"}}}).encode())
    body = reply["Payload"].read().decode()
    found = {} if reply.get("FunctionError") else json.loads(body)
    if not found.get("count"):
        fail(f"find_branches found nothing for Leeds (the seed has two): {body[:300]}")
    ok(f"find_branches finds {found['count']} branches in Leeds")


if __name__ == "__main__":
    cli(__doc__, {"tools": tools})
