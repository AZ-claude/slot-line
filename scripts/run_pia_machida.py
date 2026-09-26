#!/usr/bin/env python3
"""Execute one guarded LINE action and persist before/after Android UI captures.

Reply semantics intentionally remain in later processing. The temporary
Windows UI Automation task is removed before exit; this runner uses no OCR,
fixed screen coordinates, LINE database access, or persistent scheduler.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

try:
    from raw_storage import RawStorageError, RawStore, evaluate_trigger_cooldown
except ModuleNotFoundError:  # Also support importing this runner in unit tests.
    from scripts.raw_storage import RawStorageError, RawStore, evaluate_trigger_cooldown


SOURCE = "official_line"
ADAPTER_TYPE = "text_trigger"
LINE_PACKAGE = "jp.naver.line.android"
DEFAULT_POST_ACTION_WAIT_SECONDS = 5.0
MAX_POST_ACTION_WAIT_SECONDS = 10.0
MAX_LOADING_SETTLE_SECONDS = 3.0


class PhaseError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class AndroidContext:
    adb: str
    serial: str


@dataclass(frozen=True)
class TextTriggerConfig:
    collector_key: str
    hall_id: str
    target_title: str
    line_source_key: str
    trigger_text: str


DEFAULT_CONFIG = TextTriggerConfig(
    collector_key="pia_machida",
    hall_id="hall-pia-machida",
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
    header = find_node(
        root,
        lambda node: text_or_desc(node) == ACTIVE_CONFIG.target_title
        and resource_id(node)
        in {
            "jp.naver.line.android:id/header_title",
            "jp.naver.line.android:id/chat_header_title",
        },
    )
    # A matching chat-list row can sit near the top of the screen. Require the
    # chat composer as well as the exact header so that row text cannot pass
    # target identity verification.
    composer = find_node(
        root,
        lambda node: resource_id(node) == "jp.naver.line.android:id/chat_ui_message_edit",
    )
    return header is not None and composer is not None


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
        ["shell", "am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", url, "-p", LINE_PACKAGE],
        timeout=30,
    )
    time.sleep(0.8)
    deadline = time.monotonic() + 15
    last_error = "url_target_or_prefill_not_verified"
    last_code = "target_not_verified"
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
        if is_target_chat(root):
            last_code = "action_not_observed"
            last_error = "exact_trigger_text_not_prefilled"
        else:
            last_code = "target_not_verified"
            last_error = "exact_target_chat_not_visible"
        time.sleep(0.8)
    raise PhaseError(last_code, last_error)


def send_prefilled_trigger_android(ctx: AndroidContext) -> str:
    root, _ = dump_ui(ctx, "prefilled")
    if not is_target_chat(root):
        raise PhaseError("target_not_verified", "target_chat_changed_before_send")
    if not is_prefilled_target_chat(root):
        raise PhaseError("action_not_observed", "trigger_prefill_changed_before_send")
    send_button = find_node(
        root,
        lambda node: resource_id(node) == "jp.naver.line.android:id/chat_ui_send_button_image"
        and node_attr(node, "clickable").lower() == "true"
        and node_attr(node, "enabled").lower() == "true"
        and node_attr(node, "content-desc") not in {"", "ボイスメッセージ"},
    )
    if send_button is None:
        raise PhaseError("action_not_observed", "uiautomator_send_button_not_verified")
    tap_node(ctx, send_button)
    return utc_now()


def loading_present(root: ElementTree.Element) -> bool:
    for node in root.iter():
        resource = resource_id(node).lower()
        label = (node_attr(node, "text") + " " + node_attr(node, "content-desc")).lower()
        if "progress" in resource or "loading" in resource or "読み込み中" in label:
            return True
    return False


def save_screen_capture(
    ctx: AndroidContext,
    raw_store: RawStore,
    run_id: str,
    label: str,
) -> tuple[ElementTree.Element, list[str]]:
    root, xml_raw = dump_ui(ctx, label)
    screenshot = adb_binary_run(ctx, ["exec-out", "screencap", "-p"], timeout=30)
    if not screenshot.startswith(b"\x89PNG"):
        raise PhaseError("capture_failed", "android_screenshot_invalid")
    try:
        xml_ref = raw_store.save_ui_dump(xml_raw, run_id, f"{label}")
        screenshot_ref = raw_store.save_ui_artifact(screenshot, run_id, f"{label}", ".png")
    except RawStorageError as exc:
        raise PhaseError("capture_failed", f"raw_ui_write_failed:{exc}") from exc
    return root, [xml_ref, screenshot_ref]


def save_post_action_capture(
    ctx: AndroidContext,
    raw_store: RawStore,
    run_id: str,
    initial_wait_seconds: float,
) -> tuple[ElementTree.Element, list[str], str]:
    initial_wait = min(max(0.0, initial_wait_seconds), MAX_POST_ACTION_WAIT_SECONDS)
    time.sleep(initial_wait)
    root, _ = dump_ui(ctx, "post-action-probe")
    settled_at = utc_now()
    if loading_present(root):
        extra_wait = min(MAX_LOADING_SETTLE_SECONDS, MAX_POST_ACTION_WAIT_SECONDS - initial_wait)
        if extra_wait > 0:
            time.sleep(extra_wait)
            root, _ = dump_ui(ctx, "post-action-settle-probe")
            settled_at = utc_now()
    # Keep the authoritative XML/screenshot pair together after the bounded wait.
    root, refs = save_screen_capture(ctx, raw_store, run_id, "post_action")
    return root, refs, settled_at


def activity_snapshot(ctx: AndroidContext) -> tuple[str | None, str | None]:
    result = adb_run(ctx, ["shell", "dumpsys", "activity", "activities"], timeout=15, check=False)
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    lines = output.splitlines()
    activity_line = next(
        (line.strip() for line in lines if "topResumedActivity=" in line or "mResumedActivity:" in line),
        "",
    )
    component_match = re.search(r"\bu\d+\s+([A-Za-z0-9_.]+/[A-Za-z0-9_.$]+)", activity_line)
    component = component_match.group(1) if component_match else None
    uri_match = re.search(r"\bdat=(https?://[^\s)}]+)", activity_line, re.IGNORECASE)
    package = component.split("/", 1)[0] if component else ""
    if uri_match is None and package in {
        "com.android.chrome",
        "com.android.browser",
        "org.mozilla.firefox",
        "com.microsoft.emmx",
        "com.sec.android.app.sbrowser",
        "com.brave.browser",
    }:
        uri_matches = list(re.finditer(r"\bdat=(https?://[^\s)}]+)", output, re.IGNORECASE))
        uri_match = uri_matches[-1] if uri_matches else None
    external_url = uri_match.group(1).rstrip("]>,;") if uri_match else None
    return component, external_url


def is_external_web(component: str | None, external_url: str | None) -> bool:
    browser_packages = {
        "com.android.chrome",
        "com.android.browser",
        "org.mozilla.firefox",
        "com.microsoft.emmx",
        "com.sec.android.app.sbrowser",
        "com.brave.browser",
    }
    package = component.split("/", 1)[0] if component else ""
    return package in browser_packages or bool(external_url and external_url.startswith(("http://", "https://")))


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def send_trigger_on_windows(*, verify_only: bool = False) -> dict[str, Any]:
    """Verify the Windows LINE target and optionally send the trigger.

    The helper is ASCII-only so Windows PowerShell 5.1 cannot corrupt the
    Japanese trigger before it reaches LINE.  It is run in the current
    interactive session through a one-shot task and is removed afterwards.
    """

    task_name = f"SlotLinePhase1TextTrigger_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    base = Path(r"C:\Users\Public")
    helper_path = base / f"slot-line-phase1-send-{os.getpid()}-{uuid.uuid4().hex[:8]}.ps1"
    result_path = base / f"slot-line-phase1-send-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
    target_expression = " + ".join(f"([char]0x{ord(character):04X}).ToString()" for character in ACTIVE_CONFIG.target_title)
    desired_expression = " + ".join(f"([char]0x{ord(character):04X}).ToString()" for character in ACTIVE_CONFIG.trigger_text)
    expected_codepoints = ",".join(f"U+{ord(character):04X}" for character in ACTIVE_CONFIG.trigger_text)
    helper = f"""param([string]$OutFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
$result = [ordered]@{{ ok = $false; error = $null; target_verified = $false; target_match_count = 0; target_matches = @(); input_verified = $false; input_match_count = 0; sent_at_utc = $null; codepoints = $null }}
try {{
  $target = {target_expression}
  $desired = {desired_expression}
  $process = Get-Process -Name 'LINE' -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowHandle -ne [IntPtr]::Zero }} | Select-Object -First 1
  if ($null -eq $process) {{ throw 'LINE_process_not_found' }}
  if ($process.MainWindowHandle -eq [IntPtr]::Zero) {{ throw 'LINE_window_not_found' }}
  $line = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
  if ($null -eq $line) {{ throw 'LINE_window_not_found' }}
  $matches = @()
  $nameCondition = New-Object -TypeName System.Windows.Automation.PropertyCondition -ArgumentList @([System.Windows.Automation.AutomationElement]::NameProperty, $target)
  $targetNodes = @($line.FindAll([System.Windows.Automation.TreeScope]::Descendants, $nameCondition))
  if ($targetNodes.Count -eq 0) {{
    $automationCondition = New-Object -TypeName System.Windows.Automation.PropertyCondition -ArgumentList @([System.Windows.Automation.AutomationElement]::AutomationIdProperty, $target)
    $targetNodes = @($line.FindAll([System.Windows.Automation.TreeScope]::Descendants, $automationCondition))
  }}
  foreach ($node in $targetNodes) {{
    $matches += [ordered]@{{ name = [string]$node.Current.Name; automation_id = [string]$node.Current.AutomationId; class_name = [string]$node.Current.ClassName; value = $null; control_type = [string]$node.Current.ControlType.ProgrammaticName; bounds = [string]$node.Current.BoundingRectangle; is_offscreen = $node.Current.IsOffscreen }}
  }}
  $result.target_match_count = [int]$matches.Count
  $result.target_matches = $matches
  if ($matches.Count -ne 1 -or $matches[0].is_offscreen) {{ throw 'target_chat_not_verified' }}
  $result.target_verified = $true
  $editType = New-Object -TypeName System.Windows.Automation.PropertyCondition -ArgumentList @([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
  $editClass = New-Object -TypeName System.Windows.Automation.PropertyCondition -ArgumentList @([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'AutoSuggestTextArea')
  $editCondition = New-Object -TypeName System.Windows.Automation.AndCondition -ArgumentList @($editType, $editClass)
  $edits = @($line.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCondition))
  $result.input_match_count = [int]$edits.Count
  if ($edits.Count -ne 1 -or $edits[0].Current.IsOffscreen -or -not $edits[0].Current.IsEnabled) {{ throw 'target_input_not_unique' }}
  $edit = $edits[0]
  $valuePattern = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
  if ($null -eq $valuePattern) {{ throw 'target_input_value_pattern_not_found' }}
  $result.input_verified = $true
  if ({'$true' if verify_only else '$false'}) {{
    $result.ok = $true
  }} else {{
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
  }}
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
        deadline = time.monotonic() + (15 if verify_only else 45)
        while time.monotonic() < deadline:
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    result = None
                if isinstance(result, dict):
                    if result.get("ok") is True:
                        if result.get("target_verified") is not True or result.get("input_verified") is not True:
                            raise PhaseError("target_not_verified", "windows_uia_target_verification_incomplete")
                        if not verify_only and result.get("codepoints") != expected_codepoints:
                            raise PhaseError("trigger_failed", "trigger_unicode_readback_mismatch")
                        return result
                    raw_error = str(result.get("error") or "windows_uia_trigger_failed")
                    error = raw_error
                    if "target_match_count" in result:
                        error = (
                            f"{error}:target_match_count={result.get('target_match_count', 0)}"
                            f":input_match_count={result.get('input_match_count', 0)}"
                        )
                    code = "target_not_verified" if raw_error == "target_chat_not_verified" else "line_not_ready" if raw_error in {
                        "LINE_process_not_found",
                        "LINE_window_not_found",
                        "target_input_not_unique",
                        "target_input_value_pattern_not_found",
                    } else "trigger_failed"
                    raise PhaseError(code, error)
            time.sleep(0.5)
        raise PhaseError("trigger_failed", "temporary_task_result_timeout")
    finally:
        if created_task:
            run_process(["schtasks.exe", "/End", "/TN", task_name], timeout=30)
            run_process(["schtasks.exe", "/Delete", "/TN", task_name, "/F"], timeout=30)
        for path in (helper_path, result_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one configured text-trigger E2E target.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--collector-key", default=DEFAULT_CONFIG.collector_key)
    parser.add_argument("--hall-id", default=DEFAULT_CONFIG.hall_id)
    parser.add_argument("--target-title", default=DEFAULT_CONFIG.target_title)
    parser.add_argument("--target-title-codepoints", default=None)
    parser.add_argument("--line-source-key", default=DEFAULT_CONFIG.line_source_key)
    parser.add_argument("--trigger-text", default=DEFAULT_CONFIG.trigger_text)
    parser.add_argument("--trigger-codepoints", default=None)
    parser.add_argument(
        "--post-action-wait",
        type=float,
        default=DEFAULT_POST_ACTION_WAIT_SECONDS,
        help="Seconds to wait after the single action (0-10; default 5).",
    )
    parser.add_argument(
        "--trigger-mode",
        choices=("url", "windows-uia"),
        default="url",
        help="Preferred Android oaMessage URL trigger; windows-uia is the verified fallback only.",
    )
    parser.add_argument(
        "--windows-uia-verify-only",
        action="store_true",
        help="Verify the exact Windows LINE target and input without sending or writing RAW.",
    )
    args = parser.parse_args()
    if not 0 <= args.post_action_wait <= MAX_POST_ACTION_WAIT_SECONDS:
        parser.error("--post-action-wait must be between 0 and 10 seconds")
    return args


def active_failure_status(code: str, action_executed: bool) -> str:
    if code == "target_not_verified":
        return "target_not_verified"
    if code == "action_not_observed":
        return "action_not_observed"
    if action_executed and code in {"capture_failed", "extraction_failed", "android_unreachable"}:
        return "capture_failed"
    if code in {"capture_failed", "extraction_failed"}:
        return "capture_failed"
    if code in {"trigger_failed", "line_not_ready"}:
        return "action_execution_failed"
    return "unknown"


def main() -> int:
    global ACTIVE_CONFIG
    args = parse_args()
    target_title = decode_codepoints(args.target_title_codepoints) if args.target_title_codepoints else args.target_title
    trigger_text = decode_codepoints(args.trigger_codepoints) if args.trigger_codepoints else args.trigger_text
    ACTIVE_CONFIG = TextTriggerConfig(
        collector_key=args.collector_key,
        hall_id=args.hall_id,
        target_title=target_title,
        line_source_key=args.line_source_key,
        trigger_text=trigger_text,
    )
    repo_root = args.repo_root.resolve()
    if args.windows_uia_verify_only:
        try:
            result = send_trigger_on_windows(verify_only=True)
        except PhaseError as exc:
            print(json.dumps({"mode": "windows_uia_verify_only", "status": "fail_closed", "error": exc.detail}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"mode": "windows_uia_verify_only", "status": "success", "target": result}, ensure_ascii=False, indent=2))
        return 0
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
            "type": ADAPTER_TYPE,
            "text": ACTIVE_CONFIG.trigger_text,
            "line_id": ACTIVE_CONFIG.line_source_key,
            "action": "send_text",
            "result": None,
        },
    )
    record["trigger"]["action_id"] = "latest_information"
    if args.trigger_mode == "url":
        record["trigger"]["url"] = target_oa_message_url()
        record["trigger"]["intent_action"] = "android.intent.action.VIEW"
        record["trigger"]["intent_package"] = LINE_PACKAGE
    record["line_id"] = ACTIVE_CONFIG.line_source_key
    record["trigger_mode"] = args.trigger_mode
    record["hall_id"] = ACTIVE_CONFIG.hall_id
    record["line_source_key"] = ACTIVE_CONFIG.line_source_key
    record["action_label"] = ACTIVE_CONFIG.trigger_text
    record["action_kind"] = "text_trigger"
    record["semantic_interpretation"] = "deferred"
    record["target_verified"] = False
    record["action_executed"] = False
    record["pre_action_capture"] = False
    record["post_action_capture"] = False
    record["raw_persisted"] = False
    record["active_status"] = "unknown"
    record["pre_action_ui_filenames"] = []
    record["post_action_ui_filenames"] = []
    guard_decision = evaluate_trigger_cooldown(
        raw_store.load_recent_manifest_records(),
        hall_id=ACTIVE_CONFIG.hall_id,
        collector_key=ACTIVE_CONFIG.collector_key,
        line_source_key=ACTIVE_CONFIG.line_source_key,
        trigger_key="latest_information",
        trigger_text=ACTIVE_CONFIG.trigger_text,
    )
    if guard_decision is not None:
        record.update(guard_decision)
        record["trigger"]["result"] = "skipped_cooldown"
        record["active_status"] = "unknown"
        record["stored_message_count_total"] = len(raw_store.load_messages())
        record["finished_at"] = utc_now()
        raw_store.persist_manifest(record)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    android: AndroidContext | None = None
    storage_finalized = False
    try:
        android = discover_android()
        if args.trigger_mode == "url":
            # Verify the exact chat and prefilled text before saving the screen
            # pair and before the one permitted send-button tap.
            root = open_target_via_url(android)
        else:
            root = open_line_and_target_chat(android)
        if not is_target_chat(root):
            raise PhaseError("target_not_verified", "target_chat_identity_not_verified")
        if args.trigger_mode == "url" and not is_prefilled_target_chat(root):
            raise PhaseError("action_not_observed", "exact_trigger_text_not_prefilled")
        record["target_verified"] = True
        _, pre_refs = save_screen_capture(android, raw_store, run_id, "pre_action")
        record["pre_action_capture"] = True
        record["pre_action_ui_filenames"] = pre_refs
        record["ui_filenames"].extend(pre_refs)
        record["raw_persisted"] = True
        raw_store.persist_manifest(record)

        if args.trigger_mode == "url":
            try:
                triggered_at = send_prefilled_trigger_android(android)
            except PhaseError as exc:
                if exc.code == "android_unreachable":
                    raise PhaseError("trigger_failed", exc.detail) from exc
                raise
        else:
            # Windows LINE verifies the exact target and text before sending.
            try:
                windows_target = send_trigger_on_windows()
            except PhaseError as exc:
                if exc.code == "android_unreachable":
                    raise PhaseError("trigger_failed", exc.detail) from exc
                raise
            record["windows_target_verification"] = windows_target
            triggered_at = str(windows_target.get("sent_at_utc") or utc_now())
        record["triggered_at"] = triggered_at
        record["action_executed"] = True
        record["trigger"]["result"] = "sent"
        record["trigger"]["action_id"] = "latest_information"
        record["raw_persisted"] = True
        # Persist the attempt immediately so a crash after sending cannot bypass
        # the cooldown guard on a rerun.
        raw_store.persist_manifest(record)

        _, post_refs, _ = save_post_action_capture(
            android,
            raw_store,
            run_id,
            args.post_action_wait,
        )
        captured_at = utc_now()
        component, external_url = activity_snapshot(android)
        external = is_external_web(component, external_url)
        record["captured_at"] = captured_at
        record["current_activity"] = component
        record["external_url"] = external_url
        record["post_action_capture"] = bool(post_refs)
        record["post_action_ui_filenames"] = post_refs
        record["ui_filenames"].extend(post_refs)
        record["action_result"] = "external_web" if external else "unknown"
        record["active_status"] = "external_web" if external else "captured"
        record["message_count"] = 0
        record["stored_message_count_total"] = len(raw_store.load_messages())
        record["image_count"] = 0
        record["deduplicated_images"] = 0
        record["reply_type"] = None
        record["message_semantics"] = "not_interpreted"
        record["status"] = "success"
        record["finished_at"] = utc_now()
        record["raw_persisted"] = True
        raw_store.persist_manifest(record)
        storage_finalized = True
    except PhaseError as exc:
        record["active_status"] = active_failure_status(exc.code, bool(record.get("action_executed")))
        record["status"] = exc.code
        record["errors"].append({"code": exc.code, "detail": exc.detail})
    except RawStorageError as exc:
        record["raw_persisted"] = False
        record["active_status"] = "capture_failed"
        record["status"] = "extraction_failed"
        record["errors"].append({"code": "raw_storage_failed", "detail": str(exc)})
    except Exception as exc:  # Keep the required status vocabulary for operators.
        record["active_status"] = "capture_failed" if record.get("action_executed") else "unknown"
        record["status"] = "extraction_failed"
        record["errors"].append({"code": "extraction_failed", "detail": f"unexpected:{type(exc).__name__}:{exc}"})
    finally:
        if not storage_finalized:
            record["finished_at"] = utc_now()
            raw_store.persist_manifest(record)

    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["status"] in {"success", "skipped_cooldown"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
