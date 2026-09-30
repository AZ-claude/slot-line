import importlib.util
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


@unittest.skipUnless(importlib.util.find_spec("PIL") and importlib.util.find_spec("numpy"), "needs Pillow and numpy (Windows)")
class ReplyDetectionTests(unittest.TestCase):
    def _image(self, own_rows=None, store_rows=None):
        import tempfile
        from pathlib import Path
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (640, 700), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        if own_rows:
            draw.rectangle((500, own_rows[0], 620, own_rows[1]), fill=(195, 246, 157))
        if store_rows:
            draw.rectangle((12, store_rows[0], 400, store_rows[1]), fill=(40, 40, 40))
        path = Path(tempfile.mkdtemp()) / "bottom.png"
        image.save(path)
        return path

    def test_store_post_below_own_message_is_a_reply(self):
        from scripts.line_pc_collect import detect_store_reply

        self.assertTrue(detect_store_reply(self._image(own_rows=(300, 340), store_rows=(360, 600)))["reply"])

    def test_nothing_below_own_message_is_not_a_reply(self):
        from scripts.line_pc_collect import detect_store_reply

        result = detect_store_reply(self._image(own_rows=(620, 670), store_rows=(100, 500)))
        self.assertFalse(result["reply"])


class OcrHelpersTests(unittest.TestCase):
    def test_read_receipts_times_and_dates_are_not_replies(self):
        for noise in ("既読", "既読 2", "午後 5:26", "今日", "昨日", "9月30日(水)", "〒930", "午後932", "保存"):
            self.assertFalse(is_message_line(noise), noise)
        self.assertTrue(is_message_line("新台入替のお知らせ"))

    def test_header_similarity_tolerates_ocr_noise(self):
        self.assertGreaterEqual(similarity("スクランプル田谷店", "スクランブル田谷店"), 0.6)
        self.assertLess(similarity("Eita", "スクランブル田谷店"), 0.6)
        self.assertGreaterEqual(similarity("中山LJN0", "中山ＵＮＯ"), 0.6)
        self.assertLess(similarity("中山LJN0", "中山競馬"), 0.6)


if __name__ == "__main__":
    unittest.main()
