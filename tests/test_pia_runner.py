import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from scripts.raw_storage import RawStore
from scripts.run_pia_machida import (
    AndroidContext,
    active_failure_status,
    is_external_web,
    loading_present,
    main,
    parse_args,
    save_post_action_capture,
)


class PiaRunnerTests(unittest.TestCase):
    def test_loading_detection_is_limited_to_accessibility_evidence(self):
        self.assertTrue(loading_present(ElementTree.fromstring('<node resource-id="line:id/progress"/>')))
        self.assertTrue(loading_present(ElementTree.fromstring('<node text="読み込み中"/>')))
        self.assertFalse(loading_present(ElementTree.fromstring('<node text="PIA綱島"/>')))

    def test_post_action_wait_and_loading_settle_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-26", "pia-test", "official_line", "text_trigger")
            store.initialize()
            loading = ElementTree.fromstring('<hierarchy><node resource-id="line:id/progress"/></hierarchy>')
            settled = ElementTree.fromstring('<hierarchy><node text="最新情報"/></hierarchy>')
            with patch("scripts.run_pia_machida.dump_ui", side_effect=[(loading, b"<hierarchy/>")] * 1 + [(settled, b"<hierarchy/>")] * 2), patch(
                "scripts.run_pia_machida.adb_binary_run", return_value=b"\x89PNG\r\n\x1a\nraw"
            ), patch("scripts.run_pia_machida.time.sleep") as sleep:
                root, refs, _ = save_post_action_capture(AndroidContext("adb", "device"), store, "run-1", 5)
            self.assertEqual(root, settled)
            self.assertEqual(sleep.call_args_list[0].args, (5,))
            self.assertEqual(sleep.call_args_list[1].args, (3.0,))
            self.assertEqual(len(refs), 2)
            self.assertTrue((store.root / refs[0]).is_file())
            self.assertTrue((store.root / refs[1]).is_file())

    def test_cli_has_no_force_bypass_and_wait_is_capped_at_ten_seconds(self):
        with patch("sys.argv", ["run_pia_machida.py"]):
            self.assertEqual(parse_args().post_action_wait, 5)
        with patch("sys.argv", ["run_pia_machida.py", "--post-action-wait", "10"]):
            self.assertEqual(parse_args().post_action_wait, 10)
        with patch("sys.argv", ["run_pia_machida.py", "--post-action-wait", "11"]):
            with self.assertRaises(SystemExit):
                parse_args()
        with patch("sys.argv", ["run_pia_machida.py", "--force-trigger"]):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_failures_map_to_the_small_active_status_vocabulary(self):
        self.assertEqual(active_failure_status("target_not_verified", False), "target_not_verified")
        self.assertEqual(active_failure_status("action_not_observed", False), "action_not_observed")
        self.assertEqual(active_failure_status("trigger_failed", False), "action_execution_failed")
        self.assertEqual(active_failure_status("extraction_failed", True), "capture_failed")
        self.assertEqual(active_failure_status("android_unreachable", False), "unknown")

    def test_http_activity_is_recorded_as_external_web(self):
        self.assertTrue(is_external_web("com.android.chrome/org.chromium.Main", None))
        self.assertTrue(is_external_web("some.app/.Activity", "https://example.test/path"))
        self.assertFalse(is_external_web("jp.naver.line.android/.Main", None))

    def test_main_stores_capture_success_without_interpreting_reply(self):
        root = ElementTree.fromstring(
            '<hierarchy>'
            '<node resource-id="jp.naver.line.android:id/header_title" text="PIA町田"/>'
            '<node resource-id="jp.naver.line.android:id/chat_ui_message_edit" text="最新情報"/>'
            '</hierarchy>'
        )
        with tempfile.TemporaryDirectory() as temporary:
            argv = ["run_pia_machida.py", "--repo-root", temporary, "--hall-id", "hall-test"]
            output = io.StringIO()
            with patch("sys.argv", argv), patch("scripts.run_pia_machida.discover_android", return_value=AndroidContext("adb", "device")), patch(
                "scripts.run_pia_machida.open_target_via_url", return_value=root
            ), patch("scripts.run_pia_machida.dump_ui", return_value=(root, ElementTree.tostring(root))), patch(
                "scripts.run_pia_machida.adb_binary_run", return_value=b"\x89PNG\r\n\x1a\nraw"
            ), patch("scripts.run_pia_machida.send_prefilled_trigger_android", return_value="2026-09-26T01:00:00+00:00") as send, patch(
                "scripts.run_pia_machida.activity_snapshot", return_value=("jp.naver.line.android/.Chat", None)
            ), patch("scripts.run_pia_machida.time.sleep"), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)
            send.assert_called_once()
            record = json.loads(output.getvalue())
            self.assertEqual(record["hall_id"], "hall-test")
            self.assertTrue(record["target_verified"])
            self.assertTrue(record["action_executed"])
            self.assertTrue(record["pre_action_capture"])
            self.assertTrue(record["post_action_capture"])
            self.assertTrue(record["raw_persisted"])
            self.assertEqual(record["active_status"], "captured")
            self.assertEqual(record["semantic_interpretation"], "deferred")
            self.assertEqual(record["message_count"], 0)
            raw = Path(temporary) / "data" / "raw" / datetime.now().strftime("%Y-%m-%d") / "pia_machida"
            self.assertEqual(len(list((raw / "ui").glob("*_pre_action.xml"))), 1)
            self.assertEqual(len(list((raw / "ui").glob("*_pre_action.png"))), 1)
            self.assertEqual(len(list((raw / "ui").glob("*_post_action.xml"))), 1)
            self.assertEqual(len(list((raw / "ui").glob("*_post_action.png"))), 1)


if __name__ == "__main__":
    unittest.main()
