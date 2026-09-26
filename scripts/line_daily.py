#!/usr/bin/env python3
"""Convert canonical LINE RAW into deterministic hall/source-day observations."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


SCHEMA_VERSION = 2
DEFAULT_SOURCE = "official_line"
ADAPTER_TYPES = {"passive", "text_trigger", "android_ui_trigger", "unknown"}
ADAPTER_TYPE_PRIORITY = ("text_trigger", "android_ui_trigger", "passive", "unknown")
IDENTIFIER_PATTERN = r"[A-Za-z0-9@][A-Za-z0-9_.@:-]*"
SUCCESS_STATUSES = {"success", "skipped_already_successful"}
KNOWN_FAILURE_CODES = {
    "response_timeout",
    "trigger_failed",
    "android_unreachable",
    "extraction_failed",
    "image_save_failed",
    "pull_failed",
    "skipped_already_attempted",
    "skipped_cooldown",
}


class LineDailyValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class LineDailyIdentityError(ValueError):
    """Raised when RAW cannot be bound to one explicit hall/source identity."""

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
        return [dict(item) for item in value if isinstance(item, dict)]

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
                    "_manifest_index": record.get("_manifest_index"),
                    "line_source_key": _record_line_source_key(record),
                }
            )
    return rows


def _message_summary(messages: list[dict[str, Any]]) -> dict[str, Any]:
    times = sorted(
        _normalise_display_time(message["line_display_time"])
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


def _normalise_display_time(value: str) -> str:
    """Return a schema-compatible HH:MM value without changing the RAW row.

    Some Windows LINE UI captures emit a single-digit hour (for example
    ``0:40``).  The normalized schema deliberately keeps HH:MM, so pad only
    that harmless presentation difference and leave other invalid values for
    normal validation to reject.
    """
    match = re.fullmatch(r"(\d):(\d{2})", value)
    return f"0{match.group(1)}:{match.group(2)}" if match else value


def _raw_refs(
    records: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    raw_dir: Path,
    repo_root: Path,
    record_indices: Iterable[int],
) -> dict[str, Any]:
    run_ids = sorted({str(record["run_id"]) for record in records if record.get("run_id")})
    record_refs = [f"manifest.json#{index}" for index in sorted(set(record_indices))]
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
    return {
        "directory": directory,
        "run_ids": run_ids,
        "record_refs": record_refs,
        "message_refs": message_refs,
    }


def _line_source_from_value(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _record_line_source_key(record: dict[str, Any]) -> str | None:
    return _line_source_from_value(record.get("line_source_key") or record.get("line_id"))


def _message_line_source_key(message: dict[str, Any]) -> str | None:
    return _line_source_from_value(message.get("line_source_key") or message.get("line_id"))


def _resolve_identity_groups(
    records: list[dict[str, Any]],
    *,
    hall_id: str | None,
    line_source_key: str | None,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    if not records:
        raise LineDailyIdentityError(["raw.manifest:identity_required"])

    hall_candidates = {
        str(record["hall_id"]).strip()
        for record in records
        if isinstance(record.get("hall_id"), str) and record["hall_id"].strip()
    }
    if hall_id is not None:
        hall_id = hall_id.strip()
        if not hall_id:
            raise LineDailyIdentityError(["hall_id:empty"])
        if hall_candidates and hall_candidates != {hall_id}:
            raise LineDailyIdentityError(["hall_id:conflict"])
    elif len(hall_candidates) == 1:
        hall_id = next(iter(hall_candidates))
    elif not hall_candidates:
        raise LineDailyIdentityError(["hall_id:unresolved"])
    else:
        raise LineDailyIdentityError(["hall_id:ambiguous"])

    source_candidates = {
        source
        for record in records
        if (source := _record_line_source_key(record)) is not None
    }
    if line_source_key is not None:
        line_source_key = line_source_key.strip()
        if not line_source_key:
            raise LineDailyIdentityError(["line_source_key:empty"])
        if source_candidates and source_candidates != {line_source_key}:
            raise LineDailyIdentityError(["line_source_key:conflict"])
    elif len(source_candidates) == 1:
        line_source_key = next(iter(source_candidates))
    elif not source_candidates:
        raise LineDailyIdentityError(["line_source_key:unresolved"])

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        record_hall_id = record.get("hall_id") or hall_id
        record_source_key = _record_line_source_key(record) or line_source_key
        if not isinstance(record_hall_id, str) or not record_hall_id.strip():
            raise LineDailyIdentityError(["hall_id:unresolved"])
        if not isinstance(record_source_key, str) or not record_source_key.strip():
            raise LineDailyIdentityError(["line_source_key:unresolved"])
        key = (record_hall_id.strip(), record_source_key.strip())
        groups.setdefault(key, []).append(record)
    return groups


def _failure_code(records: list[dict[str, Any]]) -> str | None:
    if not records:
        return None
    latest = max(records, key=_record_order)
    status = _status(latest)
    if status in {"skipped_already_attempted", "skipped_cooldown"}:
        if status == "skipped_cooldown":
            return str(latest.get("skip_reason") or status)
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
    values: list[Any] = []
    for record in records:
        value = record.get(key)
        if value in (None, "") and key == "trigger_text":
            nested_trigger = record.get("trigger")
            if isinstance(nested_trigger, dict):
                value = nested_trigger.get("text")
        if value in (None, "") and key == "trigger_action":
            nested_trigger = record.get("trigger")
            if isinstance(nested_trigger, dict):
                value = nested_trigger.get("action")
        if value not in (None, ""):
            values.append(value)
    return values[-1] if values else None


def _acquisition_type(records: list[dict[str, Any]]) -> str:
    """Choose a stable daily type when an acceptance has mixed run modes."""
    valid_types = [
        str(record.get("adapter_type"))
        for record in records
        if str(record.get("adapter_type") or "") in ADAPTER_TYPES
    ]
    successful_types = [
        str(record.get("adapter_type"))
        for record in records
        if _status(record) in SUCCESS_STATUSES and str(record.get("adapter_type") or "") in ADAPTER_TYPES
    ]
    candidates = successful_types or valid_types
    for adapter_type in ADAPTER_TYPE_PRIORITY:
        if adapter_type in candidates:
            return adapter_type
    return "unknown"


def _convert_records(
    records: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    hall_id: str,
    collector_key: str,
    line_source_key: str,
    date_text: str,
    raw_dir: Path,
    repo_root: Path,
    record_indices: Iterable[int],
) -> dict[str, Any]:
    records = sorted(records, key=_record_order)
    source = str(next((record.get("source") for record in records if record.get("source")), DEFAULT_SOURCE))
    acquisition_type = _acquisition_type(records)

    statuses = {_status(record) for record in records}
    if not records:
        collection_status = "not_checked"
    elif statuses & SUCCESS_STATUSES:
        collection_status = "success"
    elif statuses & {"skipped_already_attempted", "skipped_cooldown", "partial"}:
        collection_status = "partial"
    else:
        collection_status = "failed"

    message_info = _message_summary(messages)
    has_messages = message_info["count"] > 0
    semantic_deferred = any(
        record.get("semantic_interpretation") == "deferred"
        and _status(record) in SUCCESS_STATUSES
        for record in records
    )
    line_update = (
        "present"
        if has_messages
        else "absent"
        if collection_status == "success" and not semantic_deferred
        else "unknown"
    )

    required = acquisition_type == "text_trigger"
    triggered = [record for record in records if record.get("triggered_at")]
    actual_success = [record for record in records if _status(record) == "success"]
    successful_skip = [record for record in records if _status(record) == "skipped_already_successful"]
    trigger_action = "send_text" if acquisition_type == "text_trigger" else _trigger_value(records, "trigger_action")
    trigger_text = _trigger_value(records, "trigger_text")
    explicit_trigger = bool(triggered) or any(
        isinstance(record.get("trigger"), dict) and record["trigger"].get("type") not in (None, "", "passive")
        for record in records
    )
    trigger = {
        "required": required,
        "performed": bool(triggered) if records else None,
        "action": trigger_action,
        "text": trigger_text,
        "triggered_at": _trigger_value(triggered, "triggered_at"),
        "result": None,
    }
    if explicit_trigger or required:
        if actual_success:
            trigger["result"] = "sent" if triggered else "received"
        elif successful_skip:
            trigger["result"] = "skipped_already_successful"
        elif records:
            trigger["result"] = _status(max(records, key=_record_order))

    summary_status = "pending" if line_update == "present" else "not_applicable"
    return {
        "schema_version": SCHEMA_VERSION,
        "hall_id": hall_id,
        "collector_key": collector_key,
        "line_source_key": line_source_key,
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
        "raw_refs": _raw_refs(records, messages, raw_dir, repo_root, record_indices),
    }


def _indexed_manifest_records(manifest: Any) -> list[dict[str, Any]]:
    if isinstance(manifest, dict):
        return [{**manifest, "_manifest_index": 0}]
    if isinstance(manifest, list):
        return [
            {**item, "_manifest_index": index}
            for index, item in enumerate(manifest)
            if isinstance(item, dict)
        ]
    raise ValueError("manifest must be an object or list")


def _messages_by_group(
    messages: list[dict[str, Any]],
    groups: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Assign every message to exactly one identity group or fail closed."""
    group_keys = set(groups)
    record_indices = {
        key: {record.get("_manifest_index") for record in records}
        for key, records in groups.items()
    }
    run_ids = {
        key: {str(record["run_id"]) for record in records if record.get("run_id")}
        for key, records in groups.items()
    }
    grouped = {key: [] for key in groups}

    for message in messages:
        evidence: list[set[tuple[str, str]]] = []
        message_hall_id = message.get("hall_id")
        if message_hall_id not in (None, ""):
            evidence.append({key for key in group_keys if key[0] == message_hall_id})

        message_source_key = _message_line_source_key(message)
        if message_source_key:
            evidence.append({key for key in group_keys if key[1] == message_source_key})

        manifest_index = message.get("_manifest_index")
        if manifest_index is not None:
            evidence.append({key for key in group_keys if manifest_index in record_indices[key]})

        message_run_id = message.get("run_id")
        if message_run_id:
            run_id = str(message_run_id)
            evidence.append({key for key in group_keys if run_id in run_ids[key]})

        candidates = set.intersection(*evidence) if evidence else set(group_keys)
        if not evidence and len(group_keys) != 1:
            raise LineDailyIdentityError([
                "messages.json:identity_required_for_multiple_sources"
            ])
        if len(candidates) != 1:
            reason = "ambiguous" if len(candidates) > 1 else "unmatched_or_conflicting"
            raise LineDailyIdentityError([f"messages.json:identity_{reason}"])
        grouped[next(iter(candidates))].append(message)
    return grouped


