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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRIGGER_CODEPOINTS = "6700,65B0,60C5,5831"
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
        "child_exit_code": result.returncode,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or manually run LINE regression targets.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--response-timeout", type=float, default=90.0)
    parser.add_argument("--execute", action="store_true", help="Explicitly run the two guarded regression targets.")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
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
        summary["targets"] = [run_target(repo_root, target, args.response_timeout) for target in REGRESSION_TARGETS]
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
