import json
import tempfile
import unittest
from pathlib import Path

from scripts.raw_storage import RawStore, evaluate_trigger_guard
from scripts.run_daily import append_daily_log, determine_overall_status


class RawStoreTest(unittest.TestCase):
    def test_image_and_message_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-22", "test_store", "official_line", "passive")
            store.initialize()

            first = store.root / ".incoming-one.jpg"
            first.write_bytes(b"same-image")
            first_result = store.import_image(first, "one.jpg")

            second = store.root / ".incoming-two.jpg"
            second.write_bytes(b"same-image")
            second_result = store.import_image(second, "two.jpg")

            self.assertEqual(first_result["sha256"], second_result["sha256"])
            self.assertTrue(second_result["deduplicated"])

            message = {
                "message_type": "text",
                "line_display_time": "23:00",
                "text": ["sample"],
                "content_desc": [],
            }
            store.merge_messages([message])
            store.merge_messages([message])
            self.assertEqual(len(json.loads(store.messages_path.read_text(encoding="utf-8"))), 1)

    def test_manifest_upserts_by_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-22", "test_store", "official_line", "passive")
            store.initialize()
            record = store.new_manifest_record("run-1", "started", None)
            store.persist_manifest(record)
            record["status"] = "success"
            store.persist_manifest(record)
            manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]["status"], "success")

    def _trigger_record(
        self,
        store: RawStore,
        run_id: str,
        status: str,
        triggered_at: str | None,
        trigger_type: str = "text_trigger",
    ) -> dict:
        record = store.new_manifest_record(run_id, "started", {"type": trigger_type})
        record["status"] = status
        record["triggered_at"] = triggered_at
        store.persist_manifest(record)
        return record

    def test_trigger_guard_skips_when_same_day_success_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger")
            store.initialize()
            self._trigger_record(store, "success", "success", "2026-09-23T01:00:00+00:00")

            decision = evaluate_trigger_guard(
                store.load_manifest_records(), "text_trigger", "text_trigger"
            )
            self.assertIsNotNone(decision)
            self.assertEqual(decision["status"], "skipped_already_successful")
            self.assertEqual(decision["previous_run_id"], "success")

    def test_trigger_guard_skips_after_timeout_with_triggered_at(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger")
            store.initialize()
            self._trigger_record(store, "timeout", "response_timeout", "2026-09-23T02:00:00+00:00")

            decision = evaluate_trigger_guard(
                store.load_manifest_records(), "text_trigger", "text_trigger"
            )
            self.assertIsNotNone(decision)
            self.assertEqual(decision["status"], "skipped_already_attempted")
            self.assertEqual(decision["previous_run_id"], "timeout")
            self.assertEqual(decision["previous_status"], "response_timeout")
            self.assertEqual(decision["previous_triggered_at"], "2026-09-23T02:00:00+00:00")

    def test_trigger_guard_allows_retry_after_pre_send_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger")
            store.initialize()
            self._trigger_record(store, "failed-before-send", "trigger_failed", None)

            self.assertIsNone(
                evaluate_trigger_guard(store.load_manifest_records(), "text_trigger", "text_trigger")
            )

    def test_trigger_guard_force_allows_resend_after_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger")
            store.initialize()
            self._trigger_record(store, "timeout", "response_timeout", "2026-09-23T03:00:00+00:00")

            self.assertIsNone(
                evaluate_trigger_guard(
                    store.load_manifest_records(), "text_trigger", "text_trigger", force=True
                )
            )

    def test_existing_reply_diagnostic_does_not_count_as_trigger_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger")
            store.initialize()
            self._trigger_record(store, "diagnostic", "success", "2026-09-23T04:00:00+00:00", "existing_reply")

            self.assertIsNone(
                evaluate_trigger_guard(store.load_manifest_records(), "text_trigger", "text_trigger")
            )

    def test_daily_summary_keeps_attempted_skip_as_partial_failure(self) -> None:
        self.assertEqual(
            determine_overall_status(
                "success",
                [
                    {"status": "success"},
                    {"status": "skipped_already_attempted"},
                ],
            ),
            "partial_failure",
        )
        self.assertEqual(
            determine_overall_status(
                "success",
                [
                    {"status": "success"},
                    {"status": "skipped_already_successful"},
                ],
            ),
            "success",
        )

    def test_daily_log_appends_complete_summary_with_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            summary = {
                "started_at": "2026-09-23T00:00:00+00:00",
                "finished_at": "2026-09-23T00:01:00+00:00",
                "status": "partial_failure",
                "adb_health": {"status": "success"},
                "adapters": [
                    {
                        "store_id": "pia_machida",
                        "status": "response_timeout",
                        "message_count": 0,
                        "stored_message_count_total": 0,
                        "image_count": 0,
                        "errors": [{"code": "response_timeout"}],
                        "warnings": [],
                        "run_id": "run-1",
                        "raw_path": "data/raw/2026-09-23/pia_machida",
                    }
                ],
            }
            log_path = append_daily_log(Path(temporary), summary, 1)
            append_daily_log(Path(temporary), summary, 1)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["process_exit_code"], 1)
            self.assertEqual(json.loads(lines[0])["adapters"][0]["run_id"], "run-1")

    def test_ui_artifact_is_saved_under_ui_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-22", "test_store", "official_line", "passive")
            store.initialize()
            relative = store.save_ui_artifact(b"PNG", "run-1", "reply_screen", ".png")
            self.assertEqual(relative, "ui/run-1_reply_screen.png")
            self.assertEqual((store.root / relative).read_bytes(), b"PNG")

    def test_run_message_count_is_separate_from_stored_total(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-22", "test_store", "official_line", "passive")
            store.initialize()
            existing = {"message_type": "text", "line_display_time": "10:00", "text": ["old"]}
            current = {"message_type": "text", "line_display_time": "11:00", "text": ["new"]}
            store.merge_messages([existing])
            current_messages = [current]
            stored_messages = store.merge_messages(current_messages)

            record = store.new_manifest_record("run-counts", "started", {"type": "passive"})
            record["message_count"] = len(current_messages)
            record["stored_message_count_total"] = len(stored_messages)
            store.persist_manifest(record)
            saved = json.loads(store.manifest_path.read_text(encoding="utf-8"))[0]
            self.assertEqual(saved["message_count"], 1)
            self.assertEqual(saved["stored_message_count_total"], 2)

    def test_same_image_at_different_times_is_two_message_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-22", "test_store", "official_line", "text_trigger")
            store.initialize()

            first = {
                "message_type": "image",
                "line_display_time": "12:00",
                "observed_at": "2026-09-22T03:00:00+00:00",
                "sha256": "same-image-sha",
                "image_filename": "images/image_001.jpg",
                "byte_size": 10,
            }
            second = dict(first, line_display_time="13:00", observed_at="2026-09-22T04:00:00+00:00")

            store.merge_messages([first, second])
            messages = json.loads(store.messages_path.read_text(encoding="utf-8"))
            self.assertEqual(len(messages), 2)
            self.assertEqual({message["line_display_time"] for message in messages}, {"12:00", "13:00"})

            store.merge_messages([first])
            messages = json.loads(store.messages_path.read_text(encoding="utf-8"))
            self.assertEqual(len(messages), 2)


if __name__ == "__main__":
    unittest.main()