def convert_raw_directory_all(
    raw_dir: Path,
    *,
    repo_root: Path | None = None,
    hall_id: str | None = None,
    line_source_key: str | None = None,
) -> list[dict[str, Any]]:
    """Convert one collector directory, retaining one observation per source."""
    raw_dir = raw_dir.resolve()
    if raw_dir.name == "" or raw_dir.parent.name == "":
        raise ValueError(f"invalid_raw_directory:{raw_dir}")
    date_text = raw_dir.parent.name
    collector_key = raw_dir.name
    try:
        date.fromisoformat(date_text)
    except ValueError as exc:
        raise ValueError(f"invalid_date_directory:{date_text}") from exc
    manifest = _load_json(raw_dir / "manifest.json", [])
    records = _indexed_manifest_records(manifest)
    groups = _resolve_identity_groups(
        records,
        hall_id=hall_id,
        line_source_key=line_source_key,
    )
    messages = _message_rows(raw_dir, records)
    messages_by_group = _messages_by_group(messages, groups)
    resolved_repo_root = (repo_root or raw_dir.parents[3]).resolve()
    observations: list[dict[str, Any]] = []
    for group_key, group_records in sorted(groups.items()):
        group_messages = messages_by_group[group_key]
        observations.append(
            _convert_records(
                group_records,
                group_messages,
                hall_id=group_key[0],
                collector_key=collector_key,
                line_source_key=group_key[1],
                date_text=date_text,
                raw_dir=raw_dir,
                repo_root=resolved_repo_root,
                record_indices=(record["_manifest_index"] for record in group_records),
            )
        )
    return observations


