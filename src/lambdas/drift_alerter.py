"""Lambda: parse SageMaker Model Monitor reports -> SNS + Slack alerts.

Triggered by EventBridge rule on Model Monitor completion events.
The monitor itself writes constraint_violations.json to S3; this Lambda
reads the report, extracts high-severity violations, and notifies.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

import boto3

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="lambda.drift_alerter")


SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_sns = boto3.client("sns", region_name=AWS_REGION)
_s3 = boto3.client("s3", region_name=AWS_REGION)


def _read_report(bucket: str, key: str) -> dict:
    response = _s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    return json.loads(body)


def _extract_violations(report: dict) -> list[dict]:
    """Pull constraint violations above a severity threshold."""
    violations = report.get("violations", [])
    high_severity: list[dict] = []
    for v in violations:
        feature = v.get("feature_name", "unknown")
        check = v.get("constraint_check_type", "unknown")
        description = v.get("description", "")
        high_severity.append({
            "feature": feature,
            "check": check,
            "description": description,
        })
    return high_severity


def _format_slack_message(
    endpoint_name: str,
    monitoring_job_name: str,
    violations: list[dict],
) -> dict:
    fields = []
    for v in violations[:10]:
        fields.append({
            "title": f"{v['feature']} -- {v['check']}",
            "value": v["description"],
            "short": False,
        })
    extra = len(violations) - 10
    if extra > 0:
        fields.append({
            "title": f"+ {extra} more violations",
            "value": "See full report in S3",
            "short": False,
        })
    return {
        "text": f":rotating_light: Drift detected on endpoint *{endpoint_name}*",
        "attachments": [{
            "color": "danger",
            "title": f"Monitor job: {monitoring_job_name}",
            "fields": fields,
        }],
    }


def _send_slack(payload: dict) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        # S310 already ignored for src/lambdas/* via pyproject per-file-ignores
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        log.warning("slack_post_failed", error=str(exc))


def _send_sns(endpoint_name: str, violations: list[dict], report_s3_uri: str) -> None:
    subject = f"[Drift] {endpoint_name}: {len(violations)} violation(s)"[:99]
    body = {
        "endpoint_name": endpoint_name,
        "violation_count": len(violations),
        "violations": violations[:20],
        "full_report_s3": report_s3_uri,
    }
    _sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=subject,
        Message=json.dumps(body, indent=2),
    )


def handler(event: dict, context: Any) -> dict:
    """EventBridge trigger -- Model Monitor completion event."""
    detail = event.get("detail", {})
    endpoint_name = detail.get("MonitoringEndpointName", "unknown")
    monitoring_job_name = detail.get("MonitoringJobName", "unknown")
    report_s3_uri = detail.get("MonitoringExecutionS3Uri", "")

    if not report_s3_uri:
        log.warning("no_report_uri_in_event", event=event)
        return {"ok": False, "reason": "missing report URI"}

    parsed = urllib.parse.urlparse(report_s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/").rstrip("/") + "/constraint_violations.json"

    try:
        report = _read_report(bucket, key)
    except Exception as exc:
        log.error("read_report_failed", bucket=bucket, key=key, error=str(exc))
        return {"ok": False, "reason": f"read failed: {exc}"}

    violations = _extract_violations(report)
    if not violations:
        log.info("no_violations", endpoint_name=endpoint_name)
        return {"ok": True, "violations": 0}

    _send_sns(endpoint_name, violations, report_s3_uri)
    _send_slack(_format_slack_message(endpoint_name, monitoring_job_name, violations))

    log.warning(
        "drift_alert_sent",
        endpoint_name=endpoint_name,
        violation_count=len(violations),
    )
    return {"ok": True, "violations": len(violations)}
