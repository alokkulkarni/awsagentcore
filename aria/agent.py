"""Creates and returns the ARIA banking agent instance."""

import os
import logging
from strands import Agent
from strands.models.bedrock import BedrockModel
from aria.system_prompt import ARIA_SYSTEM_PROMPT
from aria.tools import ALL_TOOLS

logger = logging.getLogger("aria.agent")

# anthropic.claude-sonnet-4-6 is available on-demand in all regions below.
_REGION_MODEL_DEFAULTS: dict[str, str] = {
    "us-east-1":      "anthropic.claude-sonnet-4-6",
    "us-west-2":      "anthropic.claude-sonnet-4-6",
    "eu-west-1":      "anthropic.claude-sonnet-4-6",
    "eu-west-2":      "anthropic.claude-sonnet-4-6",
    "eu-central-1":   "anthropic.claude-sonnet-4-6",
    "ap-southeast-1": "anthropic.claude-sonnet-4-6",
    "ap-northeast-1": "anthropic.claude-sonnet-4-6",
}
_FALLBACK_MODEL = "anthropic.claude-sonnet-4-6"


def _resolve_model_id(region: str) -> str:
    """Return the correct model ID for the given AWS region.

    If BEDROCK_MODEL_ID is explicitly set in the environment it always takes
    precedence.  Otherwise we pick the appropriate cross-region inference
    profile (or direct model ID) for the region so callers don't have to
    remember which prefix to use.
    """
    explicit = os.getenv("BEDROCK_MODEL_ID", "").strip()
    if explicit:
        return explicit
    model_id = _REGION_MODEL_DEFAULTS.get(region, _FALLBACK_MODEL)
    logger.debug("Resolved model ID '%s' for region '%s'", model_id, region)
    return model_id


def _build_boto_session(region: str):
    """Build a boto3 Session using the standard AWS credential chain.

    Resolution order (boto3 default chain, highest → lowest priority):
      1. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN env vars
      2. AWS_PROFILE env var  →  named profile in ~/.aws/credentials
      3. AWS_DEFAULT_PROFILE  →  named profile in ~/.aws/credentials
      4. [default] profile in ~/.aws/credentials
      5. IAM role attached to EC2 / ECS / Lambda instance metadata
      6. AWS SSO / credential_process entries in ~/.aws/config

    If AWS_ROLE_ARN is set the session assumes that role using STS before
    returning, which covers cross-account or least-privilege deployments.
    In all other cases the raw local credentials are used with no extra hops.
    """
    import boto3
    from botocore.exceptions import NoCredentialsError, ClientError

    profile = os.getenv("AWS_PROFILE") or os.getenv("AWS_DEFAULT_PROFILE")
    role_arn = os.getenv("AWS_ROLE_ARN", "").strip()
    role_session = os.getenv("AWS_ROLE_SESSION_NAME", "aria-banking-agent")

    if profile:
        logger.info("Using AWS named profile: %s", profile)
        session = boto3.Session(profile_name=profile, region_name=region)
    else:
        logger.info("Using default AWS credential chain (env vars / instance role / ~/.aws/credentials)")
        session = boto3.Session(region_name=region)

    # Validate credentials are resolvable before trying to assume a role
    try:
        identity = session.client("sts").get_caller_identity()
        logger.info(
            "AWS credentials resolved | account=%s arn=%s",
            identity.get("Account"),
            identity.get("Arn"),
        )
    except NoCredentialsError:
        logger.error(
            "No AWS credentials found. Configure one of: "
            "AWS_ACCESS_KEY_ID env vars, ~/.aws/credentials, or an IAM instance role."
        )
        raise
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        # ExpiredTokenException / InvalidClientTokenId are common mis-config signals
        logger.error("AWS STS credential check failed [%s]: %s", code, exc)
        raise

    if role_arn:
        logger.info("Assuming IAM role: %s (session: %s)", role_arn, role_session)
        sts = session.client("sts")
        assumed = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=role_session,
        )
        creds = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
        logger.info("Successfully assumed role: %s", role_arn)

    return session


def create_aria_agent(prior_history_block: str = "") -> Agent:
    """Creates and returns the ARIA banking agent with all tools registered.

    Args:
        prior_history_block: Optional cross-session memory block to prepend to
            the system prompt. When provided it mirrors what agentcore_voice.py
            does: injecting AgentCore Memory turns as ``=== RECENT CONVERSATION
            HISTORY ===`` before the static ARIA_SYSTEM_PROMPT.  Should only be
            set at agent creation (first turn of a new session), never on
            subsequent turns — the Strands agent accumulates its own history in
            agent.messages across turns.
    """
    region = os.getenv("AWS_REGION", "eu-west-2")
    model_id = _resolve_model_id(region)

    session = _build_boto_session(region)

    logger.info("Initialising BedrockModel | region=%s model=%s", region, model_id)

    model = BedrockModel(
        model_id=model_id,
        boto_session=session,
    )

    system_prompt = (
        prior_history_block + ARIA_SYSTEM_PROMPT
        if prior_history_block
        else ARIA_SYSTEM_PROMPT
    )

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        tools=ALL_TOOLS,
        callback_handler=None,  # silence streaming — main.py controls all terminal output
    )
    return agent
