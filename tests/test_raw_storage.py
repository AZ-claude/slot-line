import json
import tempfile
import unittest
from pathlib import Path

from scripts.raw_storage import RawStore


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

    def test_successful_trigger_guard_ignores_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-23", "pia_machida", "official_line", "text_trigger")
            store.initialize()
            failed = store.new_manifest_record("failed", "started", {"type": "text_trigger"})
            failed["status"] = "response_timeout"
            store.persist_manifest(failed)
            self.assertFalse(store.has_successful_trigger("text_trigger", "text_trigger"))

            successful = store.new_manifest_record("success", "started", {"type": "text_trigger"})
            successful["status"] = "success"
            store.persist_manifest(successful)
            self.assertTrue(store.has_successful_trigger("text_trigger", "text_trigger"))

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
