#!/usr/bin/env python3
"""Run the minimal single-target text-trigger acquisition flow.

This is intentionally a single-store PoC.  It uses only the mechanisms that
were verified during Phase 0/1:

* Windows LINE input through UI Automation + a temporary interactive task.
* Android LINE navigation/reply inspection through adb/uiautomator.
* LINE's standard image download button, followed by adb pull.

The temporary scheduled task is deleted before the command exits.  No
persistent task, OCR, Windows LINE database access, or Android Japanese input
is used.
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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

try:
    from raw_storage import RawStorageError, RawStore, evaluate_trigger_guard
except ModuleNotFoundError:  # Also support importing this runner in unit tests.
    from scripts.raw_storage import RawStorageError, RawStore, evaluate_trigger_guard


SOURCE = "official_line"
ADAPTER_TYPE = "text_trigger"
LINE_PACKAGE = "jp.naver.line.android"
ANDROID_IMAGE_DIR = "/sdcard/Pictures/LINE"
STAY_ON_KEY = "stay_on_while_plugged_in"
REPLY_SETTLE_MAX_SECONDS = 5.0
REPLY_SETTLE_INTERVAL_SECONDS = 1.0


class PhaseError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class AndroidContext:
    adb: str
    serial: str
    original_stay_on: str | None = None
    gallery_open: bool = False


@dataclass(frozen=True)
class TextTriggerConfig:
    collector_key: str
    target_title: str
    line_source_key: str
    trigger_text: str


DEFAULT_CONFIG = TextTriggerConfig(
    collector_key="pia_machida",
    target_title="PIA町田",
    line_source_key="@030pwlwx",
    trigger_text="".join(chr(codepoint) for codepoint in (0x6700, 0x65B0, 0x60C5, 0x5831)),
)
ACTIVE_CONFIG = DEFAULT_CONFIG


def decode_codepoints(value: str) -> str:
    try:
        codepoints = [int(part.strip(), 16) for part in value.split(",") if part.strip()]
        decoded = "".join(chr(codepoint) for codepoint in codepoints)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_codepoints:{value}") from exc
    if not decoded:
        raise ValueError("empty_codepoints")
    return decoded


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_process(args: list[str], *, timeout: float = 30.0, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PhaseError("android_unreachable", f"command_not_found:{args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PhaseError("android_unreachable", f"command_timeout:{args[0]}") from exc


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value or "")
    if not match:
        return None
    left, top, right, bottom = (int(part) for part in match.groups())
    return left, top, right, bottom


def center_of_bounds(value: str) -> tuple[int, int] | None:
    bounds = parse_bounds(value)
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2


def node_attr(node: ElementTree.Element, name: str) -> str:
    return node.attrib.get(name, "")


def resource_id(node: ElementTree.Element) -> str:
    return node_attr(node, "resource-id")


def descendant_nodes(node: ElementTree.Element) -> list[ElementTree.Element]:
    return list(node.iter())


def find_node(root: ElementTree.Element, predicate) -> ElementTree.Element | None:
    for node in root.iter():
        if predicate(node):
            return node
    return None


def text_or_desc(node: ElementTree.Element) -> str:
    return node_attr(node, "text") or node_attr(node, "content-desc")


def adb_run(ctx: AndroidContext, args: list[str], *, timeout: float = 30.0, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = run_process([ctx.adb, "-s", ctx.serial, *args], timeout=timeout)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\r", " ").replace("\n", " ")
        raise PhaseError("android_unreachable", f"adb_failed:{' '.join(args[:3])}:{detail[:300]}")
    return result


def adb_binary_run(ctx: AndroidContext, args: list[str], *, timeout: float = 30.0) -> bytes:
    try:
        result = subprocess.run(
            [ctx.adb, "-s", ctx.serial, *args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PhaseError("android_unreachable", "adb_not_found") from exc
    except subprocess.TimeoutExpired as exc:
        raise PhaseError("android_unreachable", "adb_binary_command_timeout") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise PhaseError("extraction_failed", f"adb_binary_failed:{detail[:300]}")
    return result.stdout


def discover_android() -> AndroidContext:
    adb = shutil.which("adb")
    if not adb:
        raise PhaseError("android_unreachable", "adb_not_found")
    result = run_process([adb, "devices"], timeout=15)
    if result.returncode != 0:
        raise PhaseError("android_unreachable", "adb_devices_failed")
    candidates: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            candidates.append(parts[0])
    if not candidates:
        raise PhaseError("android_unreachable", "no_android_device")
    return AndroidContext(adb=adb, serial=candidates[0])


def dump_ui(ctx: AndroidContext, suffix: str) -> tuple[ElementTree.Element, bytes]:
    remote_name = f"/sdcard/slot-line-phase1-{os.getpid()}-{suffix}.xml"
    try:
        dumped = adb_run(ctx, ["shell", "uiautomator", "dump", remote_name], timeout=30)
        if dumped.returncode != 0:
            raise PhaseError("extraction_failed", "uiautomator_dump_failed")
        raw = (adb_run(ctx, ["exec-out", "cat", remote_name], timeout=30).stdout or "").encode("utf-8", errors="replace")
        if not raw.strip().startswith(b"<"):
            raise PhaseError("extraction_failed", "uiautomator_dump_empty")
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            raise PhaseError("extraction_failed", "uiautomator_xml_invalid") from exc
        return root, raw
    finally:
        adb_run(ctx, ["shell", "rm", "-f", remote_name], timeout=15, check=False)


def is_system_ui(root: ElementTree.Element) -> bool:
    packages = {node_attr(node, "package") for node in root.iter() if node_attr(node, "package")}
    return bool(packages) and packages.issubset({"com.android.systemui", "android"})


def is_target_chat(root: ElementTree.Element) -> bool:
    for node in root.iter():
        value = text_or_desc(node)
        if value == ACTIVE_CONFIG.target_title and resource_id(node) in {
            "jp.naver.line.android:id/header_title",
            "jp.naver.line.android:id/chat_header_title",
        }:
            return True
    # The header resource id can vary between LINE builds.  A visible exact
    # title near the top is acceptable for this single-store PoC.
    for node in root.iter():
        if text_or_desc(node) == ACTIVE_CONFIG.target_title:
            bounds = parse_bounds(node_attr(node, "bounds"))
            if bounds and bounds[1] < 250:
                return True
    return False


def tap_node(ctx: AndroidContext, node: ElementTree.Element) -> None:
    center = center_of_bounds(node_attr(node, "bounds"))
    if center is None:
        raise PhaseError("extraction_failed", "uiautomator_node_without_bounds")
    adb_run(ctx, ["shell", "input", "tap", str(center[0]), str(center[1])], timeout=15)


def open_line_and_target_chat(ctx: AndroidContext) -> ElementTree.Element:
    adb_run(ctx, ["shell", "input", "keyevent", "KEYCODE_WAKEUP"], timeout=15)
    adb_run(ctx, ["shell", "monkey", "-p", LINE_PACKAGE, "1"], timeout=30)
    time.sleep(1.5)
    root, _ = dump_ui(ctx, "open")
    if is_system_ui(root):
        raise PhaseError("android_unreachable", "android_secure_lock_or_system_ui")
    if is_target_chat(root):
        return root

    # Use only a visible exact target entry if LINE is on its chat list.
    # No coordinate is hard-coded; the current UI hierarchy supplies bounds.
    for _ in range(5):
        entry = find_node(root, lambda node: text_or_desc(node) == ACTIVE_CONFIG.target_title and bool(parse_bounds(node_attr(node, "bounds"))))
        if entry is None:
            time.sleep(0.5)
            root, _ = dump_ui(ctx, "navigate")
            continue
        tap_node(ctx, entry)
        time.sleep(1.0)
        root, _ = dump_ui(ctx, "chat")
        if is_system_ui(root):
            raise PhaseError("android_unreachable", "android_secure_lock_or_system_ui")
        if is_target_chat(root):
            return root
    raise PhaseError("android_unreachable", "target_chat_not_visible_in_android_ui")


def target_oa_message_url() -> str:
    encoded_id = quote(ACTIVE_CONFIG.line_source_key, safe="")
    encoded_text = quote(ACTIVE_CONFIG.trigger_text, safe="")
    return f"https://line.me/R/oaMessage/{encoded_id}/?{encoded_text}"


def is_prefilled_target_chat(root: ElementTree.Element) -> bool:
    if not is_target_chat(root):
        return False
    input_node = find_node(root, lambda node: resource_id(node) == "jp.naver.line.android:id/chat_ui_message_edit")
    return input_node is not None and node_attr(input_node, "text") == ACTIVE_CONFIG.trigger_text


def open_target_via_url(ctx: AndroidContext) -> ElementTree.Element:
    url = target_oa_message_url()
    adb_run(ctx, ["shell", "input", "keyevent", "KEYCODE_WAKEUP"], timeout=15)
    adb_run(
        ctx,
        ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url],
        timeout=30,
    )
    time.sleep(0.8)
    deadline = time.monotonic() + 15
    last_error = "url_target_or_prefill_not_verified"
    while time.monotonic() < deadline:
        try:
            root, _ = dump_ui(ctx, "url")
        except PhaseError as exc:
            # LINE can briefly expose an empty UiAutomation root while the
            # URL resolver hands control to the LINE chat activity.  Retry
            # that transient state, but never send until verification passes.
            if exc.code != "extraction_failed":
                raise
            last_error = exc.detail
            time.sleep(0.8)
            continue
        if is_system_ui(root):
            raise PhaseError("android_unreachable", "android_secure_lock_or_system_ui")
        if is_prefilled_target_chat(root):
            return root
        time.sleep(0.8)
    raise PhaseError("trigger_failed", last_error)


def send_prefilled_trigger_android(ctx: AndroidContext) -> str:
    root, _ = dump_ui(ctx, "prefilled")
    if not is_prefilled_target_chat(root):
        raise PhaseError("trigger_failed", "target_or_prefill_changed_before_send")
    send_button = find_node(
        root,
        lambda node: resource_id(node) == "jp.naver.line.android:id/chat_ui_send_button_image"
        and node_attr(node, "clickable").lower() == "true"
        and node_attr(node, "enabled").lower() == "true"
        and node_attr(node, "content-desc") not in {"", "ボイスメッセージ"},
    )
    if send_button is None:
        raise PhaseError("trigger_failed", "uiautomator_send_button_not_verified")
    tap_node(ctx, send_button)
    return utc_now()


def focus_latest_message(ctx: AndroidContext, root: ElementTree.Element) -> ElementTree.Element:
    for _ in range(2):
        marker = find_node(
            root,
            lambda node: resource_id(node) in {
                "jp.naver.line.android:id/chat_ui_scroll_to_new_message",
                "jp.naver.line.android:id/chat_ui_new_message_text",
            }
            and bool(parse_bounds(node_attr(node, "bounds"))),
        )
        if marker is None:
            return root
        tap_node(ctx, marker)
        time.sleep(0.6)
        root, _ = dump_ui(ctx, "latest")
    return root


def extract_message_rows(root: ElementTree.Element) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in root.iter():
        if resource_id(row) != "jp.naver.line.android:id/chat_ui_row_swipeable_framelayout":
            continue
        descendants = descendant_nodes(row)
        ids = [resource_id(node) for node in descendants]
        incoming = any("_receive_" in value for value in ids) or any(
            resource_id(node) == "jp.naver.line.android:id/chat_ui_row_thumbnail"
            and bool(node_attr(node, "content-desc"))
            for node in descendants
        )
        kind = None
        image_node = None
        if "jp.naver.line.android:id/chat_ui_row_image_balloon_root" in ids:
            kind = "image"
            image_node = next(
                (node for node in descendants if resource_id(node) == "jp.naver.line.android:id/chat_ui_row_image_balloon_root"),
                None,
            )
        elif "jp.naver.line.android:id/chat_ui_row_receive_rich_container" in ids:
            kind = "rich_card"
        elif "jp.naver.line.android:id/chat_ui_row_text_message" in ids:
            kind = "text"
        if kind is None:
            continue
        timestamp_node = next(
            (node for node in descendants if resource_id(node) == "jp.naver.line.android:id/chat_ui_row_timestamp"),
            None,
        )
        text_values = [
            node_attr(node, "text")
            for node in descendants
            if node is not timestamp_node and node_attr(node, "text")
        ]
        desc_values = [node_attr(node, "content-desc") for node in descendants if node_attr(node, "content-desc")]
        message = {
            "kind": kind,
            "incoming": incoming,
            "timestamp": text_or_desc(timestamp_node) if timestamp_node is not None else None,
            "bounds": node_attr(row, "bounds"),
            "image_bounds": node_attr(image_node, "bounds") if image_node is not None else None,
            "text": text_values,
            "content_desc": desc_values,
            "resource_ids": sorted({value for value in ids if value}),
        }
        rows.append(message)
    return rows


def row_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("kind"),
        row.get("timestamp"),
        tuple(row.get("text") or []),
        tuple(row.get("content_desc") or []),
    )


def settled_row_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    """Include rendering resources so loader and final rich-card rows differ."""
    return (
        row.get("kind"),
        row.get("timestamp"),
        tuple(row.get("text") or []),
        tuple(row.get("content_desc") or []),
        tuple(row.get("resource_ids") or []),
        row.get("bounds"),
        row.get("image_bounds"),
    )


def has_reply_progress(rows: list[dict[str, Any]]) -> bool:
    progress_id = "jp.naver.line.android:id/chat_ui_row_progress"
    return any(progress_id in (row.get("resource_ids") or []) for row in rows)


def incoming_rows_since_baseline(
    rows: list[dict[str, Any]],
    baseline_counts: Counter,
) -> list[dict[str, Any]]:
    new_rows: list[dict[str, Any]] = []
    remaining = baseline_counts.copy()
    for row in rows:
        signature = row_signature(row)
        if remaining[signature] > 0:
            remaining[signature] -= 1
        else:
            new_rows.append(row)
    return [
        row
        for row in new_rows
        if row.get("incoming") and row["kind"] in {"text", "rich_card", "image"}
    ]


def settle_reply_ui(
    ctx: AndroidContext,
    baseline_counts: Counter,
    initial_rows: list[dict[str, Any]],
    initial_raw: bytes,
    *,
    max_wait_seconds: float = REPLY_SETTLE_MAX_SECONDS,
) -> tuple[list[dict[str, Any]], bytes]:
    """Capture two consecutive stable reply signatures without deduplication."""
    last_rows = initial_rows
    last_raw = initial_raw
    previous_signature: tuple[Any, ...] | None = None
    deadline = time.monotonic() + min(REPLY_SETTLE_MAX_SECONDS, max_wait_seconds)

    # Give LINE one full rendering interval after the first reply boundary.
    time.sleep(min(REPLY_SETTLE_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic())))
    while time.monotonic() < deadline:
        root, raw = dump_ui(ctx, "reply-settle")
        if is_system_ui(root):
            raise PhaseError("android_unreachable", "android_locked_during_reply_settle")
        root = focus_latest_message(ctx, root)
        root, focused_raw = dump_ui(ctx, "reply-settle-final")
        rows = incoming_rows_since_baseline(extract_message_rows(root), baseline_counts)
        if rows:
            signature = tuple(settled_row_signature(row) for row in rows)
            last_rows = rows
            last_raw = focused_raw or raw
            if signature == previous_signature and not has_reply_progress(rows):
                return last_rows, last_raw
            previous_signature = signature
        time.sleep(min(REPLY_SETTLE_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic())))

    # A reply boundary was already observed. Return the latest capture after
    # the bounded settle window rather than converting a slow render to a
    # response timeout or deduplicating any rows.
    return last_rows, last_raw


def wait_for_reply(ctx: AndroidContext, baseline: list[dict[str, Any]], timeout_seconds: float) -> tuple[list[dict[str, Any]], bytes]:
    baseline_counts = Counter(row_signature(row) for row in baseline)
    deadline = time.monotonic() + timeout_seconds
    last_raw = b""
    while time.monotonic() < deadline:
        root, raw = dump_ui(ctx, "reply")
        last_raw = raw
        if is_system_ui(root):
            raise PhaseError("android_unreachable", "android_locked_during_reply_wait")
        root = focus_latest_message(ctx, root)
        if root is not None:
            root, focused_raw = dump_ui(ctx, "reply-final")
            last_raw = focused_raw
        rows = extract_message_rows(root)
        # Ignore a possible outgoing trigger text row and return as soon as an
        # incoming text, rich-card, or image boundary appears.  Images are an
        # optional part of a successful response and are handled separately.
        incoming = incoming_rows_since_baseline(rows, baseline_counts)
        if incoming:
            return settle_reply_ui(ctx, baseline_counts, incoming, last_raw)
        time.sleep(1.0)
    raise PhaseError("response_timeout", f"no_new_target_reply_within_{timeout_seconds:g}s")


def list_android_line_files(ctx: AndroidContext) -> set[str]:
    result = adb_run(ctx, ["shell", "find", ANDROID_IMAGE_DIR, "-type", "f"], timeout=30, check=False)
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip().startswith(ANDROID_IMAGE_DIR + "/")}


def save_image_from_line(ctx: AndroidContext, image_row: dict[str, Any], before_files: set[str]) -> str:
    center = center_of_bounds(image_row.get("image_bounds") or "")
    if center is None:
        raise PhaseError("image_save_failed", "image_message_without_bounds")
    adb_run(ctx, ["shell", "input", "tap", str(center[0]), str(center[1])], timeout=15)
    ctx.gallery_open = True
    time.sleep(1.0)
    gallery_root, _ = dump_ui(ctx, "gallery")
    download = find_node(
        gallery_root,
        lambda node: resource_id(node) == "jp.naver.line.android:id/chat_media_content_download_button"
        or node_attr(node, "content-desc") == "ダウンロード",
    )
    if download is None:
        raise PhaseError("image_save_failed", "line_download_button_not_found")
    tap_node(ctx, download)
    time.sleep(1.5)
    after_files = list_android_line_files(ctx)
    new_files = sorted(after_files - before_files)
    if not new_files:
        raise PhaseError("image_save_failed", "no_new_file_in_line_picture_directory")
    # The verified reply contains one image.  If LINE generated more than one
    # candidate, use the newest lexicographic filename deterministically.
    return new_files[-1]


def pull_image_to_stage(ctx: AndroidContext, android_path: str, raw_store: RawStore, run_id: str) -> Path:
    stage = raw_store.stage_path(run_id, android_path)
    pulled = adb_run(ctx, ["pull", android_path, str(stage)], timeout=90, check=False)
    if pulled.returncode != 0 or not stage.exists():
        raw_store.cleanup_stage(stage)
        detail = (pulled.stderr or pulled.stdout).strip().replace("\r", " ").replace("\n", " ")
        raise PhaseError("pull_failed", detail[:300] or "adb_pull_failed")
    return stage


def save_rendered_screenshot(ctx: AndroidContext, raw_store: RawStore, run_id: str) -> str:
    screenshot = adb_binary_run(ctx, ["exec-out", "screencap", "-p"], timeout=30)
    if not screenshot.startswith(b"\x89PNG"):
        raise PhaseError("extraction_failed", "android_screenshot_invalid")
    return raw_store.save_ui_artifact(screenshot, run_id, "reply_screen", ".png")


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def send_trigger_on_windows() -> tuple[str, str]:
    """Set and send the trigger in the logged-on Windows LINE UI.

    The helper is ASCII-only so Windows PowerShell 5.1 cannot corrupt the
    Japanese trigger before it reaches LINE.  It is run in the current
    interactive session through a one-shot task and is removed afterwards.
    """

    task_name = f"SlotLinePhase1TextTrigger_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    base = Path(r"C:\Users\Public")
    helper_path = base / f"slot-line-phase1-send-{os.getpid()}-{uuid.uuid4().hex[:8]}.ps1"
    result_path = base / f"slot-line-phase1-send-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
    desired_expression = " + ".join(f"([char]0x{ord(character):04X}).ToString()" for character in ACTIVE_CONFIG.trigger_text)
    expected_codepoints = ",".join(f"U+{ord(character):04X}" for character in ACTIVE_CONFIG.trigger_text)
    helper = f"""param([string]$OutFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
$result = [ordered]@{{ ok = $false; error = $null; sent_at_utc = $null; codepoints = $null }}
try {{
  $desired = {desired_expression}
  $process = Get-Process -Name 'LINE' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -eq $process) {{ throw 'LINE_process_not_found' }}
  if ($process.MainWindowHandle -eq [IntPtr]::Zero) {{ throw 'LINE_window_not_found' }}
  $line = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
  if ($null -eq $line) {{ throw 'LINE_window_not_found' }}
  $editType = New-Object -TypeName System.Windows.Automation.PropertyCondition -ArgumentList @([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
  $editClass = New-Object -TypeName System.Windows.Automation.PropertyCondition -ArgumentList @([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'AutoSuggestTextArea')
  $editCondition = New-Object -TypeName System.Windows.Automation.AndCondition -ArgumentList @($editType, $editClass)
  $edit = $line.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
  if ($null -eq $edit) {{ throw 'target_input_not_found' }}
  $valuePattern = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
  if ($null -eq $valuePattern) {{ throw 'target_input_value_pattern_not_found' }}
  $edit.SetFocus()
  $valuePattern.SetValue($desired)
  Start-Sleep -Milliseconds 200
  $readBack = $valuePattern.Current.Value
  if ($readBack -ne $desired) {{ throw 'trigger_unicode_readback_mismatch' }}
  [System.Windows.Forms.SendKeys]::SendWait('{{ENTER}}')
  Start-Sleep -Milliseconds 300
  $result.ok = $true
  $result.sent_at_utc = [DateTimeOffset]::Now.ToUniversalTime().ToString('o')
  $result.codepoints = (($desired.ToCharArray() | ForEach-Object {{ 'U+{{0:X4}}' -f [int][char]$_ }}) -join ',')
}} catch {{
  $result.error = $_.Exception.Message
}}
$result | ConvertTo-Json -Compress | Set-Content -LiteralPath $OutFile -Encoding UTF8
"""
    created_task = False
    try:
        helper_path.write_text(helper, encoding="ascii", newline="\r\n")
        tomorrow = datetime.now().replace(second=0, microsecond=0)
        start_time = (tomorrow.timestamp() + 60)
        start_dt = datetime.fromtimestamp(start_time)
        start_text = start_dt.strftime("%H:%M")
        create = run_process(
            [
                "schtasks.exe",
                "/Create",
                "/TN",
                task_name,
                "/SC",
                "ONCE",
                "/ST",
                start_text,
                "/IT",
                "/F",
                "/TR",
                f"powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File {ps_quote(str(helper_path))} {ps_quote(str(result_path))}",
            ],
            timeout=30,
        )
        if create.returncode != 0:
            raise PhaseError("trigger_failed", f"temporary_task_create_failed:{create.stderr.strip()[:300]}")
        created_task = True
        run = run_process(["schtasks.exe", "/Run", "/TN", task_name], timeout=30)
        if run.returncode != 0:
            raise PhaseError("trigger_failed", f"temporary_task_run_failed:{run.stderr.strip()[:300]}")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    result = None
                if isinstance(result, dict):
                    if result.get("ok") is True and result.get("codepoints") == "U+6700,U+65B0,U+60C5,U+5831":
                        return ACTIVE_CONFIG.trigger_text, str(result.get("sent_at_utc") or utc_now())
                    error = str(result.get("error") or "windows_uia_trigger_failed")
                    code = "line_not_ready" if error in {
                        "LINE_process_not_found",
                        "LINE_window_not_found",
                        "target_input_not_found",
                        "target_input_value_pattern_not_found",
                    } else "trigger_failed"
                    raise PhaseError(code, error)
            time.sleep(0.5)
        raise PhaseError("trigger_failed", "temporary_task_result_timeout")
    finally:
        if created_task:
            run_process(["schtasks.exe", "/Delete", "/TN", task_name, "/F"], timeout=30)
        for path in (helper_path, result_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def restore_android(ctx: AndroidContext) -> None:
    if ctx.gallery_open:
        adb_run(ctx, ["shell", "input", "keyevent", "KEYCODE_BACK"], timeout=15, check=False)
        ctx.gallery_open = False
    if ctx.original_stay_on is not None:
        adb_run(ctx, ["shell", "settings", "put", "global", STAY_ON_KEY, ctx.original_stay_on], timeout=15, check=False)


def rows_to_messages(rows: list[dict[str, Any]], observed_at: str) -> list[dict[str, Any]]:
    return [
        {
            "message_type": row.get("kind"),
            "incoming": bool(row.get("incoming")),
            "line_display_time": row.get("timestamp"),
            "observed_at": observed_at,
            "text": row.get("text") or [],
            "content_desc": row.get("content_desc") or [],
            "resource_ids": row.get("resource_ids") or [],
            "image_filename": None,
            "byte_size": None,
            "sha256": None,
            "bounds": row.get("bounds"),
            "image_bounds": row.get("image_bounds"),
        }
        for row in rows
    ]


def delete_android_image(ctx: AndroidContext, android_path: str) -> str | None:
    result = adb_run(ctx, ["shell", "rm", "-f", android_path], timeout=30, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\r", " ").replace("\n", " ")
        return detail[:300] or "android_image_cleanup_failed"
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one configured text-trigger E2E target.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--collector-key", default=DEFAULT_CONFIG.collector_key)
    parser.add_argument("--target-title", default=DEFAULT_CONFIG.target_title)
    parser.add_argument("--target-title-codepoints", default=None)
    parser.add_argument("--line-source-key", default=DEFAULT_CONFIG.line_source_key)
    parser.add_argument("--trigger-text", default=DEFAULT_CONFIG.trigger_text)
    parser.add_argument("--trigger-codepoints", default=None)
    parser.add_argument("--response-timeout", type=float, default=90.0)
    parser.add_argument(
        "--trigger-mode",
        choices=("url", "windows-uia"),
        default="url",
        help="Preferred Android oaMessage URL trigger; windows-uia is the verified fallback only.",
    )
    parser.add_argument(
        "--existing-reply",
        action="store_true",
        help="Import the currently visible target reply without sending a trigger; diagnostic only.",
    )
    parser.add_argument(
        "--force-trigger",
        action="store_true",
        help="Explicitly allow a new trigger even when today's trigger was already attempted.",
    )
    return parser.parse_args()


def main() -> int:
    global ACTIVE_CONFIG
    args = parse_args()
    target_title = decode_codepoints(args.target_title_codepoints) if args.target_title_codepoints else args.target_title
    trigger_text = decode_codepoints(args.trigger_codepoints) if args.trigger_codepoints else args.trigger_text
    ACTIVE_CONFIG = TextTriggerConfig(
        collector_key=args.collector_key,
        target_title=target_title,
        line_source_key=args.line_source_key,
        trigger_text=trigger_text,
    )
    repo_root = args.repo_root.resolve()
    raw_store = RawStore(
        repo_root,
        datetime.now().strftime("%Y-%m-%d"),
        ACTIVE_CONFIG.collector_key,
        SOURCE,
        ADAPTER_TYPE,
        line_source_key=ACTIVE_CONFIG.line_source_key,
    )
    raw_store.initialize()
    run_id = datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    started_at = utc_now()
    record = raw_store.new_manifest_record(
        run_id,
        started_at,
        {
            "type": "existing_reply" if args.existing_reply else ADAPTER_TYPE,
            "text": None if args.existing_reply else ACTIVE_CONFIG.trigger_text,
            "mode": "existing_reply" if args.existing_reply else args.trigger_mode,
            "line_id": ACTIVE_CONFIG.line_source_key,
        },
    )
    record["line_id"] = ACTIVE_CONFIG.line_source_key
    record["trigger_mode"] = "existing_reply" if args.existing_reply else args.trigger_mode
    guard_decision = None
    if not args.existing_reply:
        guard_decision = evaluate_trigger_guard(
            raw_store.load_manifest_records(),
            ADAPTER_TYPE,
            ADAPTER_TYPE,
            force=args.force_trigger,
        )
    if guard_decision is not None:
        record.update(guard_decision)
        record["stored_message_count_total"] = len(raw_store.load_messages())
        record["finished_at"] = utc_now()
        raw_store.persist_manifest(record)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    android: AndroidContext | None = None
    android_image_path: str | None = None
    storage_finalized = False
    try:
        android = discover_android()
        original = adb_run(android, ["shell", "settings", "get", "global", STAY_ON_KEY], timeout=15).stdout.strip()
        android.original_stay_on = original if original.isdigit() else "0"
        adb_run(android, ["shell", "settings", "put", "global", STAY_ON_KEY, "2"], timeout=15)
        if args.existing_reply:
            root = open_line_and_target_chat(android)
            root = focus_latest_message(android, root)
            new_rows = [row for row in extract_message_rows(root) if row.get("incoming")]
            if not new_rows:
                raise PhaseError("extraction_failed", "existing_target_reply_not_visible")
            _, reply_raw = dump_ui(android, "existing-reply")
        elif args.trigger_mode == "url":
            # The URL opens the target chat and prefills the text.  The exact
            # target title and exact input value are checked immediately before
            # the send-button tap; otherwise the run fails closed.
            root = open_target_via_url(android)
            root = focus_latest_message(android, root)
            baseline = extract_message_rows(root)
            triggered_at = send_prefilled_trigger_android(android)
        else:
            root = open_line_and_target_chat(android)
            root = focus_latest_message(android, root)
            baseline = extract_message_rows(root)
            # Windows LINE must expose the verified AutoSuggestTextArea in the
            # logged-on interactive session.  No message body is copied/read
            # from Windows; Android is the source of truth for the reply.
            _, triggered_at = send_trigger_on_windows()
        if not args.existing_reply:
            record["triggered_at"] = triggered_at

        if not args.existing_reply:
            new_rows, reply_raw = wait_for_reply(android, baseline, args.response_timeout)
        received_at = utc_now()
        ui_filename = raw_store.save_ui_dump(reply_raw, run_id, "reply")
        record["ui_filenames"] = [ui_filename]
        record["received_at"] = received_at

        messages = rows_to_messages(new_rows, received_at)
        image_row = next((row for row in reversed(new_rows) if row.get("kind") == "image"), None)
        if image_row is not None:
            before_files = list_android_line_files(android)
            android_image_path = save_image_from_line(android, image_row, before_files)
            stage = pull_image_to_stage(android, android_image_path, raw_store, run_id)
            image_info = raw_store.import_image(stage, android_image_path)
            image_message = next(message for message in messages if message["message_type"] == "image")
            image_message.update(
                {
                    "image_filename": image_info["image_filename"],
                    "byte_size": image_info["byte_size"],
                    "sha256": image_info["sha256"],
                }
            )
            record["image_count"] = 1
            record["deduplicated_images"] = int(image_info["deduplicated"])
        else:
            record["image_count"] = 0
            record["deduplicated_images"] = 0
            if any(message["message_type"] == "rich_card" for message in messages):
                try:
                    record["ui_filenames"].append(save_rendered_screenshot(android, raw_store, run_id))
                except PhaseError as exc:
                    record["errors"].append({"code": "screenshot_warning", "detail": exc.detail})
        merged_messages = raw_store.merge_messages(messages)
        record["message_count"] = len(messages)
        record["stored_message_count_total"] = len(merged_messages)
        record["status"] = "success"
        record["finished_at"] = utc_now()
        raw_store.persist_manifest(record)
        storage_finalized = True

        if android_image_path is not None:
            cleanup_error = delete_android_image(android, android_image_path)
            if cleanup_error:
                record["errors"].append({"code": "cleanup_warning", "detail": cleanup_error})
                raw_store.persist_manifest(record)
    except PhaseError as exc:
        record["status"] = exc.code
        record["errors"].append({"code": exc.code, "detail": exc.detail})
    except RawStorageError as exc:
        record["status"] = "extraction_failed"
        record["errors"].append({"code": "raw_storage_failed", "detail": str(exc)})
    except Exception as exc:  # Keep the required status vocabulary for operators.
        record["status"] = "extraction_failed"
        record["errors"].append({"code": "extraction_failed", "detail": f"unexpected:{type(exc).__name__}:{exc}"})
    finally:
        if android is not None:
            restore_android(android)
        if not storage_finalized:
            record["finished_at"] = utc_now()
            raw_store.persist_manifest(record)

    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