def convert_raw_directory(
    raw_dir: Path,
    *,
    repo_root: Path | None = None,
    hall_id: str | None = None,
    line_source_key: str | None = None,
) -> dict[str, Any]:
    """Convert a single-source directory; reject source ambiguity."""
    observations = convert_raw_directory_all(
        raw_dir,
        repo_root=repo_root,
        hall_id=hall_id,
        line_source_key=line_source_key,
    )
    if len(observations) != 1:
        raise LineDailyIdentityError([
            "raw.manifest:multiple_line_sources_use_convert_raw_directory_all"
        ])
    return observations[0]


def make_not_checked(
    hall_id: str,
    date_text: str,
    *,
    repo_root: Path,
    line_source_key: str,
    collector_key: str = "not_checked",
    acquisition_type: str = "unknown",
    source: str = DEFAULT_SOURCE,
) -> dict[str, Any]:
    if acquisition_type not in ADAPTER_TYPES:
        raise ValueError(f"invalid_acquisition_type:{acquisition_type}")
    raw_dir = repo_root / "data" / "raw" / date_text / collector_key
    result = _convert_records(
        [],
        [],
        hall_id=hall_id,
        collector_key=collector_key,
        line_source_key=line_source_key,
        date_text=date_text,
        raw_dir=raw_dir,
        repo_root=repo_root,
        record_indices=[],
    )
    result["source"] = source
    result["acquisition_type"] = acquisition_type
    result["trigger"]["required"] = acquisition_type == "text_trigger"
    result["trigger"]["action"] = "send_text" if acquisition_type == "text_trigger" else None
    return result


