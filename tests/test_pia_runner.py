import unittest
from collections import Counter
from unittest.mock import patch

from scripts.run_pia_machida import (
    has_reply_progress,
    incoming_rows_since_baseline,
    parse_args,
    settled_row_signature,
)


class PiaRunnerTests(unittest.TestCase):
    def test_loader_and_rendered_rich_card_have_different_settle_signatures(self):
        loader = {
            "kind": "rich_card",
            "incoming": True,
            "timestamp": None,
            "text": [],
            "content_desc": [],
            "resource_ids": ["jp.naver.line.android:id/chat_ui_row_progress"],
            "bounds": "[0,163][720,869]",
            "image_bounds": None,
        }
        rendered = {
            **loader,
            "timestamp": "21:43",
            "resource_ids": ["jp.naver.line.android:id/chat_ui_row_receive_rich_container"],
            "bounds": "[0,300][720,1347]",
            "image_bounds": "[9,309][711,1302]",
        }
        self.assertNotEqual(settled_row_signature(loader), settled_row_signature(rendered))
        self.assertTrue(has_reply_progress([loader]))
        self.assertFalse(has_reply_progress([rendered]))

    def test_settle_input_keeps_duplicate_raw_rows(self):
        row = {
            "kind": "rich_card",
            "incoming": True,
            "timestamp": "21:43",
            "text": [],
            "content_desc": [],
            "resource_ids": ["jp.naver.line.android:id/chat_ui_row_receive_rich_container"],
            "bounds": "[0,300][720,1347]",
            "image_bounds": "[9,309][711,1302]",
        }
        result = incoming_rows_since_baseline([row, dict(row)], Counter())
        self.assertEqual(len(result), 2)

    def test_windows_uia_verify_only_is_explicit_and_non_sending_mode(self):
        with patch(
            "sys.argv",
            [
                "run_pia_machida.py",
                "--trigger-mode",
                "windows-uia",
                "--windows-uia-verify-only",
            ],
        ):
            args = parse_args()
        self.assertTrue(args.windows_uia_verify_only)
        self.assertEqual(args.trigger_mode, "windows-uia")


if __name__ == "__main__":
    unittest.main()
