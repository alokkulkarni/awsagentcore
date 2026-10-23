"""The Amazon Connect instance itself, and what lives directly on it.

    instance        create the instance (or find the one this run made), wait until ACTIVE, turn on the attributes
                    in templates/connect.json, and store chat transcripts and call recordings in a new S3 bucket
    queues          the default hours, queue and routing profile (every new instance has them), plus the queues
                    in templates/connect.json; every queue joins the Basic Routing Profile for voice and chat
    admin-user      the first admin who signs in to the Connect admin website (username and password from stdin)
    associate       allow the instance to call these Lambdas (by name: extra arguments)
    origin          approve a web origin for in-app calls and chat (extra argument: https://...)
    phone           optional: claim a UK number and point it at ARIA's main flow
"""

from __future__ import annotations

import json
import sys
import time

from common import TAGS, TEMPLATES, ask, cli, exists_error, fail, info, load_json, ok, paged, wait, warn

CONNECT = load_json(TEMPLATES / "connect.json")


def instance(ctx) -> None:
    connect = ctx.client("connect")
    alias = ctx.state.need("INSTANCE_ALIAS")
    found = ctx.state.get("INSTANCE_ID")
    if not found:
        for summary in paged(connect.list_instances, "InstanceSummaryList"):
            if summary.get("InstanceAlias") == alias:
                tags = connect.list_tags_for_resource(resourceArn=summary["Arn"]).get("tags", {})
                if tags.get("project") != TAGS["project"]:
                    fail(f"An instance called {alias} exists and wasn't made by deploy-fresh-instance. "
                         "Pick another INSTANCE_ALIAS in your config; this script never takes over an instance.")
                found = summary["Id"]
        if not found:
            info(f"Creating instance {alias} (Connect-managed users, inbound and outbound calls)...")
            made = connect.create_instance(IdentityManagementType="CONNECT_MANAGED", InstanceAlias=alias,
                                           InboundCallsEnabled=True, OutboundCallsEnabled=True, Tags=TAGS)
            found = made["Id"]
        ctx.state.set("INSTANCE_ID", found)
    def settled():
        now = connect.describe_instance(InstanceId=found)["Instance"]["InstanceStatus"]
        return now if now in ("ACTIVE", "CREATION_FAILED") else None
    status = wait(settled, "the instance to become ACTIVE", timeout=900, every=15)
    if status != "ACTIVE":
        fail(f"The instance's creation failed ({status}). Delete it in the Connect console and run this step again.")
    described = connect.describe_instance(InstanceId=found)["Instance"]
    ctx.state.set("INSTANCE_ARN", described["Arn"])
    ok(f"Instance {alias}: {found} (ACTIVE)")

    for attribute, value in CONNECT["attributes"].items():
        try:
            connect.update_instance_attribute(InstanceId=found, AttributeType=attribute, Value=value)
        except connect.exceptions.InvalidRequestException as err:
            warn(f"{attribute} couldn't be set ({err.response['Error']['Message']}). Carrying on.")
    ok(f"Attributes on: {', '.join(CONNECT['attributes'])}")

    s3 = ctx.client("s3")
    bucket = ctx.state.get("STORAGE_BUCKET") or f"amazon-connect-{alias}-{ctx.account}"[:63]
    try:
        params = {"Bucket": bucket}
        if ctx.region != "us-east-1":
            params["CreateBucketConfiguration"] = {"LocationConstraint": ctx.region}
        s3.create_bucket(**params)
        s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
        s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in TAGS.items()]})
        ok(f"Bucket {bucket} created")
    except Exception as err:  # noqa: BLE001 - "already ours" is fine, anything else isn't
        if not exists_error(err):
            raise
    ctx.state.set("STORAGE_BUCKET", bucket)
    for resource, prefix in (("CHAT_TRANSCRIPTS", "ChatTranscripts"), ("CALL_RECORDINGS", "CallRecordings")):
        have = connect.list_instance_storage_configs(InstanceId=found, ResourceType=resource).get("StorageConfigs", [])
        if have:
            continue
        connect.associate_instance_storage_config(InstanceId=found, ResourceType=resource, StorageConfig={
            "StorageType": "S3", "S3Config": {"BucketName": bucket, "BucketPrefix": f"connect/{alias}/{prefix}"}})
    ok("Chat transcripts and call recordings go to the bucket")
    ctx.state.set("CONNECT_URL", f"https://{alias}.my.connect.aws")


