"""Copy LINE PC capture RAW from Windows to the Mac (data/line_pc_raw/<date>/), no LLM.

Only the collector's output is copied: line_pc_run_*.json manifests and each
store's line_pc/ folder. data/line_pc_raw is git-ignored (screenshots of chats).

    python3 scripts/line_pc_sync.py              # the last 3 capture dates
    python3 scripts/line_pc_sync.py --date 2026-10-01
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "pokeca-windows"
WINDOWS_RAW = r"D:\slot-line\raw"  # moved off C: on 2026-10-02 (C: has ~45 GB free)


def sync_date(day: str, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    listing = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, f'if exist "{WINDOWS_RAW}\\{day}" dir /b /s "{WINDOWS_RAW}\\{day}\\line_pc_run_*.json" "{WINDOWS_RAW}\\{day}\\*line_pc"'],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    members = []
    for line in listing.stdout.splitlines():
        line = line.strip()
        if line and line.lower().startswith(WINDOWS_RAW.lower()):
            members.append(line[len(WINDOWS_RAW) + 1:].replace("\\", "/"))
    if not members:
        return 0
    tar = subprocess.Popen(["ssh", "-o", "BatchMode=yes", HOST, f'cd /d "{WINDOWS_RAW}" && tar -cf - ' + " ".join(f'"{m}"' for m in members)],
                           stdout=subprocess.PIPE)
    subprocess.run(["tar", "-xf", "-", "-C", str(dest)], stdin=tar.stdout, check=True)
    if tar.wait() != 0:
        raise RuntimeError(f"remote tar failed for {day}")
    return len(members)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", action="append")
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()
    days = args.date or [(date.today() - timedelta(days=n)).isoformat() for n in range(args.days)]
    dest = ROOT / "data" / "line_pc_raw"
    for day in days:
        print(day, sync_date(day, dest), "items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
