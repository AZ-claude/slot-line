#!/usr/bin/env python3
"""Run the two fixed Phase 1 adapters once and print a compact run summary.

This is a manual-run coordinator only.  It does not create or modify a
Task Scheduler task and deliberately keeps each adapter as a separate child
process so one store failure does not prevent the other store from running.
The ``--dry-run`` path validates the scheduled runtime without invoking either
adapter or sending a LINE trigger.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
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
LINE_PACKAGE = "jp.naver.line.android"


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


def run_dry_run(repo_root: Path) -> tuple[dict[str, Any], int]:
    """Validate the scheduled execution path without running either adapter."""
    started_at = utc_now()
    result: dict[str, Any] = {
        "mode": "dry_run",
        "started_at": started_at,
        "finished_at": None,
        "status": "failure",
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "repo_root": str(repo_root),
        "working_directory": str(Path.cwd()),
        "adb": None,
        "adb_health": None,
        "android_command": None,
        "line_package": {"name": LINE_PACKAGE, "status": "not_checked", "path": None},
        "raw_storage": {"path": str(repo_root / "data" / "raw"), "status": "not_checked"},
        "errors": [],
        "warnings": [],
        "task_scheduler_changed": False,
    }

    adb = shutil.which("adb")
    result["adb"] = adb
    if not adb:
        result["errors"].append({"code": "adb_not_found"})
    else:
        health = check_adb_health()
        result["adb_health"] = health
        if health["status"] != "success":
            result["errors"].append({"code": health["status"], "detail": health.get("errors", [])})
        else:
            serial = health["serial"]
            command = [adb, "-s", serial, "shell", "getprop", "ro.build.version.release"]
            try:
                probe = subprocess.run(
                    command,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                result["android_command"] = {
                    "command": command,
                    "returncode": probe.returncode,
                    "stdout": probe.stdout.strip(),
                    "stderr": probe.stderr.strip(),
                }
                if probe.returncode != 0:
                    result["errors"].append({"code": "android_command_failed"})
            except subprocess.TimeoutExpired:
                result["errors"].append({"code": "android_command_timeout"})

            package_command = [adb, "-s", serial, "shell", "pm", "path", LINE_PACKAGE]
            try:
                package_probe = subprocess.run(
                    package_command,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                package_path = package_probe.stdout.strip()
                result["line_package"] = {
                    "name": LINE_PACKAGE,
                    "status": "present" if package_probe.returncode == 0 and package_path else "missing",
                    "path": package_path,
                }
                if result["line_package"]["status"] != "present":
                    result["errors"].append({"code": "line_package_missing"})
            except subprocess.TimeoutExpired:
                result["line_package"]["status"] = "check_timeout"
                result["errors"].append({"code": "line_package_check_timeout"})

    raw_path = repo_root / "data" / "raw"
    marker = raw_path / f".scheduler_dry_run_{uuid.uuid4().hex}.tmp"
    try:
        raw_path.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"slot-line dry-run {started_at}\n", encoding="utf-8")
        marker.unlink()
        result["raw_storage"] = {"path": str(raw_path), "status": "writable", "temporary_file_removed": True}
    except OSError as exc:
        result["raw_storage"] = {"path": str(raw_path), "status": "not_writable", "temporary_file_removed": False}
        result["errors"].append({"code": "raw_storage_not_writable", "detail": str(exc)})
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            result["warnings"].append({"code": "dry_run_marker_cleanup_failed"})

    result["status"] = "success" if not result["errors"] else "failure"
    result["finished_at"] = utc_now()
    return result, 0 if result["status"] == "success" else 1


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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate Python, ADB, Android, LINE package, and RAW storage without running adapters.",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.dry_run:
        dry_run, exit_code = run_dry_run(repo_root)
        print(json.dumps(dry_run, ensure_ascii=False, indent=2))
        return exit_code
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
