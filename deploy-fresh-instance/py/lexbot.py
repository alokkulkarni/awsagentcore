"""The Lex bot that hands every customer turn to ARIA (the Q in Connect assistant).

    bot     a bot with one locale (en_GB) and the AMAZON.QInConnectIntent pointing at the assistant, built,
            versioned, behind a "production" alias, and associated with the instance. It uses a Lex service-linked
            role: Lex adds the Q in Connect permissions to that role itself when the intent is created (Lex V2
            guide, AMAZON.QinConnectIntent → Permissions). Same settings as today's bot: 300 s idle, not child-directed.
"""

from __future__ import annotations

from common import TAGS, cli, ok, paged, wait

LOCALE = "en_GB"


def bot(ctx) -> None:
    lex, iam, connect = ctx.client("lexv2-models"), ctx.client("iam"), ctx.client("connect")
    alias_name = ctx.state.need("INSTANCE_ALIAS")
    assistant_arn = ctx.state.need("ASSISTANT_ARN")
    suffix = alias_name.replace("-", "")[:30]
    role_name = f"AWSServiceRoleForLexV2Bots_{suffix}"
    try:
        role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        role_arn = iam.create_service_linked_role(AWSServiceName="lexv2.amazonaws.com", CustomSuffix=suffix,
                                                  Description="ARIA bot (deploy-fresh-instance)")["Role"]["Arn"]
        ok(f"Service-linked role {role_name}")

    name = f"{alias_name}-aria-bot"
    bot_id = ctx.state.get("LEX_BOT_ID") or next(
        (b["botId"] for b in paged(lex.list_bots, "botSummaries", token="nextToken") if b["botName"] == name), None)
    if not bot_id:
        bot_id = lex.create_bot(botName=name, roleArn=role_arn, dataPrivacy={"childDirected": False},
                                idleSessionTTLInSeconds=300, botTags=TAGS,
                                description="Hands each customer turn to ARIA (Q in Connect)")["botId"]
    ctx.state.set("LEX_BOT_ID", bot_id)
    wait(lambda: lex.describe_bot(botId=bot_id)["botStatus"] == "Available", "the bot", timeout=300, every=5)

    locales = {l["localeId"] for l in paged(lex.list_bot_locales, "botLocaleSummaries", token="nextToken",
                                             botId=bot_id, botVersion="DRAFT")}
    if LOCALE not in locales:
        lex.create_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=LOCALE, nluIntentConfidenceThreshold=0.40,
                              voiceSettings={"voiceId": "Amy", "engine": "neural"})
    wait(lambda: lex.describe_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=LOCALE)["botLocaleStatus"]
         in ("NotBuilt", "Built", "ReadyExpressTesting"), "the en_GB locale", timeout=300, every=5)
    intents = {i["intentName"] for i in paged(lex.list_intents, "intentSummaries", token="nextToken",
                                              botId=bot_id, botVersion="DRAFT", localeId=LOCALE)}
    if "AmazonQinConnect" not in intents:
        lex.create_intent(botId=bot_id, botVersion="DRAFT", localeId=LOCALE, intentName="AmazonQinConnect",
                          parentIntentSignature="AMAZON.QInConnectIntent",
                          qInConnectIntentConfiguration={"qInConnectAssistantConfiguration": {"assistantArn": assistant_arn}})
        ok("Intent AmazonQinConnect → the assistant")

    if not ctx.state.get("LEX_ALIAS_ID"):
        lex.build_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=LOCALE)

        def built():
            status = lex.describe_bot_locale(botId=bot_id, botVersion="DRAFT", localeId=LOCALE)
            if status["botLocaleStatus"] == "Failed":
                raise SystemExit(f"[FAIL] The bot didn't build: {status.get('failureReasons')}")
            return status["botLocaleStatus"] == "Built"
        wait(built, "the bot to build", timeout=600, every=10)
        version = lex.create_bot_version(botId=bot_id, botVersionLocaleSpecification={
            LOCALE: {"sourceBotVersion": "DRAFT"}})["botVersion"]
        wait(lambda: lex.describe_bot_version(botId=bot_id, botVersion=version)["botStatus"] == "Available",
             f"bot version {version}", timeout=300, every=5)
        alias = lex.create_bot_alias(botAliasName="production", botId=bot_id, botVersion=version,
                                     botAliasLocaleSettings={LOCALE: {"enabled": True}}, tags=TAGS)
        ctx.state.set("LEX_ALIAS_ID", alias["botAliasId"])
    alias_id = ctx.state.need("LEX_ALIAS_ID")
    wait(lambda: lex.describe_bot_alias(botId=bot_id, botAliasId=alias_id)["botAliasStatus"] == "Available",
         "the production alias", timeout=300, every=5)
    alias_arn = f"arn:aws:lex:{ctx.region}:{ctx.account}:bot-alias/{bot_id}/{alias_id}"
    ctx.state.set("LEX_ALIAS_ARN", alias_arn)
    ctx.state.set("LEX_BOT_ALIAS_PATH", f"{bot_id}/{alias_id}")
    have = paged(connect.list_bots, "LexBots", InstanceId=ctx.instance_id, LexVersion="V2")
    if not any(b.get("LexV2Bot", {}).get("AliasArn") == alias_arn for b in have):
        connect.associate_bot(InstanceId=ctx.instance_id, LexV2Bot={"AliasArn": alias_arn})
    ok(f"Bot {name} ({bot_id}/{alias_id}) is on the instance")


if __name__ == "__main__":
    cli(__doc__, {"bot": bot})
