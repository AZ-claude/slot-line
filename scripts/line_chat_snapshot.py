"""Photograph friended stores' chats from the talk list (no taps on menus, no sends).

Used to re-check a rich menu (e.g. before calling it absent_confirmed). Each
target is "hall_id|chat header name". Two UI dumps 1.5 s apart plus one
screenshot are saved per store.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

try:
    from line_richmenu_tap import Device, norm
except ImportError:  # run as module
    from scripts.line_richmenu_tap import Device, norm


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--adb", default="/tmp/codex-adb-bridge/adb")
    parser.add_argument("--serial", default="HQ615G150D")
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    device = Device(args.adb, args.serial, args.out)
    for spec in args.targets:
        hall, name = spec.split("|")[:2]
        if not device.portrait():
            print("STOP: device is not portrait")
            return 2
        if not device.open_chat_by_name(name):
            print(json.dumps({"hall_id": hall, "status": "chat_not_found_in_talk_list"}, ensure_ascii=False))
            continue
        probe = device.dump(device.scratch / "probe.xml")
        if not any(norm(t) == norm(name) for t in re.findall(r'text="([^"]+)"[^>]*resource-id="jp.naver.line.android:id/\w*title', probe)):
            print(json.dumps({"hall_id": hall, "status": "chat_header_mismatch_nothing_saved"}, ensure_ascii=False))
            device.run("shell", "input", "keyevent", "KEYCODE_BACK")
            continue
        first = device.dump(args.out / f"{hall}_snap_1.xml")
        time.sleep(1.5)
        second = device.dump(args.out / f"{hall}_snap_2.xml")
        shot = device.screenshot(args.out / f"{hall}_snap")
        titles = re.findall(r'text="([^"]+)"[^>]*resource-id="jp.naver.line.android:id/\w*title', second)
        print(json.dumps({
            "hall_id": hall,
            "header_match": any(norm(t) == norm(name) for t in titles),
            "rich_menu_node": "oa_richmenu" in first or "oa_richmenu" in second,
            "menu_bar": "chat_ui_oa_bottombar" in second,
            "composer": "chat_ui_message_edit" in second,
            "screenshot": str(shot),
        }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
