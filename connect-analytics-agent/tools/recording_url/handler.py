import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_parameters

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)


def _parse_s3_location(location: str):
    if location.startswith("s3://"):
        parsed = urlparse(location)
        return parsed.netloc, parsed.path.lstrip("/")
    parsed = urlparse(location)
    if parsed.scheme in ("http", "https") and ".s3" in parsed.netloc:
        bucket = parsed.netloc.split(".s3", 1)[0]
        return bucket, parsed.path.lstrip("/")
    # Bare "bucket/key" format returned by Amazon Connect describe_contact
    if "/" in location:
        bucket, _, key = location.partition("/")
        return bucket, key
    raise ValueError(f"Unsupported recording location format: {location}")


def lambda_handler(event, _context):
    try:
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        contact_id = params.get("contact_id")
        if not contact_id:
            raise ValueError("contact_id is required.")

        expiry_seconds = min(int(params.get("expiry_seconds") or 3600), 43200)
        connect_client = boto3.client("connect")
        s3_client = boto3.client("s3")

        contact = connect_client.describe_contact(InstanceId=instance_id, ContactId=contact_id).get("Contact", {})
        recordings = contact.get("Recordings", [])
        if not recordings:
            return build_response(
                event,
                {
                    "contact_id": contact_id,
                    "message": "No recording is available for this contact.",
                    "url": None,
                },
                status_code=200,
            )

        recording = recordings[0]
        location = recording.get("Location")
        bucket, key = _parse_s3_location(location)
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry_seconds,
        )

        start = recording.get("StartTimestamp")
        stop = recording.get("StopTimestamp")
        duration_seconds = max((stop - start).total_seconds(), 0) if start and stop else None

        return build_response(
            event,
            {
                "contact_id": contact_id,
                "url": url,
                "expiry_seconds": expiry_seconds,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds),
                "recording": {
                    "bucket": bucket,
                    "key": key,
                    "location": location,
                    "storage_type": recording.get("StorageType"),
                    "participant_type": recording.get("ParticipantType"),
                    "media_stream_type": recording.get("MediaStreamType"),
                    "status": recording.get("Status"),
                    "format": key.rsplit(".", 1)[-1].lower() if "." in key else None,
                    "duration_seconds": duration_seconds,
                    "duration": format_duration(duration_seconds),
                },
            },
        )
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to generate recording URL")
        return build_error_response(event, "Unable to generate an Amazon Connect recording URL", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while generating recording URL")
        return build_error_response(event, "An unexpected error occurred while generating the recording URL", status_code=500)
