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

    def test_ui_artifact_is_saved_under_ui_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RawStore(Path(temporary), "2026-09-22", "test_store", "official_line", "passive")
            store.initialize()
            relative = store.save_ui_artifact(b"PNG", "run-1", "reply_screen", ".png")
            self.assertEqual(relative, "ui/run-1_reply_screen.png")
            self.assertEqual((store.root / relative).read_bytes(), b"PNG")

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
