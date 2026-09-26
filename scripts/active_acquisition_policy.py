"""Evidence-first Type A/B/C policy derivation for the registered LINE sources."""

from __future__ import annotations

from collections import Counter
from typing import Any


COLLECTION_TYPES = {
    "type_a_passive",
    "type_b_passive_plus_active",
    "type_c_passive_external_web",
    "unresolved",
}
ACTION_RESULTS = {"line_reply", "external_web", "external_app", "static_display", "no_effect_observed", "unknown"}
ACTIVE_STATUSES = {
    "active_verified",
    "active_candidate",
    "no_active_action_confirmed",
    "active_not_observed",
    "unknown",
}


def _latest_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = record.get("action_candidates")
    if not isinstance(candidates, list):
        menu = record.get("rich_menu_observation")
        candidates = menu.get("action_candidates") if isinstance(menu, dict) else None
    if not isinstance(candidates, list):
        return []
    return [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and candidate.get("action_category") == "latest_information"
        and isinstance(candidate.get("visible_label"), str)
        and candidate["visible_label"]
    ]


def _action_kind_has_rich_menu(record: dict[str, Any]) -> bool:
    action = record.get("action_execution")
    kinds = action.get("action_kind") if isinstance(action, dict) else None
    if isinstance(kinds, str):
        kinds = [kinds]
    return isinstance(kinds, list) and "rich_menu" in kinds


def _verified_latest_result(record: dict[str, Any]) -> str | None:
    execution = record.get("action_execution")
    if isinstance(execution, dict):
        result = execution.get("result")
        kinds = execution.get("action_kind")
        if isinstance(kinds, str):
            kinds = [kinds]
        if (
            execution.get("status") == "previously_executed_and_verified"
            and result in {"line_reply", "external_web"}
            and (
                _action_kind_has_rich_menu(record)
                or (
                    result == "line_reply"
                    and isinstance(kinds, list)
                    and "text_trigger" in kinds
                    and record.get("text_trigger_route_verified") is True
                )
            )
        ):
            return result
    verified = {
        candidate.get("execution_result")
        for candidate in _latest_candidates(record)
        if candidate.get("execution_verified") is True
        and candidate.get("destination_verified") is True
        and candidate.get("execution_result") in {"line_reply", "external_web"}
    }
    return next(iter(verified)) if len(verified) == 1 else None


def _text_trigger_status(record: dict[str, Any], collection_type: str) -> tuple[bool, bool]:
    if record.get("text_trigger_verified") is True:
        return True, False
    route_status = record.get("text_trigger_route_status")
    equivalence = record.get("text_trigger_equivalence_status")
    candidate = route_status in {
        "candidate",
        "prefill_verified_reply_timeout",
        "capture_succeeded_result_unclassified",
    } or equivalence == "candidate"
    if collection_type != "type_b_passive_plus_active":
        return False, candidate
    return False, candidate


def _trigger_text(record: dict[str, Any]) -> str | None:
    value = record.get("text_trigger_value")
    if isinstance(value, str) and value:
        return value
    execution = record.get("action_execution")
    value = execution.get("trigger_value") if isinstance(execution, dict) else None
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    if record.get("hall_id") == "pia-tsunashima":
        human = record.get("human_evidence")
        if isinstance(human, dict) and human.get("reported_text_trigger") == "最新情報":
            return "最新情報"
    return None


def _external_url(record: dict[str, Any]) -> str | None:
    execution = record.get("action_execution")
    destinations = execution.get("observed_destinations") if isinstance(execution, dict) else None
    if isinstance(destinations, list):
        for destination in destinations:
            if isinstance(destination, dict):
                url = destination.get("url")
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    return url
    for candidate in _latest_candidates(record):
        details = candidate.get("destination_details")
        if (
            candidate.get("execution_verified") is True
            and candidate.get("execution_result") == "external_web"
            and isinstance(details, dict)
            and isinstance(details.get("url"), str)
        ):
            return details["url"]
    return None


