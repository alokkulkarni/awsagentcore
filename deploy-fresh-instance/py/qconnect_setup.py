"""Amazon Q in Connect: the assistant behind ARIA and her knowledge.

    assistant       the assistant (type AGENT) and its WISDOM_ASSISTANT association with the instance
    knowledge-base  knowledgebase/meridian-bank in S3 → a Bedrock knowledge base on S3 Vectors (Titan text
                    embeddings v2, 1024 dimensions, as today's) → ingested → associated with the assistant
                    (its association ID goes into ARIA's Retrieve tool)
    guardrail       ARIA's guardrail from connect-bot-flow-modular/ai-agent/reference/aria-guardrail-v3.json, published
    logging         the assistant's AI agent event logs (each turn's model input and output) to CloudWatch Logs
"""

from __future__ import annotations

import json
import mimetypes
import time

from common import ROOT, TAGS, cli, exists_error, fail, info, load_json, ok, paged, wait, warn

EMBEDDING = "amazon.titan-embed-text-v2:0"
KB_FOLDER = ROOT / "knowledgebase" / "meridian-bank"
KB_PREFIX = "meridian-bank-kb/"
GUARDRAIL = ROOT / "connect-bot-flow-modular" / "ai-agent" / "reference" / "aria-guardrail-v3.json"


def assistant(ctx) -> None:
    q = ctx.client("qconnect")
    connect = ctx.client("connect")
    name = f"{ctx.state.need('INSTANCE_ALIAS')}-domain"
    aid = ctx.state.get("ASSISTANT_ID")
    if not aid:
        for a in paged(q.list_assistants, "assistantSummaries", token="nextToken"):
            if a["name"] == name:
                aid = a["assistantId"]
        if not aid:
            # Today's assistant uses a customer-managed key whose policy is the account default; do the same rather
            # than rely on an AWS-owned key nothing has verified with Connect, chat and Lex.
            kms = ctx.client("kms")
            key = ctx.state.get("ASSISTANT_KMS_KEY") or kms.create_key(
                Description=f"Q in Connect assistant {name} (deploy-fresh-instance)",
                Tags=[{"TagKey": k, "TagValue": v} for k, v in TAGS.items()],
                Policy=json.dumps({"Version": "2012-10-17", "Statement": [{
                    "Sid": "Enable IAM User Permissions", "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{ctx.account}:root"}, "Action": "kms:*", "Resource": "*"}]}),
            )["KeyMetadata"]["Arn"]
            ctx.state.set("ASSISTANT_KMS_KEY", key)
            aid = q.create_assistant(name=name, type="AGENT", tags=TAGS, description="ARIA (deploy-fresh-instance)",
                                     serverSideEncryptionConfiguration={"kmsKeyId": key})["assistant"]["assistantId"]
            ok(f"Assistant {name}: {aid} (encrypted with {key})")
        ctx.state.set("ASSISTANT_ID", aid)
    arn = q.get_assistant(assistantId=aid)["assistant"]["assistantArn"]
    ctx.state.set("ASSISTANT_ARN", arn)
    linked = paged(connect.list_integration_associations, "IntegrationAssociationSummaryList",
                   InstanceId=ctx.instance_id, IntegrationType="WISDOM_ASSISTANT")
    if not any(link["IntegrationArn"] == arn for link in linked):
        connect.create_integration_association(InstanceId=ctx.instance_id, IntegrationType="WISDOM_ASSISTANT",
                                               IntegrationArn=arn, Tags=TAGS)
    ok(f"Assistant {aid} is the instance's Q in Connect domain")


def _role(ctx, name: str, trust: dict, policy: dict) -> str:
    iam = ctx.client("iam")
    try:
        arn = iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust),
                              Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])["Role"]["Arn"]
        info(f"Role {name} created; giving IAM a moment to spread it")
        created = True
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=name)["Role"]
        if not any(t["Key"] == "project" and t["Value"] == TAGS["project"] for t in iam.list_role_tags(RoleName=name)["Tags"]):
            fail(f"Role {name} exists and wasn't made by deploy-fresh-instance. Not changing it.")
        arn, created = role["Arn"], False
    iam.put_role_policy(RoleName=name, PolicyName="access", PolicyDocument=json.dumps(policy))
    if created:
        time.sleep(12)
    return arn


