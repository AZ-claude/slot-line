import unittest

from scripts.build_line_collection_plan import build_plan
from scripts.line_pc_collect import is_message_line, similarity


def target(hall_id, name="店A"):
    return {"hall_id": hall_id, "line_source_key": "@x", "store_name": name, "chat_header_name": name, "active": True}


class CollectionPlanTests(unittest.TestCase):
    def test_trigger_modes_follow_policy_and_checks(self):
        policy = {
            "b-verified": {"collection_type": "type_b_passive_plus_active", "active_method": "text_trigger", "text_trigger_verified": True},
            "b-menu": {"collection_type": "type_b_passive_plus_active", "active_method": "rich_menu", "text_trigger_verified": False},
            "b-checked-yes": {"collection_type": "type_b_passive_plus_active", "active_method": "rich_menu"},
            "b-checked-no": {"collection_type": "type_b_passive_plus_active", "active_method": "rich_menu"},
            "c": {"collection_type": "type_c_passive_external_web", "active_method": "none"},
        }
        checks = {"b-checked-yes": {"result": "reply"}, "b-checked-no": {"result": "no_reply"}}
        plan = {row["hall_id"]: row for row in build_plan([target(h) for h in policy] + [target("new")], policy, checks)}
        self.assertEqual(plan["b-verified"]["text_trigger"], "daily")
        self.assertEqual(plan["b-menu"]["text_trigger"], "verify_once")
        self.assertEqual(plan["b-checked-yes"]["text_trigger"], "daily")
        self.assertEqual(plan["b-checked-no"]["text_trigger"], "off")
        self.assertEqual(plan["c"]["text_trigger"], "off")
        self.assertEqual(plan["new"]["collection_type"], "unresolved")
        self.assertIsNone(plan["c"]["trigger_text"])

    def test_inactive_targets_are_left_out(self):
        self.assertEqual(build_plan([target("a") | {"active": False}], {}, {}), [])


class OcrHelpersTests(unittest.TestCase):
    def test_read_receipts_times_and_dates_are_not_replies(self):
        for noise in ("既読", "既読 2", "午後 5:26", "今日", "昨日", "9月30日(水)"):
            self.assertFalse(is_message_line(noise), noise)
        self.assertTrue(is_message_line("新台入替のお知らせ"))

    def test_header_similarity_tolerates_ocr_noise(self):
        self.assertGreaterEqual(similarity("スクランプル田谷店", "スクランブル田谷店"), 0.6)
        self.assertLess(similarity("Eita", "スクランブル田谷店"), 0.6)


if __name__ == "__main__":
    unittest.main()
