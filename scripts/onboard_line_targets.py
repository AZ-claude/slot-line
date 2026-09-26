"""One-time LINE onboarding for new collector targets.

candidates: join the canonical hall master with the P-WORLD LINE list.
onboard:    open each official LINE URL, verify identity, friend-add only on a
            verified identity, open the chat and capture a portrait snapshot.

Identity is verified when the LINE profile shows the hall's exact P-WORLD page
or its normalized store name. Nothing is sent and no rich-menu cell is tapped.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
import unicodedata
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
PWORLD_LIST = ROOT / "kanagawa_pworld_line_x_20260923.md"
CANONICAL_MAP = ROOT / "data/hall_id_canonical_map.json"
LINE_PACKAGE = "jp.naver.line.android"
LINE_ID = f"{LINE_PACKAGE}:id/"


def canonical_hall_ids(path: Path = CANONICAL_MAP) -> dict[str, str]:
    """Legacy slot-line hall_id -> hall-master hall_id (identity only; ids stay as-is)."""
    if not path.exists():
        return {}
    return {legacy: item["canonical_hall_id"] for legacy, item in json.loads(path.read_text(encoding="utf-8"))["mappings"].items()}


def normalize_name(value: str) -> str:
    return re.sub(r"[\s・]", "", unicodedata.normalize("NFKC", value)).lower()


def pworld_path(value: str) -> str | None:
    match = re.search(r"p-world\.co\.jp/(?:sp/)?([a-z]+/[^?#\s\"]+\.htm)", value)
    return match.group(1) if match else None


def resolve_short_link(token: str) -> str:
    """lin.ee links are browser redirects; resolve them to the line.me URL LINE can open."""
    if not token.startswith("https://lin.ee/"):
        return token
    proc = subprocess.run(["curl", "-sI", "--max-time", "15", token], capture_output=True, text=True)
    match = re.search(r"^location:\s*(\S+)", proc.stdout, re.I | re.M)
    return match.group(1) if match else token


def line_url(token: str) -> str:
    if token.startswith(("http://", "https://")):
        return token
    return "https://line.me/R/ti/p/" + urllib.parse.quote(token)


def line_source_key(token: str) -> str:
    match = re.search(r"/ti/p/([^?#/]+)", token)
    return urllib.parse.unquote(match.group(1)) if match else token


def parse_pworld_line_list(path: Path = PWORLD_LIST) -> dict[str, list[str]]:
    """Map normalized store name -> LINE tokens in listing order (duplicate rows merged)."""
    result: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith(("| 店舗名", "|---")):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        tokens = [token for token in cells[1].split("<br>") if token and token != "—"]
        bucket = result.setdefault(normalize_name(cells[0]), [])
        seen = {line_source_key(token) for token in bucket}
        for token in tokens:
            if line_source_key(token) not in seen:
                seen.add(line_source_key(token))
                bucket.append(token)
    return result


def build_candidates(halls_csv: Path, registered: set[str]) -> list[dict[str, Any]]:
    listing = parse_pworld_line_list()
    canonical = canonical_hall_ids()
    registered = registered | {canonical.get(hall_id, hall_id) for hall_id in registered}
    rows = []
    with halls_csv.open(encoding="utf-8") as handle:
        for hall in csv.DictReader(handle):
            if hall.get("pref") != "神奈川県" or hall.get("status") != "active":
                continue
            tokens = listing.get(normalize_name(hall["name"]), [])
            detail = re.search(r"detail=([^;]+)", hall.get("source_evidence", ""))
            rows.append(
                {
                    "hall_id": hall["hall_id"],
                    "store_name": hall["name"],
                    "pworld_detail_url": detail.group(1) if detail else None,
                    "line_tokens": tokens,
                    "status": "registered" if hall["hall_id"] in registered else ("pending" if tokens else "no_line_listed"),
                }
            )
    return rows


class Device:
    def __init__(self, adb: str, serial: str):
        self.base = [adb, "-s", serial]

    def run(self, *args: str, timeout: int = 60, binary: bool = False) -> Any:
        proc = subprocess.run([*self.base, *args], capture_output=True, timeout=timeout)
        return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")

    def dump(self) -> str:
        self.run("shell", "uiautomator", "dump", "/sdcard/slot-line-onboard.xml")
        return self.run("exec-out", "cat", "/sdcard/slot-line-onboard.xml", timeout=30)

    def tap(self, x: int, y: int) -> None:
        self.run("shell", "input", "tap", str(x), str(y))

    def ensure_ready(self) -> None:
        if "mWakefulness=Awake" not in self.run("shell", "dumpsys", "power"):
            self.run("shell", "input", "keyevent", "KEYCODE_WAKEUP")
            time.sleep(1.5)
        if "mCurrentOrientation=0" not in self.run("shell", "dumpsys", "display"):
            raise RuntimeError("device_not_portrait")

    def screenshot(self, path: Path) -> Path:
        png = path.with_suffix(".png")
        png.write_bytes(self.run("exec-out", "screencap", "-p", binary=True))
        jpg = path.with_suffix(".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "60", str(png), "--out", str(jpg)], capture_output=True, check=True)
        png.unlink()
        return jpg


def nodes(xml: str) -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []
    result = []
    for node in root.iter("node"):
        bounds = re.findall(r"\d+", node.get("bounds", ""))
        if len(bounds) != 4:
            continue
        x1, y1, x2, y2 = map(int, bounds)
        result.append(
            {
                "text": node.get("text", ""),
                "desc": node.get("content-desc", ""),
                "id": node.get("resource-id", "").removeprefix(LINE_ID),
                "center": ((x1 + x2) // 2, (y1 + y2) // 2),
                "visible": x2 > x1 and y2 > y1,
            }
        )
    return result


def classify_screen(xml: str) -> dict[str, Any]:
    items = nodes(xml)
    texts = [item["text"] for item in items if item["text"]]
    dialog = next((item for item in items if item["id"] == "common_dialog_content_text"), None)
    if dialog:
        ok = next((item for item in items if item["id"] == "common_dialog_ok_btn"), None)
        return {"screen": "dialog", "message": dialog["text"], "ok": ok["center"] if ok else None}
    header = next((item["text"] for item in items if item["id"] in {"chat_ui_title", "header_title"} and item["text"]), None)
    if header and any(item["id"].startswith("chat_ui") for item in items):
        return {"screen": "chat", "name": header, "rich_menu": any("oa_richmenu" in item["id"] for item in items)}
    add = next((item for item in items if item["text"] == "友だち追加" and item["visible"]), None)
    text_items = [item for item in items if item["text"]]
    count_index = next((i for i, item in enumerate(text_items) if re.fullmatch(r"友だち\s*[\d,]+", item["text"])), None)
    talk = next((item for item in items if item["text"] == "トーク" and item["visible"]), None)
    pworld = next((pworld_path(value) for value in texts + [item["desc"] for item in items] if pworld_path(value)), None)
    if add or talk:
        name = text_items[count_index - 1]["text"] if count_index else None
        return {"screen": "profile", "name": name, "pworld_path": pworld, "add": add["center"] if add else None, "talk": talk["center"] if talk else None}
    return {"screen": "unknown", "texts": texts[:12]}


def identity(screen: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    expected_path = pworld_path(candidate.get("pworld_detail_url") or "")
    if screen.get("pworld_path") and expected_path and screen["pworld_path"] == expected_path:
        return "verified_pworld_url"
    if not screen.get("name"):
        return None
    observed, expected = normalize_name(screen["name"]), normalize_name(candidate["store_name"])
    if observed == expected:
        return "verified_normalized_name"
    if observed.removesuffix("店") == expected.removesuffix("店"):
        return "verified_name_without_store_suffix"
    if observed in {normalize_name(name) for name in candidate.get("owner_confirmed_profile_names", [])}:
        return "verified_owner_confirmed_name"
    return None


def open_url(device: Device, url: str) -> dict[str, Any]:
    stale = classify_screen(device.dump())
    if stale["screen"] == "dialog" and stale.get("ok"):
        device.tap(*stale["ok"])
        time.sleep(1)
    device.run("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(1)
    device.run("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url, LINE_PACKAGE)
    screen: dict[str, Any] = {"screen": "unknown"}
    for _ in range(4):
        time.sleep(3)
        screen = classify_screen(device.dump())
        if screen["screen"] != "unknown":
            break
    return screen


def onboard_one(device: Device, candidate: dict[str, Any], evidence: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"hall_id": candidate["hall_id"], "store_name": candidate["store_name"], "attempts": []}
    tokens: list[str] = []
    for token in map(resolve_short_link, candidate["line_tokens"]):
        if line_source_key(token) not in {line_source_key(seen) for seen in tokens}:
            tokens.append(token)
    for index, token in enumerate(tokens):
        device.ensure_ready()
        attempt: dict[str, Any] = {"line_source_key": line_source_key(token), "url": line_url(token)}
        record["attempts"].append(attempt)
        screen = open_url(device, attempt["url"])
        attempt["first_screen"] = screen["screen"]
        if screen["screen"] == "profile":
            profile_xml = evidence / f"{candidate['hall_id']}_profile_{index}.xml"
            profile_xml.write_text(device.dump(), encoding="utf-8")
            attempt["profile_xml"] = str(profile_xml.relative_to(ROOT))
        if screen["screen"] == "dialog":
            attempt["result"] = "dialog:" + screen["message"][:80]
            if screen.get("ok"):
                device.tap(*screen["ok"])
            continue
        if screen["screen"] == "chat":
            attempt["identity"] = identity(screen, candidate)
            attempt["friend_added"] = False
            attempt["already_friend"] = True
        elif screen["screen"] == "profile":
            attempt["profile_name"] = screen.get("name")
            attempt["profile_pworld_path"] = screen.get("pworld_path")
            attempt["identity"] = identity(screen, candidate)
            if not attempt["identity"]:
                attempt["result"] = "identity_unverified"
                continue
            if screen.get("add"):
                device.tap(*screen["add"])
                time.sleep(4)
                screen = classify_screen(device.dump())
                attempt["friend_added"] = True
            else:
                attempt["friend_added"] = False
                attempt["already_friend"] = True
            if screen["screen"] == "profile" and screen.get("talk"):
                device.tap(*screen["talk"])
                time.sleep(5)
                screen = classify_screen(device.dump())
        else:
            attempt["result"] = "unknown_screen"
            attempt["texts"] = screen.get("texts")
            continue
        if screen["screen"] != "chat":
            attempt["result"] = "chat_not_reached"
            continue
        if not attempt.get("identity"):
            attempt["identity"] = identity(screen, candidate)
        if not attempt["identity"]:
            attempt["result"] = "identity_unverified"
            continue
        attempt["chat_header"] = screen["name"]
        time.sleep(2)
        xml = device.dump()
        if "oa_richmenu_imageview" not in xml:
            bar = next((item for item in nodes(xml) if item["id"] == "chat_ui_oa_bottombar_menu_text"), None)
            if bar:
                device.tap(*bar["center"])
                time.sleep(2.5)
                xml = device.dump()
                attempt["menu_expanded"] = True
        stem = evidence / candidate["hall_id"]
        stem.with_suffix(".xml").write_text(xml, encoding="utf-8")
        attempt["screenshot"] = str(device.screenshot(stem).relative_to(ROOT))
        attempt["ui_xml"] = str(stem.with_suffix(".xml").relative_to(ROOT))
        attempt["rich_menu_node"] = "oa_richmenu" in xml
        attempt["bottom_bar"] = "chat_ui_oa_bottombar" in xml
        attempt["result"] = "onboarded"
        record.update(
            result="onboarded",
            line_source_key=attempt["line_source_key"],
            identity_status=attempt["identity"],
            friend_added=attempt.get("friend_added", False),
            onboarded_at=datetime.now(timezone.utc).isoformat(),
        )
        return record
    record["result"] = "not_onboarded"
    return record


REGISTRY_FIELDS = ("hall_id", "collector_key", "line_source_key", "store_name", "prefecture", "identity_status",
                   "profile_display_name", "chat_header_name", "profile_expected_names")


def build_registry(capability: dict[str, Any], onboarding_files: list[Path]) -> list[dict[str, Any]]:
    """Collector targets: the identity-verified frozen survey rows plus onboarded stores."""
    targets = [
        {key: row[key] for key in REGISTRY_FIELDS if row.get(key)} | {"source": "line_capability_50_live_2026-09-25", "active": True}
        for row in capability["records"]
        if row.get("profile_verified") and str(row.get("identity_status", "")).startswith("verified_")
    ]
    canonical = canonical_hall_ids()
    for row in targets:
        row["canonical_hall_id"] = canonical.get(row["hall_id"], row["hall_id"])
    known = {row["hall_id"] for row in targets}
    for path in sorted(onboarding_files):
        for record in json.loads(path.read_text(encoding="utf-8"))["records"]:
            if record.get("result") != "onboarded" or record["hall_id"] in known:
                continue
            attempt = next(item for item in record["attempts"] if item.get("result") == "onboarded")
            targets.append(
                {
                    "hall_id": record["hall_id"],
                    "canonical_hall_id": record["hall_id"],
                    "collector_key": record["hall_id"],
                    "line_source_key": record["line_source_key"],
                    "store_name": record["store_name"],
                    "prefecture": "神奈川県",
                    "identity_status": record["identity_status"],
                    "chat_header_name": attempt.get("chat_header"),
                    "profile_expected_names": [record["store_name"]],
                    "source": path.name,
                    "active": True,
                }
            )
            known.add(record["hall_id"])
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cand = sub.add_parser("candidates")
    cand.add_argument("--halls-csv", type=Path, required=True)
    cand.add_argument("--registered", type=Path, default=ROOT / "data/line_targets.json", help="collector registry (or a policy table) of registered stores")
    cand.add_argument("--output", type=Path, required=True)
    registry = sub.add_parser("registry")
    registry.add_argument("--capability", type=Path, default=ROOT / "data/surveys/line_capability_50_live_2026-09-25.json")
    registry.add_argument("--onboarding", type=Path, nargs="*", default=sorted((ROOT / "data/surveys").glob("line_onboarding_batch*_2026-*.json")))
    registry.add_argument("--output", type=Path, default=ROOT / "data/line_targets.json")
    onboard = sub.add_parser("onboard")
    onboard.add_argument("--candidates", type=Path, required=True)
    onboard.add_argument("--hall-ids", required=True, help="comma-separated hall_ids from the candidates file")
    onboard.add_argument("--output", type=Path, required=True)
    onboard.add_argument("--evidence-dir", type=Path, required=True)
    onboard.add_argument("--adb", default="/tmp/codex-adb-bridge/adb")
    onboard.add_argument("--serial", default="HQ615G150D")
    onboard.add_argument("--retry-failed", action="store_true", help="retry hall_ids whose previous result was not_onboarded")
    onboard.add_argument("--owner-confirmed-name", action="append", default=[], metavar="HALL_ID=PROFILE_NAME",
                         help="LINE profile name the owner confirmed as this hall (exact after normalization)")
    args = parser.parse_args()

    if args.command == "candidates":
        source = json.loads(args.registered.read_text(encoding="utf-8"))
        registered = {row["hall_id"] for row in source.get("targets") or source["stores"]}
        rows = build_candidates(args.halls_csv, registered)
        args.output.write_text(json.dumps({"schema_version": 1, "source_halls_csv": str(args.halls_csv), "source_pworld_list": PWORLD_LIST.name, "candidates": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        print(json.dumps(counts, ensure_ascii=False))
        return 0

    if args.command == "registry":
        targets = build_registry(json.loads(args.capability.read_text(encoding="utf-8")), args.onboarding)
        from collect_passive_incremental import _validate_target_set

        _validate_target_set(targets, len(targets))
        args.output.write_text(json.dumps({"schema_version": 1, "targets": targets}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"target_count": len(targets)}, ensure_ascii=False))
        return 0

    by_id = {row["hall_id"]: row for row in json.loads(args.candidates.read_text(encoding="utf-8"))["candidates"]}
    for item in args.owner_confirmed_name:
        hall_id, _, name = item.partition("=")
        if hall_id not in by_id or not name:
            parser.error(f"bad --owner-confirmed-name: {item}")
        by_id[hall_id].setdefault("owner_confirmed_profile_names", []).append(name)
    wanted = [hall_id.strip() for hall_id in args.hall_ids.split(",") if hall_id.strip()]
    missing = [hall_id for hall_id in wanted if hall_id not in by_id or by_id[hall_id]["status"] != "pending"]
    if missing:
        parser.error(f"not pending candidates: {missing}")
    args.evidence_dir = args.evidence_dir.resolve()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    output = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {"schema_version": 1, "records": []}
    if args.retry_failed:
        output["records"] = [
            record for record in output["records"]
            if record.get("result") == "onboarded" or record["hall_id"] not in wanted
        ]
    done = {record["hall_id"] for record in output["records"]}
    device = Device(args.adb, args.serial)
    for hall_id in wanted:
        if hall_id in done:
            continue
        record = onboard_one(device, by_id[hall_id], args.evidence_dir)
        output["records"].append(record)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({key: record.get(key) for key in ("hall_id", "result", "line_source_key", "identity_status", "friend_added")}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
