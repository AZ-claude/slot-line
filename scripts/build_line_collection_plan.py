"""Build data/line_collection_plan.json: what the daily LINE PC collector does per store.

Inputs: data/line_targets.json (registered stores) and every
data/surveys/collection_policy_*.json table (Type A/B/C/unresolved).
Optional: data/line_text_trigger_results.json (results of one-time text-trigger checks).

Per store:
  search_name        LINE display name to type into LINE PC's chat search
  collection_type    from the policy table
  text_trigger       "daily"        send the trigger every day (verified)
                     "verify_once"  Type B not yet verified: send once, then an owner/AI decides
                     "off"          never send
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIGGER_TEXT = "最新情報"


def load_policy_rows(pattern: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in sorted(glob.glob(pattern)):
        if path.endswith("_review.json"):
            continue
        for row in json.loads(Path(path).read_text(encoding="utf-8"))["stores"]:
            rows[row["hall_id"]] = row | {"policy_file": Path(path).name}
    return rows


def build_plan(targets: list[dict], policy: dict[str, dict], checks: dict[str, dict]) -> list[dict]:
    plan = []
    for target in targets:
        if not target.get("active", True):
            continue
        row = policy.get(target["hall_id"], {})
        collection_type = row.get("collection_type", "unresolved")
        check = checks.get(target["hall_id"], {})
        if collection_type != "type_b_passive_plus_active":
            mode = "off"
        elif row.get("text_trigger_verified") or row.get("active_method") == "text_trigger" or check.get("result") == "reply":
            mode = "daily"
        elif check.get("result") == "no_reply":
            mode = "off"  # stays a rich-menu (Android) store
        else:
            mode = "verify_once"
        plan.append({
            "hall_id": target["hall_id"],
            "line_source_key": target["line_source_key"],
            "search_name": target.get("chat_header_name") or target.get("profile_display_name") or target["store_name"],
            "collection_type": collection_type,
            "text_trigger": mode,
            "trigger_text": TRIGGER_TEXT if mode != "off" else None,
            "policy_file": row.get("policy_file"),
        })
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--targets", type=Path, default=ROOT / "data/line_targets.json")
    parser.add_argument("--policy-glob", default=str(ROOT / "data/surveys/collection_policy_*.json"))
    parser.add_argument("--checks", type=Path, default=ROOT / "data/line_text_trigger_results.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/line_collection_plan.json")
    args = parser.parse_args()
    targets = json.loads(args.targets.read_text(encoding="utf-8"))["targets"]
    checks = json.loads(args.checks.read_text(encoding="utf-8"))["stores"] if args.checks.exists() else {}
    plan = build_plan(targets, load_policy_rows(args.policy_glob), checks)
    counts: dict[str, int] = {}
    for row in plan:
        counts[row["text_trigger"]] = counts.get(row["text_trigger"], 0) + 1
    args.output.write_text(json.dumps({"schema_version": 1, "trigger_text": TRIGGER_TEXT, "stores": plan},
                                      ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"stores": len(plan), "text_trigger": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
