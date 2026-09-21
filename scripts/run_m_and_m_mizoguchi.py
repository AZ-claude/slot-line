#!/usr/bin/env python3
"""Collect already-received M&M Mizoguchi messages into canonical RAW.

This is the intentionally small passive adapter.  It never sends a trigger;
it only opens the visible official-account chat, reads the Android UI tree,
and stores the final UI dump plus any LINE-standard image downloads.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from raw_storage import RawStorageError, RawStore


STORE_ID = "m_and_m_mizoguchi"
SOURCE = "official_line"
ADAPTER_TYPE = "passive"
TARGET_TITLE = "エムアンドエム溝口"
LINE_PACKAGE = "jp.naver.line.android"
ANDROID_IMAGE_DIR = "/sdcard/Pictures/LINE"


class PassiveError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_process(args: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PassiveError("android_unreachable", f"command_not_found:{args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PassiveError("android_unreachable", f"command_timeout:{args[0]}") from exc


def adb_run(adb: str, serial: str, args: list[str], *, timeout: float = 30.0, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = run_process([adb, "-s", serial, *args], timeout=timeout)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\r", " ").replace("\n", " ")
        raise PassiveError("android_unreachable", f"adb_failed:{detail[:300]}")
    return result


def discover_android() -> tuple[str, str]:
    adb = shutil.which("adb")
    if not adb:
        raise PassiveError("android_unreachable", "adb_not_found")
    result = run_process([adb, "devices"], timeout=15)
    devices = [line.split()[0] for line in result.stdout.splitlines() if len(line.split()) >= 2 and line.split()[1] == "device"]
    if not devices:
        raise PassiveError("android_unreachable", "no_android_device")
    return adb, devices[0]


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value or "")
    return tuple(int(part) for part in match.groups()) if match else None


def center_of_bounds(value: str) -> tuple[int, int] | None:
    bounds = parse_bounds(value)
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def resource_id(node: ElementTree.Element) -> str:
    return node.attrib.get("resource-id", "")


def text_or_desc(node: ElementTree.Element) -> str:
    return node.attrib.get("text", "") or node.attrib.get("content-desc", "")


def dump_ui(adb: str, serial: str, suffix: str) -> tuple[ElementTree.Element, bytes]:
    remote = f"/sdcard/slot-line-passive-{os.getpid()}-{suffix}.xml"
    try:
        result = adb_run(adb, serial, ["shell", "uiautomator", "dump", remote], timeout=30)
        if result.returncode != 0:
            raise PassiveError("extraction_failed", "uiautomator_dump_failed")
        raw = (adb_run(adb, serial, ["exec-out", "cat", remote], timeout=30).stdout or "").encode("utf-8", errors="replace")
        if not raw.strip().startswith(b"<"):
            raise PassiveError("extraction_failed", "uiautomator_dump_empty")
        try:
            return ElementTree.fromstring(raw), raw
        except ElementTree.ParseError as exc:
            raise PassiveError("extraction_failed", "uiautomator_xml_invalid") from exc
    finally:
        adb_run(adb, serial, ["shell", "rm", "-f", remote], timeout=15, check=False)


def is_system_ui(root: ElementTree.Element) -> bool:
    packages = {node.attrib.get("package", "") for node in root.iter() if node.attrib.get("package")}
    return bool(packages) and packages.issubset({"com.android.systemui", "android"})


def is_target_chat(root: ElementTree.Element) -> bool:
    for node in root.iter():
        if text_or_desc(node) == TARGET_TITLE and resource_id(node) in {
            "jp.naver.line.android:id/header_title",
            "jp.naver.line.android:id/chat_header_title",
        }:
            return True
    return False


def tap_node(adb: str, serial: str, node: ElementTree.Element) -> None:
    center = center_of_bounds(node.attrib.get("bounds", ""))
    if center is None:
        raise PassiveError("extraction_failed", "target_node_without_bounds")
    adb_run(adb, serial, ["shell", "input", "tap", str(center[0]), str(center[1])], timeout=15)


def open_target_chat(adb: str, serial: str) -> tuple[ElementTree.Element, bytes]:
    adb_run(adb, serial, ["shell", "input", "keyevent", "KEYCODE_WAKEUP"], timeout=15)
    adb_run(adb, serial, ["shell", "monkey", "-p", LINE_PACKAGE, "1"], timeout=30)
    time.sleep(1.5)
    for attempt in range(6):
        root, raw = dump_ui(adb, serial, f"open-{attempt}")
        if is_system_ui(root):
            raise PassiveError("android_unreachable", "android_secure_lock_or_system_ui")
        if is_target_chat(root):
            return root, raw
        entry = next(
            (
                node
                for node in root.iter()
                if text_or_desc(node) == TARGET_TITLE and center_of_bounds(node.attrib.get("bounds", "")) is not None
            ),
            None,
        )
        if entry is not None:
            tap_node(adb, serial, entry)
        else:
            adb_run(adb, serial, ["shell", "input", "keyevent", "KEYCODE_BACK"], timeout=15, check=False)
        time.sleep(1.0)
    raise PassiveError("android_unreachable", "target_chat_not_visible_in_android_ui")


def extract_message_rows(root: ElementTree.Element) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in root.iter():
        if resource_id(row) != "jp.naver.line.android:id/chat_ui_row_swipeable_framelayout":
            continue
        descendants = list(row.iter())
        ids = [resource_id(node) for node in descendants]
        kind: str | None = None
        image_node: ElementTree.Element | None = None
        if "jp.naver.line.android:id/chat_ui_row_image_balloon_root" in ids:
            kind = "image"
            image_node = next(node for node in descendants if resource_id(node) == "jp.naver.line.android:id/chat_ui_row_image_balloon_root")
        elif "jp.naver.line.android:id/chat_ui_row_receive_rich_container" in ids:
            kind = "rich_card"
        elif "jp.naver.line.android:id/chat_ui_row_text_message" in ids:
            kind = "text"
        if kind is None:
            continue
        timestamp = next((node for node in descendants if resource_id(node) == "jp.naver.line.android:id/chat_ui_row_timestamp"), None)
        rows.append(
            {
                "kind": kind,
                "timestamp": text_or_desc(timestamp) if timestamp is not None else None,
                "bounds": row.attrib.get("bounds"),
                "image_bounds": image_node.attrib.get("bounds") if image_node is not None else None,
                "text": [node.attrib["text"] for node in descendants if node.attrib.get("text")],
                "content_desc": [node.attrib["content-desc"] for node in descendants if node.attrib.get("content-desc")],
            }
        )
    return rows


def list_android_files(adb: str, serial: str) -> set[str]:
    result = adb_run(adb, serial, ["shell", "find", ANDROID_IMAGE_DIR, "-type", "f"], timeout=30, check=False)
    return {line.strip() for line in result.stdout.splitlines() if line.strip().startswith(ANDROID_IMAGE_DIR + "/")}


def save_image_from_line(adb: str, serial: str, row: dict[str, Any], before: set[str]) -> str:
    center = center_of_bounds(row.get("image_bounds") or "")
    if center is None:
        raise PassiveError("image_save_failed", "image_message_without_bounds")
    adb_run(adb, serial, ["shell", "input", "tap", str(center[0]), str(center[1])], timeout=15)
    time.sleep(1.0)
    gallery, _ = dump_ui(adb, serial, "gallery")
    download = next(
        (
            node
            for node in gallery.iter()
            if resource_id(node) == "jp.naver.line.android:id/chat_media_content_download_button"
            or node.attrib.get("content-desc") == "ダウンロード"
        ),
        None,
    )
    if download is None:
        raise PassiveError("image_save_failed", "line_download_button_not_found")
    tap_node(adb, serial, download)
    time.sleep(1.5)
    new_files = sorted(list_android_files(adb, serial) - before)
    if not new_files:
        raise PassiveError("image_save_failed", "no_new_file_in_line_picture_directory")
    return new_files[-1]


def pull_to_stage(adb: str, serial: str, android_path: str, store: RawStore, run_id: str) -> Path:
    stage = store.stage_path(run_id, android_path)
    pulled = adb_run(adb, serial, ["pull", android_path, str(stage)], timeout=90, check=False)
    if pulled.returncode != 0 or not stage.exists():
        store.cleanup_stage(stage)
        raise PassiveError("pull_failed", "adb_pull_failed")
    return stage


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect M&M Mizoguchi passive LINE messages into canonical RAW.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    store = RawStore(args.repo_root.resolve(), datetime.now().strftime("%Y-%m-%d"), STORE_ID, SOURCE, ADAPTER_TYPE)
    store.initialize()
    run_id = datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    record = store.new_manifest_record(run_id, utc_now(), {"type": ADAPTER_TYPE})
    android_paths: list[str] = []
    storage_finalized = False
    adb: str | None = None
    serial: str | None = None
    try:
        adb, serial = discover_android()
        root, ui_raw = open_target_chat(adb, serial)
        rows = extract_message_rows(root)
        observed_at = utc_now()
        ui_filename = store.save_ui_dump(ui_raw, run_id, "passive")
        record["ui_filenames"] = [ui_filename]
        messages = [
            {
                "message_type": row["kind"],
                "line_display_time": row.get("timestamp"),
                "observed_at": observed_at,
                "text": row.get("text") or [],
                "content_desc": row.get("content_desc") or [],
                "image_filename": None,
                "byte_size": None,
                "sha256": None,
                "bounds": row.get("bounds"),
                "image_bounds": row.get("image_bounds"),
            }
            for row in rows
        ]
        image_count = 0
        deduplicated_count = 0
        for index, row in enumerate(rows):
            if row["kind"] != "image":
                continue
            before = list_android_files(adb, serial)
            android_path = save_image_from_line(adb, serial, row, before)
            android_paths.append(android_path)
            stage = pull_to_stage(adb, serial, android_path, store, run_id)
            image_info = store.import_image(stage, android_path)
            messages[index].update(
                {
                    "image_filename": image_info["image_filename"],
                    "byte_size": image_info["byte_size"],
                    "sha256": image_info["sha256"],
                }
            )
            image_count += 1
            deduplicated_count += int(image_info["deduplicated"])
            adb_run(adb, serial, ["shell", "input", "keyevent", "KEYCODE_BACK"], timeout=15, check=False)
            time.sleep(0.5)
        store.merge_messages(messages)
        record["message_count"] = len(messages)
        record["image_count"] = image_count
        record["deduplicated_images"] = deduplicated_count
        record["status"] = "success"
        record["finished_at"] = utc_now()
        store.persist_manifest(record)
        storage_finalized = True
        for android_path in android_paths:
            cleanup = adb_run(adb, serial, ["shell", "rm", "-f", android_path], timeout=30, check=False)
            if cleanup.returncode != 0:
                record["errors"].append({"code": "cleanup_warning", "detail": android_path})
        if record["errors"]:
            store.persist_manifest(record)
    except PassiveError as exc:
        record["status"] = exc.code
        record["errors"].append({"code": exc.code, "detail": exc.detail})
    except RawStorageError as exc:
        record["status"] = "extraction_failed"
        record["errors"].append({"code": "raw_storage_failed", "detail": str(exc)})
    except Exception as exc:
        record["status"] = "extraction_failed"
        record["errors"].append({"code": "extraction_failed", "detail": f"unexpected:{type(exc).__name__}:{exc}"})
    finally:
        if adb is not None and serial is not None and android_paths:
            adb_run(adb, serial, ["shell", "input", "keyevent", "KEYCODE_BACK"], timeout=15, check=False)
        if not storage_finalized:
            record["finished_at"] = utc_now()
            store.persist_manifest(record)

    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
