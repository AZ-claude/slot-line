#!/usr/bin/env python3
"""Run the two fixed Phase 1 adapters once and print a compact run summary.

This is a manual-run coordinator only.  It does not create or modify a
Task Scheduler task and deliberately keeps each adapter as a separate child
process so one store failure does not prevent the other store from running.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ADAPTERS = (
    {
        "store_id": "m_and_m_mizoguchi",
        "script": "run_m_and_m_mizoguchi.py",
        "adapter_type": "passive",
    },
    {
        "store_id": "pia_machida",
        "script": "run_pia_machida.py",
        "adapter_type": "text_trigger",
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_adb_health() -> dict[str, Any]:
    adb = shutil.which("adb")
    if not adb:
        return {"status": "android_unreachable", "serial": None, "errors": ["adb_not_found"]}
    try:
        result = subprocess.run(
            [adb, "devices"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "android_unreachable", "serial": None, "errors": ["adb_devices_timeout"]}
    devices = [
        parts[0]
        for line in result.stdout.splitlines()
        if len(parts := line.split()) >= 2 and parts[1] == "device"
    ]
    if result.returncode != 0:
        return {"status": "android_unreachable", "serial": None, "errors": ["adb_devices_failed"]}
    if not devices:
        return {"status": "android_unreachable", "serial": None, "errors": ["no_android_device"]}
    return {"status": "success", "serial": devices[0], "errors": []}


def parse_child_record(stdout: str) -> dict[str, Any] | None:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(stdout[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def split_warnings(errors: Any) -> tuple[list[Any], list[Any]]:
    errors_out: list[Any] = []
    warnings_out: list[Any] = []
    for item in errors if isinstance(errors, list) else []:
        code = item.get("code", "") if isinstance(item, dict) else str(item)
        if "warning" in code:
            warnings_out.append(item)
        else:
            errors_out.append(item)
    return errors_out, warnings_out


def run_adapter(repo_root: Path, adapter: dict[str, str], timeout: float, force_trigger: bool) -> dict[str, Any]:
    script = repo_root / "scripts" / adapter["script"]
    if not script.exists():
        script = Path(__file__).resolve().parent / adapter["script"]
    command = [sys.executable, str(script), "--repo-root", str(repo_root)]
    if force_trigger and adapter["store_id"] == "pia_machida":
        command.append("--force-trigger")
    try:
        result = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "store_id": adapter["store_id"],
            "adapter_type": adapter["adapter_type"],
            "status": "extraction_failed",
            "message_count": 0,
            "image_count": 0,
            "errors": [{"code": "adapter_timeout", "detail": adapter["script"]}],
            "warnings": [],
            "raw_path": str(repo_root / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / adapter["store_id"]),
        }

    record = parse_child_record(result.stdout)
    if record is None:
        detail = (result.stderr or result.stdout).strip().replace("\r", " ").replace("\n", " ")
        return {
            "store_id": adapter["store_id"],
            "adapter_type": adapter["adapter_type"],
            "status": "extraction_failed",
            "message_count": 0,
            "image_count": 0,
            "errors": [{"code": "adapter_output_invalid", "detail": detail[:300]}],
            "warnings": [],
            "raw_path": str(repo_root / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / adapter["store_id"]),
        }

    errors, warnings = split_warnings(record.get("errors", []))
    if result.returncode != 0 and not errors:
        errors.append({"code": record.get("status", "adapter_failed"), "detail": adapter["script"]})
    summary = {
        "store_id": record.get("store_id", adapter["store_id"]),
        "adapter_type": record.get("adapter_type", adapter["adapter_type"]),
        "status": record.get("status", "extraction_failed"),
        "message_count": int(record.get("message_count", 0) or 0),
        "stored_message_count_total": int(record.get("stored_message_count_total", 0) or 0),
        "image_count": int(record.get("image_count", 0) or 0),
        "errors": errors,
        "warnings": warnings,
        "raw_path": str(repo_root / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / adapter["store_id"]),
        "run_id": record.get("run_id"),
    }
    for field in ("skip_reason", "previous_run_id", "previous_status", "previous_triggered_at"):
        if field in record:
            summary[field] = record[field]
    return summary


def determine_overall_status(health_status: str, adapters: list[dict[str, Any]]) -> str:
    """Keep an attempted-but-skipped trigger visible as a partial failure."""
    success_like = {"success", "skipped_already_successful"}
    if health_status == "success" and all(item["status"] in success_like for item in adapters):
        return "success"
    if any(item["status"] in success_like or item["status"] == "skipped_already_attempted" for item in adapters):
        return "partial_failure"
    return "failure"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run both fixed Phase 1 LINE adapters once.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--adapter-timeout", type=float, default=180.0)
    parser.add_argument(
        "--force-trigger",
        action="store_true",
        help="Explicitly allow a new PIA text trigger when today's trigger was already attempted.",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    started_at = utc_now()
    health = check_adb_health()
    adapters = [run_adapter(repo_root, adapter, args.adapter_timeout, args.force_trigger) for adapter in ADAPTERS]
    overall_status = determine_overall_status(health["status"], adapters)
    summary = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": overall_status,
        "adb_health": health,
        "adapters": adapters,
        "task_scheduler_changed": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if overall_status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
