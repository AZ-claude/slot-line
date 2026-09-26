import unittest

from scripts.active_acquisition_policy import (
    build_policy_row,
    build_policy_table,
    classify_inventory,
    classify_inventory_record,
)


def base_record(hall_id="hall-a", menu_status="present"):
    return {
        "hall_id": hall_id,
        "collector_key": hall_id,
        "line_source_key": "@line-a",
        "store_name": "Fixture store",
        "identity_verified": True,
        "rich_menu_observation": {"status": menu_status, "evidence_refs": []},
        "action_candidates_status": "not_observed",
        "action_candidates": None,
        "action_execution": {
            "status": "not_attempted_in_collector_acceptance",
            "result": "unknown",
            "action_kind": None,
            "trigger_value": None,
            "observed_destinations": [],
        },
        "text_trigger_route_status": "not_observed",
        "text_trigger_route_verified": False,
        "text_trigger_verified": False,
        "text_trigger_equivalence_status": "not_verified",
        "evidence_sources": {"active_evidence_refs": []},
    }


class ActiveAcquisitionPolicyTests(unittest.TestCase):
    def test_absent_menu_alone_does_not_confirm_no_active_action(self):
        record = classify_inventory_record(base_record(menu_status="absent_confirmed"))
        self.assertEqual(record["collection_type"], "unresolved")
        self.assertEqual(record["active_status"], "active_not_observed")

    def test_type_a_requires_explicit_no_active_action_confirmation(self):
        fixture = base_record(menu_status="absent_confirmed")
        fixture["no_active_action_confirmed"] = True
        record = classify_inventory_record(fixture)
        self.assertEqual(record["collection_type"], "type_a_passive")
        self.assertEqual(record["active_method"], "none")
        self.assertTrue(record["passive_collection_required"])
        self.assertFalse(record["active_collection_required"])

    def test_present_menu_with_verified_line_reply_is_type_b_rich_menu(self):
        record = base_record()
        record["rich_menu_observation"]["visible_labels"] = ["最新情報"]
        record["action_candidates"] = [
            {
                "visible_label": "最新情報",
                "action_category": "latest_information",
                "execution_verified": True,
                "destination_verified": True,
                "execution_result": "line_reply",
                "evidence_refs": ["raw/menu.png"],
            }
        ]
        record = classify_inventory_record(record)
        self.assertEqual(record["collection_type"], "type_b_passive_plus_active")
        self.assertEqual(record["action_result"], "line_reply")
        self.assertEqual(record["active_method"], "rich_menu")
        self.assertEqual(record["evidence_refs"], ["raw/menu.png"])

    def test_human_reported_menu_label_stays_a_candidate_without_collector_execution(self):
        record = base_record()
        record["rich_menu_observation"]["action_candidates"] = [
            {
                "visible_label": "最新情報",
                "action_category": "latest_information",
                "collector_observed": False,
                "execution_verified": False,
                "destination_verified": False,
            }
        ]
        classified = classify_inventory_record(record)
        self.assertEqual(classified["latest_action_status"], "candidate")
        self.assertEqual(classified["collection_type"], "unresolved")
        self.assertEqual(classified["active_status"], "active_candidate")

    def test_type_b_prefers_only_verified_text_trigger(self):
        record = base_record()
        record["action_execution"] = {
            "status": "previously_executed_and_verified",
            "result": "line_reply",
            "action_kind": ["rich_menu", "text_trigger"],
            "trigger_value": ["最新情報"],
            "observed_destinations": [],
        }
        record["text_trigger_verified"] = True
        classified = classify_inventory_record(record)
        self.assertEqual(classified["collection_type"], "type_b_passive_plus_active")
        self.assertEqual(classified["active_method"], "text_trigger")
        self.assertTrue(classified["text_trigger_verified"])
        self.assertEqual(classified["trigger_text"], "最新情報")

    def test_verified_text_only_line_reply_is_an_active_only_candidate(self):
        record = base_record(menu_status="absent_confirmed")
        record["action_execution"] = {
            "status": "previously_executed_and_verified",
            "result": "line_reply",
            "action_kind": ["text_trigger"],
            "trigger_value": ["最新情報"],
            "observed_destinations": [],
        }
        record["text_trigger_route_verified"] = True
        record["text_trigger_verified"] = True
        classified = classify_inventory_record(record)
        self.assertEqual(classified["collection_type"], "type_b_passive_plus_active")
        self.assertEqual(classified["active_method"], "text_trigger")
        self.assertEqual(classified["collection_policy_candidate"], "active_only_candidate")

    def test_captured_text_trigger_without_semantic_result_stays_unresolved(self):
        record = base_record()
        record["text_trigger_route_status"] = "capture_succeeded_result_unclassified"
        record["action_execution"] = {
            "status": "attempted_response_timeout",
            "result": "unknown",
            "action_kind": "text_trigger_via_oa_message_url",
            "trigger_value": "最新情報",
            "observed_destinations": [],
        }
        record["collector_capture_acceptance"] = {
            "status": "passed",
            "action_kind": "text_trigger",
            "action_result": "unknown",
            "raw_persisted": True,
        }
        classified = classify_inventory_record(record)
        self.assertEqual(classified["collection_type"], "unresolved")
        self.assertEqual(classified["active_status"], "active_candidate")
        self.assertEqual(classified["active_method"], "text_trigger")
        self.assertEqual(classified["action_result"], "unknown")
        self.assertTrue(classified["text_trigger_candidate"])

    def test_type_c_keeps_passive_collection_and_records_external_url(self):
        record = base_record()
        record["action_execution"] = {
            "status": "previously_executed_and_verified",
            "result": "external_web",
            "action_kind": ["rich_menu"],
            "observed_destinations": [{"url": "https://example.test/latest"}],
        }
        classified = classify_inventory_record(record)
        self.assertEqual(classified["collection_type"], "type_c_passive_external_web")
        self.assertEqual(classified["active_method"], "rich_menu")
        self.assertEqual(classified["external_url"], "https://example.test/latest")
        self.assertTrue(classified["passive_collection_required"])
        self.assertFalse(classified["active_collection_required"])

    def test_unobserved_or_unknown_menu_never_becomes_type_a(self):
        for menu_status in ("not_observed", "unknown", "present"):
            classified = classify_inventory_record(base_record(menu_status=menu_status))
            self.assertEqual(classified["collection_type"], "unresolved")
            self.assertEqual(classified["active_method"], "unknown")

    def test_inventory_summary_preserves_pending_passive_acceptance(self):
        inventory = {
            "passive_acceptance": "pending_real_change_acceptance",
            "records": [
                {**base_record(menu_status="absent_confirmed"), "no_active_action_confirmed": True},
                base_record(hall_id="hall-b"),
            ],
        }
        result = classify_inventory(inventory)
        self.assertEqual(result["summary"]["collection_type_counts"]["type_a_passive"], 1)
        self.assertEqual(result["summary"]["collection_type_counts"]["unresolved"], 1)
        self.assertEqual(result["summary"]["passive_collection_target_count"], 2)
        self.assertEqual(result["summary"]["active_trigger_target_count"], 0)
        self.assertEqual(result["passive_acceptance"], "pending_real_change_acceptance")
        self.assertTrue(result["summary"]["pending_natural_message_acceptance_preserved"])


