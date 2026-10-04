#!/bin/zsh
# Mac side of the nightly LINE run (after the Windows collector, which starts at 21:30 and ends around 23:00).
# Copies the new captures, cuts them into posts, sorts them (Vision + Qwen), records machine-hint
# cards and rebuilds the site. No step sends anything anywhere.
#   scripts/line_nightly_mac.sh            # logs to data/line_pc_nightly.log
set -u
cd "$(dirname "$0")/.." || exit 1
log=data/line_pc_nightly.log
{
  echo "=== $(date '+%F %T') start"
  # one run at a time (a long first sort may still be going)
  for _ in {1..48}; do pgrep -f "scripts/line_(triage|hints|pc_posts).py" >/dev/null || break; sleep 300; done
  # wait for the Windows run of today to finish (up to 3 hours)
  for _ in {1..36}; do
    if ssh -o BatchMode=yes pokeca-windows 'schtasks /Query /TN SlotLineLinePc /FO LIST' 2>/dev/null | iconv -f cp932 -t utf-8 | grep -q "準備完了"; then break; fi
    sleep 300
  done
  python3 scripts/line_pc_sync.py --days 2 &&
  .venv/bin/python scripts/line_pc_posts.py &&
  .venv/bin/python scripts/line_triage.py --since "$(date -v-3d +%F)" &&
  .venv/bin/python scripts/line_hints.py --since "$(date -v-3d +%F)" &&
  .venv/bin/python scripts/line_pc_site.py
  echo "=== $(date '+%F %T') end (exit $?)"
} >> "$log" 2>&1
