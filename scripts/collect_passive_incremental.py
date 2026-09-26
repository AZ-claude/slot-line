#!/usr/bin/env python3
"""Read-only LINE conversation-list incremental-collection PoC.

This deliberately remains separate from the production daily runner and scheduler.
RAW UI dumps are append-only. The checkpoint is derived state and is atomically
replaced after each run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_FILE = ROOT / "data/surveys/line_capability_50_live_2026-09-25.json"
ACQUISITION_FILE = ROOT / "data/surveys/line_acquisition_20_2026-09-25.json"
OUTPUT_FILE = ROOT / "data/surveys/passive_incremental_20_2026-09-25.json"
CHECKPOINT_FILE = ROOT / "data/surveys/passive_incremental_20_checkpoint.json"
EVIDENCE_DIR = ROOT / "data/surveys/passive_incremental_20_2026-09-25_evidence"
OUTPUT_FILE_41 = ROOT / "data/surveys/passive_incremental_41_acceptance_2026-09-26.json"
CHECKPOINT_FILE_41 = ROOT / "data/surveys/passive_incremental_41_checkpoint_2026-09-26.json"
EVIDENCE_DIR_41 = ROOT / "data/surveys/passive_incremental_41_evidence_2026-09-26"
REGISTRY_FILE = ROOT / "data/line_targets.json"
OUTPUT_FILE_REGISTRY = ROOT / "data/surveys/passive_incremental_registry_runs.json"
CHECKPOINT_FILE_REGISTRY = ROOT / "data/surveys/passive_incremental_registry_checkpoint.json"
EVIDENCE_DIR_REGISTRY = ROOT / "data/surveys/passive_incremental_registry_evidence"
TIMEZONE = ZoneInfo("Asia/Tokyo")
LINE_ID_PREFIX = "jp.naver.line.android:id/"
LIST_SCROLL_LIMIT = 80
LIST_NO_PROGRESS_LIMIT = 3
MAX_SETTLE_RETRIES = 2
DEFAULT_FRONTIER_STABLE_ROWS = 8
UNREAD_RESOURCE_RE = re.compile(r"unread|badge|new_message|unread_count|message_count", re.I)

REQUIRED_KEYS = {
    "doki-waku-rando-ch-go-ekimae-ten",
    "pia-keiky-kawasaki",
    "japan-ny-arufa-kurami-ten",
    "deizu-shinsugita-ten",
    "p-ru-shoppu-tomo-e-fuchinobe-ten",
}
EXCLUDED_ACQUISITION_KEYS = {
    "m_and_m_mizoguchi",
    "purego-yugawara-ten",
    "sanrakk-sagamihara-ten",
}
ORDINARY_NOTICE_RE = re.compile(
    r"新台|店休日|休業|抽選|イベント|取材|入荷|来店|営業|入替|景品|整理券|営業時間|開店|"
    r"シルバーウィーク|本日の情報|最新情報|ご案内|本日も|本日のお知らせ"
)
RICH_CARD_NOTICE_RE = re.compile(
    r"新台|店休日|休業|抽選|イベント|取材|入荷|来店|営業|入替|景品|整理券|営業時間|開店|"
    r"シルバーウィーク|本日の情報|本日のお知らせ"
)
WELCOME_RE = re.compile(r"友だち登録ありがとう|友だち追加ありがとう|友達登録ありがとう|追加ありがとうございます")
TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
DATE_RE = re.compile(r"^(?:\d{1,2}月\d{1,2}日(?:\([^)]+\))?|\d{1,2}/\d{1,2}|今日|昨日|一昨日)$")


def now_local() -> str:
    return datetime.now(TIMEZONE).isoformat()


def normalise(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()


def bounds_of(node: ET.Element) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.attrib.get("bounds", ""))
    return tuple(map(int, match.groups())) if match else None


def text_of(node: ET.Element) -> str:
    return node.attrib.get("text", "") or node.attrib.get("content-desc", "")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def select_targets(sample_size: int | str = 20) -> list[dict[str, Any]]:
    if sample_size == "registry":
        result = [row for row in load_json(REGISTRY_FILE)["targets"] if row.get("active", True)]
        for row in result:
            if not str(row.get("identity_status", "")).startswith("verified_"):
                raise RuntimeError(f"registry target identity not verified: {row.get('collector_key')}")
        return _validate_target_set(result, len(result))
    capability = load_json(CAPABILITY_FILE)
    cap_by_key = {row["collector_key"]: row for row in capability["records"]}
    if sample_size == 20:
        previous = load_json(ACQUISITION_FILE)
        base_keys = [
            row["collector_key"]
            for row in previous["records"]
            if row["collector_key"] not in EXCLUDED_ACQUISITION_KEYS
        ]
        keys = base_keys + [
            "japan-ny-arufa-kurami-ten",
            "deizu-shinsugita-ten",
            "p-ru-shoppu-tomo-e-fuchinobe-ten",
        ]
        if len(keys) != 20 or len(set(keys)) != 20 or not REQUIRED_KEYS.issubset(keys):
            raise RuntimeError("fixed PoC target set failed its 20-store/required-store guard")
        result = []
        for key in keys:
            row = cap_by_key.get(key)
            if not row:
                raise RuntimeError(f"target absent from frozen 50: {key}")
            if not row.get("profile_verified") or not str(row.get("identity_status", "")).startswith("verified_"):
                raise RuntimeError(f"target identity not verified in frozen survey: {key}")
            if row.get("prefecture") != "神奈川県":
                raise RuntimeError(f"target outside Kanagawa: {key}")
            result.append(row)
    elif sample_size == 41:
        result = [
            row for row in capability["records"]
            if row.get("profile_verified")
            and str(row.get("identity_status", "")).startswith("verified_")
            and row.get("prefecture") == "神奈川県"
        ]
        if len(result) != 41 or not REQUIRED_KEYS.issubset({row["collector_key"] for row in result}):
            raise RuntimeError(f"frozen identity-confirmed sample expected 41 rows; found {len(result)}")
    else:
        raise ValueError(f"unsupported fixed sample size: {sample_size}")
    return _validate_target_set(result, sample_size)


def _validate_target_set(result: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    if len({r["hall_id"] for r in result}) != sample_size:
        raise RuntimeError(f"fixed target hall_id values are not unique for {sample_size} stores")
    if len({r["line_source_key"] for r in result}) != sample_size:
        raise RuntimeError(f"fixed target line_source_key values are not unique for {sample_size} stores")
    alias_owners: dict[str, list[str]] = defaultdict(list)
    for row in result:
        for alias in aliases_for(row):
            alias_owners[alias].append(row["collector_key"])
    collisions = {name: owners for name, owners in alias_owners.items() if len(set(owners)) > 1}
    if collisions:
        raise RuntimeError(f"ambiguous exact chat aliases in fixed sample: {collisions}")
    return result


def _signature(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def observation_content_signature(observation: dict[str, Any]) -> str | None:
    if observation.get("content_signature"):
        return str(observation["content_signature"])
    if not observation.get("displayed_name"):
        return None
    resource_ids = observation.get("row_resource_ids") or observation.get("stable_resource_ids") or []
    content_ids = sorted(rid for rid in resource_ids if not UNREAD_RESOURCE_RE.search(rid))
    return _signature({
        "displayed_name": normalise(observation.get("displayed_name", "")),
        "preview_text": normalise(observation.get("preview_text", "")),
        "displayed_time": normalise(observation.get("displayed_time", "")),
        "stable_content_resource_ids": content_ids,
    })


def observation_state_signature(observation: dict[str, Any]) -> str | None:
    if observation.get("state_signature"):
        return str(observation["state_signature"])
    if "unread_state" not in observation:
        return None
    resource_ids = observation.get("row_resource_ids") or observation.get("stable_resource_ids") or []
    state_ids = sorted(rid for rid in resource_ids if UNREAD_RESOURCE_RE.search(rid))
    return _signature({
        "unread_state": observation.get("unread_state"),
        "unread_count": observation.get("unread_count"),
        "unread_resource_ids": state_ids,
    })


def is_exact_day_label_rollover(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Prove the narrowly supported HH:mm -> 昨日 presentation-only rollover.

    Missing resource IDs are not evidence of matching stable row structure. This
    deliberately fails closed when LINE exposes no stable content IDs.
    """
    previous_ids = sorted(previous.get("stable_content_resource_ids") or [])
    current_ids = sorted(current.get("stable_content_resource_ids") or [])
    previous_state = observation_state_signature(previous)
    current_state = observation_state_signature(current)
    previous_label = str(previous.get("displayed_time") or "")
    if (
        not previous.get("row_complete_in_viewport")
        or not current.get("row_complete_in_viewport")
        or previous.get("loading_or_progress_present")
        or current.get("loading_or_progress_present")
        or not normalise(previous.get("displayed_name", ""))
        or normalise(previous.get("displayed_name", "")) != normalise(current.get("displayed_name", ""))
        or not normalise(previous.get("preview_text", ""))
        or normalise(previous.get("preview_text", "")) != normalise(current.get("preview_text", ""))
        or not previous_ids
        or previous_ids != current_ids
        or not previous_state
        or previous_state != current_state
        or current.get("displayed_time") != "昨日"
        or not TIME_RE.fullmatch(previous_label)
    ):
        return False
    try:
        previous_dt = datetime.fromisoformat(str(previous["observed_at"]).replace("Z", "+00:00")).astimezone(TIMEZONE)
        current_dt = datetime.fromisoformat(str(current["observed_at"]).replace("Z", "+00:00")).astimezone(TIMEZONE)
    except (KeyError, TypeError, ValueError):
        return False
    day_delta = current_dt.date() - previous_dt.date()
    if day_delta != timedelta(days=1):
        return False
    old_hour, old_minute = (int(part) for part in previous_label.split(":"))
    # HH:mm is only consistent with a same-day label when it is not later than
    # the previous observation's local wall clock. Do not generalize other
    # date-label transitions or same-day stale-label refreshes.
    return (old_hour, old_minute) <= (previous_dt.hour, previous_dt.minute)


def aliases_for(row: dict[str, Any]) -> set[str]:
    values = {
        row.get("store_name"),
        row.get("profile_display_name"),
        row.get("chat_header_name"),
        *(row.get("profile_expected_names") or []),
    }
    return {str(value) for value in values if value}


def adb_call(adb: str, serial: str, args: list[str], timeout: int = 40) -> subprocess.CompletedProcess:
    command = [adb, "-s", serial, *args]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        def readable(value: str | bytes | None) -> str:
            if value is None:
                return ""
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=readable(exc.stdout),
            stderr=f"adb command timeout after {timeout}s: {readable(exc.stderr)}",
        )