def queues(ctx) -> None:
    connect = ctx.client("connect")
    iid = ctx.instance_id
    hours = {h["Name"]: h["Id"] for h in paged(connect.list_hours_of_operations, "HoursOfOperationSummaryList", InstanceId=iid)}
    basic_hours = hours.get(CONNECT["default_hours"]) or fail(f"No '{CONNECT['default_hours']}' on the instance.")
    ctx.state.set("HOURS_BASIC", basic_hours)
    have = {q["Name"]: q["Id"] for q in paged(connect.list_queues, "QueueSummaryList", InstanceId=iid, QueueTypes=["STANDARD"])}
    for queue in CONNECT["queues"]:
        if queue["name"] in have:
            continue
        made = connect.create_queue(InstanceId=iid, Name=queue["name"], Description=queue["description"],
                                    HoursOfOperationId=basic_hours, Tags=TAGS)
        have[queue["name"]] = made["QueueId"]
        ok(f"Queue {queue['name']}")
    ctx.state.set("QUEUES_JSON", json.dumps(have, separators=(",", ":")))
    profiles = {p["Name"]: p["Id"] for p in paged(connect.list_routing_profiles, "RoutingProfileSummaryList", InstanceId=iid)}
    profile = profiles.get(CONNECT["default_routing_profile"]) or fail("No Basic Routing Profile on the instance.")
    ctx.state.set("ROUTING_PROFILE_BASIC", profile)
    linked = {q["QueueId"] for q in paged(connect.list_routing_profile_queues, "RoutingProfileQueueConfigSummaryList",
                                          InstanceId=iid, RoutingProfileId=profile)}
    configs = [{"QueueReference": {"QueueId": qid, "Channel": channel}, "Priority": 1, "Delay": 0}
               for qid in have.values() if qid not in linked for channel in ("VOICE", "CHAT")]
    for start in range(0, len(configs), 10):          # the API takes at most 10 at a time
        connect.associate_routing_profile_queues(InstanceId=iid, RoutingProfileId=profile,
                                                 QueueConfigs=configs[start:start + 10])
    ok(f"{len(have)} queues, all in the Basic Routing Profile (voice and chat)")
    sps = {s["Name"]: s["Id"] for s in paged(connect.list_security_profiles, "SecurityProfileSummaryList", InstanceId=iid)}
    for name, key in (("Admin", "SP_ADMIN"), ("Agent", "SP_AGENT")):
        ctx.state.set(key, sps.get(name) or fail(f"No '{name}' security profile on the instance."))


def admin_user(ctx) -> None:
    connect = ctx.client("connect")
    iid = ctx.instance_id
    username, password = sys.stdin.readline().strip(), sys.stdin.readline().rstrip("\n")
    if not username or not password:
        fail("Username and password are both needed.")
    for user in paged(connect.list_users, "UserSummaryList", InstanceId=iid):
        if user["Username"] == username:
            ok(f"User {username} already exists")
            ctx.state.set("ADMIN_USER", username)
            return
    connect.create_user(InstanceId=iid, Username=username, Password=password,
                        IdentityInfo={"FirstName": "Demo", "LastName": "Admin"},
                        PhoneConfig={"PhoneType": "SOFT_PHONE", "AutoAccept": False},
                        SecurityProfileIds=[ctx.state.need("SP_ADMIN"), ctx.state.need("SP_AGENT")],
                        RoutingProfileId=ctx.state.need("ROUTING_PROFILE_BASIC"), Tags=TAGS)
    ctx.state.set("ADMIN_USER", username)
    ok(f"Admin {username} can sign in at {ctx.state.get('CONNECT_URL')}")


def associate(ctx) -> None:
    connect = ctx.client("connect")
    have = set(paged(connect.list_lambda_functions, "LambdaFunctions", InstanceId=ctx.instance_id))
    for name in ctx.extra:
        arn = f"arn:aws:lambda:{ctx.region}:{ctx.account}:function:{name}"
        if arn not in have:
            connect.associate_lambda_function(InstanceId=ctx.instance_id, FunctionArn=arn)
        ok(f"The instance may call {name}")


def origin(ctx) -> None:
    from urllib.parse import urlparse
    connect = ctx.client("connect")
    have = set(paged(connect.list_approved_origins, "Origins", InstanceId=ctx.instance_id))
    for url in filter(None, ctx.extra):
        parts = urlparse(url)
        site = f"{parts.scheme}://{parts.netloc}"            # an origin is scheme and host, never a path
        if parts.scheme != "https" or not parts.netloc:
            fail(f"{url!r} isn't an https address.")
        if site not in have:
            connect.associate_approved_origin(InstanceId=ctx.instance_id, Origin=site)
            have.add(site)
        ok(f"Approved origin {site}")


def phone(ctx) -> None:
    connect = ctx.client("connect")
    if ctx.state.get("PHONE_NUMBER"):
        ok(f"Phone number {ctx.state.get('PHONE_NUMBER')} already claimed")
        return
    if not ask("Claim a UK phone number for ARIA? It has a monthly cost.", ctx):
        warn("No phone number claimed. Chat and in-app calls work without one; run this step later to add one.")
        return
    found = connect.search_available_phone_numbers(TargetArn=ctx.instance_arn, PhoneNumberCountryCode="GB",
                                                   PhoneNumberType="DID", MaxResults=5).get("AvailableNumbersList", [])
    if not found:
        fail("No UK direct-dial numbers are available right now. Try again later.")
    number = found[0]["PhoneNumber"]
    claimed = connect.claim_phone_number(TargetArn=ctx.instance_arn, PhoneNumber=number,
                                         PhoneNumberDescription="ARIA main flow", Tags=TAGS)
    pid = claimed["PhoneNumberId"]
    wait(lambda: connect.describe_phone_number(PhoneNumberId=pid)["ClaimedPhoneNumberSummary"]
         ["PhoneNumberStatus"]["Status"] == "CLAIMED", "the number to be claimed", timeout=300)
    connect.associate_phone_number_contact_flow(PhoneNumberId=pid, InstanceId=ctx.instance_id,
                                                ContactFlowId=ctx.state.need("FLOW_MAIN"))
    ctx.state.set("PHONE_NUMBER", number)
    ctx.state.set("PHONE_NUMBER_ID", pid)
    ok(f"{number} now rings ARIA's main flow")


if __name__ == "__main__":
    cli(__doc__, {"instance": instance, "queues": queues, "admin-user": admin_user, "associate": associate,
                  "origin": origin, "phone": phone})
