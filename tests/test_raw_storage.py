import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.raw_storage import RawStorageError, RawStore, evaluate_trigger_cooldown
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

    def test_message_source_attribution_is_preserved_and_part_of_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            message = {"message_type": "text", "line_display_time": "23:00", "text": ["sample"]}
            source_a = RawStore(root, "2026-09-22", "hall-a", "official_line", "passive", "@line-a")
            source_a.initialize()
            source_a.merge_messages([message])
            source_b = RawStore(root, "2026-09-22", "hall-a", "official_line", "passive", "@line-b")
            source_b.initialize()
            source_b.merge_messages([message])
            messages = json.loads(source_b.messages_path.read_text(encoding="utf-8"))
            self.assertEqual({item["line_source_key"] for item in messages}, {"@line-a", "@line-b"})
            with self.assertRaises(RawStorageError):
                source_a.merge_messages([{**message, "line_source_key": "@line-b"}])

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
        record = store.new_manifest_record(
            run_id,
            "started",
            {"type": trigger_type, "text": "最新情報", "action_id": "latest_information"},
        )
        record.update({"hall_id": "hall-test", "line_source_key": "@line-test"})
        record["status"] = status
        record["triggered_at"] = triggered_at
        store.persist_manifest(record)
        return record

    def _cooldown(self, records, now, *, collector_key="pia_machida", hall_id="hall-test", line_source_key="@line-test"):
        return evaluate_trigger_cooldown(
            records,
            hall_id=hall_id,
            collector_key=collector_key,
            line_source_key=line_source_key,
            trigger_key="latest_information",
            trigger_text="最新情報",
            now=now,
        )

    def test_cooldown_skips_an_identical_action_inside_ten_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger", "@line-test")
            store.initialize()
            self._trigger_record(store, "success", "success", "2026-09-23T01:00:00+00:00")
            decision = self._cooldown(
                store.load_manifest_records(), datetime.fromisoformat("2026-09-23T01:05:00+00:00")
            )
            self.assertIsNotNone(decision)
            self.assertEqual(decision["status"], "skipped_cooldown")
            self.assertEqual(decision["cooldown_remaining_seconds"], 300)
            self.assertEqual(decision["previous_run_id"], "success")

    def test_cooldown_expires_after_ten_minutes_across_date_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-24", "pia_machida", "official_line", "text_trigger", "@line-test")
            store.initialize()
            yesterday = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger", "@line-test")
            yesterday.initialize()
            self._trigger_record(yesterday, "timeout", "response_timeout", "2026-09-23T23:58:00+00:00")
            self.assertIsNone(
                self._cooldown(
                    store.load_recent_manifest_records(),
                    datetime.fromisoformat("2026-09-24T00:08:01+00:00"),
                )
            )

    def test_cooldown_allows_retry_after_expiry_and_pre_send_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger", "@line-test")
            store.initialize()
            self._trigger_record(store, "failed-before-send", "trigger_failed", None)
            self.assertIsNone(
                self._cooldown(store.load_manifest_records(), datetime.fromisoformat("2026-09-23T04:00:00+00:00"))
            )

    def test_exactly_ten_minutes_remains_inside_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger", "@line-test")
            store.initialize()
            self._trigger_record(store, "run", "response_timeout", "2026-09-23T03:00:00+00:00")
            decision = self._cooldown(
                store.load_manifest_records(), datetime.fromisoformat("2026-09-23T03:10:00+00:00")
            )
            self.assertEqual(decision["status"], "skipped_cooldown")

    def test_cooldown_is_scoped_to_hall_source_and_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger", "@line-test")
            store.initialize()
            self._trigger_record(store, "timeout", "response_timeout", "2026-09-23T03:00:00+00:00")
            self.assertIsNone(
                self._cooldown(
                    store.load_manifest_records(),
                    datetime.fromisoformat("2026-09-23T03:01:00+00:00"),
                    hall_id="other-hall",
                )
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
        self.assertEqual(
            determine_overall_status("success", [{"status": "skipped_cooldown"}]),
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