class Android:
    def __init__(self, adb: str, serial: str, remote_xml: str):
        self.adb = adb
        self.serial = serial
        self.remote_xml = remote_xml
        self.dump_attempt_count = 0
        self.dump_success_count = 0

    def command(self, args: list[str], timeout: int = 40) -> subprocess.CompletedProcess:
        proc = adb_call(self.adb, self.serial, args, timeout)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or f"exit={proc.returncode}")[:500]
            raise RuntimeError(f"adb {' '.join(args[:3])}: {detail}")
        return proc

    def dump(self, retries: int = MAX_SETTLE_RETRIES) -> tuple[bytes | None, str | None, int]:
        last_error = "ui_dump_failed"
        for attempt in range(retries + 1):
            self.dump_attempt_count += 1
            proc = adb_call(self.adb, self.serial, ["shell", "uiautomator", "dump", self.remote_xml], 50)
            combined = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 0 and "dumped to" in combined.lower():
                cat = adb_call(self.adb, self.serial, ["exec-out", "cat", self.remote_xml], 30)
                raw = cat.stdout.encode("utf-8") if isinstance(cat.stdout, str) else cat.stdout
                if cat.returncode == 0 and raw.lstrip().startswith((b"<?xml", b"<hierarchy")):
                    try:
                        ET.fromstring(raw)
                        self.dump_success_count += 1
                        return raw, None, attempt
                    except ET.ParseError:
                        last_error = "uiautomator_xml_parse_error"
                else:
                    last_error = "uiautomator_dump_empty"
            else:
                last_error = combined[:400] or f"uiautomator_exit={proc.returncode}"
            if attempt < retries:
                time.sleep(1.0 + 0.25 * attempt)
        return None, last_error, retries

    def cleanup(self) -> None:
        # Remove only this PoC's temporary device-side dump after a completed run.
        adb_call(self.adb, self.serial, ["shell", "rm", "-f", self.remote_xml], 10)

    def back(self) -> None:
        self.command(["shell", "input", "keyevent", "4"], 10)

    def tap_live_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        x = (bounds[0] + bounds[2]) // 2
        y = (bounds[1] + bounds[3]) // 2
        self.command(["shell", "input", "tap", str(x), str(y)], 10)

    def swipe_in_node(self, node_bounds: tuple[int, int, int, int], direction: str) -> None:
        left, top, right, bottom = node_bounds
        x = (left + right) // 2
        if direction == "toward_older":
            start_y = top + int((bottom - top) * 0.78)
            end_y = top + int((bottom - top) * 0.25)
        elif direction == "toward_newer":
            start_y = top + int((bottom - top) * 0.25)
            end_y = top + int((bottom - top) * 0.78)
        else:
            raise ValueError(direction)
        self.command(["shell", "input", "swipe", str(x), str(start_y), str(x), str(end_y), "420"], 15)


def parse_root(raw: bytes) -> ET.Element:
    return ET.fromstring(raw)


def package_set(root: ET.Element) -> set[str]:
    return {node.attrib.get("package", "") for node in root.iter() if node.attrib.get("package")}


def is_chat_list(root: ET.Element) -> bool:
    talk_label = any(node.attrib.get("text", "").strip() == "トーク" for node in root.iter())
    has_conversation_row = any(node.attrib.get("clickable") == "true" and bounds_of(node) for node in root.iter())
    has_chat_header = any(
        node.attrib.get("resource-id") in {LINE_ID_PREFIX + "header_title", LINE_ID_PREFIX + "chat_header_title"}
        and node.attrib.get("text")
        for node in root.iter()
    )
    return talk_label and has_conversation_row and not has_chat_header


def chat_header(root: ET.Element) -> str | None:
    for node in root.iter():
        if node.attrib.get("resource-id") in {
            LINE_ID_PREFIX + "header_title",
            LINE_ID_PREFIX + "chat_header_title",
        } and node.attrib.get("text"):
            return node.attrib["text"]
    return None


def ensure_chat_list(android: Android) -> tuple[ET.Element | None, bytes | None, str | None]:
    raw, error, _ = android.dump()
    if raw is None:
        return None, None, error
    root = parse_root(raw)
    if is_chat_list(root):
        return root, raw, None
    if "jp.naver.line.android" not in package_set(root):
        return None, raw, "foreground_ui_is_not_LINE"
    # Back is only used to leave the currently open chat; no send/action controls are activated.
    for _ in range(2):
        if chat_header(root):
            android.back()
            time.sleep(0.55)
        raw, error, _ = android.dump()
        if raw is None:
            return None, None, error
        root = parse_root(raw)
        if is_chat_list(root):
            return root, raw, None
        if not chat_header(root):
            return None, raw, "LINE_conversation_list_not_ready"
    return None, raw, "could_not_return_to_conversation_list"


def clickable_row_for(
    label_node: ET.Element,
    parents: dict[ET.Element, ET.Element],
    screen_width: int,
) -> ET.Element | None:
    node = label_node
    while node in parents:
        node = parents[node]
        b = bounds_of(node)
        if (
            b
            and node.attrib.get("clickable") == "true"
            and (b[2] - b[0]) >= screen_width * 0.70
            and (b[3] - b[1]) >= 48
        ):
            return node
    return None


def list_scroll_container(root: ET.Element) -> ET.Element | None:
    candidates = []
    for node in root.iter():
        if node.attrib.get("scrollable") != "true":
            continue
        b = bounds_of(node)
        if not b or (b[2] - b[0]) < 300 or (b[3] - b[1]) < 200:
            continue
        # The conversation list viewport can grow upward after scrolling beneath the ad header.
        # Exclude the full-screen tab ViewPager, then choose the smaller scrollable content node.
        if node.attrib.get("resource-id") != LINE_ID_PREFIX + "viewpager":
            candidates.append((max(0, b[2] - b[0]) * max(0, b[3] - b[1]), node))
    return min(candidates, key=lambda pair: pair[0])[1] if candidates else None


def loading_present(root: ET.Element) -> bool:
    for node in root.iter():
        rid = node.attrib.get("resource-id", "").lower()
        label = (node.attrib.get("text", "") + " " + node.attrib.get("content-desc", "")).lower()
        if "progress" in rid or "loading" in rid or "読み込み中" in label:
            return True
    return False


def row_observation(
    root: ET.Element,
    target: dict[str, Any],
    aliases: dict[str, list[dict[str, Any]]],
    raw_ref: str,
    page_index: int,
    observed_at: str,
) -> dict[str, Any] | None:
    width = 720
    for node in root.iter():
        b = bounds_of(node)
        if b:
            width = max(width, b[2])
    parents = {child: parent for parent in root.iter() for child in parent}
    matches = []
    for node in root.iter():
        label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
        if label in aliases and target["collector_key"] in {
            row["collector_key"] for row in aliases.get(label, [])
        }:
            clickable = clickable_row_for(node, parents, width)
            if clickable is not None:
                matches.append((node, clickable))
    if not matches:
        return None
    # Exact labels can be duplicated by overlay/accessibility replicas. Keep the largest visible row.
    label_node, row_node = max(
        matches,
        key=lambda pair: (
            (bounds_of(pair[1])[2] - bounds_of(pair[1])[0]) * (bounds_of(pair[1])[3] - bounds_of(pair[1])[1])
            if bounds_of(pair[1])
            else 0
        ),
    )
    list_node = list_scroll_container(root)
    list_bounds = bounds_of(list_node) if list_node is not None else None
    row_bounds = bounds_of(row_node)
    row_nodes = list(row_node.iter())
    row_text_values = []
    row_desc_values = []
    row_resource_ids = set()
    time_values = []
    numeric_nodes = []
    unread_hints = []
    for child in row_nodes:
        rid = child.attrib.get("resource-id", "")
        text = (child.attrib.get("text") or "").strip()
        desc = (child.attrib.get("content-desc") or "").strip()
        if rid:
            row_resource_ids.add(rid)
        if text:
            row_text_values.append(text)
            if TIME_RE.fullmatch(text) or DATE_RE.fullmatch(text):
                time_values.append(text)
            elif re.fullmatch(r"\d{1,3}", text):
                numeric_nodes.append((text, bounds_of(child), rid))
        if desc:
            row_desc_values.append(desc)
        if re.search(r"未読|unread|未読メッセージ|新規メッセージ", desc, re.I):
            unread_hints.append(desc)
        if rid and re.search(r"unread|badge|new_message|unread_count", rid, re.I):
            unread_hints.append(rid)
    displayed_time = time_values[-1] if time_values else None
    preview_values = [
        text
        for text in row_text_values
        if text != label_node.attrib.get("text", "").strip()
        and text not in time_values
        and not re.fullmatch(r"\d{1,3}", text)
    ]
    preview_text = " ".join(preview_values).strip()
    unread_count = None
    if unread_hints:
        unread_state = "unread"
        if numeric_nodes:
            unread_count = numeric_nodes[-1][0]
    elif numeric_nodes:
        unread_state = "unread"
        unread_count = numeric_nodes[-1][0]
    else:
        unread_state = "none_observed" if row_bounds and list_bounds else "unknown"
    row_intersects_viewport = bool(
        row_bounds
        and list_bounds
        and row_bounds[0] < list_bounds[2]
        and row_bounds[2] > list_bounds[0]
        and row_bounds[1] < list_bounds[3]
        and row_bounds[3] > list_bounds[1]
    )
    clickable_center_visible = bool(
        row_bounds
        and list_bounds
        and list_bounds[0] <= (row_bounds[1] + row_bounds[3]) // 2 < list_bounds[3]
    )
    row_field_nodes = [
        child for child in row_nodes
        if child.attrib.get("text", "").strip() or child.attrib.get("content-desc", "").strip()
    ]
    all_accessible_fields_visible = bool(row_field_nodes) and all(
        (field_bounds := bounds_of(child)) is not None
        and list_bounds is not None
        and field_bounds[0] >= list_bounds[0]
        and field_bounds[1] >= list_bounds[1]
        and field_bounds[2] <= list_bounds[2]
        and field_bounds[3] <= list_bounds[3]
        for child in row_field_nodes
    )
    complete = bool(row_intersects_viewport and clickable_center_visible and all_accessible_fields_visible)
    stable_ids = sorted(row_resource_ids)
    state_resource_ids = sorted(rid for rid in stable_ids if UNREAD_RESOURCE_RE.search(rid))
    content_resource_ids = sorted(set(stable_ids) - set(state_resource_ids))
    content_signature = _signature({
        "displayed_name": normalise(label_node.attrib.get("text") or label_node.attrib.get("content-desc", "")),
        "preview_text": normalise(preview_text),
        "displayed_time": normalise(displayed_time or ""),
        "stable_content_resource_ids": content_resource_ids,
    })
    state_signature = _signature({
        "unread_state": unread_state,
        "unread_count": unread_count,
        "unread_resource_ids": state_resource_ids,
    })
    signature_payload = {
        "content_signature": content_signature,
        "state_signature": state_signature,
    }
    stable_signature = _signature(signature_payload)
    return {
        "line_source_key": target["line_source_key"],
        "hall_id": target["hall_id"],
        "collector_key": target["collector_key"],
        "displayed_name": label_node.attrib.get("text") or label_node.attrib.get("content-desc"),
        "preview_text": preview_text,
        "preview_capture_status": "text_observed" if preview_text else "empty_or_not_exposed",
        "displayed_time": displayed_time,
        "unread_state": unread_state,
        "unread_count": unread_count,
        "row_resource_ids": stable_ids,
        "stable_content_resource_ids": content_resource_ids,
        "unread_resource_ids": state_resource_ids,
        "content_desc": row_desc_values,
        "row_text_values": row_text_values,
        "bounds": row_node.attrib.get("bounds"),
        "list_bounds": list_node.attrib.get("bounds") if list_node is not None else None,
        "row_complete_in_viewport": complete,
        "row_shell_clipped_but_fields_visible": bool(
            complete and row_bounds and list_bounds
            and (
                row_bounds[0] < list_bounds[0]
                or row_bounds[1] < list_bounds[1]
                or row_bounds[2] > list_bounds[2]
                or row_bounds[3] > list_bounds[3]
            )
        ),
        "clickable_row": row_node.attrib.get("clickable") == "true",
        "content_signature": content_signature,
        "state_signature": state_signature,
        "stable_row_signature": stable_signature,
        "signature_components": signature_payload,
        "source": "conversation_list_preview",
        "source_distinction": "preview is a list observation, not a complete chat_message body",
        "observed_at": observed_at,
        "raw_snapshot_ref": raw_ref,
        "page_index": page_index,
        "loading_or_progress_present": loading_present(root),
    }