class PolicyTableTests(unittest.TestCase):
    def test_absent_confirmed_menu_is_type_a_candidate_in_policy_table(self):
        row = build_policy_row(classify_inventory_record(base_record(menu_status="absent_confirmed")), None)
        self.assertEqual(row["collection_type"], "type_a_passive")
        self.assertEqual(row["active_method"], "none")
        self.assertEqual(row["verification_status"], "rich_menu_absent_confirmed")
        self.assertEqual(row["daily_policy"], {"passive_scan": True, "active_trigger": False, "external_url_role": None})

    def test_reviewed_menu_without_latest_label_stays_unresolved(self):
        review = {"menu_review_status": "reviewed_no_latest_label", "evidence_refs": ["snap.png"]}
        row = build_policy_row(classify_inventory_record(base_record()), review)
        self.assertEqual(row["collection_type"], "unresolved")
        self.assertEqual(row["verification_status"], "menu_reviewed_no_latest_label")
        self.assertIn("snap.png", row["evidence_refs"])

    def test_observed_line_reply_mapping_promotes_to_type_b_rich_menu(self):
        review = {
            "latest_action_label": "最新情報",
            "action_mapping": {"executed": True, "action_result": "line_reply", "content_observed": True},
        }
        row = build_policy_row(classify_inventory_record(base_record()), review)
        self.assertEqual(row["collection_type"], "type_b_passive_plus_active")
        self.assertEqual(row["active_method"], "rich_menu")
        self.assertFalse(row["text_trigger_verified"])
        self.assertTrue(row["daily_policy"]["active_trigger"])

    def test_external_web_mapping_is_type_c_with_auxiliary_url(self):
        review = {
            "latest_action_label": "最新情報",
            "action_mapping": {
                "executed": True,
                "action_result": "external_web",
                "content_observed": True,
                "external_url": "https://example.test/hall",
            },
        }
        row = build_policy_row(classify_inventory_record(base_record()), review)
        self.assertEqual(row["collection_type"], "type_c_passive_external_web")
        self.assertEqual(row["external_url"], "https://example.test/hall")
        self.assertEqual(row["daily_policy"]["external_url_role"], "auxiliary_source")
        self.assertFalse(row["daily_policy"]["active_trigger"])

    def test_executed_action_without_observed_result_stays_unresolved(self):
        for mapping, status in (
            ({"executed": True, "action_result": "unknown", "content_observed": False}, "action_executed_result_unconfirmed"),
            (
                {"executed": True, "action_result": "unknown", "content_observed": False, "blocked_by": "liff_consent_required"},
                "liff_consent_required",
            ),
            ({"executed": True, "action_result": "line_reply", "content_observed": False}, "action_executed_result_unconfirmed"),
        ):
            row = build_policy_row(classify_inventory_record(base_record()), {"action_mapping": mapping})
            self.assertEqual(row["collection_type"], "unresolved")
            self.assertEqual(row["verification_status"], status)

    def test_owner_confirmations_are_marked_separately_from_collector_evidence(self):
        type_a = build_policy_row(
            classify_inventory_record(base_record()),
            {"no_collection_action_confirmed": True, "confirmed_by": "owner"},
        )
        self.assertEqual(type_a["collection_type"], "type_a_passive")
        self.assertEqual(type_a["verification_status"], "owner_confirmed_no_collection_action")
        type_c = build_policy_row(
            classify_inventory_record(base_record()),
            {"action_mapping": {"executed": True, "action_result": "external_web", "content_observed": True, "observed_by": "owner"}},
        )
        self.assertEqual(type_c["collection_type"], "type_c_passive_external_web")
        self.assertEqual(type_c["verification_status"], "owner_reported_action_result")
        self.assertEqual(type_c["confidence"], "medium")

    def test_policy_table_rejects_reviews_for_unknown_halls(self):
        inventory = classify_inventory({"records": [base_record()]})
        with self.assertRaises(ValueError):
            build_policy_table(inventory, {"stores": {"missing-hall": {}}})


if __name__ == "__main__":
    unittest.main()
