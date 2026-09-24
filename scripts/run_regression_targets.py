#!/usr/bin/env python3
"""Manual-only runner for the fixed LINE regression targets.

This runner is intentionally separate from ``run_daily.py``.  It has no
Task Scheduler integration and defaults to a no-send plan.  ``--execute`` is
required before either target process can be started; each child keeps its
own collector directory and same-day trigger guard.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid


TRIGGER_CODEPOINTS = "6700,65B0,60C5,5831"
LINE_PACKAGE = "jp.naver.line.android"
REGRESSION_TARGETS: tuple[dict[str, str], ...] = (
    {
        "name": "pia_machida",
        "role": "non-Kanagawa regression",
        "collector_key": "pia_machida",
        "line_source_key": "@030pwlwx",
        "target_title_codepoints": "0050,0049,0041,753A,7530",
        "trigger_codepoints": TRIGGER_CODEPOINTS,
        "script": "run_pia_machida.py",
    },
    {
        "name": "pia-keiky-kawasaki",
        "role": "Kanagawa regression",
        "collector_key": "pia-keiky-kawasaki",
        "line_source_key": "@rmh1818e",
        "target_title_codepoints": "0050,0049,0041,0020,4EAC,6025,5DDD,5D0E",
        "trigger_codepoints": TRIGGER_CODEPOINTS,
        "script": "run_pia_machida.py",
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_target_configs(targets: tuple[dict[str, str], ...] = REGRESSION_TARGETS) -> None:
    required = {
        "name",
        "role",
        "collector_key",
        "line_source_key",
        "target_title_codepoints",
        "trigger_codepoints",
        "script",
    }
    seen_collectors: set[str] = set()
    seen_sources: set[str] = set()
    for target in targets:
        missing = required - set(target)
        if missing:
            raise ValueError(f"regression_target_missing:{','.join(sorted(missing))}")
        collector_key = target["collector_key"]
        line_source_key = target["line_source_key"]
        if collector_key in seen_collectors:
            raise ValueError(f"duplicate_collector_key:{collector_key}")
        if line_source_key in seen_sources:
            raise ValueError(f"duplicate_line_source_key:{line_source_key}")
        seen_collectors.add(collector_key)
        seen_sources.add(line_source_key)
        if target["script"] != "run_pia_machida.py":
            raise ValueError(f"unsupported_regression_script:{target['script']}")


def build_command(repo_root: Path, target: dict[str, str], response_timeout: float) -> list[str]:
    validate_target_configs((target,))
    script = repo_root / "scripts" / target["script"]
    return [
        sys.executable,
        str(script),
        "--repo-root",
        str(repo_root),
        "--collector-key",
        target["collector_key"],
        "--target-title-codepoints",
        target["target_title_codepoints"],
        "--line-source-key",
        target["line_source_key"],
        "--trigger-codepoints",
        target["trigger_codepoints"],
        "--trigger-mode",
        "url",
        "--response-timeout",
        str(response_timeout),
    ]


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


def regression_log_path(repo_root: Path, date_text: str | None = None) -> Path:
    date_value = date_text or datetime.now().strftime("%Y-%m-%d")
    return repo_root / "data" / "logs" / f"regression_{date_value}.log"


def append_regression_log(repo_root: Path, execution_id: str, result: dict[str, Any]) -> Path:
    path = regression_log_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "execution_id": execution_id,
        "target": result.get("name"),
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "collector_key": result.get("collector_key"),
        "line_source_key": result.get("line_source_key"),
        "message_count": int(result.get("message_count", 0) or 0),
        "raw_path": result.get("raw_path"),
        "skip_reason": result.get("skip_reason"),
        "previous_run_id": result.get("previous_run_id"),
        "process_exit_code": result.get("process_exit_code"),
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    with os.fdopen(descriptor, "a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def check_adb_health() -> dict[str, Any]:
    adb = shutil.which("adb")
    if not adb:
        return {"status": "android_unreachable", "adb": None, "serial": None, "errors": ["adb_not_found"]}
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
        return {"status": "android_unreachable", "adb": adb, "serial": None, "errors": ["adb_devices_timeout"]}
    devices = [
        parts[0]
        for line in result.stdout.splitlines()
        if len(parts := line.split()) >= 2 and parts[1] == "device"
    ]
    if result.returncode != 0:
        return {"status": "android_unreachable", "adb": adb, "serial": None, "errors": ["adb_devices_failed"]}
    if not devices:
        return {"status": "android_unreachable", "adb": adb, "serial": None, "errors": ["no_android_device"]}
    return {"status": "success", "adb": adb, "serial": devices[0], "errors": []}


def check_line_package(health: dict[str, Any]) -> dict[str, Any]:
    adb = health.get("adb")
    serial = health.get("serial")
    if health.get("status") != "success" or not adb or not serial:
        return {"name": LINE_PACKAGE, "status": "not_checked", "path": None}
    try:
        result = subprocess.run(
            [adb, "-s", serial, "shell", "pm", "path", LINE_PACKAGE],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"name": LINE_PACKAGE, "status": "check_timeout", "path": None}
    path = result.stdout.strip()
    return {
        "name": LINE_PACKAGE,
        "status": "present" if result.returncode == 0 and path else "missing",
        "path": path or None,
    }


def run_dry_run(repo_root: Path) -> tuple[dict[str, Any], int]:
    errors: list[dict[str, Any]] = []
    config = [
        {
            "target": target["name"],
            "collector_key": target["collector_key"],
            "line_source_key": target["line_source_key"],
        }
        for target in REGRESSION_TARGETS
    ]
    try:
        validate_target_configs()
        config_status = "valid"
    except ValueError as exc:
        config_status = "invalid"
        errors.append({"code": "config_invalid", "detail": str(exc)})

    repo_status = "present" if repo_root.is_dir() else "missing"
    if repo_status != "present":
        errors.append({"code": "repo_root_missing", "detail": str(repo_root)})
    scripts_status = "present" if all((repo_root / "scripts" / target["script"]).is_file() for target in REGRESSION_TARGETS) else "missing"
    if scripts_status != "present":
        errors.append({"code": "runner_script_missing"})

    health = check_adb_health()
    if health["status"] != "success":
        errors.append({"code": health["status"], "detail": health.get("errors", [])})
    line_package = check_line_package(health)
    if line_package["status"] != "present":
        errors.append({"code": "line_package_" + line_package["status"]})

    log_path = regression_log_path(repo_root)
    log_status = "writable"
    marker = log_path.with_name(f".{log_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("regression dry-run\n", encoding="utf-8")
        marker.unlink()
    except OSError as exc:
        log_status = "not_writable"
        errors.append({"code": "regression_log_not_writable", "detail": str(exc)})
        marker.unlink(missing_ok=True)

    result = {
        "mode": "dry_run",
        "started_at": utc_now(),
        "finished_at": None,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "repo_root": str(repo_root),
        "config": {"status": config_status, "targets": config, "force_trigger": False},
        "adb": health,
        "line_package": line_package,
        "log_path": str(log_path),
        "log_status": log_status,
        "scheduler_changed": False,
        "trigger_executed": False,
        "errors": errors,
    }
    result["status"] = "success" if not errors else "failure"
    result["finished_at"] = utc_now()
    return result, 0 if result["status"] == "success" else 1


def run_target(repo_root: Path, target: dict[str, str], response_timeout: float) -> dict[str, Any]:
    command = build_command(repo_root, target, response_timeout)
    try:
        result = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=response_timeout + 60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "name": target["name"],
            "collector_key": target["collector_key"],
            "line_source_key": target["line_source_key"],
            "status": "extraction_failed",
            "run_id": None,
            "message_count": 0,
            "raw_path": str(repo_root / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / target["collector_key"]),
            "skip_reason": None,
            "previous_run_id": None,
            "process_exit_code": None,
            "errors": [{"code": "regression_target_timeout"}],
        }

    record = parse_child_record(result.stdout)
    if record is None:
        detail = (result.stderr or result.stdout).strip().replace("\r", " ").replace("\n", " ")
        return {
            "name": target["name"],
            "collector_key": target["collector_key"],
            "line_source_key": target["line_source_key"],
            "status": "extraction_failed",
            "run_id": None,
            "message_count": 0,
            "raw_path": str(repo_root / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / target["collector_key"]),
            "skip_reason": None,
            "previous_run_id": None,
            "process_exit_code": result.returncode,
            "errors": [{"code": "regression_target_output_invalid", "detail": detail[:300]}],
        }

    return {
        "name": target["name"],
        "role": target["role"],
        "collector_key": target["collector_key"],
        "line_source_key": target["line_source_key"],
        "status": record.get("status", "extraction_failed"),
        "run_id": record.get("run_id"),
        "message_count": int(record.get("message_count", 0) or 0),
        "raw_path": str(repo_root / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / target["collector_key"]),
        "skip_reason": record.get("skip_reason"),
        "previous_run_id": record.get("previous_run_id"),
        "errors": record.get("errors", []),
        "process_exit_code": result.returncode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or manually run LINE regression targets.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--response-timeout", type=float, default=90.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Explicitly run the two guarded regression targets.")
    mode.add_argument("--dry-run", action="store_true", help="Check runtime, ADB, LINE, config, and log path without sending.")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.dry_run:
        dry_run, exit_code = run_dry_run(repo_root)
        print(json.dumps(dry_run, ensure_ascii=False, indent=2))
        return exit_code
    validate_target_configs()
    summary: dict[str, Any] = {
        "mode": "execute" if args.execute else "plan",
        "started_at": utc_now(),
        "finished_at": None,
        "scheduler_changed": False,
        "force_trigger": False,
        "targets": [],
    }
    if args.execute:
        execution_id = datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
        summary["execution_id"] = execution_id
        summary["targets"] = [run_target(repo_root, target, args.response_timeout) for target in REGRESSION_TARGETS]
        log_paths: set[Path] = set()
        for result in summary["targets"]:
            log_paths.add(append_regression_log(repo_root, execution_id, result))
        summary["log_path"] = str(next(iter(log_paths))) if log_paths else str(regression_log_path(repo_root))
    else:
        summary["targets"] = [
            {
                "name": target["name"],
                "role": target["role"],
                "collector_key": target["collector_key"],
                "line_source_key": target["line_source_key"],
                "command": build_command(repo_root, target, args.response_timeout),
                "status": "not_run",
            }
            for target in REGRESSION_TARGETS
        ]
    summary["finished_at"] = utc_now()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0
    success_like = {"success", "skipped_already_successful"}
    return 0 if all(item.get("status") in success_like for item in summary["targets"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