def aliases_map(targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        for alias in aliases_for(target):
            result[alias].append(target)
    return result


def all_visible_row_signature(root: ET.Element) -> str:
    parents = {child: parent for parent in root.iter() for child in parent}
    page_rows = []
    width = 720
    for node in root.iter():
        b = bounds_of(node)
        if b:
            width = max(width, b[2])
    seen_rows = set()
    for node in root.iter():
        if node.attrib.get("text", "").strip():
            clickable = clickable_row_for(node, parents, width)
            if clickable is None or id(clickable) in seen_rows:
                continue
            seen_rows.add(id(clickable))
            row_text = [
                (child.attrib.get("text") or "").strip()
                for child in clickable.iter()
                if (child.attrib.get("text") or "").strip()
            ]
            page_rows.append(row_text)
    encoded = json.dumps(page_rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def conversation_rows_in_view(
    root: ET.Element,
    targets: list[dict[str, Any]],
    aliases: dict[str, list[dict[str, Any]]],
    raw_ref: str,
    page_index: int,
    observed_at: str,
) -> list[dict[str, Any]]:
    """Capture ordered visible list rows, including non-target rows for frontier proof."""
    scroll_node = list_scroll_container(root)
    viewport = bounds_of(scroll_node) if scroll_node is not None else None
    if not viewport:
        return []
    width = max((bounds_of(node)[2] for node in root.iter() if bounds_of(node)), default=720)
    parents = {child: parent for parent in root.iter() for child in parent}
    seen: set[int] = set()
    rows = []
    for text_node in root.iter():
        label = (text_node.attrib.get("text") or text_node.attrib.get("content-desc") or "").strip()
        if not label:
            continue
        row_node = clickable_row_for(text_node, parents, width)
        if row_node is None or id(row_node) in seen:
            continue
        row_bounds = bounds_of(row_node)
        if not row_bounds:
            continue
        center_y = (row_bounds[1] + row_bounds[3]) // 2
        if not (viewport[1] <= center_y < viewport[3]):
            continue
        seen.add(id(row_node))

        fields = []
        text_values = []
        desc_values = []
        resource_ids = set()
        numeric_values = []
        time_values = []
        unread_hints = []
        field_nodes = []
        for child in row_node.iter():
            rid = child.attrib.get("resource-id", "")
            if rid:
                resource_ids.add(rid)
            text = (child.attrib.get("text") or "").strip()
            desc = (child.attrib.get("content-desc") or "").strip()
            bounds = bounds_of(child)
            if text:
                text_values.append(text)
                field_nodes.append((bounds, text, "text", rid))
                if TIME_RE.fullmatch(text) or DATE_RE.fullmatch(text):
                    time_values.append(text)
                elif re.fullmatch(r"\d{1,3}", text):
                    numeric_values.append(text)
            if desc:
                desc_values.append(desc)
                field_nodes.append((bounds, desc, "content_desc", rid))
            if re.search(r"未読|unread|未読メッセージ|新規メッセージ", desc, re.I):
                unread_hints.append(desc)
            if rid and UNREAD_RESOURCE_RE.search(rid):
                unread_hints.append(rid)
        if field_nodes:
            field_nodes.sort(
                key=lambda item: (
                    item[0][1] if item[0] else 10**9,
                    item[0][0] if item[0] else 10**9,
                    item[2],
                )
            )
        ordered_text = []
        for bounds, value, kind, _rid in field_nodes:
            if kind == "text" and value not in ordered_text:
                ordered_text.append(value)
        if not ordered_text and not desc_values:
            continue
        matched_titles = [value for value in ordered_text if aliases.get(value)]
        title = matched_titles[0] if matched_titles else (ordered_text[0] if ordered_text else desc_values[0])
        possible_target_keys = {
            owner["collector_key"]
            for owner in aliases.get(title, [])
            if owner["collector_key"] in {target["collector_key"] for target in targets}
        }
        target_key = next(iter(possible_target_keys)) if len(possible_target_keys) == 1 else None
        displayed_time = time_values[-1] if time_values else None
        preview_values = [
            value for value in ordered_text
            if value != title and value not in time_values and not re.fullmatch(r"\d{1,3}", value)
        ]
        preview_text = " ".join(preview_values).strip()
        if unread_hints:
            unread_state = "unread"
            unread_count = numeric_values[-1] if numeric_values else None
        elif numeric_values:
            unread_state = "unread"
            unread_count = numeric_values[-1]
        else:
            unread_state = "none_observed"
            unread_count = None
        stable_ids = sorted(resource_ids)
        unread_ids = sorted(rid for rid in stable_ids if UNREAD_RESOURCE_RE.search(rid))
        content_ids = sorted(set(stable_ids) - set(unread_ids))
        stable_text = [
            normalise(value) for value in ordered_text
            if value not in time_values and not re.fullmatch(r"\d{1,3}", value)
        ]
        stable_desc = [
            normalise(value) for value in desc_values
            if not re.search(r"未読|unread|未読メッセージ|新規メッセージ", value, re.I)
        ]
        content_signature = _signature({
            "target_key": target_key,
            "displayed_name": normalise(title),
            "stable_text_fields": stable_text,
            "content_desc": stable_desc,
            "displayed_time": normalise(displayed_time or ""),
            "stable_content_resource_ids": content_ids,
        })
        state_signature = _signature({
            "unread_state": unread_state,
            "unread_count": unread_count,
            "unread_resource_ids": unread_ids,
        })
        field_bounds = [bounds for bounds, _value, _kind, _rid in field_nodes]
        fields_inside_view = bool(field_bounds) and all(
            bounds is not None
            and bounds[0] >= viewport[0]
            and bounds[1] >= viewport[1]
            and bounds[2] <= viewport[2]
            and bounds[3] <= viewport[3]
            for bounds in field_bounds
        )
        row_inside_view = (
            row_bounds[0] >= viewport[0]
            and row_bounds[1] >= viewport[1]
            and row_bounds[2] <= viewport[2]
            and row_bounds[3] <= viewport[3]
        )
        rows.append({
            "target_key": target_key,
            "displayed_name": title,
            "preview_text": preview_text,
            "displayed_time": displayed_time,
            "unread_state": unread_state,
            "unread_count": unread_count,
            "row_resource_ids": stable_ids,
            "stable_content_resource_ids": content_ids,
            "unread_resource_ids": unread_ids,
            "content_signature": content_signature,
            "state_signature": state_signature,
            "frontier_signature": _signature([content_signature, state_signature]),
            "complete_in_viewport": fields_inside_view and row_inside_view,
            "bounds": row_node.attrib.get("bounds"),
            "page_index": page_index,
            "observed_at": observed_at,
            "raw_snapshot_ref": raw_ref,
        })
    rows.sort(key=lambda row: (bounds_of(ET.Element("row", {"bounds": row["bounds"]}))[1], row["displayed_name"]))
    return rows


def merge_row_pages(
    previous: list[dict[str, Any]], page_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool, dict[str, Any]]:
    complete_page_rows = [row for row in page_rows if row.get("complete_in_viewport")]
    excluded_incomplete = len(page_rows) - len(complete_page_rows)
    page_rows = complete_page_rows
    if not previous:
        return list(page_rows), True, {
            "overlap_rows": 0,
            "merge_basis": "first_page",
            "excluded_incomplete_rows": excluded_incomplete,
        }
    prev_sig = [row["frontier_signature"] for row in previous]
    next_sig = [row["frontier_signature"] for row in page_rows]
    max_len = min(len(prev_sig), len(next_sig))
    overlaps = [
        size for size in range(1, max_len + 1)
        if prev_sig[-size:] == next_sig[:size]
    ]
    if not overlaps:
        return previous + page_rows, False, {
            "overlap_rows": 0,
            "merge_basis": "no_exact_page_overlap",
            "excluded_incomplete_rows": excluded_incomplete,
        }
    size = max(overlaps)
    overlap_sig = prev_sig[-size:]
    ambiguous = any(
        prev_sig.count(signature) != 1 or next_sig.count(signature) != 1
        for signature in overlap_sig
    )
    if size < 2 or ambiguous:
        return previous + page_rows[size:], False, {
            "overlap_rows": size,
            "merge_basis": "overlap_too_short_or_duplicate_signature",
            "excluded_incomplete_rows": excluded_incomplete,
        }
    return previous + page_rows[size:], True, {
        "overlap_rows": size,
        "merge_basis": "unique_exact_suffix_prefix",
        "excluded_incomplete_rows": excluded_incomplete,
    }


def find_stable_frontier(
    current_rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
    required_rows: int,
) -> dict[str, Any] | None:
    if len(current_rows) < required_rows or len(previous_rows) < required_rows:
        return None
    prior_positions: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(previous_rows):
        prior_positions[row["frontier_signature"]].append(index)
    prior_signatures = [row["frontier_signature"] for row in previous_rows]
    current_signatures = [row["frontier_signature"] for row in current_rows]
    for start, signature in enumerate(current_signatures):
        positions = prior_positions.get(signature, [])
        if len(positions) != 1 or current_signatures.count(signature) != 1:
            continue
        prior_start = positions[0]
        run = 1
        while run < required_rows and start + run < len(current_rows) and prior_start + run < len(previous_rows):
            current_sig = current_signatures[start + run]
            if (
                current_sig != prior_signatures[prior_start + run]
                or len(prior_positions.get(current_sig, [])) != 1
                or current_signatures.count(current_sig) != 1
            ):
                break
            run += 1
        if run >= required_rows:
            return {
                "current_start_index": start,
                "current_end_index": start + run - 1,
                "previous_start_index": prior_start,
                "previous_end_index": prior_start + run - 1,
                "stable_row_count": run,
                "required_stable_rows": required_rows,
                "basis": "unique_exact_consecutive_content_and_state_frontier",
            }
    return None


def save_raw(evidence_dir: Path, name: str, raw: bytes) -> str:
    path = evidence_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite RAW evidence file: {path}")
    path.write_bytes(raw)
    return str(path.relative_to(ROOT))


def scan_conversation_list(
    android: Android,
    targets: list[dict[str, Any]],
    evidence_dir: Path,
    attempt_offset: int = 0,
    scan_mode: str = "targets",
    previous_frontier_rows: list[dict[str, Any]] | None = None,
    previous_frontier_complete: bool = False,
    frontier_stable_rows: int = DEFAULT_FRONTIER_STABLE_ROWS,
) -> dict[str, Any]:
    aliases = aliases_map(targets)
    started = time.perf_counter()
    dump_success_start = android.dump_success_count
    dump_attempt_start = android.dump_attempt_count
    root, raw, error = ensure_chat_list(android)
    if root is None or raw is None:
        return {
            "status": "unknown",
            "scan_completeness": "unknown",
            "error": error,
            "list_scan_seconds": time.perf_counter() - started,
            "ui_dump_success_count": android.dump_success_count - dump_success_start,
            "ui_dump_attempt_count": android.dump_attempt_count - dump_attempt_start,
            "all_pages_settled": False,
            "pages": [],
            "target_observations": {target["collector_key"]: [] for target in targets},
            "all_target_rows_found": False,
            "all_target_rows_complete": False,
            "full_list_complete": False,
            "frontier_order_safe": False,
            "ordered_rows": [],
            "frontier": None,
            "last_root": None,
            "last_raw": None,
        }
    top_reset_observations = []
    top_reset_settled = not loading_present(root)
    top_no_progress = 0
    previous_signature = all_visible_row_signature(root)
    top_reset_stop = "top_reset_limit"
    for rewind_index in range(LIST_SCROLL_LIMIT):
        scroll_node = list_scroll_container(root)
        scroll_bounds = bounds_of(scroll_node) if scroll_node is not None else None
        if not scroll_bounds:
            top_reset_stop = "conversation_list_scroll_container_not_observed"
            break
        try:
            android.swipe_in_node(scroll_bounds, "toward_newer")
        except Exception as exc:
            top_reset_stop = f"adb_failed_during_top_reset:{type(exc).__name__}:{exc}"
            break
        time.sleep(0.45)
        top_raw, top_error, _ = android.dump()
        if top_raw is None:
            top_reset_stop = f"ui_dump_failed_during_top_reset:{top_error}"
            break
        root = parse_root(top_raw)
        if not is_chat_list(root):
            top_reset_stop = "conversation_list_lost_during_top_reset"
            break
        top_reset_settled = top_reset_settled and not loading_present(root)
        raw_ref = save_raw(evidence_dir, f"conversation_list/top_reset_{rewind_index:03d}.xml", top_raw)
        signature = all_visible_row_signature(root)
        top_reset_observations.append(
            {
                "raw_snapshot_ref": raw_ref,
                "observed_at": now_local(),
                "page_signature": signature,
                "scroll_container_bounds": scroll_node.attrib.get("bounds"),
            }
        )
        print(
            f"LIST_TOP_RESET step={rewind_index + 1} unchanged_streak="
            f"{top_no_progress + 1 if signature == previous_signature else 0}",
            flush=True,
        )
        if signature == previous_signature:
            top_no_progress += 1
        else:
            top_no_progress = 0
        previous_signature = signature
        if top_no_progress >= 2:
            top_reset_stop = "two_swipes_toward_newer_without_view_change"
            raw = top_raw
            break
        raw = top_raw
    if top_reset_stop == "top_reset_limit":
        top_reset_stop = "top_reset_scroll_limit"
    if (
        top_reset_stop.startswith(("ui_dump_failed", "adb_failed"))
        or top_reset_stop == "conversation_list_lost_during_top_reset"
    ):
        return {
            "status": "unknown",
            "scan_completeness": "unknown",
            "error": top_reset_stop,
            "list_scan_seconds": time.perf_counter() - started,
            "pages": [],
            "top_reset_observations": top_reset_observations,
            "target_observations": {target["collector_key"]: [] for target in targets},
            "all_target_rows_found": False,
            "all_target_rows_complete": False,
            "full_list_complete": False,
            "frontier_order_safe": False,
            "ordered_rows": [],
            "frontier": None,
            "last_root": None,
            "last_raw": None,
        }
    pages = []
    target_observations: dict[str, list[dict[str, Any]]] = {
        target["collector_key"]: [] for target in targets
    }
    seen_page_signatures = set()
    no_progress = 0
    stop_reason = "list_scroll_limit"
    dump_count = 0
    ordered_rows: list[dict[str, Any]] = []
    frontier_order_safe = True
    merge_events = []
    frontier = None
    full_list_complete = False
    all_pages_settled = top_reset_settled
    fallback_reason = None
    if scan_mode == "frontier" and not previous_frontier_complete:
        fallback_reason = "previous_full_list_order_checkpoint_not_complete"
    for page_index in range(LIST_SCROLL_LIMIT):
        if page_index == 0:
            page_raw = raw
        else:
            page_raw, dump_error, _ = android.dump()
            if page_raw is None:
                stop_reason = f"ui_dump_failed:{dump_error}"
                break
            root = parse_root(page_raw)
            if not is_chat_list(root):
                stop_reason = "conversation_list_lost"
                break
        dump_count += 1
        observed_at = now_local()
        raw_ref = save_raw(evidence_dir, f"conversation_list/list_{attempt_offset + dump_count - 1:03d}.xml", page_raw)
        page_signature = all_visible_row_signature(root)
        visible_targets = []
        for target in targets:
            observation = row_observation(root, target, aliases, raw_ref, page_index, observed_at)
            if observation:
                visible_targets.append(target["collector_key"])
                target_observations[target["collector_key"]].append(observation)
        page_rows = conversation_rows_in_view(root, targets, aliases, raw_ref, page_index, observed_at)
        ordered_rows, merge_ok, merge_metadata = merge_row_pages(ordered_rows, page_rows)
        frontier_order_safe = frontier_order_safe and merge_ok
        merge_events.append({"page_index": page_index, **merge_metadata, "merge_safe": merge_ok})
        scroll_node = list_scroll_container(root)
        scroll_bounds = bounds_of(scroll_node) if scroll_node is not None else None
        loading = loading_present(root)
        all_pages_settled = all_pages_settled and not loading
        pages.append(
            {
                "page_index": page_index,
                "observed_at": observed_at,
                "raw_snapshot_ref": raw_ref,
                "visible_target_keys": visible_targets,
                "page_signature": page_signature,
                "loading_or_progress_present": loading,
                "list_row_count": len(page_rows),
                "complete_list_row_count": sum(row.get("complete_in_viewport", False) for row in page_rows),
                "excluded_incomplete_list_row_count": merge_metadata.get("excluded_incomplete_rows", 0),
                "scroll_container_resource_id": scroll_node.attrib.get("resource-id") if scroll_node is not None else None,
                "scroll_container_bounds": scroll_node.attrib.get("bounds") if scroll_node is not None else None,
            }
        )
        complete_keys = {
            key
            for key, observations in target_observations.items()
            if any(o["row_complete_in_viewport"] and not o["loading_or_progress_present"] for o in observations)
        }
        print(
            f"LIST_PAGE run-evidence={raw_ref} page={page_index} target_rows={len(visible_targets)} "
            f"complete={len(complete_keys)}",
            flush=True,
        )
        if scan_mode == "targets" and len(complete_keys) == len(targets):
            stop_reason = "all_fixed_targets_found_in_complete_rows"
            break
        if scan_mode == "frontier" and fallback_reason is None and frontier_order_safe:
            frontier = find_stable_frontier(
                ordered_rows,
                previous_frontier_rows or [],
                frontier_stable_rows,
            )
            if frontier:
                if len(complete_keys) == len(targets):
                    stop_reason = "stable_ordered_row_frontier_reached_after_all_targets_observed"
                    break
                # A global UI-row watermark alone cannot certify target rows
                # below the frontier. Continue through the fixed target set;
                # unseen stores stay unknown until their exact rows are seen.
                fallback_reason = "stable_frontier_before_all_fixed_target_rows_observed"
        if (
            scan_mode == "frontier"
            and fallback_reason
            and len(complete_keys) == len(targets)
        ):
            stop_reason = "all_fixed_targets_found_after_frontier_fallback"
            break
        if page_signature in seen_page_signatures:
            no_progress += 1
        else:
            no_progress = 0
        seen_page_signatures.add(page_signature)
        if no_progress >= LIST_NO_PROGRESS_LIMIT:
            stop_reason = "three_list_scrolls_without_new_visible_content"
            full_list_complete = all_pages_settled
            if not all_pages_settled:
                fallback_reason = fallback_reason or "loading_or_progress_seen_during_list_scan"
            if scan_mode == "frontier" and frontier is None and fallback_reason is None:
                fallback_reason = "frontier_not_reached_before_full_list_boundary"
            break
        if not scroll_bounds:
            stop_reason = "conversation_list_scroll_container_not_observed"
            break
        try:
            android.swipe_in_node(scroll_bounds, "toward_older")
        except Exception as exc:
            stop_reason = f"adb_failed_during_list_scroll:{type(exc).__name__}:{exc}"
            break
        time.sleep(0.55)
    if scan_mode == "frontier" and fallback_reason and (
        full_list_complete or stop_reason == "all_fixed_targets_found_after_frontier_fallback"
    ):
        scan_completeness = "fallback_full_scan"
    elif scan_mode == "frontier" and frontier:
        scan_completeness = "incremental_complete"
    elif scan_mode == "full" and full_list_complete:
        scan_completeness = "full_scan_complete"
    elif scan_mode == "targets" and stop_reason == "all_fixed_targets_found_in_complete_rows":
        scan_completeness = "target_set_complete"
    else:
        scan_completeness = "unknown"
    return {
        "status": "success" if pages and all_pages_settled else "unknown",
        "scan_completeness": scan_completeness,
        "error": None if pages else stop_reason,
        "list_scan_seconds": time.perf_counter() - started,
        "pages": pages,
        "target_observations": target_observations,
        "all_target_rows_found": all(bool(items) for items in target_observations.values()),
        "all_target_rows_complete": all(
            any(o["row_complete_in_viewport"] and not o["loading_or_progress_present"] for o in items)
            for items in target_observations.values()
        ),
        "full_list_complete": full_list_complete,
        "frontier_order_safe": frontier_order_safe,
        "ordered_rows": ordered_rows,
        "frontier": frontier,
        "frontier_stable_rows_required": frontier_stable_rows if scan_mode == "frontier" else None,
        "previous_frontier_complete": previous_frontier_complete if scan_mode == "frontier" else None,
        "fallback_reason": fallback_reason,
        "row_sequence_merge_events": merge_events,
        "top_reset_observations": top_reset_observations,
        "top_reset_stop_reason": top_reset_stop,
        "stop_reason": stop_reason,
        "dump_count": dump_count + len(top_reset_observations),
        "ui_dump_success_count": android.dump_success_count - dump_success_start,
        "ui_dump_attempt_count": android.dump_attempt_count - dump_attempt_start,
        "all_pages_settled": all_pages_settled,
        "last_root": root,
        "last_raw": raw,
    }


def choose_best_observation(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not observations:
        return None
    return max(
        observations,
        key=lambda row: (
            bool(row.get("row_complete_in_viewport")),
            not bool(row.get("loading_or_progress_present")),
            bool(row.get("preview_text")),
            bool(row.get("displayed_time")),
            row.get("page_index", -1),
        ),
    )


def detect_candidate(
    observation: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    list_status: str,
) -> tuple[str, str]:
    if list_status != "success" or observation is None:
        return "unknown", "target_row_not_observed_in_a_successful_conversation_list_scan"
    if not observation.get("row_complete_in_viewport") or observation.get("loading_or_progress_present"):
        return "unknown", "target_row_partial_or_list_still_loading"
    if previous is None:
        return "first_observation", "no_previous_checkpoint"
    current_content = observation_content_signature(observation)
    previous_content = observation_content_signature(previous)
    if not current_content or not previous_content:
        return "unknown", "content_signature_missing_from_current_or_previous_checkpoint"
    has_signal = bool(
        observation.get("preview_text")
        or observation.get("displayed_time")
        or observation.get("unread_state") == "unread"
    )
    if not has_signal:
        return "unknown", "row_has_no_comparable_preview_time_or_unread_signal"
    if current_content != previous_content:
        if is_exact_day_label_rollover(previous, observation):
            return "unchanged", "line_time_label_rollover_only"
        return "changed", "preview_time_name_or_stable_content_fields_changed"
    current_state = observation_state_signature(observation)
    previous_state = observation_state_signature(previous)
    if not current_state or not previous_state:
        return "unknown", "state_signature_missing_from_current_or_previous_checkpoint"
    if current_state == previous_state:
        return "unchanged", "complete_row_content_and_ui_state_match_checkpoint"

    # A chat open can clear the unread badge. Suppress only the exact transition
    # that the previous run recorded as its own expected read-state effect.
    expected_read = previous.get("expected_read_state_transition")
    if (
        expected_read
        and previous.get("unread_state") == "unread"
        and observation.get("unread_state") == "none_observed"
        and not observation.get("unread_count")
    ):
        return "unchanged", "collector_expected_read_state_transition_with_same_content"

    # State changes in either direction are retained and investigated. In
    # particular, a new unread badge/count can signal activity even when the
    # preview text and displayed minute happen to be unchanged.
    return "changed", "ui_read_state_changed_without_content_change_requires_chat_check"


def load_active_events(targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    wanted = {row["line_source_key"]: row["collector_key"] for row in targets}
    events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for manifest_path in sorted((ROOT / "data/raw").rglob("manifest.json")):
        try:
            data = load_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            line_key = entry.get("line_source_key")
            key = entry.get("collector_key") or wanted.get(line_key)
            if key not in {target["collector_key"] for target in targets} or wanted.get(line_key) != key:
                continue
            if entry.get("adapter_type") == "passive":
                continue
            received = entry.get("received_at")
            if not received:
                continue
            try:
                local = datetime.fromisoformat(received.replace("Z", "+00:00")).astimezone(TIMEZONE)
            except ValueError:
                continue
            trigger = entry.get("trigger") or {}
            events[key].append(
                {
                    "line_source_key": line_key,
                    "triggered_at": entry.get("triggered_at"),
                    "received_at": received,
                    "local_date": local.date().isoformat(),
                    "local_time": local.strftime("%H:%M"),
                    "run_id": entry.get("run_id"),
                    "trigger_text": trigger.get("text") or trigger.get("trigger_text") or trigger.get("action_label"),
                    "manifest": str(manifest_path.relative_to(ROOT)),
                }
            )
    return events


def date_context_matches(contexts: list[str], local_date: str) -> bool:
    date = datetime.fromisoformat(local_date).date()
    survey_date = datetime.now(TIMEZONE).date()
    for context in contexts:
        if context == "今日" and date == survey_date:
            return True
        if context == "昨日" and date == survey_date - timedelta(days=1):
            return True
        if context == "一昨日" and date == survey_date - timedelta(days=2):
            return True
        match = re.match(r"^(\d{1,2})月(\d{1,2})日", context)
        if match and (date.month, date.day) == (int(match.group(1)), int(match.group(2))):
            return True
        match = re.match(r"^(\d{1,2})/(\d{1,2})$", context)
        if match and (date.month, date.day) == (int(match.group(1)), int(match.group(2))):
            return True
    return False


def message_rows(root: ET.Element, line_source_key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    date_contexts = []
    row_resource_id = LINE_ID_PREFIX + "chat_ui_row_swipeable_framelayout"
    for node in root.iter():
        if node.attrib.get("resource-id") == row_resource_id:
            continue
        label = text_of(node).strip()
        if DATE_RE.fullmatch(label) and label not in date_contexts:
            date_contexts.append(label)
    logical = {}
    raw_rows = []
    for index, row in enumerate(
        node for node in root.iter() if node.attrib.get("resource-id") == row_resource_id
    ):
        nodes = list(row.iter())
        ids = sorted({node.attrib.get("resource-id", "") for node in nodes if node.attrib.get("resource-id")})
        texts, descs, times = [], [], []
        for node in nodes:
            rid = node.attrib.get("resource-id", "")
            text = (node.attrib.get("text") or "").strip()
            desc = (node.attrib.get("content-desc") or "").strip()
            if rid == LINE_ID_PREFIX + "chat_ui_row_timestamp" and text:
                times.append(text)
            elif text:
                texts.append(text)
            if desc:
                descs.append(desc)
        if LINE_ID_PREFIX + "chat_ui_row_receive_rich_container" in ids:
            kind = "rich_card"
        elif LINE_ID_PREFIX + "chat_ui_row_send_rich_container" in ids:
            kind = "rich_card"
        elif LINE_ID_PREFIX + "chat_ui_row_image_balloon_root" in ids:
            kind = "image"
        elif LINE_ID_PREFIX + "chat_ui_row_text_message" in ids:
            kind = "text"
        else:
            kind = "unknown"
        if any("row_receive" in value or "message_receive" in value for value in ids):
            direction = "incoming"
            direction_evidence = "LINE_receive_resource_id"
        elif any("row_send" in value or "row_sent" in value or "message_send" in value for value in ids):
            direction = "outgoing"
            direction_evidence = "LINE_send_resource_id"
        else:
            b = bounds_of(row)
            width = max((bounds_of(node)[2] for node in root.iter() if bounds_of(node)), default=720)
            if b:
                center_x = (b[0] + b[2]) / 2
                direction = "incoming" if center_x < width / 2 else "outgoing"
                direction_evidence = "bubble_alignment_relative_to_dump_width"
            else:
                direction, direction_evidence = "unknown", "no_direction_evidence"
        display_time = times[-1] if times else None
        payload = {
            "line_source_key": line_source_key,
            "message_type": kind,
            "direction": direction,
            "line_display_time": display_time,
            "date_separator_context": date_contexts,
            "text": texts,
            "content_desc": descs,
            "stable_resource_ids": ids,
        }
        has_stable_data = bool(display_time or texts or descs)
        logical_key = (
            hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if has_stable_data
            else None
        )
        item = {
            **payload,
            "source": "chat_message",
            "direction": direction,
            "direction_evidence": direction_evidence,
            "bounds": row.attrib.get("bounds"),
            "raw_row_index": index,
            "logical_candidate_key": logical_key,
            "candidate_status": "identity_uncertain" if logical_key is None else None,
        }
        raw_rows.append(item)
        if logical_key:
            logical.setdefault(logical_key, item.copy())
            logical[logical_key]["raw_observation_count"] = logical[logical_key].get("raw_observation_count", 0) + 1
    return raw_rows, list(logical.values())


def classify_origin(
    row: dict[str, Any],
    events: list[dict[str, Any]],
    identity_verified: bool,
) -> tuple[str, str]:
    if row.get("direction") == "outgoing":
        return "user_outgoing", "not_incoming"
    if row.get("direction") != "incoming" or not identity_verified:
        return "unknown", "incoming_direction_or_identity_not_verified"
    payload = normalise(" ".join(row.get("text", []) + row.get("content_desc", [])))
    if WELCOME_RE.search(payload):
        return "welcome_greeting", "welcome_text"
    possible = [
        event for event in events
        if row.get("line_display_time") and row["line_display_time"] == event.get("local_time")
    ]
    if any(date_context_matches(row.get("date_separator_context") or [], event["local_date"]) for event in possible):
        return "active_reply", "manifest_run_time_and_visible_date_context_match"
    if possible and not row.get("date_separator_context"):
        return "unknown", "possible_active_manifest_time_match_but_date_context_missing"
    if events and not row.get("line_display_time") and not row.get("date_separator_context"):
        return "unknown", "active_manifest_cannot_be_ruled_out_without_message_time_or_date_context"
    if row.get("message_type") == "rich_card" and not normalise(" ".join(row.get("text", []))):
        accessible_card_label = normalise(" ".join(row.get("content_desc", [])))
        if not RICH_CARD_NOTICE_RE.search(accessible_card_label):
            return "unknown", "rich_card_exposes_only_a_generic_or_non_notice_accessibility_label"
    if ORDINARY_NOTICE_RE.search(payload):
        return "passive_candidate", "incoming_ordinary_notice_text; no matched active manifest"
    return "unknown", "incoming_content_does_not_verify_natural_store_notice"


def preview_association(preview: str, rows: list[dict[str, Any]], displayed_time: str | None) -> dict[str, Any]:
    incoming = [row for row in rows if row.get("direction") == "incoming"]
    p = normalise(preview)
    exact = []
    if p:
        for row in incoming:
            row_text = normalise(" ".join(row.get("text", [])))
            row_desc = normalise(" ".join(row.get("content_desc", [])))
            if p in row_text or p in row_desc:
                exact.append(row.get("logical_candidate_key"))
    if exact:
        return {
            "status": "preview_and_chat_matched",
            "basis": "preview text exactly occurs in focused-chat incoming text/content-desc",
            "matched_candidate_keys": exact,
        }
    same_minute = [
        row for row in incoming
        if displayed_time and row.get("line_display_time") == displayed_time
    ]
    if preview and same_minute:
        return {
            "status": "association_uncertain",
            "basis": "incoming row has the same displayed minute but its content does not match; time alone is not used to associate",
            "same_minute_candidate_keys": [row.get("logical_candidate_key") for row in same_minute],
        }
    if preview:
        return {
            "status": "preview_only",
            "basis": "preview exists, but focused-chat UI provided no content match or same-minute incoming row",
        }
    if incoming:
        return {"status": "chat_only", "basis": "incoming focused-chat row exists while list preview is empty"}
    return {"status": "association_uncertain", "basis": "neither preview text nor incoming chat content was available"}


def infer_current_page(
    root: ET.Element,
    targets: list[dict[str, Any]],
    aliases: dict[str, list[dict[str, Any]]],
    pages: list[dict[str, Any]],
    default_page: int,
) -> int:
    current_keys = {
        target["collector_key"]
        for target in targets
        if row_observation(root, target, aliases, "", default_page, now_local()) is not None
    }
    best_page, best_score = default_page, 0
    for page in pages:
        page_keys = set(page.get("visible_target_keys", []))
        score = len(page_keys & current_keys)
        if score > best_score:
            best_page, best_score = page.get("page_index", default_page), score
    return best_page


def locate_live_row(
    android: Android,
    target: dict[str, Any],
    aliases: dict[str, list[dict[str, Any]]],
    evidence_dir: Path,
    pages: list[dict[str, Any]],
    start_page: int,
    dump_index: int,
    cached_root: ET.Element | None = None,
    cached_raw: bytes | None = None,
) -> tuple[ET.Element | None, ET.Element | None, bytes | None, str | None, int, int]:
    current_page = start_page
    no_progress = 0
    for attempt in range(LIST_SCROLL_LIMIT):
        raw_ref = None
        if cached_root is not None and cached_raw is not None:
            root, raw = cached_root, cached_raw
            cached_root = None
            cached_raw = None
        else:
            raw, error, _ = android.dump()
            if raw is None:
                return None, None, None, error, current_page, dump_index
            root = parse_root(raw)
            dump_index += 1
            raw_ref = save_raw(evidence_dir, f"conversation_list/navigation_{dump_index:03d}.xml", raw)
        if not is_chat_list(root):
            return None, root, raw, "conversation_list_lost_while_locating_target", current_page, dump_index
        live = row_observation(root, target, aliases, raw_ref, current_page, now_local())
        if live and live.get("row_complete_in_viewport") and not live.get("loading_or_progress_present"):
            _, row_node = _live_row_node(root, target, aliases)
            return row_node, root, raw, None, current_page, dump_index
        scroll_node = list_scroll_container(root)
        b = bounds_of(scroll_node) if scroll_node is not None else None
        if not b:
            return None, root, raw, "conversation_list_scroll_node_missing", current_page, dump_index
        target_page = max(
            (
                observation.get("page_index", start_page)
                for observation in pages
                if target["collector_key"] in observation.get("visible_target_keys", [])
            ),
            default=start_page,
        )
        direction = "toward_newer" if current_page > target_page else "toward_older"
        before = all_visible_row_signature(root)
        try:
            android.swipe_in_node(b, direction)
        except Exception as exc:
            return None, cached_root, cached_raw, f"adb_failed_while_locating_target:{type(exc).__name__}:{exc}", current_page, dump_index
        time.sleep(0.55)
        next_raw, next_error, _ = android.dump()
        if next_raw is None:
            return None, None, None, next_error, current_page, dump_index
        next_root = parse_root(next_raw)
        dump_index += 1
        save_raw(evidence_dir, f"conversation_list/navigation_{dump_index:03d}.xml", next_raw)
        after = all_visible_row_signature(next_root)
        if before == after:
            no_progress += 1
        else:
            no_progress = 0
            current_page += 1 if direction == "toward_older" else -1
        cached_root, cached_raw = next_root, next_raw
        raw_ref = None
        if no_progress >= LIST_NO_PROGRESS_LIMIT:
            return None, next_root, next_raw, "target_not_visible_after_dynamic_list_scroll", current_page, dump_index
    return None, None, None, "target_row_location_scroll_limit", current_page, dump_index


def _live_row_node(
    root: ET.Element,
    target: dict[str, Any],
    aliases: dict[str, list[dict[str, Any]]],
) -> tuple[ET.Element | None, ET.Element | None]:
    width = 720
    for node in root.iter():
        b = bounds_of(node)
        if b:
            width = max(width, b[2])
    parents = {child: parent for parent in root.iter() for child in parent}
    for node in root.iter():
        label = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
        if label not in aliases or target["collector_key"] not in {
            row["collector_key"] for row in aliases.get(label, [])
        }:
            continue
        row = clickable_row_for(node, parents, width)
        if row is not None:
            return node, row
    return None, None


def match_active_status(row: dict[str, Any], events: list[dict[str, Any]]) -> tuple[str, str]:
    origin, reason = classify_origin(row, events, True)
    return origin, reason


def acquire_chat(
    android: Android,
    target: dict[str, Any],
    live_row: ET.Element,
    list_root: ET.Element,
    list_scan: dict[str, Any],
    active_events: list[dict[str, Any]],
    previous_message_keys: set[str],
    previous_checkpoint: dict[str, Any] | None,
    evidence_dir: Path,
    chat_index: int,
) -> tuple[dict[str, Any], dict[str, Any] | None, int]:
    started = time.perf_counter()
    row_bounds = bounds_of(live_row)
    if not row_bounds:
        return {
            "status": "navigation_failed",
            "error_class": "navigation_failed",
            "identity_verified": False,
            "elapsed_seconds": time.perf_counter() - started,
        }, None, 0
    android.tap_live_bounds(row_bounds)
    time.sleep(0.75)
    dumps = []
    root = None
    raw = None
    error = None
    settle_attempts = 0
    settled = False
    for attempt in range(MAX_SETTLE_RETRIES + 1):
        settle_attempts = attempt
        raw, error, retries_used = android.dump(retries=0)
        if raw is None:
            error = error or "uiautomator_dump_failed"
        else:
            root = parse_root(raw)
            if chat_header(root) in aliases_for(target) and not loading_present(root):
                settled = True
                break
            if chat_header(root) not in aliases_for(target):
                error = "target_header_not_verified"
        if attempt < MAX_SETTLE_RETRIES:
            time.sleep(1.1 + attempt * 0.35)
    if raw is None or root is None or chat_header(root) not in aliases_for(target) or not settled:
        result = {
            "status": "identity_uncertain",
            "error_class": (
                "target_not_verified"
                if root is not None and chat_header(root) not in aliases_for(target)
                else "ui_not_settled"
            ),
            "error": error,
            "identity_verified": False,
            "observed_chat_header": chat_header(root) if root is not None else None,
            "settle_retry_count": settle_attempts,
            "elapsed_seconds": time.perf_counter() - started,
            "preview_chat_association": {"status": "association_uncertain", "basis": "target chat identity/UI not verified"},
            "raw_ui_observations": [],
            "logical_message_candidates": [],
        }
        try:
            android.back()
            time.sleep(0.35)
        except Exception:
            pass
        return result, None, 0

    target_aliases = aliases_for(target)
    first_name = f"chat/chat_{chat_index:02d}_{target['collector_key']}_open.xml"
    raw_ref = save_raw(evidence_dir, first_name, raw)
    dumps.append({"raw_snapshot_ref": raw_ref, "observed_at": now_local(), "loading_or_progress_present": loading_present(root)})
    bottom_button = next(
        (
            node for node in root.iter()
            if node.attrib.get("resource-id") == LINE_ID_PREFIX + "chat_ui_scroll_to_bottom_button"
            and bounds_of(node)
        ),
        None,
    )
    used_latest_navigation = False
    if bottom_button is not None:
        # This is the explicit LINE "jump to latest messages" navigation control, not a message/menu action.
        android.tap_live_bounds(bounds_of(bottom_button))
        used_latest_navigation = True
        time.sleep(0.65)
        latest_raw, latest_error, _ = android.dump()
        if latest_raw:
            raw = latest_raw
            root = parse_root(raw)
            latest_ref = save_raw(
                evidence_dir,
                f"chat/chat_{chat_index:02d}_{target['collector_key']}_latest.xml",
                raw,
            )
            dumps.append(
                {
                    "raw_snapshot_ref": latest_ref,
                    "observed_at": now_local(),
                    "loading_or_progress_present": loading_present(root),
                    "latest_navigation": True,
                }
            )
        else:
            error = latest_error

    raw_rows, logical_rows = message_rows(root, target["line_source_key"])
    row_results = []
    new_verified = duplicate_count = uncertain_count = 0
    prior_preview = (previous_checkpoint or {}).get("preview_text", "")
    current_preview = list_scan.get("selected_observation", {}).get("preview_text", "")
    preview_changed = bool(current_preview) and current_preview != prior_preview
    has_chat_baseline = bool(
        previous_checkpoint
        and "message_candidate_keys" in previous_checkpoint
        and previous_checkpoint.get("message_baseline_status") != "preview_only_list_baseline"
    )
    for row in logical_rows:
        key = row.get("logical_candidate_key")
        origin, origin_reason = match_active_status(row, active_events)
        row["origin_class"] = origin
        row["origin_reason"] = origin_reason
        if not previous_checkpoint:
            status = "identity_uncertain"
            status_reason = "baseline_capture_without_previous_message_checkpoint"
        elif not key:
            status = "identity_uncertain"
            status_reason = "message_row_has_no_stable_candidate_key"
        elif key in previous_message_keys:
            status = "duplicate_candidate"
            status_reason = "candidate_signature_exists_in_previous_checkpoint"
            duplicate_count += 1
        elif origin == "passive_candidate" and preview_changed and association.get("status") == "preview_and_chat_matched":
            status = "new_verified"
            status_reason = "incoming notice exactly matches a changed checkpointed conversation-list preview"
            new_verified += 1
        elif origin == "passive_candidate" and has_chat_baseline and (
            row.get("line_display_time") or row.get("date_separator_context")
        ):
            status = "new_verified"
            status_reason = "new incoming ordinary notice has usable message time/date context; identity verified; no matching active manifest"
            new_verified += 1
        else:
            status = "identity_uncertain"
            if origin == "passive_candidate" and not has_chat_baseline:
                status_reason = "preview_only_baseline_requires_exact_match_to_changed_preview"
            elif origin == "passive_candidate" and not row.get("line_display_time") and not row.get("date_separator_context"):
                status_reason = "message key is new but the chat row has no date/time and the preview was not changed; age cannot be verified"
            else:
                status_reason = f"new row but origin is {origin}: {origin_reason}"
            uncertain_count += 1
        row["candidate_status"] = status
        row["candidate_status_reason"] = status_reason
        row_results.append(row)
    association = preview_association(
        list_scan.get("selected_observation", {}).get("preview_text", ""),
        logical_rows,
        list_scan.get("selected_observation", {}).get("displayed_time"),
    )
    result = {
        "status": "success",
        "error_class": "success",
        "identity_verified": True,
        "observed_chat_header": chat_header(root),
        "settle_retry_count": settle_attempts,
        "latest_navigation_control_used": used_latest_navigation,
        "raw_observation_row_count": len(raw_rows),
        "unique_logical_candidate_count": len(logical_rows),
        "raw_message_row_observations": raw_rows,
        "logical_message_candidates": row_results,
        "preview_chat_association": association,
        "new_verified_count": new_verified,
        "duplicate_candidate_count": duplicate_count,
        "identity_uncertain_count": uncertain_count,
        "raw_ui_observations": dumps,
        "elapsed_seconds": time.perf_counter() - started,
    }
    checkpoint_update = {
        "message_candidate_keys": sorted(set(previous_message_keys) | {r["logical_candidate_key"] for r in logical_rows if r.get("logical_candidate_key")})[-500:],
        "message_baseline_status": "chat_rows_captured",
        "last_chat_observed_at": now_local(),
        "last_preview_chat_association": association,
    }
    try:
        android.back()
        time.sleep(0.45)
    except Exception:
        result["return_to_list_error"] = "back_navigation_failed"
    return result, checkpoint_update, len(dumps)


def load_serial(adb: str, requested: str | None) -> str:
    proc = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=20, check=False)
    if proc.returncode != 0:
        raise RuntimeError("could not enumerate adb devices")
    devices = [
        line.split()[0]
        for line in proc.stdout.splitlines()[1:]
        if line.strip() and len(line.split()) >= 2 and line.split()[1] == "device"
    ]
    if requested:
        if requested not in devices:
            raise RuntimeError(f"requested Android device is not ready: {requested}")
        return requested
    if len(devices) != 1:
        raise RuntimeError(f"expected exactly one ready Android device; found {len(devices)}")
    return devices[0]


def seed_checkpoint_from_existing_list_run(
    targets: list[dict[str, Any]],
    source_run_id: str,
    checkpoint_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Build a 41-store list baseline from already preserved exact-name list XML."""
    if checkpoint_path.exists():
        raise RuntimeError(f"refusing to overwrite existing checkpoint: {checkpoint_path}")
    source_output = load_json(OUTPUT_FILE)
    source_run = next(
        (run for run in source_output.get("runs", []) if run.get("run_id") == source_run_id),
        None,
    )
    if source_run is None:
        raise RuntimeError(f"existing survey has no run_id={source_run_id}")
    aliases = aliases_map(targets)
    observations: dict[str, list[dict[str, Any]]] = {target["collector_key"]: [] for target in targets}
    frontier_rows: list[dict[str, Any]] = []
    merge_safe = True
    for page in source_run.get("conversation_list_scan", {}).get("pages", []):
        raw_path = ROOT / page["raw_snapshot_ref"]
        if not raw_path.is_file():
            raise RuntimeError(f"existing RAW list snapshot missing: {raw_path}")
        root = parse_root(raw_path.read_bytes())
        for target in targets:
            row = row_observation(
                root,
                target,
                aliases,
                page["raw_snapshot_ref"],
                page.get("page_index", 0),
                page.get("observed_at", now_local()),
            )
            if row:
                observations[target["collector_key"]].append(row)
        page_rows = conversation_rows_in_view(
            root,
            targets,
            aliases,
            page["raw_snapshot_ref"],
            page.get("page_index", 0),
            page.get("observed_at", now_local()),
        )
        frontier_rows, page_merge_safe, _merge_metadata = merge_row_pages(frontier_rows, page_rows)
        merge_safe = merge_safe and page_merge_safe
    chosen = {
        key: choose_best_observation(rows)
        for key, rows in observations.items()
    }
    incomplete = [
        key for key, row in chosen.items()
        if not row or not row.get("row_complete_in_viewport") or row.get("loading_or_progress_present")
    ]
    if incomplete:
        raise RuntimeError(f"cannot safely seed list baseline; target rows incomplete: {incomplete}")

    old_checkpoint = load_json(CHECKPOINT_FILE, {"targets": {}})
    old_targets = old_checkpoint.get("targets", {})
    checkpoint_targets = {}
    for target in targets:
        key = target["collector_key"]
        row = dict(chosen[key])
        old = old_targets.get(key)
        if old and "message_candidate_keys" in old:
            row["message_candidate_keys"] = list(old.get("message_candidate_keys") or [])
            row["message_baseline_status"] = old.get("message_baseline_status", "chat_rows_captured")
            for field in ("last_chat_observed_at", "last_preview_chat_association"):
                if field in old:
                    row[field] = old[field]
        else:
            row["message_baseline_status"] = "preview_only_list_baseline"
        checkpoint_targets[key] = row

    checkpoint = {
        "schema_version": "2",
        "updated_at": now_local(),
        "source_survey": str(CAPABILITY_FILE.relative_to(ROOT)),
        "derived_state_only": True,
        "target_set_size": 41,
        "targets": checkpoint_targets,
        "frontier_rows": frontier_rows,
        "frontier_rows_order_safe": merge_safe,
        "frontier_list_complete": False,
        "baseline_source": {
            "type": "preserved_raw_conversation_list_xml",
            "source_file": str(OUTPUT_FILE.relative_to(ROOT)),
            "source_run_id": source_run_id,
            "target_rows_found_and_complete": len(chosen),
            "message_baseline_from_prior_20_store_checkpoint_count": sum(key in old_targets and "message_candidate_keys" in old_targets[key] for key in checkpoint_targets),
            "target_count": len(targets),
            "full_list_boundary_observed": False,
        },
    }
    atomic_json(checkpoint_path, checkpoint)
    existing_output = load_json(output_path, {"schema_version": "1.0", "runs": []})
    existing_output.setdefault("survey_id", "passive-incremental-41-acceptance-2026-09-26")
    existing_output.setdefault("timezone", "Asia/Tokyo")
    existing_output.setdefault("source_survey", str(CAPABILITY_FILE.relative_to(ROOT)))
    existing_output.setdefault("target_keys", [target["collector_key"] for target in targets])
    existing_output.setdefault("runs", [])
    existing_output["existing_evidence_baseline"] = checkpoint["baseline_source"] | {
        "target_keys": [target["collector_key"] for target in targets],
        "frontier_prefix_rows": len(frontier_rows),
        "frontier_prefix_merge_safe": merge_safe,
        "note": "No chat was opened to seed; 21 added targets start from exact list previews and can only yield a verified new message when an incoming row exactly matches a changed checkpointed preview.",
    }
    atomic_json(output_path, existing_output)
    return {
        "target_count": len(targets),
        "complete_target_list_rows": len(chosen),
        "chat_history_baseline_count": checkpoint["baseline_source"]["message_baseline_from_prior_20_store_checkpoint_count"],
        "preview_only_baseline_count": len(targets) - checkpoint["baseline_source"]["message_baseline_from_prior_20_store_checkpoint_count"],
        "frontier_prefix_rows": len(frontier_rows),
        "frontier_prefix_merge_safe": merge_safe,
        "full_list_boundary_observed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="unique label, e.g. 41-full-01 or 41-frontier-01")
    parser.add_argument("--serial", help="Android serial; inferred only when exactly one device is ready")
    parser.add_argument("--adb", default=shutil.which("adb") or "/tmp/codex-adb-bridge/adb")
    parser.add_argument("--target-set", choices=("20", "41", "registry"), default="20")
    parser.add_argument("--scan-mode", choices=("targets", "full", "frontier"))
    parser.add_argument("--frontier-stable-rows", type=int, default=DEFAULT_FRONTIER_STABLE_ROWS)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--seed-existing-list-run", help="build the 41-store list baseline from preserved raw list XML and exit")
    args = parser.parse_args()
    if args.run_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,40}", args.run_id):
        parser.error("run-id must use letters, digits, underscore or hyphen")
    if args.frontier_stable_rows < 4:
        parser.error("frontier-stable-rows must be at least 4")

    if args.target_set != "registry":
        args.target_set = int(args.target_set)
    if args.target_set == "registry":
        args.checkpoint = args.checkpoint or CHECKPOINT_FILE_REGISTRY
        args.output = args.output or OUTPUT_FILE_REGISTRY
        args.evidence_dir = args.evidence_dir or EVIDENCE_DIR_REGISTRY
    elif args.target_set == 41:
        args.checkpoint = args.checkpoint or CHECKPOINT_FILE_41
        args.output = args.output or OUTPUT_FILE_41
        args.evidence_dir = args.evidence_dir or EVIDENCE_DIR_41
    else:
        args.checkpoint = args.checkpoint or CHECKPOINT_FILE
        args.output = args.output or OUTPUT_FILE
        args.evidence_dir = args.evidence_dir or EVIDENCE_DIR
    targets = select_targets(args.target_set)
    aliases = aliases_map(targets)
    if args.seed_existing_list_run:
        if args.target_set != 41:
            parser.error("--seed-existing-list-run requires --target-set 41")
        summary = seed_checkpoint_from_existing_list_run(
            targets, args.seed_existing_list_run, args.checkpoint, args.output
        )
        print(json.dumps({"seeded_from_run": args.seed_existing_list_run, "summary": summary}, ensure_ascii=False))
        return
    if not args.run_id:
        parser.error("--run-id is required unless --seed-existing-list-run is used")
    scan_mode = args.scan_mode or ("targets" if args.target_set == 20 else "full")
    serial = load_serial(args.adb, args.serial)
    checkpoint = load_json(args.checkpoint, {"schema_version": "1", "targets": {}})
    if args.target_set == 41 and len(checkpoint.get("targets", {})) != 41:
        raise RuntimeError("41-store list baseline is incomplete; seed from preserved evidence before scanning")
    existing_output = load_json(args.output, {"schema_version": "1", "runs": []})
    if any(run.get("run_id") == args.run_id for run in existing_output.get("runs", [])):
        raise RuntimeError(f"run_id already exists in output; refusing to overwrite: {args.run_id}")
    evidence_dir = args.evidence_dir / args.run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    android = Android(args.adb, serial, f"/sdcard/slot-line-passive-incremental-{os.getpid()}.xml")
    active_events = load_active_events(targets)
    started = time.perf_counter()
    run_dump_success_start = android.dump_success_count
    run_dump_attempt_start = android.dump_attempt_count

    list_scan = scan_conversation_list(
        android,
        targets,
        evidence_dir,
        scan_mode=scan_mode,
        previous_frontier_rows=checkpoint.get("frontier_rows", []),
        previous_frontier_complete=bool(
            checkpoint.get("frontier_list_complete") and checkpoint.get("frontier_rows_order_safe")
        ),
        frontier_stable_rows=args.frontier_stable_rows,
    )
    scan_finished = time.perf_counter()
    checkpoint_targets = checkpoint.setdefault("targets", {})
    observations = list_scan.get("target_observations", {})
    chosen = {
        key: choose_best_observation(observations.get(key, []))
        for key in [target["collector_key"] for target in targets]
    }
    candidate_started = time.perf_counter()
    outcomes = {}
    scan_is_complete_enough_to_decide = list_scan.get("scan_completeness") in {
        "target_set_complete", "full_scan_complete", "incremental_complete", "fallback_full_scan"
    }
    for target in targets:
        key = target["collector_key"]
        prior = checkpoint_targets.get(key)
        if not scan_is_complete_enough_to_decide:
            candidate_status, reason = "unknown", "conversation_list_scan_incomplete_or_frontier_unproven"
        else:
            candidate_status, reason = detect_candidate(chosen.get(key), prior, list_scan.get("status", "unknown"))
        outcomes[key] = {
            "candidate_detection": candidate_status,
            "candidate_detection_reason": reason,
            "chat_open_required": candidate_status in {"changed", "first_observation"},
            "passive_update_status": "absent" if candidate_status == "unchanged" else "unknown",
            "conversation_list_observation": chosen.get(key),
            "conversation_list_observations": observations.get(key, []),
            "chat_acquisition": None,
            "changed_message_count": 0,
        }
    candidate_detection_seconds = time.perf_counter() - candidate_started

    candidates = [
        target for target in targets
        if outcomes[target["collector_key"]]["candidate_detection"] in {"changed", "first_observation"}
        and chosen.get(target["collector_key"])
        and chosen[target["collector_key"]].get("row_complete_in_viewport")
    ]
    # Work from the last scrolled page toward the first to minimize list navigation.
    candidates.sort(
        key=lambda target: (
            chosen[target["collector_key"]].get("page_index", 0),
            chosen[target["collector_key"]].get("displayed_name", ""),
        ),
        reverse=True,
    )
    chat_started = time.perf_counter()
    current_page = max((page.get("page_index", 0) for page in list_scan.get("pages", [])), default=0)
    current_list_root = list_scan.get("last_root")
    current_list_raw = list_scan.get("last_raw")
    navigation_dump_index = list_scan.get("dump_count", 0)
    opened_chat_count = 0
    chat_attempt_count = 0
    chat_dump_count = 0
    total_new_verified = 0
    association_counts = CounterLike()
    list_after_open_observations = []
    page_keys = list_scan.get("pages", [])
    for chat_index, target in enumerate(candidates, 1):
        key = target["collector_key"]
        locate_start = time.perf_counter()
        live_row, live_root, _, locate_error, current_page, navigation_dump_index = locate_live_row(
            android,
            target,
            aliases,
            evidence_dir,
            page_keys,
            current_page,
            navigation_dump_index,
            current_list_root,
            current_list_raw,
        )
        outcomes[key]["live_row_navigation_seconds"] = time.perf_counter() - locate_start
        if live_row is None or live_root is None:
            if live_root is not None and is_chat_list(live_root):
                current_list_root, current_list_raw = live_root, _
            else:
                current_list_root, current_list_raw = None, None
            outcomes[key]["candidate_detection"] = "unknown"
            outcomes[key]["candidate_detection_reason"] = locate_error or "live_exact_row_not_observed"
            outcomes[key]["passive_update_status"] = "unknown"
            continue
        live_label, live_row = _live_row_node(live_root, target, aliases)
        if live_label is None or live_row is None or not bounds_of(live_row):
            outcomes[key]["candidate_detection"] = "unknown"
            outcomes[key]["candidate_detection_reason"] = "live_exact_clickable_row_missing"
            outcomes[key]["passive_update_status"] = "unknown"
            continue
        current_list_root, current_list_raw = None, None
        previous = checkpoint_targets.get(key)
        previous_keys = set((previous or {}).get("message_candidate_keys", []))
        chat_attempt_count += 1
        chat_result, chat_checkpoint, dumps_added = acquire_chat(
            android,
            target,
            live_row,
            live_root,
            {
                "selected_observation": outcomes[key].get("conversation_list_observation") or {},
            },
            active_events.get(key, []),
            previous_keys,
            previous,
            evidence_dir,
            chat_index,
        )
        opened_chat_count += int(chat_result.get("status") == "success")
        chat_dump_count += dumps_added
        total_new_verified += chat_result.get("new_verified_count", 0)
        association_counts.add(chat_result.get("preview_chat_association", {}).get("status", "association_uncertain"))
        outcomes[key]["chat_acquisition"] = chat_result
        if chat_result.get("new_verified_count", 0) > 0:
            outcomes[key]["passive_update_status"] = "present"
        elif chat_result.get("status") == "success":
            # A successful chat read is not enough to claim there was no update.
            # Only an unchanged, complete conversation-list row proves absence;
            # first observations and changed rows with no verified new message
            # remain unknown (the chat hierarchy may omit preview content).
            outcomes[key]["passive_update_status"] = "unknown"
        else:
            outcomes[key]["passive_update_status"] = "unknown"
        print(
            f"CHAT {chat_index}/{len(candidates)} {key} status={chat_result.get('status')} "
            f"rows={(chat_result.get('unique_logical_candidate_count', 0))} "
            f"new={chat_result.get('new_verified_count', 0)}",
            flush=True,
        )

        # Opening a chat may clear its unread badge. Refresh the exact list row before checkpointing.
        post_root, post_raw, post_error = ensure_chat_list(android)
        if post_root is None or post_raw is None:
            current_list_root, current_list_raw = None, None
            outcomes[key]["post_chat_list_refresh_error"] = post_error
            if outcomes[key]["passive_update_status"] != "present":
                outcomes[key]["passive_update_status"] = "unknown"
            if chat_result.get("status") == "success":
                prior_row = checkpoint_targets.setdefault(key, dict(chosen.get(key) or {}))
                prior_row["expected_read_state_transition"] = {
                    "after_chat_open_at": now_local(),
                    "expected_state": "none_observed",
                    "source_state_signature": observation_state_signature(chosen.get(key) or {}),
                }
            continue
        current_list_root, current_list_raw = post_root, post_raw
        current_page = infer_current_page(post_root, targets, aliases, page_keys, current_page)
        navigation_dump_index += 1
        post_ref = save_raw(
            evidence_dir,
            f"conversation_list/post_open_{chat_index:02d}_{key}.xml",
            post_raw,
        )
        post_observation = row_observation(post_root, target, aliases, post_ref, current_page, now_local())
        list_after_open_observations.append(
            {"collector_key": key, "raw_snapshot_ref": post_ref, "observation": post_observation}
        )
        if post_observation and post_observation.get("row_complete_in_viewport"):
            outcomes[key]["post_chat_conversation_list_observation"] = post_observation
            chosen[key] = post_observation
            if chat_checkpoint:
                next_checkpoint = dict(post_observation)
                next_checkpoint.update(chat_checkpoint)
                checkpoint_targets[key] = next_checkpoint
        elif chat_checkpoint:
            # Preserve the old row checkpoint when the post-open row cannot be safely reacquired.
            prior_row = checkpoint_targets.setdefault(key, dict(chosen.get(key) or {}))
            prior_row.update(chat_checkpoint)
            prior_row["expected_read_state_transition"] = {
                "after_chat_open_at": now_local(),
                "expected_state": "none_observed",
                "source_state_signature": observation_state_signature(chosen.get(key) or {}),
            }

    chat_acquisition_seconds = time.perf_counter() - chat_started
    all_observed_keys = set()
    for target in targets:
        key = target["collector_key"]
        outcome = outcomes[key]
        row = chosen.get(key)
        if row and row.get("row_complete_in_viewport") and not row.get("loading_or_progress_present"):
            prior = checkpoint_targets.get(key)
            if outcome.get("chat_open_required") and (outcome.get("chat_acquisition") or {}).get("status") != "success":
                # Keep the old row checkpoint so an unverified or failed open
                # cannot consume a detected change.
                outcome["checkpoint_advanced"] = False
                continue
            # For unchanged rows the current list state is the checkpoint. For candidates with an
            # opened chat, retain the refreshed post-open row if it was available.
            if outcome.get("chat_acquisition") and outcome["chat_acquisition"].get("status") == "success":
                current_row = outcome.get("post_chat_conversation_list_observation")
                if current_row:
                    row = current_row
            if row is not None:
                updated = dict(row)
                if prior:
                    fields_to_retain = ["message_candidate_keys", "message_baseline_status", "last_chat_observed_at", "last_preview_chat_association"]
                    if outcome.get("candidate_detection_reason") != "collector_expected_read_state_transition_with_same_content":
                        fields_to_retain.append("expected_read_state_transition")
                    updated.update({k: prior[k] for k in fields_to_retain if k in prior})
                checkpoint_targets[key] = updated
                outcome["checkpoint_advanced"] = True
                all_observed_keys.add(key)
        elif outcome["candidate_detection"] in {"first_observation", "changed", "unchanged"}:
            outcome["passive_update_status"] = "unknown"
            outcome["candidate_detection"] = "unknown"
            outcome["candidate_detection_reason"] = "complete_target_row_not_available_for_safe_checkpoint"

    total_time = time.perf_counter() - started
    if list_scan.get("full_list_complete") and list_scan.get("frontier_order_safe") and not chat_attempt_count:
        checkpoint["frontier_rows"] = list_scan.get("ordered_rows", [])
        checkpoint["frontier_rows_order_safe"] = True
        checkpoint["frontier_list_complete"] = True
        checkpoint["frontier_checkpoint_run_id"] = args.run_id
        checkpoint["frontier_checkpoint_observed_at"] = now_local()
    required_chat_opens = sum(
        bool(outcome.get("chat_open_required") and outcome.get("candidate_detection") in {"changed", "first_observation"})
        for outcome in outcomes.values()
    )
    successful_chat_opens = sum(
        bool((outcome.get("chat_acquisition") or {}).get("status") == "success")
        for outcome in outcomes.values()
    )
    false_unchanged = sum(
        1
        for target in targets
        if outcomes[target["collector_key"]].get("candidate_detection") == "unchanged"
        and not (
            (row := chosen.get(target["collector_key"]))
            and row.get("row_complete_in_viewport")
            and not row.get("loading_or_progress_present")
            and observation_content_signature(row)
            and observation_state_signature(row)
        )
    )
    historical_new_message_keys = {
        message.get("logical_candidate_key")
        for prior_run in existing_output.get("runs", [])
        for store in prior_run.get("stores", [])
        for message in (store.get("chat_acquisition") or {}).get("logical_message_candidates", [])
        if message.get("candidate_status") == "new_verified" and message.get("logical_candidate_key")
    }
    current_new_message_keys = {
        message.get("logical_candidate_key")
        for outcome in outcomes.values()
        for message in (outcome.get("chat_acquisition") or {}).get("logical_message_candidates", [])
        if message.get("candidate_status") == "new_verified" and message.get("logical_candidate_key")
    }
    repeated_message_false_positives = len(historical_new_message_keys & current_new_message_keys)
    run = {
        "run_id": args.run_id,
        "observed_at": now_local(),
        "android_serial": serial,
        "read_only": True,
        "run_valid_for_acceptance": bool(
            list_scan.get("status") == "success"
            and (
                list_scan.get("scan_completeness") in {"full_scan_complete", "fallback_full_scan", "target_set_complete"}
            )
            and list_scan.get("all_pages_settled")
            and list_scan.get("all_target_rows_complete")
            and false_unchanged == 0
            and required_chat_opens == successful_chat_opens
        ),
        "conversation_list_scan": {
            "status": list_scan.get("status"),
            "scan_mode_requested": scan_mode,
            "scan_completeness": list_scan.get("scan_completeness"),
            "error": list_scan.get("error"),
            "fallback_reason": list_scan.get("fallback_reason"),
            "stop_reason": list_scan.get("stop_reason"),
            "elapsed_seconds": list_scan.get("list_scan_seconds", 0),
            "dump_count": list_scan.get("dump_count", 0),
            "ui_dump_success_count": list_scan.get("ui_dump_success_count", 0),
            "ui_dump_attempt_count": list_scan.get("ui_dump_attempt_count", 0),
            "all_pages_settled": list_scan.get("all_pages_settled", False),
            "full_list_complete": list_scan.get("full_list_complete", False),
            "frontier_order_safe": list_scan.get("frontier_order_safe", False),
            "frontier": list_scan.get("frontier"),
            "frontier_stable_rows_required": list_scan.get("frontier_stable_rows_required"),
            "ordered_row_count": len(list_scan.get("ordered_rows", [])),
            "row_sequence_merge_events": list_scan.get("row_sequence_merge_events", []),
            "pages": list_scan.get("pages", []),
            "top_reset_observations": list_scan.get("top_reset_observations", []),
            "top_reset_stop_reason": list_scan.get("top_reset_stop_reason"),
            "all_fixed_targets_found": list_scan.get("all_target_rows_found", False),
            "all_fixed_target_rows_complete": list_scan.get("all_target_rows_complete", False),
            "post_open_refreshes": list_after_open_observations,
        },
        "target_set_size": len(targets),
        "candidate_detection_seconds": candidate_detection_seconds,
        "opened_chat_count": opened_chat_count,
        "chat_dump_count": chat_dump_count,
        "chat_acquisition_seconds": chat_acquisition_seconds,
        "total_elapsed_seconds": total_time,
        "stores": [
            {
                "hall_id": target["hall_id"],
                "collector_key": target["collector_key"],
                "line_source_key": target["line_source_key"],
                "store_name": target["store_name"],
                "identity_verified_in_source_survey": True,
                **outcomes[target["collector_key"]],
            }
            for target in targets
        ],
        "summary": {
            "target_count": len(targets),
            "conversation_list_found_count": sum(bool(chosen.get(t["collector_key"])) for t in targets),
            "changed": sum(o["candidate_detection"] == "changed" for o in outcomes.values()),
            "unchanged": sum(o["candidate_detection"] == "unchanged" for o in outcomes.values()),
            "first_observation": sum(o["candidate_detection"] == "first_observation" for o in outcomes.values()),
            "unknown": sum(o["candidate_detection"] == "unknown" for o in outcomes.values()),
            "list_scan_completeness": list_scan.get("scan_completeness"),
            "list_pages": len(list_scan.get("pages", [])),
            "list_dump_count": list_scan.get("ui_dump_success_count", 0),
            "list_dump_attempt_count": list_scan.get("ui_dump_attempt_count", 0),
            "total_ui_dump_count": android.dump_success_count - run_dump_success_start,
            "total_ui_dump_attempt_count": android.dump_attempt_count - run_dump_attempt_start,
            "passive_present": sum(o["passive_update_status"] == "present" for o in outcomes.values()),
            "passive_absent": sum(o["passive_update_status"] == "absent" for o in outcomes.values()),
            "passive_unknown": sum(o["passive_update_status"] == "unknown" for o in outcomes.values()),
            "opened_chat_count": opened_chat_count,
            "chat_attempt_count": chat_attempt_count,
            "required_chat_open_count": required_chat_opens,
            "successful_chat_open_count": successful_chat_opens,
            "new_verified_passive_message_count": total_new_verified,
            "repeated_message_false_positive_count": repeated_message_false_positives,
            "target_identity_misattribution_count": sum(
                1
                for outcome in outcomes.values()
                if (outcome.get("chat_acquisition") or {}).get("error_class") == "target_not_verified"
                and (outcome.get("chat_acquisition") or {}).get("raw_message_row_observations")
            ),
            "state_only_change_count": sum(
                outcome.get("candidate_detection_reason") == "ui_read_state_changed_without_content_change_requires_chat_check"
                for outcome in outcomes.values()
            ),
            "collector_expected_read_state_suppression_count": sum(
                outcome.get("candidate_detection_reason") == "collector_expected_read_state_transition_with_same_content"
                for outcome in outcomes.values()
            ),
            "midnight_time_label_rollover_requires_chat_check_count": sum(
                outcome.get("candidate_detection_reason") == "line_time_label_rolled_to_yesterday; verify_message_identity_before_checkpoint"
                for outcome in outcomes.values()
            ),
            "day_label_rollover_safely_suppressed_count": sum(
                outcome.get("candidate_detection_reason") == "line_time_label_rollover_only"
                for outcome in outcomes.values()
            ),
            "preview_association_counts": association_counts.as_dict(),
            "chat_row_candidate_count": sum(
                (o.get("chat_acquisition") or {}).get("unique_logical_candidate_count", 0)
                for o in outcomes.values()
            ),
            "ambiguous_raw_row_count": sum(
                1
                for o in outcomes.values()
                for row in (o.get("chat_acquisition") or {}).get("raw_message_row_observations", [])
                if not row.get("logical_candidate_key")
            ),
            "false_unchanged_from_missing_or_failed_rows": false_unchanged,
        },
        "timing": {
            "conversation_list_scan_seconds": list_scan.get("list_scan_seconds", 0),
            "candidate_detection_seconds": candidate_detection_seconds,
            "chat_acquisition_seconds": chat_acquisition_seconds,
            "total_seconds": total_time,
        },
        "safety": {
            "line_messages_sent": 0,
            "rich_menu_clicks": 0,
            "friend_adds": 0,
            "ocr_used": False,
            "fixed_coordinates_used": False,
            "force_trigger_used": False,
            "android_settings_changed": False,
            "windows_settings_changed": False,
            "scheduler_changed": False,
            "slot_repo_runtime_changed": False,
            "only_live_node_bounds_used_for_navigation_and_scroll": True,
        },
    }
    # The output is a history of runs; RAW UI files are never overwritten.
    existing_output.setdefault("survey_id", "passive-incremental-20-2026-09-25")
    existing_output.setdefault("schema_version", "1.0")
    existing_output.setdefault("timezone", "Asia/Tokyo")
    existing_output.setdefault("source_survey", str(CAPABILITY_FILE.relative_to(ROOT)))
    existing_output.setdefault("target_keys", [target["collector_key"] for target in targets])
    existing_output.setdefault("runs", [])
    existing_output["runs"].append(run)

    checkpoint["schema_version"] = "1"
    checkpoint["updated_at"] = now_local()
    checkpoint["source_survey"] = str(CAPABILITY_FILE.relative_to(ROOT))
    checkpoint["derived_state_only"] = True
    checkpoint["targets"] = checkpoint_targets
    atomic_json(args.checkpoint, checkpoint)
    atomic_json(args.output, existing_output)
    android.cleanup()
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "serial": serial,
                "summary": run["summary"],
                "timing": run["timing"],
                "checkpoint_path": str(args.checkpoint),
                "output_path": str(args.output),
            },
            ensure_ascii=False,
        )
    )


class CounterLike:
    def __init__(self):
        self.values: dict[str, int] = defaultdict(int)

    def add(self, value: str) -> None:
        self.values[value] += 1

    def as_dict(self) -> dict[str, int]:
        return dict(self.values)


if __name__ == "__main__":
    main()