def knowledge_base(ctx) -> None:
    alias, account, region = ctx.state.need("INSTANCE_ALIAS"), ctx.account, ctx.region
    aid, assistant_arn = ctx.state.need("ASSISTANT_ID"), ctx.state.need("ASSISTANT_ARN")
    s3 = ctx.client("s3")
    bucket = ctx.state.get("KB_BUCKET") or f"{alias}-kb-{account}"[:63]
    try:
        params = {"Bucket": bucket}
        if region != "us-east-1":
            params["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**params)
        s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    except Exception as err:  # noqa: BLE001
        if not exists_error(err):
            raise
    ctx.state.set("KB_BUCKET", bucket)
    files = [p for p in KB_FOLDER.rglob("*") if p.is_file()]
    for path in files:
        key = KB_PREFIX + path.relative_to(KB_FOLDER).as_posix()
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": mimetypes.guess_type(path.name)[0] or "text/plain"})
    ok(f"{len(files)} knowledge files in s3://{bucket}/{KB_PREFIX}")

    vectors = ctx.client("s3vectors")
    vector_bucket, index = f"{alias}-kb-vectors"[:63], "aria-kb-index"
    try:
        vectors.create_vector_bucket(vectorBucketName=vector_bucket, tags=TAGS)
    except Exception as err:  # noqa: BLE001
        if not exists_error(err):
            raise
    try:
        vectors.create_index(vectorBucketName=vector_bucket, indexName=index, dataType="float32", dimension=1024,
                             distanceMetric="cosine",
                             metadataConfiguration={"nonFilterableMetadataKeys": ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]})
    except Exception as err:  # noqa: BLE001
        if not exists_error(err):
            raise
    index_arn = vectors.get_index(vectorBucketName=vector_bucket, indexName=index)["index"]["indexArn"]
    vector_bucket_arn = index_arn.split("/index/")[0]
    ok(f"Vector index {index_arn}")

    kb_role = _role(ctx, f"{alias}-bedrock-kb-role"[:64], {
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "bedrock.amazonaws.com"},
                                                "Action": "sts:AssumeRole",
                                                "Condition": {"StringEquals": {"aws:SourceAccount": account}}}]}, {
        "Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "bedrock:InvokeModel",
             "Resource": f"arn:aws:bedrock:{region}::foundation-model/{EMBEDDING}"},
            {"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"],
             "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"]},
            {"Effect": "Allow", "Action": ["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                                           "s3vectors:QueryVectors", "s3vectors:GetIndex"],
             "Resource": [vector_bucket_arn, index_arn]}]})

    bedrock = ctx.client("bedrock-agent")
    kb_id = ctx.state.get("KB_ID")
    if not kb_id:
        name = f"{alias}-knowledge"
        existing = [k for k in paged(bedrock.list_knowledge_bases, "knowledgeBaseSummaries", token="nextToken") if k["name"] == name]
        kb_id = existing[0]["knowledgeBaseId"] if existing else bedrock.create_knowledge_base(
            name=name, roleArn=kb_role, tags=TAGS,
            knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": f"arn:aws:bedrock:{region}::foundation-model/{EMBEDDING}",
                "embeddingModelConfiguration": {"bedrockEmbeddingModelConfiguration": {"dimensions": 1024,
                                                                                       "embeddingDataType": "FLOAT32"}}}},
            storageConfiguration={"type": "S3_VECTORS", "s3VectorsConfiguration": {"indexArn": index_arn}},
        )["knowledgeBase"]["knowledgeBaseId"]
        ctx.state.set("KB_ID", kb_id)
    wait(lambda: bedrock.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]["status"] == "ACTIVE",
         "the knowledge base to become ACTIVE", timeout=600)
    kb_arn = bedrock.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]["knowledgeBaseArn"]
    sources = paged(bedrock.list_data_sources, "dataSourceSummaries", token="nextToken", knowledgeBaseId=kb_id)
    ds_id = sources[0]["dataSourceId"] if sources else bedrock.create_data_source(
        knowledgeBaseId=kb_id, name="meridian-bank-kb",
        dataSourceConfiguration={"type": "S3", "s3Configuration": {"bucketArn": f"arn:aws:s3:::{bucket}",
                                                                   "inclusionPrefixes": [KB_PREFIX]}},
    )["dataSource"]["dataSourceId"]
    job = bedrock.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)["ingestionJob"]["ingestionJobId"]

    def ingested():
        got = bedrock.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id, ingestionJobId=job)["ingestionJob"]
        return got if got["status"] in ("COMPLETE", "FAILED", "STOPPED") else None
    done = wait(ingested, "the documents to be indexed", timeout=900, every=15)
    if done["status"] != "COMPLETE":
        fail(f"Indexing ended {done['status']}: {done.get('failureReasons')}")
    stats = done.get("statistics", {})
    ok(f"Knowledge base {kb_id}: {stats.get('numberOfNewDocumentsIndexed', 0)} new, "
       f"{stats.get('numberOfDocumentsFailed', 0)} failed")

    access_role = _role(ctx, f"{alias}-assistant-kb-access"[:64], {
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "wisdom.amazonaws.com"},
                                                "Action": "sts:AssumeRole",
                                                "Condition": {"StringEquals": {"aws:SourceAccount": account},
                                                              "ArnLike": {"aws:SourceArn": assistant_arn}}}]}, {
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "bedrock:Retrieve", "Resource": kb_arn}]})
    q = ctx.client("qconnect")
    have = paged(q.list_assistant_associations, "assistantAssociationSummaries", token="nextToken", assistantId=aid)
    link = next((a for a in have if a["associationType"] == "EXTERNAL_BEDROCK_KNOWLEDGE_BASE"), None)
    if not link:
        link = q.create_assistant_association(
            assistantId=aid, associationType="EXTERNAL_BEDROCK_KNOWLEDGE_BASE", tags=TAGS,
            association={"externalBedrockKnowledgeBaseConfig": {"bedrockKnowledgeBaseArn": kb_arn,
                                                                "accessRoleArn": access_role}})["assistantAssociation"]
    ctx.state.set("KB_ASSOC_ID", link["assistantAssociationId"])
    ok(f"Knowledge base associated with the assistant: {link['assistantAssociationId']}")


