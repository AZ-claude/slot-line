import json
import tempfile
import unittest
from pathlib import Path

from scripts.line_daily import (
    LineDailyValidationError,
    convert_raw_directory,
    make_not_checked,
    validate_observation,
    write_observation,
)


class LineDailyTests(unittest.TestCase):
    def write_raw(self, root: Path, records, messages=None, store_id="pia_machida", date_text="2026-09-23") -> Path:
        raw_dir = root / "data" / "raw" / date_text / store_id
        raw_dir.mkdir(parents=True)
        (raw_dir / "manifest.json").write_text(json.dumps(records), encoding="utf-8")
        if messages is not None:
            (raw_dir / "messages.json").write_text(json.dumps(messages), encoding="utf-8")
        return raw_dir

    def record(self, run_id, status, *, triggered_at=None, message_types=None, message_times=None, error_code=None):
        return {
            "store_id": "pia_machida",
            "source": "official_line",
            "adapter_type": "text_trigger",
            "run_id": run_id,
            "started_at": f"2026-09-23T12:00:{run_id[-2:]}+00:00",
            "finished_at": f"2026-09-23T12:01:{run_id[-2:]}+00:00",
            "trigger_text": "最新情報",
            "triggered_at": triggered_at,
            "status": status,
            "error": {"code": error_code} if error_code else None,
            "message_types": message_types or [],
            "message_times": message_times or [],
        }

    def test_passive_received(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [{
                    **self.record("passive-01", "success"),
                    "adapter_type": "passive",
                    "message_types": ["rich_card"],
                    "message_times": ["21:05"],
                }],
                [{"message_type": "rich_card", "line_display_time": "21:05"}],
                store_id="m_and_m_mizoguchi",
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["collection"]["status"], "success")
            self.assertEqual(result["line_update"], "present")
            self.assertEqual(result["messages"]["count"], 1)
            self.assertFalse(result["trigger"]["required"])

    def test_passive_no_message_is_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(root, [{**self.record("passive-02", "success"), "adapter_type": "passive"}], [])
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["line_update"], "absent")
            self.assertEqual(result["summary"]["status"], "not_applicable")

    def test_pia_success_rich_card(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("pia-01", "success", triggered_at="2026-09-23T12:00:01+00:00", message_types=["rich_card"], message_times=["21:05"])],
                [{"message_id": "message-1", "message_type": "rich_card", "line_display_time": "21:05"}],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["collection"]["status"], "success")
            self.assertEqual(result["line_update"], "present")
            self.assertEqual(result["trigger"]["result"], "sent")
            self.assertEqual(result["raw_refs"]["run_ids"], ["pia-01"])

    def test_pia_timeout_is_unknown_not_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("pia-02", "response_timeout", triggered_at="2026-09-23T12:00:01+00:00", error_code="response_timeout")],
                [],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["collection"]["status"], "failed")
            self.assertEqual(result["collection"]["failure_code"], "response_timeout")
            self.assertEqual(result["line_update"], "unknown")

    def test_skipped_attempted_is_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [{**self.record("pia-03", "skipped_already_attempted"), "previous_status": "response_timeout"}],
                [],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["collection"]["status"], "partial")
            self.assertEqual(result["collection"]["failure_code"], "response_timeout")
            self.assertEqual(result["line_update"], "unknown")

    def test_pia_success_wins_over_timeout_and_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = [
                self.record("pia-01", "success", triggered_at="2026-09-23T12:00:01+00:00", message_types=["rich_card"], message_times=["21:05"]),
                self.record("pia-02", "response_timeout", triggered_at="2026-09-23T13:00:01+00:00", error_code="response_timeout"),
                self.record("pia-03", "skipped_already_successful"),
                {**self.record("pia-04", "skipped_already_attempted"), "previous_status": "response_timeout"},
            ]
            raw = self.write_raw(root, records, [{"message_id": "message-1", "message_type": "rich_card", "line_display_time": "21:05"}])
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["collection"]["status"], "success")
            self.assertEqual(result["line_update"], "present")
            self.assertEqual(result["collection"]["failure_code"], None)
            self.assertEqual(result["trigger"]["result"], "sent")
            self.assertEqual(result["raw_refs"]["run_ids"], ["pia-01", "pia-02", "pia-03", "pia-04"])

    def test_not_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = make_not_checked("store-1", "2026-09-23", repo_root=Path(temporary))
            self.assertEqual(result["collection"], {"status": "not_checked", "checked_at": None, "failure_code": None})
            self.assertEqual(result["line_update"], "unknown")
            validate_observation(result, known_store_ids={"store-1"})

    def test_summary_statuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = make_not_checked("store-1", "2026-09-23", repo_root=root)
            self.assertEqual(pending["summary"]["status"], "pending")
            generated = json.loads(json.dumps(pending))
            generated["summary"] = {
                "status": "generated",
                "text": "最新情報あり",
                "generated_at": "2026-09-23T12:00:00+09:00",
                "generator": "test-generator-v1",
            }
            validate_observation(generated, known_store_ids={"store-1"})
            not_applicable = json.loads(json.dumps(pending))
            not_applicable["collection"]["status"] = "success"
            not_applicable["line_update"] = "absent"
            not_applicable["summary"]["status"] = "not_applicable"
            validate_observation(not_applicable, known_store_ids={"store-1"})
            failed = json.loads(json.dumps(pending))
            failed["summary"]["status"] = "failed"
            validate_observation(failed, known_store_ids={"store-1"})

    def test_unknown_store_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = make_not_checked("unknown-store", "2026-09-23", repo_root=Path(temporary))
            with self.assertRaises(LineDailyValidationError):
                validate_observation(value, known_store_ids={"known-store"})

    def test_schema_output_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = make_not_checked("known-store", "2026-09-23", repo_root=root)
            output = root / "observation.json"
            write_observation(value, output, known_store_ids={"known-store"})
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), value)

    def test_existing_pia_raw_is_reproducible(self):
        repo_root = Path(__file__).resolve().parents[1]
        raw_dir = repo_root / "data" / "raw" / "2026-09-21" / "pia_machida"
        first = convert_raw_directory(raw_dir, repo_root=repo_root)
        second = convert_raw_directory(raw_dir, repo_root=repo_root)
        self.assertEqual(first, second)
        self.assertEqual(first["collection"]["status"], "success")
        self.assertEqual(first["line_update"], "present")
        self.assertEqual(first["messages"]["types"], ["image", "rich_card"])


if __name__ == "__main__":
    unittest.main()
