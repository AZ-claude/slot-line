#!/usr/bin/env python3
"""Convert canonical LINE RAW into deterministic store-day observations."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
DEFAULT_SOURCE = "official_line"
ADAPTER_TYPES = {"passive", "text_trigger", "android_ui_trigger", "unknown"}
SUCCESS_STATUSES = {"success", "skipped_already_successful"}
KNOWN_FAILURE_CODES = {
    "response_timeout",
    "trigger_failed",
    "android_unreachable",
    "extraction_failed",
    "image_save_failed",
    "pull_failed",
    "skipped_already_attempted",
}


class LineDailyValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_json:{path}") from exc


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    raise ValueError("manifest must be an object or list")


def _status(record: dict[str, Any]) -> str:
    return str(record.get("status") or record.get("acquisition_status") or "unknown")


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _latest_timestamp(records: Iterable[dict[str, Any]]) -> str | None:
    candidates: list[tuple[datetime, str]] = []
    for record in records:
        for field in ("finished_at", "received_at", "triggered_at", "started_at"):
            value = record.get(field)
            parsed = _parse_datetime(value)
            if parsed is not None:
                candidates.append((parsed, str(value)))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _record_order(record: dict[str, Any]) -> tuple[datetime, str]:
    for field in ("finished_at", "received_at", "triggered_at", "started_at"):
        parsed = _parse_datetime(record.get(field))
        if parsed is not None:
            return parsed, str(record.get("run_id") or "")
    return datetime.min.replace(tzinfo=timezone.utc), str(record.get("run_id") or "")


def _message_rows(raw_dir: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages_path = raw_dir / "messages.json"
    if messages_path.exists():
        value = _load_json(messages_path, [])
        if not isinstance(value, list):
            raise ValueError("messages.json must contain an array")
        return [item for item in value if isinstance(item, dict)]

    # The first RAW schema version only had message_types/message_times in the
    # manifest. Keep this read-only compatibility path for those existing RAWs.
    rows: list[dict[str, Any]] = []
    for record in records:
        if _status(record) not in SUCCESS_STATUSES:
            continue
        types = record.get("message_types") or []
        times = record.get("message_times") or []
        if not isinstance(types, list):
            continue
        for index, message_type in enumerate(types):
            rows.append(
                {
                    "message_type": message_type,
                    "line_display_time": times[index] if index < len(times) else None,
                }
            )
    return rows


def _message_summary(messages: list[dict[str, Any]]) -> dict[str, Any]:
    times = sorted(
        str(message["line_display_time"])
        for message in messages
        if isinstance(message.get("line_display_time"), str) and message["line_display_time"]
    )
    types = sorted(
        {
            str(message["message_type"])
            for message in messages
            if isinstance(message.get("message_type"), str) and message["message_type"]
        }
    )
    return {
        "count": len(messages),
        "first_display_time": times[0] if times else None,
        "last_display_time": times[-1] if times else None,
        "types": types,
    }


def _raw_refs(records: list[dict[str, Any]], messages: list[dict[str, Any]], raw_dir: Path, repo_root: Path) -> dict[str, Any]:
    run_ids = sorted({str(record["run_id"]) for record in records if record.get("run_id")})
    message_refs = sorted(
        {
            str(message[key])
            for message in messages
            for key in ("message_id", "id", "ref")
            if message.get(key)
        }
    )
    try:
        directory = raw_dir.relative_to(repo_root).as_posix()
    except ValueError:
        directory = raw_dir.as_posix()
    return {"directory": directory, "run_ids": run_ids, "message_refs": message_refs}


def _failure_code(records: list[dict[str, Any]]) -> str | None:
    if not records:
        return None
    latest = max(records, key=_record_order)
    status = _status(latest)
    if status == "skipped_already_attempted":
        previous = latest.get("previous_status")
        if isinstance(previous, str) and previous in KNOWN_FAILURE_CODES:
            return previous
        return status
    error = latest.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    errors = latest.get("errors")
    if isinstance(errors, list):
        for item in reversed(errors):
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                return item["code"]
    return status if status not in {"running", "unknown"} else None


def _trigger_value(records: list[dict[str, Any]], key: str) -> Any:
    values = [record.get(key) for record in records if record.get(key) not in (None, "")]
    return values[-1] if values else None


def _convert_records(
    records: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    store_id: str,
    date_text: str,
    raw_dir: Path,
    repo_root: Path,
) -> dict[str, Any]:
    records = sorted(records, key=_record_order)
    source = str(next((record.get("source") for record in records if record.get("source")), DEFAULT_SOURCE))
    acquisition_type = str(next((record.get("adapter_type") for record in records if record.get("adapter_type")), "unknown"))
    if acquisition_type not in ADAPTER_TYPES:
        acquisition_type = "unknown"

    statuses = {_status(record) for record in records}
    if not records:
        collection_status = "not_checked"
    elif statuses & SUCCESS_STATUSES:
        collection_status = "success"
    elif "skipped_already_attempted" in statuses or "partial" in statuses:
        collection_status = "partial"
    else:
        collection_status = "failed"

    message_info = _message_summary(messages)
    has_messages = message_info["count"] > 0
    line_update = (
        "present"
        if has_messages
        else "absent"
        if collection_status == "success"
        else "unknown"
    )

    required = acquisition_type == "text_trigger"
    triggered = [record for record in records if record.get("triggered_at")]
    actual_success = [record for record in records if _status(record) == "success"]
    successful_skip = [record for record in records if _status(record) == "skipped_already_successful"]
    trigger = {
        "required": required,
        "performed": bool(triggered) if records else None,
        "action": "send_text" if required else None,
        "text": _trigger_value(records, "trigger_text") if required else None,
        "triggered_at": _trigger_value(triggered, "triggered_at"),
        "result": None,
    }
    if required:
        if actual_success:
            trigger["result"] = "sent" if triggered else "received"
        elif successful_skip:
            trigger["result"] = "skipped_already_successful"
        elif records:
            trigger["result"] = _status(max(records, key=_record_order))

    summary_status = "not_applicable" if line_update == "absent" else "pending"
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": store_id,
        "date": date_text,
        "source": source,
        "acquisition_type": acquisition_type,
        "collection": {
            "status": collection_status,
            "checked_at": _latest_timestamp(records),
            "failure_code": None if collection_status in {"success", "not_checked"} else _failure_code(records),
        },
        "line_update": line_update,
        "trigger": trigger,
        "messages": message_info,
        "summary": {
            "status": summary_status,
            "text": None,
            "generated_at": None,
            "generator": None,
        },
        "raw_refs": _raw_refs(records, messages, raw_dir, repo_root),
    }


def convert_raw_directory(raw_dir: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    raw_dir = raw_dir.resolve()
    if raw_dir.name == "" or raw_dir.parent.name == "":
        raise ValueError(f"invalid_raw_directory:{raw_dir}")
    date_text = raw_dir.parent.name
    store_id = raw_dir.name
    try:
        date.fromisoformat(date_text)
    except ValueError as exc:
        raise ValueError(f"invalid_date_directory:{date_text}") from exc
    manifest = _load_json(raw_dir / "manifest.json", [])
    records = _records(manifest)
    messages = _message_rows(raw_dir, records)
    return _convert_records(
        records,
        messages,
        store_id=store_id,
        date_text=date_text,
        raw_dir=raw_dir,
        repo_root=(repo_root or raw_dir.parents[3]).resolve(),
    )


def make_not_checked(
    store_id: str,
    date_text: str,
    *,
    repo_root: Path,
    acquisition_type: str = "unknown",
    source: str = DEFAULT_SOURCE,
) -> dict[str, Any]:
    if acquisition_type not in ADAPTER_TYPES:
        raise ValueError(f"invalid_acquisition_type:{acquisition_type}")
    raw_dir = repo_root / "data" / "raw" / date_text / store_id
    result = _convert_records(
        [],
        [],
        store_id=store_id,
        date_text=date_text,
        raw_dir=raw_dir,
        repo_root=repo_root,
    )
    result["source"] = source
    result["acquisition_type"] = acquisition_type
    result["trigger"]["required"] = acquisition_type == "text_trigger"
    result["trigger"]["action"] = "send_text" if acquisition_type == "text_trigger" else None
    return result


def load_store_ids(master_path: Path) -> set[str]:
    with master_path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        field = "store_id" if "store_id" in (rows.fieldnames or []) else "hall_id"
        if field not in (rows.fieldnames or []):
            raise ValueError(f"store_id_column_missing:{master_path}")
        return {str(row[field]).strip() for row in rows if row.get(field)}


def _require(mapping: dict[str, Any], key: str, errors: list[str], path: str) -> Any:
    if key not in mapping:
        errors.append(f"{path}.{key}:required")
        return None
    return mapping[key]


def _check_string(value: Any, errors: list[str], path: str, *, allow_null: bool = False, pattern: str | None = None) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str):
        errors.append(f"{path}:string")
        return
    if pattern and re.fullmatch(pattern, value) is None:
        errors.append(f"{path}:format")


def validate_observation(value: Any, *, known_store_ids: Iterable[str] | None = None) -> None:
    errors: list[str] = []
    if not isinstance(value, dict):
        raise LineDailyValidationError(["$:object"])

    schema_version = _require(value, "schema_version", errors, "$")
    if schema_version != SCHEMA_VERSION:
        errors.append("$.schema_version:unsupported")
    store_id = _require(value, "store_id", errors, "$")
    _check_string(store_id, errors, "$.store_id", pattern=r"[a-z0-9][a-z0-9_-]*")
    if known_store_ids is not None and store_id not in set(known_store_ids):
        errors.append("$.store_id:unknown")
    date_text = _require(value, "date", errors, "$")
    _check_string(date_text, errors, "$.date", pattern=r"\d{4}-\d{2}-\d{2}")
    if isinstance(date_text, str):
        try:
            date.fromisoformat(date_text)
        except ValueError:
            errors.append("$.date:invalid")
    source = _require(value, "source", errors, "$")
    _check_string(source, errors, "$.source")
    acquisition_type = _require(value, "acquisition_type", errors, "$")
    if acquisition_type not in ADAPTER_TYPES:
        errors.append("$.acquisition_type:enum")

    collection = _require(value, "collection", errors, "$")
    if isinstance(collection, dict):
        status = _require(collection, "status", errors, "$.collection")
        if status not in {"success", "partial", "failed", "not_checked"}:
            errors.append("$.collection.status:enum")
        checked_at = _require(collection, "checked_at", errors, "$.collection")
        if checked_at is not None and _parse_datetime(checked_at) is None:
            errors.append("$.collection.checked_at:date-time")
        failure_code = _require(collection, "failure_code", errors, "$.collection")
        if failure_code is not None:
            _check_string(failure_code, errors, "$.collection.failure_code")

    line_update = _require(value, "line_update", errors, "$")
    if line_update not in {"present", "absent", "unknown"}:
        errors.append("$.line_update:enum")

    trigger = _require(value, "trigger", errors, "$")
    if isinstance(trigger, dict):
        required = _require(trigger, "required", errors, "$.trigger")
        if not isinstance(required, bool):
            errors.append("$.trigger.required:boolean")
        performed = _require(trigger, "performed", errors, "$.trigger")
        if performed is not None and not isinstance(performed, bool):
            errors.append("$.trigger.performed:boolean|null")
        for key in ("action", "text", "triggered_at", "result"):
            item = _require(trigger, key, errors, "$.trigger")
            if key == "triggered_at" and item is not None and _parse_datetime(item) is None:
                errors.append("$.trigger.triggered_at:date-time")

    messages = _require(value, "messages", errors, "$")
    if isinstance(messages, dict):
        count = _require(messages, "count", errors, "$.messages")
        if not isinstance(count, int) or count < 0:
            errors.append("$.messages.count:nonnegative-integer")
        for key in ("first_display_time", "last_display_time"):
            item = _require(messages, key, errors, "$.messages")
            if item is not None and (not isinstance(item, str) or re.fullmatch(r"\d{2}:\d{2}", item) is None):
                errors.append(f"$.messages.{key}:HH:MM|null")
        types = _require(messages, "types", errors, "$.messages")
        if not isinstance(types, list) or not all(isinstance(item, str) for item in types):
            errors.append("$.messages.types:string-array")

    summary = _require(value, "summary", errors, "$")
    if isinstance(summary, dict):
        summary_status = _require(summary, "status", errors, "$.summary")
        if summary_status not in {"pending", "generated", "not_applicable", "failed"}:
            errors.append("$.summary.status:enum")
        text = _require(summary, "text", errors, "$.summary")
        generated_at = _require(summary, "generated_at", errors, "$.summary")
        generator = _require(summary, "generator", errors, "$.summary")
        if text is not None and not isinstance(text, str):
            errors.append("$.summary.text:string|null")
        if generated_at is not None and _parse_datetime(generated_at) is None:
            errors.append("$.summary.generated_at:date-time")
        if generator is not None and not isinstance(generator, str):
            errors.append("$.summary.generator:string|null")
        if summary_status == "generated" and (not text or not generated_at or not generator):
            errors.append("$.summary.generated:requires-text-generated_at-generator")

    raw_refs = _require(value, "raw_refs", errors, "$")
    if isinstance(raw_refs, dict):
        directory = _require(raw_refs, "directory", errors, "$.raw_refs")
        _check_string(directory, errors, "$.raw_refs.directory")
        for key in ("run_ids", "message_refs"):
            refs = _require(raw_refs, key, errors, "$.raw_refs")
            if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
                errors.append(f"$.raw_refs.{key}:string-array")

    if isinstance(collection, dict) and collection.get("status") == "not_checked" and collection.get("checked_at") is not None:
        errors.append("$.collection.not_checked_requires-null-checked_at")
    if line_update == "absent" and isinstance(collection, dict) and collection.get("status") != "success":
        errors.append("$.line_update.absent-requires-success")
    if errors:
        raise LineDailyValidationError(errors)


def write_observation(observation: dict[str, Any], path: Path, *, known_store_ids: Iterable[str] | None = None) -> None:
    validate_observation(observation, known_store_ids=known_store_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser("convert")
    convert.add_argument("raw_dir", type=Path)
    convert.add_argument("--repo-root", type=Path)
    convert.add_argument("--output", type=Path)
    convert.add_argument("--store-master", type=Path)

    not_checked = subparsers.add_parser("not-checked")
    not_checked.add_argument("--repo-root", type=Path, required=True)
    not_checked.add_argument("--date", dest="date_text", required=True)
    not_checked.add_argument("--store-id", action="append", required=True)
    not_checked.add_argument("--output-root", type=Path)
    not_checked.add_argument("--store-master", type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("path", type=Path)
    validate.add_argument("--store-master", type=Path)

    args = parser.parse_args()
    if args.command == "convert":
        repo_root = (args.repo_root or args.raw_dir.parents[3]).resolve()
        observation = convert_raw_directory(args.raw_dir, repo_root=repo_root)
        known = load_store_ids(args.store_master) if args.store_master else None
        write_observation(observation, args.output or repo_root / "data" / "normalized" / "line_daily" / observation["date"] / f"{observation['store_id']}.json", known_store_ids=known)
    elif args.command == "not-checked":
        known = load_store_ids(args.store_master) if args.store_master else None
        output_root = (args.output_root or args.repo_root / "data" / "normalized" / "line_daily").resolve()
        for store_id in sorted(args.store_id):
            observation = make_not_checked(store_id, args.date_text, repo_root=args.repo_root.resolve())
            write_observation(observation, output_root / args.date_text / f"{store_id}.json", known_store_ids=known)
    else:
        observation = _load_json(args.path, {})
        known = load_store_ids(args.store_master) if args.store_master else None
        validate_observation(observation, known_store_ids=known)
        print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