def guardrail(ctx) -> None:
    q = ctx.client("qconnect")
    aid = ctx.state.need("ASSISTANT_ID")
    source = load_json(GUARDRAIL)
    source = source.get("aiGuardrail", source)
    gid = ctx.state.get("GUARDRAIL_ID")
    if not gid:
        have = [g for g in paged(q.list_ai_guardrails, "aiGuardrailSummaries", token="nextToken", assistantId=aid)
                if g["name"] == source["name"]]
        if have:
            gid = have[0]["aiGuardrailId"]
        else:
            fields = {k: source[k] for k in ("description", "topicPolicyConfig", "contentPolicyConfig", "wordPolicyConfig",
                                             "sensitiveInformationPolicyConfig", "contextualGroundingPolicyConfig")
                      if source.get(k)}
            gid = q.create_ai_guardrail(assistantId=aid, name=source["name"], visibilityStatus="PUBLISHED",
                                        blockedInputMessaging=source["blockedInputMessaging"],
                                        blockedOutputsMessaging=source["blockedOutputsMessaging"], tags=TAGS,
                                        **fields)["aiGuardrail"]["aiGuardrailId"]
        ctx.state.set("GUARDRAIL_ID", gid)
    if not ctx.state.get("GUARDRAIL_VERSION"):
        version = q.create_ai_guardrail_version(assistantId=aid, aiGuardrailId=gid)["versionNumber"]
        ctx.state.set("GUARDRAIL_VERSION", version)
    ok(f"Guardrail {source['name']}: {gid}:{ctx.state.get('GUARDRAIL_VERSION')}")


def logging(ctx) -> None:
    logs = ctx.client("logs")
    alias, aid, arn = ctx.state.need("INSTANCE_ALIAS"), ctx.state.need("ASSISTANT_ID"), ctx.state.need("ASSISTANT_ARN")
    group = f"/aws/vendedlogs/connect/ai-agents/{aid}"
    try:
        logs.create_log_group(logGroupName=group, tags=TAGS)
        logs.put_retention_policy(logGroupName=group, retentionInDays=30)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    group_arn = f"arn:aws:logs:{ctx.region}:{ctx.account}:log-group:{group}"
    source, destination = f"{alias}-assistant-event-logs", f"{alias}-assistant-event-logs-cwl"
    logs.put_delivery_source(name=source, resourceArn=arn, logType="EVENT_LOGS", tags=TAGS)
    dest_arn = logs.put_delivery_destination(name=destination, outputFormat="json", tags=TAGS,
                                             deliveryDestinationConfiguration={"destinationResourceArn": group_arn}
                                             )["deliveryDestination"]["arn"]
    try:
        logs.create_delivery(deliverySourceName=source, deliveryDestinationArn=dest_arn, tags=TAGS)
    except logs.exceptions.ConflictException:
        pass
    ok(f"AI agent event logs go to {group} (kept 30 days)")


if __name__ == "__main__":
    cli(__doc__, {"assistant": assistant, "knowledge-base": knowledge_base, "guardrail": guardrail, "logging": logging})
