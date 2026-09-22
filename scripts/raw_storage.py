"""Canonical Windows-side RAW storage for the LINE collectors."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class RawStorageError(RuntimeError):
    """A local RAW storage operation failed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RawStorageError(f"invalid_json:{path.name}") from exc
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    raise RawStorageError(f"invalid_json_shape:{path.name}")


def _message_key(message: dict[str, Any]) -> str:
    image_hash = message.get("sha256")
    if image_hash:
        stable = {
            "message_type": message.get("message_type"),
            "line_display_time": message.get("line_display_time"),
            "sha256": image_hash,
        }
        encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "image_message:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    stable = {
        "message_type": message.get("message_type"),
        "line_display_time": message.get("line_display_time"),
        "text": message.get("text") or [],
        "content_desc": message.get("content_desc") or [],
    }
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "message:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RawStore:
    """Own one date/store directory and make its writes idempotent."""

    def __init__(self, repo_root: Path, date_text: str, store_id: str, source: str, adapter_type: str):
        self.root = repo_root / "data" / "raw" / date_text / store_id
        self.store_id = store_id
        self.source = source
        self.adapter_type = adapter_type
        self.manifest_path = self.root / "manifest.json"
        self.messages_path = self.root / "messages.json"
        self.images_dir = self.root / "images"
        self.ui_dir = self.root / "ui"

    def initialize(self) -> None:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.ui_dir.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            _atomic_write_json(self.manifest_path, [])
        if not self.messages_path.exists():
            _atomic_write_json(self.messages_path, [])

    def new_manifest_record(self, run_id: str, started_at: str, trigger: Any) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "source": self.source,
            "adapter_type": self.adapter_type,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": None,
            "trigger": trigger,
            "triggered_at": None,
            "received_at": None,
            "status": "running",
            "errors": [],
            "messages_filename": "messages.json",
            "ui_filenames": [],
            "message_count": 0,
            "stored_message_count_total": 0,
            "image_count": 0,
            "deduplicated_images": 0,
        }

    def persist_manifest(self, record: dict[str, Any]) -> None:
        records = _load_json_list(self.manifest_path)
        for index, existing in enumerate(records):
            if existing.get("run_id") == record.get("run_id"):
                records[index] = record
                break
        else:
            records.append(record)
        _atomic_write_json(self.manifest_path, records)

    def load_manifest_records(self) -> list[dict[str, Any]]:
        return _load_json_list(self.manifest_path)

    def load_messages(self) -> list[dict[str, Any]]:
        return _load_json_list(self.messages_path)

    def has_successful_trigger(self, adapter_type: str, trigger_type: str) -> bool:
        return any(
            record.get("status") == "success"
            and record.get("adapter_type") == adapter_type
            and isinstance(record.get("trigger"), dict)
            and record["trigger"].get("type") == trigger_type
            for record in self.load_manifest_records()
        )

    def save_ui_artifact(self, raw: bytes, run_id: str, label: str, suffix: str) -> str:
        if not raw:
            raise RawStorageError("ui_artifact_empty")
        filename = f"{run_id}_{label}{suffix}"
        path = self.ui_dir / filename
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, path)
        return str(Path("ui") / filename)

    def save_ui_dump(self, raw: bytes, run_id: str, label: str = "reply") -> str:
        if not raw.strip().startswith(b"<"):
            raise RawStorageError("ui_dump_empty")
        return self.save_ui_artifact(raw, run_id, label, ".xml")

    def import_image(self, pulled_path: Path, source_name: str | None = None) -> dict[str, Any]:
        if not pulled_path.exists() or not pulled_path.is_file():
            raise RawStorageError("pulled_image_missing")
        digest, size = sha256_and_size(pulled_path)
        for existing in sorted(self.images_dir.iterdir()):
            if not existing.is_file():
                continue
            existing_digest, _ = sha256_and_size(existing)
            if existing_digest == digest:
                pulled_path.unlink(missing_ok=True)
                return {
                    "image_filename": str(Path("images") / existing.name),
                    "byte_size": size,
                    "sha256": digest,
                    "deduplicated": True,
                }

        suffix = Path(source_name or pulled_path.name).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".bin"}:
            suffix = ".bin"
        number = 1
        while (self.images_dir / f"image_{number:03d}{suffix}").exists():
            number += 1
        destination = self.images_dir / f"image_{number:03d}{suffix}"
        os.replace(pulled_path, destination)
        return {
            "image_filename": str(Path("images") / destination.name),
            "byte_size": size,
            "sha256": digest,
            "deduplicated": False,
        }

    def merge_messages(self, messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        existing = _load_json_list(self.messages_path)
        by_key = {_message_key(item): item for item in existing}
        for message in messages:
            normalized = dict(message)
            normalized.setdefault("observed_at", utc_now())
            key = _message_key(normalized)
            if key in by_key:
                merged = dict(by_key[key])
                merged.update({key: value for key, value in normalized.items() if value not in (None, [], "")})
                by_key[key] = merged
            else:
                by_key[key] = normalized
        merged_records = list(by_key.values())
        _atomic_write_json(self.messages_path, merged_records)
        return merged_records

    def stage_path(self, run_id: str, source_name: str | None = None) -> Path:
        suffix = Path(source_name or "image.bin").suffix or ".bin"
        return self.root / f".incoming_{run_id}{suffix}"

    def cleanup_stage(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
