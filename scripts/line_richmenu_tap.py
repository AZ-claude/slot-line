"""Tap one rich-menu tile per store, once, and record what happened.

The chat must already be reachable from the LINE talk list (the store is a
friend). Chats are opened from the talk list, never by LINE ID URL, so this
does not spend the account's ID-search quota.

Guards before the tap (any failure = no tap, logged as guard_failed):
  - device is portrait
  - chat header equals the expected store name (whitespace ignored)
  - the tap point is inside the rich-menu image
  - the store has no earlier "executed" row in action_results.jsonl

Each target is "hall_id|line_source_key|chat header name|x|y|label[|row_x,row_y]".
row_x,row_y is the talk-list row to tap when the name search cannot find it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

LINE_PACKAGE = "jp.naver.line.android"


def norm(value: str) -> str:
    return re.sub(r"\s+", "", value)


class Device:
    def __init__(self, adb: str, serial: str, out: Path):
        self.base = [adb, "-s", serial]
        self.out = out

    def run(self, *args: str, timeout: int = 120, binary: bool = False):
        proc = subprocess.run([*self.base, *args], capture_output=True, timeout=timeout)
        return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")

    def dump(self, path: Path) -> str:
        xml = ""
        for _ in range(3):
            self.run("shell", "uiautomator", "dump", "/sdcard/slot-line-tap.xml")
            xml = self.run("exec-out", "cat", "/sdcard/slot-line-tap.xml", timeout=30)
            if len(xml) > 500:
                break
            time.sleep(2)
        path.write_text(xml, encoding="utf-8")
        return xml

    def screenshot(self, stem: Path) -> Path:
        png = stem.with_suffix(".png")
        png.write_bytes(self.run("exec-out", "screencap", "-p", binary=True))
        jpg = stem.with_suffix(".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "60", str(png), "--out", str(jpg)],
                       capture_output=True, check=True)
        png.unlink()
        return jpg

    def tap(self, x: int, y: int) -> None:
        self.run("shell", "input", "tap", str(x), str(y))

    def portrait(self) -> bool:
        return "mCurrentOrientation=0" in self.run("shell", "dumpsys", "display")

    def open_talk_list(self) -> None:
        self.run("shell", "input", "keyevent", "KEYCODE_HOME")
        time.sleep(1)
        self.run("shell", "monkey", "-p", LINE_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(4)
        # LINE resumes the last open screen (a chat, browser or dialog); back out to the talk list.
        for _ in range(4):
            xml = self.dump(self.out / "_chatlist.xml")
            if "header_title" not in xml and 'text="トーク"' in xml:
                return
            self.run("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1.2)
        self.run("shell", "monkey", "-p", LINE_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(3)

    def open_chat_by_name(self, name: str, pages: int = 8) -> bool:
        self.open_talk_list()
        for _ in range(pages):
            xml = self.dump(self.out / "_chatlist.xml")
            for m in re.finditer(r'text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
                if norm(m[1]) == norm(name) and 420 < int(m[3]) < 1340:
                    self.tap((int(m[2]) + int(m[4])) // 2, (int(m[3]) + int(m[5])) // 2)
                    time.sleep(4)
                    return True
            self.run("shell", "input", "swipe", "360", "1200", "360", "500", "400")
            time.sleep(1.2)
        return False


def texts(xml: str) -> list[str]:
    return re.findall(r' text="([^"]+)"', xml)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="evidence folder, e.g. data/surveys/line_onboarding_batch03_<date>_evidence/actions")
    parser.add_argument("--adb", default="/tmp/codex-adb-bridge/adb")
    parser.add_argument("--serial", default="HQ615G150D")
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    log = out / "action_results.jsonl"
    done = set()
    if log.exists():
        done = {json.loads(line)["hall_id"] for line in log.read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("status") == "executed"}
    device = Device(args.adb, args.serial, out)

    def write(record: dict) -> None:
        print(json.dumps(record, ensure_ascii=False), flush=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    for spec in args.targets:
        parts = spec.split("|")
        hall, line_id, name, xs, ys, label = parts[:6]
        x, y = int(xs), int(ys)
        record = {"hall_id": hall, "line_source_key": line_id, "visible_action_label": label, "tap": [x, y]}
        if hall in done:
            print(json.dumps({"hall_id": hall, "skip": "already_executed"}, ensure_ascii=False))
            continue
        if not device.portrait():
            print("STOP: device is not portrait")
            return 2
        if len(parts) > 6:
            device.open_talk_list()
            rx, ry = parts[6].split(",")
            device.tap(int(rx), int(ry))
            time.sleep(4)
        elif not device.open_chat_by_name(name):
            write(record | {"status": "guard_failed", "reason": "chat_not_found_in_talk_list"})
            continue
        pre = device.dump(out / f"{hall}_pre_action.xml")
        if "oa_richmenu_imageview" not in pre:
            bar = re.search(r'chat_ui_oa_bottombar_menu_text"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', pre)
            if bar:
                device.tap((int(bar[1]) + int(bar[3])) // 2, (int(bar[2]) + int(bar[4])) // 2)
                time.sleep(2.5)
                pre = device.dump(out / f"{hall}_pre_action.xml")
                record["menu_expanded_before_action"] = True
        titles = re.findall(r'text="([^"]+)"[^>]*resource-id="jp.naver.line.android:id/\w*title', pre)
        menu = re.search(r'oa_richmenu_imageview"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', pre)
        device.screenshot(out / f"{hall}_pre_action")
        title_ok = any(norm(t) == norm(name) for t in titles)
        tap_ok = bool(menu) and int(menu[1]) <= x <= int(menu[3]) and int(menu[2]) <= y <= int(menu[4])
        if not (title_ok and tap_ok):
            write(record | {"status": "guard_failed", "titles": titles, "menu_bounds": menu.group(0) if menu else None})
            continue
        record["triggered_at"] = datetime.now(timezone.utc).isoformat()
        device.tap(x, y)
        time.sleep(12)
        post = device.dump(out / f"{hall}_post_action.xml")
        device.screenshot(out / f"{hall}_post_action")
        before = set(texts(pre))
        record.update(
            new_texts=[t for t in texts(post) if t not in before][:40],
            urls_in_post=re.findall(r'text="(https?://[^"]+)"', post)[:5],
            other_app=sorted({p for p in re.findall(r'package="([^"]+)"', post) if p != LINE_PACKAGE}),
            status="executed",
            captured_at=datetime.now(timezone.utc).isoformat(),
        )
        write(record)
        device.run("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
