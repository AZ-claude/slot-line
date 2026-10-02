"""Tap one rich-menu tile per store, once, and record what happened.

The chat must already be reachable from the LINE talk list (the store is a
friend). Chats are opened from the talk list, never by LINE ID URL, so this
does not spend the account's ID-search quota.

Guards before the tap (any failure = no tap, logged as guard_failed):
  - device is portrait
  - chat header equals the expected store name (whitespace ignored)
  - the tap point is inside the rich-menu image
  - the store has no earlier "executed" row in action_results.jsonl

Each target is "hall_id|line_source_key|chat header name|x|y|label".
Run with --dry-run first: it opens the chat, checks the guards and saves
<hall_id>_dryrun.jpg with the menu bounds, but does not tap. If the chat is
not found in the talk list, stop and report; never open rows by coordinates.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
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
        # Talk-list dumps show other (personal) chats: keep them out of the evidence folder.
        self.scratch = Path(tempfile.mkdtemp(prefix="slot-line-chatlist-"))

    def run(self, *args: str, timeout: int = 120, binary: bool = False):
        for attempt in range(3):  # the SSH->ADB bridge stalls now and then; retrying is enough
            try:
                proc = subprocess.run([*self.base, *args], capture_output=True, timeout=timeout)
                break
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise
                time.sleep(5)
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
            xml = self.dump(self.scratch / "chatlist.xml")
            if "header_title" not in xml and 'text="トーク"' in xml:
                return
            self.run("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1.2)
        self.run("shell", "monkey", "-p", LINE_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(3)

    def scroll_to_top(self) -> None:
        # LINE keeps the talk list's last scroll position; newer stores sit at the top.
        # The Talk tab has a トーク/友だち toggle at the top-left; make sure トーク is shown.
        xml = self.dump(self.scratch / "chatlist.xml")
        if 'text="グループ"' in xml or 'text="30日以内の予定"' in xml:
            self.tap(80, 102)
            time.sleep(1.5)
        # Fast flings until the search box at the very top of the list is visible.
        for _ in range(12):
            self.run("shell", "input", "swipe", "360", "450", "360", "1300", "80")
            time.sleep(0.7)
            xml = self.dump(self.scratch / "chatlist.xml")
            if re.search(r'text="検索"[^>]*bounds="\[\d+,1[5-9]\d\]', xml):
                return

    def open_chat_by_name(self, name: str, pages: int = 60) -> bool:
        self.open_talk_list()
        self.scroll_to_top()
        previous = None
        for _ in range(pages):
            xml = self.dump(self.scratch / "chatlist.xml")
            for m in re.finditer(r'text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
                if norm(m[1]) == norm(name) and 420 < int(m[3]) < 1300:
                    self.tap((int(m[2]) + int(m[4])) // 2, (int(m[3]) + int(m[5])) // 2)
                    time.sleep(4)
                    return True
            names = re.findall(r'text="([^"]+)"', xml)
            if names and names == previous:
                return False  # reached the end of the talk list
            previous = names
            self.run("shell", "input", "swipe", "360", "1200", "360", "600", "500")
            time.sleep(1.2)
        return False


def texts(xml: str) -> list[str]:
    return re.findall(r' text="([^"]+)"', xml)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="evidence folder, e.g. data/surveys/line_onboarding_batch03_<date>_evidence/actions")
    parser.add_argument("--adb", default="/tmp/codex-adb-bridge/adb")
    parser.add_argument("--serial", default="HQ615G150D")
    parser.add_argument("--dry-run", action="store_true", help="open and check only; never tap the menu")
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    log = out / "action_results.jsonl"
    done = set()
    if log.exists():
        done = {json.loads(line)["hall_id"] for line in log.read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("status") in {"executed", "tapped_capture_pending"}}
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
        if len(parts) != 6:
            print(json.dumps({"hall_id": hall, "error": "target needs exactly 6 fields"}, ensure_ascii=False))
            return 2
        if not device.open_chat_by_name(name):
            write(record | {"status": "guard_failed", "reason": "chat_not_found_in_talk_list"})
            continue
        pre = device.dump(device.scratch / "pre_action.xml")
        titles = re.findall(r'text="([^"]+)"[^>]*resource-id="jp.naver.line.android:id/\w*title', pre)
        if not any(norm(t) == norm(name) for t in titles):
            # Wrong chat (possibly a personal one): save nothing from it and do not tap.
            write(record | {"status": "guard_failed", "reason": "chat_header_mismatch"})
            device.run("shell", "input", "keyevent", "KEYCODE_BACK")
            continue
        (out / f"{hall}_pre_action.xml").write_text(pre, encoding="utf-8")
        if "oa_richmenu_imageview" not in pre:
            bar = re.search(r'chat_ui_oa_bottombar_menu_text"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', pre)
            if bar:
                device.tap((int(bar[1]) + int(bar[3])) // 2, (int(bar[2]) + int(bar[4])) // 2)
                time.sleep(2.5)
                pre = device.dump(out / f"{hall}_pre_action.xml")
                record["menu_expanded_before_action"] = True
        titles = re.findall(r'text="([^"]+)"[^>]*resource-id="jp.naver.line.android:id/\w*title', pre)
        menu = re.search(r'oa_richmenu_imageview"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', pre)
        title_ok = any(norm(t) == norm(name) for t in titles)
        tap_ok = bool(menu) and int(menu[1]) <= x <= int(menu[3]) and int(menu[2]) <= y <= int(menu[4])
        if args.dry_run:
            shot = device.screenshot(out / f"{hall}_dryrun")
            print(json.dumps(record | {"status": "dry_run", "header_ok": title_ok, "tap_inside_menu": tap_ok,
                                        "menu_bounds": f"[{menu[1]},{menu[2]}][{menu[3]},{menu[4]}]" if menu else None, "screenshot": str(shot)}, ensure_ascii=False), flush=True)
            device.run("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(1)
            continue
        device.screenshot(out / f"{hall}_pre_action")
        if not (title_ok and tap_ok):
            write(record | {"status": "guard_failed", "titles": titles, "menu_bounds": f"[{menu[1]},{menu[2]}][{menu[3]},{menu[4]}]" if menu else None})
            continue
        record["triggered_at"] = datetime.now(timezone.utc).isoformat()
        device.tap(x, y)
        # Log the tap before capturing: a capture failure must never lead to a second tap.
        write(record | {"status": "tapped_capture_pending"})
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