def load_hall_ids(master_path: Path) -> set[str]:
    with master_path.open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        field = "hall_id"
        if field not in (rows.fieldnames or []):
            raise ValueError(f"hall_id_column_missing:{master_path}")
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


def validate_observation(value: Any, *, known_hall_ids: Iterable[str] | None = None) -> None:
    errors: list[str] = []
    if not isinstance(value, dict):
        raise LineDailyValidationError(["$:object"])
    allowed_keys = {
        "schema_version",
        "hall_id",
        "collector_key",
        "line_source_key",
        "date",
        "source",
        "acquisition_type",
        "collection",
        "line_update",
        "trigger",
        "messages",
        "summary",
        "raw_refs",
    }
    errors.extend(f"$.{key}:additional-property" for key in sorted(set(value) - allowed_keys))

    schema_version = _require(value, "schema_version", errors, "$")
    if schema_version != SCHEMA_VERSION:
        errors.append("$.schema_version:unsupported")
    hall_id = _require(value, "hall_id", errors, "$")
    _check_string(hall_id, errors, "$.hall_id", pattern=r"[a-z0-9][a-z0-9_-]*")
    if known_hall_ids is not None and hall_id not in set(known_hall_ids):
        errors.append("$.hall_id:unknown")
    collector_key = _require(value, "collector_key", errors, "$")
    _check_string(collector_key, errors, "$.collector_key", pattern=r"[a-z0-9][a-z0-9_-]*")
    line_source_key = _require(value, "line_source_key", errors, "$")
    _check_string(line_source_key, errors, "$.line_source_key", pattern=IDENTIFIER_PATTERN)
    date_text = _require(value, "date", errors, "$")
    _check_string(date_text, errors, "$.date", pattern=r"\d{4}-\d{2}-\d{2}")
    if isinstance(date_text, str):
        try:
            date.fromisoformat(date_text)
        except ValueError:
            errors.append("$.date:invalid")
    source = _require(value, "source", errors, "$")
    _check_string(source, errors, "$.source")
    if source != DEFAULT_SOURCE:
        errors.append("$.source:unsupported")
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
        for key in ("run_ids", "record_refs", "message_refs"):
            refs = _require(raw_refs, key, errors, "$.raw_refs")
            if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
                errors.append(f"$.raw_refs.{key}:string-array")

    if isinstance(collection, dict) and collection.get("status") == "not_checked" and collection.get("checked_at") is not None:
        errors.append("$.collection.not_checked_requires-null-checked_at")
    if line_update == "absent" and isinstance(collection, dict) and collection.get("status") != "success":
        errors.append("$.line_update.absent-requires-success")
    if errors:
        raise LineDailyValidationError(errors)