def _evidence_refs(record: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    menu = record.get("rich_menu_observation")
    if isinstance(menu, dict):
        refs.extend(item for item in menu.get("evidence_refs", []) if isinstance(item, str))
        node_evidence = menu.get("node_evidence")
        if isinstance(node_evidence, dict):
            for key in ("source_xml", "latest_chat_snapshot_ref"):
                item = node_evidence.get(key)
                if isinstance(item, str):
                    refs.append(item)
    sources = record.get("evidence_sources")
    if isinstance(sources, dict):
        refs.extend(item for item in sources.get("active_evidence_refs", []) if isinstance(item, str))
    for candidate in _latest_candidates(record):
        refs.extend(item for item in candidate.get("evidence_refs", []) if isinstance(item, str))
    return list(dict.fromkeys(refs))


def classify_inventory_record(record: dict[str, Any]) -> dict[str, Any]:
    """Add policy fields without turning missing evidence into confirmed absence."""
    menu = record.get("rich_menu_observation")
    menu_status = menu.get("status") if isinstance(menu, dict) else "unknown"
    verified_result = _verified_latest_result(record)
    if record.get("no_active_action_confirmed") is True and verified_result is not None:
        raise ValueError(f"conflicting_active_action_evidence:{record.get('hall_id')}")
    if verified_result == "line_reply":
        collection_type = "type_b_passive_plus_active"
    elif menu_status == "present" and verified_result == "external_web":
        collection_type = "type_c_passive_external_web"
    elif menu_status == "absent_confirmed" and record.get("no_active_action_confirmed") is True:
        collection_type = "type_a_passive"
    else:
        collection_type = "unresolved"

    text_verified, text_candidate = _text_trigger_status(record, collection_type)
    if collection_type == "type_a_passive":
        active_method = "none"
        action_result = "unknown"
    elif collection_type == "type_b_passive_plus_active":
        active_method = "text_trigger" if text_verified or (
            isinstance(record.get("action_execution"), dict)
            and "text_trigger" in (
                record["action_execution"].get("action_kind")
                if isinstance(record["action_execution"].get("action_kind"), list)
                else [record["action_execution"].get("action_kind")]
            )
        ) else "rich_menu"
        action_result = "line_reply"
    elif collection_type == "type_c_passive_external_web":
        active_method = "rich_menu"
        action_result = "external_web"
    else:
        execution = record.get("action_execution")
        result = execution.get("result") if isinstance(execution, dict) else None
        action_result = result if result in ACTION_RESULTS else "unknown"
        capture = record.get("collector_capture_acceptance")
        capture_kind = capture.get("action_kind") if isinstance(capture, dict) else None
        execution_kinds = execution.get("action_kind") if isinstance(execution, dict) else None
        if isinstance(execution_kinds, str):
            execution_kinds = [execution_kinds]
        if capture_kind == "text_trigger" or (
            isinstance(execution_kinds, list)
            and any(kind in {"text_trigger", "text_trigger_via_oa_message_url"} for kind in execution_kinds)
        ):
            active_method = "text_trigger"
        else:
            active_method = "unknown"

    latest_candidates = _latest_candidates(record)
    if verified_result:
        latest_action_status = "verified"
    elif latest_candidates:
        latest_action_status = "candidate"
    elif menu_status == "absent_confirmed" and verified_result is None:
        latest_action_status = "not_applicable"
    elif record.get("action_candidates_status") == "not_observed":
        latest_action_status = "not_observed"
    else:
        latest_action_status = "unknown"

    source_active_status = record.get("active_status")
    if record.get("no_active_action_confirmed") is True:
        active_status = "no_active_action_confirmed"
    elif verified_result is not None:
        active_status = "active_verified"
    elif source_active_status in ACTIVE_STATUSES:
        active_status = source_active_status
    elif latest_candidates or record.get("text_trigger_route_status") in {
        "candidate",
        "prefill_verified_reply_timeout",
        "capture_succeeded_result_unclassified",
    } or isinstance(record.get("collector_capture_acceptance"), dict):
        active_status = "active_candidate"
    elif menu_status in {"present", "absent_confirmed", "not_observed"}:
        active_status = "active_not_observed"
    else:
        active_status = "unknown"

    text_only_verified = (
        collection_type == "type_b_passive_plus_active"
        and active_method == "text_trigger"
        and not _action_kind_has_rich_menu(record)
    )
    collection_policy_candidate = {
        "type_a_passive": "passive_only_candidate",
        "type_b_passive_plus_active": "passive_plus_active_candidate",
        "type_c_passive_external_web": "passive_only_candidate",
        "unresolved": "unresolved",
    }[collection_type]
    if text_only_verified:
        collection_policy_candidate = "active_only_candidate"

    record.update(
        {
            "rich_menu_status": menu_status if menu_status in {"present", "absent_confirmed", "not_observed", "unknown"} else "unknown",
            "latest_action_status": latest_action_status,
            "action_result": action_result,
            "collection_type": collection_type,
            "active_status": active_status,
            "active_method": active_method,
            "trigger_text": _trigger_text(record),
            "text_trigger_verified": text_verified,
            "text_trigger_candidate": text_candidate,
            "external_url": _external_url(record) if action_result == "external_web" else None,
            "evidence_refs": _evidence_refs(record),
            "passive_collection_required": True,
            "active_collection_required": collection_type == "type_b_passive_plus_active",
            "collection_policy_candidate": collection_policy_candidate,
        }
    )
    return record


def classify_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    records = inventory.get("records")
    if not isinstance(records, list):
        raise ValueError("inventory_records_must_be_list")
    classified = [classify_inventory_record(record) for record in records if isinstance(record, dict)]
    counts = Counter(record["collection_type"] for record in classified)
    menu_counts = Counter(record["rich_menu_status"] for record in classified)
    inventory["records"] = classified
    summary = inventory.setdefault("summary", {})
    summary["collection_type_counts"] = {key: counts.get(key, 0) for key in COLLECTION_TYPES}
    summary["passive_collection_target_count"] = sum(record["passive_collection_required"] for record in classified)
    summary["active_trigger_target_count"] = sum(record["active_collection_required"] for record in classified)
    summary["type_b_text_trigger_verified_count"] = sum(
        record["text_trigger_verified"] for record in classified
    )
    summary["type_b_text_trigger_candidate_count"] = sum(
        record["collection_type"] == "type_b_passive_plus_active" and record["text_trigger_candidate"]
        for record in classified
    )
    summary["text_trigger_candidate_count"] = sum(record["text_trigger_candidate"] for record in classified)
    summary["type_b_latest_action_verified_count"] = sum(
        record["collection_type"] == "type_b_passive_plus_active" for record in classified
    )
    summary["rich_menu_latest_action_verified_count"] = sum(
        record["collection_type"] in {"type_b_passive_plus_active", "type_c_passive_external_web"}
        and _action_kind_has_rich_menu(record)
        and record["latest_action_status"] == "verified"
        for record in classified
    )
    summary["rich_menu_present"] = menu_counts.get("present", 0)
    summary["rich_menu_absent_confirmed"] = menu_counts.get("absent_confirmed", 0)
    summary["latest_action_verified_count"] = sum(record["latest_action_status"] == "verified" for record in classified)
    summary["line_reply_count"] = sum(record["action_result"] == "line_reply" for record in classified)
    summary["external_web_count"] = sum(record["action_result"] == "external_web" for record in classified)
    summary["text_trigger_verified_count"] = sum(record["text_trigger_verified"] for record in classified)
    summary["text_trigger_route_verified_count"] = sum(
        record.get("text_trigger_route_verified") is True for record in classified
    )
    summary["active_status_counts"] = {
        key: sum(record["active_status"] == key for record in classified)
        for key in ACTIVE_STATUSES
    }
    for key in ACTIVE_STATUSES:
        summary[key] = summary["active_status_counts"][key]
    summary["pending_natural_message_acceptance_preserved"] = (
        inventory.get("passive_acceptance") == "pending_real_change_acceptance"
    )
    summary["collection_policy_candidates"] = {
        key: sum(record["collection_policy_candidate"] == key for record in classified)
        for key in ("passive_only_candidate", "active_only_candidate", "passive_plus_active_candidate", "unresolved")
    }
    summary["collection_policy_basis"] = {
        "passive_only_candidate": "confirmed no-action Type A or Type C whose external web route is recorded separately from LINE active triggers",
        "active_only_candidate": "verified text-trigger LINE reply without a verified rich-menu action",
        "passive_plus_active_candidate": "verified LINE latest-information reply action; passive delivery remains pending validation",
        "unresolved": "active route or delivery mode lacks sufficient evidence",
    }
    inventory["policy_version"] = 1
    inventory["passive_acceptance"] = "pending_real_change_acceptance"
    inventory["passive_collector_modified"] = False
    inventory["scheduler_modified"] = False
    inventory["slot_repository_modified"] = False
    return inventory


POLICY_ROW_FIELDS = (
    "hall_id",
    "line_source_key",
    "rich_menu_status",
    "latest_action_label",
    "action_result",
    "collection_type",
    "active_method",
    "trigger_text",
    "text_trigger_verified",
    "external_url",
    "evidence_refs",
    "confidence",
    "verification_status",
)
DAILY_POLICY = {
    "type_a_passive": {"passive_scan": True, "active_trigger": False, "external_url_role": None},
    "type_b_passive_plus_active": {"passive_scan": True, "active_trigger": True, "external_url_role": None},
    "type_c_passive_external_web": {"passive_scan": True, "active_trigger": False, "external_url_role": "auxiliary_source"},
    "unresolved": {"passive_scan": True, "active_trigger": False, "external_url_role": None},
}


def build_policy_row(record: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a classified inventory record with its one-time onboarding review.

    A reviewed action only counts when the review saw its result; a missing label or
    an unexecuted tile never becomes Type A. Rich-menu absence alone is a Type A
    candidate, per the onboarding policy.
    """
    review = review or {}
    menu_status = record.get("rich_menu_status", "unknown")
    mapping = review.get("action_mapping") or {}
    mapped_result = mapping.get("action_result") if mapping.get("content_observed") is True else None

    if record.get("collection_type") in {"type_b_passive_plus_active", "type_c_passive_external_web"}:
        collection_type = record["collection_type"]
        action_result = record["action_result"]
    elif mapped_result == "line_reply":
        collection_type, action_result = "type_b_passive_plus_active", "line_reply"
    elif mapped_result == "external_web":
        collection_type, action_result = "type_c_passive_external_web", "external_web"
    elif (
        menu_status == "absent_confirmed"
        or record.get("no_active_action_confirmed") is True
        or review.get("no_collection_action_confirmed") is True
    ):
        collection_type, action_result = "type_a_passive", "not_applicable"
    else:
        collection_type = "unresolved"
        action_result = mapping.get("action_result") or record.get("action_result") or "unknown"

    text_verified = record.get("text_trigger_verified") is True or review.get("text_trigger_verified") is True
    if collection_type == "type_b_passive_plus_active":
        if text_verified or (record.get("active_method") == "text_trigger" and menu_status == "absent_confirmed"):
            active_method = "text_trigger"
        else:
            active_method = "rich_menu"
    elif collection_type == "type_c_passive_external_web":
        active_method = "none"
    elif collection_type == "type_a_passive":
        active_method = "none"
    else:
        active_method = "unknown"

    external_url = mapping.get("external_url") or record.get("external_url")
    label = review.get("latest_action_label", record.get("trigger_text") if collection_type != "unresolved" else None)
    refs = list(dict.fromkeys([*record.get("evidence_refs", []), *review.get("evidence_refs", [])]))

    owner_observed = mapping.get("observed_by") == "owner" or review.get("confirmed_by") == "owner"
    if collection_type in {"type_b_passive_plus_active", "type_c_passive_external_web"}:
        confidence, status = ("medium", "owner_reported_action_result") if owner_observed else ("high", "active_action_verified")
    elif collection_type == "type_a_passive":
        confidence, status = ("medium", "owner_confirmed_no_collection_action") if owner_observed else ("medium", "rich_menu_absent_confirmed")
    elif review.get("menu_visual_review_required"):
        confidence, status = "low", "menu_visual_review_required"
    elif mapping.get("blocked_by"):
        confidence, status = "low", mapping["blocked_by"]
    elif mapping.get("executed"):
        confidence, status = "low", "action_executed_result_unconfirmed"
    elif review.get("menu_review_status") in {"reviewed_no_latest_label", "latest_like_label_not_executed"}:
        confidence, status = "low", (
            "menu_reviewed_no_latest_label"
            if review["menu_review_status"] == "reviewed_no_latest_label"
            else "latest_like_label_not_executed"
        )
    else:
        confidence, status = "low", "insufficient_evidence"

    row = {
        "hall_id": record["hall_id"],
        "line_source_key": record["line_source_key"],
        "store_name": record.get("store_name"),
        "rich_menu_status": menu_status,
        "menu_visual_review_required": bool(review.get("menu_visual_review_required")),
        "latest_action_label": label,
        "action_result": action_result,
        "collection_type": collection_type,
        "active_method": active_method,
        "trigger_text": (review.get("trigger_text") or record.get("trigger_text")) if active_method == "text_trigger" or text_verified else None,
        "text_trigger_verified": text_verified,
        "external_url": external_url if collection_type == "type_c_passive_external_web" else None,
        "evidence_refs": refs,
        "confidence": confidence,
        "verification_status": status,
        "daily_policy": DAILY_POLICY[collection_type],
    }
    if review.get("notes"):
        row["notes"] = review["notes"]
    return row


def onboarding_inventory_record(record: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    """Inventory-shaped record for a newly onboarded store; menu status comes from the review."""
    attempt = next(item for item in record["attempts"] if item.get("result") == "onboarded")
    menu_status = (review or {}).get("rich_menu_status", "not_observed")
    return {
        "hall_id": record["hall_id"],
        "collector_key": record["hall_id"],
        "line_source_key": record["line_source_key"],
        "store_name": record["store_name"],
        "identity_verified": True,
        "rich_menu_observation": {"status": menu_status, "evidence_refs": [attempt["screenshot"], attempt["ui_xml"]]},
        "action_candidates_status": "not_observed",
        "action_execution": {"status": "not_attempted", "result": "unknown", "action_kind": None, "observed_destinations": []},
        "text_trigger_route_status": "not_observed",
        "text_trigger_verified": False,
        "evidence_sources": {"active_evidence_refs": []},
    }


def build_policy_table(inventory: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    reviews = review.get("stores", {})
    unknown = set(reviews) - {record["hall_id"] for record in inventory["records"]}
    if unknown:
        raise ValueError(f"review_for_unknown_hall:{sorted(unknown)}")
    rows = [build_policy_row(record, reviews.get(record["hall_id"])) for record in inventory["records"]]
    counts = Counter(row["collection_type"] for row in rows)
    return {
        "schema_version": 1,
        "policy_id": review.get("policy_id"),
        "source_inventory": review.get("source_inventory"),
        "source_review": review.get("review_id"),
        "scheduler_modified": False,
        "passive_collector_modified": False,
        "daily_policy": {
            "type_a_passive": "passive scan only",
            "type_b_passive_plus_active": "passive scan + scheduled active trigger (text trigger when text_trigger_verified, otherwise the verified rich-menu action)",
            "type_c_passive_external_web": "passive scan only; external_url is an auxiliary source",
            "unresolved": "passive scan only until evidence is sufficient",
        },
        "counts": {key: counts.get(key, 0) for key in ("type_a_passive", "type_b_passive_plus_active", "type_c_passive_external_web", "unresolved")},
        "store_count": len(rows),
        "stores": rows,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Build the permanent per-store collection policy table.")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--onboarding", type=Path, nargs="*", default=[], help="onboarding outputs whose onboarded stores are added")
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    review = json.loads(args.review.read_text(encoding="utf-8"))
    raw_inventory = json.loads(args.inventory.read_text(encoding="utf-8")) if args.inventory else {"records": []}
    for path in args.onboarding:
        for record in json.loads(path.read_text(encoding="utf-8"))["records"]:
            if record.get("result") == "onboarded":
                raw_inventory["records"].append(onboarding_inventory_record(record, review.get("stores", {}).get(record["hall_id"])))
    inventory = classify_inventory(raw_inventory)
    table = build_policy_table(inventory, review)
    args.output.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(table["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