def write_observation(observation: dict[str, Any], path: Path, *, known_hall_ids: Iterable[str] | None = None) -> None:
    if known_hall_ids is None:
        raise LineDailyValidationError(["$.hall_id:canonical_master_required"])
    validate_observation(observation, known_hall_ids=known_hall_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def observation_filename(observation: dict[str, Any]) -> str:
    hall_id = quote(str(observation["hall_id"]), safe="-._~")
    line_source_key = quote(str(observation["line_source_key"]), safe="-._~")
    return f"{hall_id}__{line_source_key}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser("convert")
    convert.add_argument("raw_dir", type=Path)
    convert.add_argument("--repo-root", type=Path)
    convert.add_argument("--output", type=Path)
    convert.add_argument("--output-root", type=Path)
    convert.add_argument("--hall-id")
    convert.add_argument("--line-source-key")
    convert.add_argument("--store-master", type=Path, required=True, help="Read-only slot hall master used for hall_id validation")

    not_checked = subparsers.add_parser("not-checked")
    not_checked.add_argument("--repo-root", type=Path, required=True)
    not_checked.add_argument("--date", dest="date_text", required=True)
    not_checked.add_argument("--hall-id", required=True)
    not_checked.add_argument("--line-source-key", action="append", required=True)
    not_checked.add_argument("--collector-key", default="not_checked")
    not_checked.add_argument("--output-root", type=Path)
    not_checked.add_argument("--store-master", type=Path, required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("path", type=Path)
    validate.add_argument("--store-master", type=Path)

    args = parser.parse_args()
    if args.command == "convert":
        repo_root = (args.repo_root or args.raw_dir.parents[3]).resolve()
        observations = convert_raw_directory_all(
            args.raw_dir,
            repo_root=repo_root,
            hall_id=args.hall_id,
            line_source_key=args.line_source_key,
        )
        known = load_hall_ids(args.store_master) if args.store_master else None
        if args.output and len(observations) != 1:
            raise SystemExit("--output is only valid when RAW resolves to one LINE source")
        output_root = (
            args.output_root
            or repo_root / "data" / "normalized" / "line_daily"
        ).resolve()
        for observation in observations:
            output = args.output if args.output else output_root / observation["date"] / observation_filename(observation)
            write_observation(observation, output, known_hall_ids=known)
    elif args.command == "not-checked":
        known = load_hall_ids(args.store_master) if args.store_master else None
        output_root = (args.output_root or args.repo_root / "data" / "normalized" / "line_daily").resolve()
        for source_key in sorted(set(args.line_source_key)):
            observation = make_not_checked(
                args.hall_id,
                args.date_text,
                repo_root=args.repo_root.resolve(),
                line_source_key=source_key,
                collector_key=args.collector_key,
            )
            write_observation(
                observation,
                output_root / args.date_text / observation_filename(observation),
                known_hall_ids=known,
            )
    else:
        observation = _load_json(args.path, {})
        known = load_hall_ids(args.store_master) if args.store_master else None
        validate_observation(observation, known_hall_ids=known)
        print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
