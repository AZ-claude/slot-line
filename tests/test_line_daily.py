import json
import tempfile
import unittest
from pathlib import Path

from scripts.line_daily import (
    LineDailyIdentityError,
    LineDailyValidationError,
    convert_raw_directory,
    convert_raw_directory_all,
    make_not_checked,
    observation_filename,
    validate_observation,
    write_observation,
)


class LineDailyTests(unittest.TestCase):
    def write_raw(
        self,
        root: Path,
        records,
        messages=None,
        collector_key="pia_machida",
        date_text="2026-09-23",
    ) -> Path:
        raw_dir = root / "data" / "raw" / date_text / collector_key
        raw_dir.mkdir(parents=True)
        (raw_dir / "manifest.json").write_text(json.dumps(records), encoding="utf-8")
        if messages is not None:
            (raw_dir / "messages.json").write_text(json.dumps(messages), encoding="utf-8")
        return raw_dir

    def record(
        self,
        run_id,
        status,
        *,
        hall_id="hall-a",
        line_source_key="@line-a",
        adapter_type="text_trigger",
        triggered_at=None,
        message_types=None,
        message_times=None,
        error_code=None,
    ):
        record = {
            "store_id": "pia_machida",
            "source": "official_line",
            "adapter_type": adapter_type,
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
        if hall_id is not None:
            record["hall_id"] = hall_id
        if line_source_key is not None:
            record["line_source_key"] = line_source_key
        return record

    def test_hall_id_is_required_and_store_id_is_not_a_normalized_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = make_not_checked(
                "hall-a",
                "2026-09-23",
                repo_root=root,
                line_source_key="@line-a",
            )
            without_hall = json.loads(json.dumps(value))
            without_hall.pop("hall_id")
            with self.assertRaises(LineDailyValidationError):
                validate_observation(without_hall)
            with_store_id = json.loads(json.dumps(value))
            with_store_id["store_id"] = "hall-a"
            with self.assertRaises(LineDailyValidationError):
                validate_observation(with_store_id)

    def test_unknown_hall_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = make_not_checked(
                "unknown-hall",
                "2026-09-23",
                repo_root=Path(temporary),
                line_source_key="@line-a",
            )
            with self.assertRaises(LineDailyValidationError):
                validate_observation(value, known_hall_ids={"known-hall"})

    def test_collector_key_alone_cannot_create_normalized_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("pia-01", "success", hall_id=None, line_source_key="@line-a")],
            )
            with self.assertRaises(LineDailyIdentityError):
                convert_raw_directory(raw, repo_root=root)

    def test_one_hall_one_line_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("pia-01", "success", triggered_at="2026-09-23T12:00:01+00:00")],
                [{"message_id": "message-1", "message_type": "rich_card", "line_display_time": "21:05"}],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["hall_id"], "hall-a")
            self.assertEqual(result["collector_key"], "pia_machida")
            self.assertEqual(result["line_source_key"], "@line-a")

    def test_single_digit_raw_display_hour_is_normalized_to_schema_hh_mm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("pia-01", "success")],
                [{"message_type": "rich_card", "line_display_time": "0:40"}],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["messages"]["first_display_time"], "00:40")
            validate_observation(result)

    def test_one_hall_multiple_line_sources_are_not_merged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [
                    self.record("line-a-01", "success", line_source_key="@line-a"),
                    self.record("line-b-01", "success", line_source_key="@line-b"),
                ],
                [
                    {"line_source_key": "@line-a", "message_id": "a-1", "message_type": "rich_card", "line_display_time": "21:01"},
                    {"line_source_key": "@line-b", "message_id": "b-1", "message_type": "text", "line_display_time": "21:02"},
                ],
            )
            results = convert_raw_directory_all(raw, repo_root=root)
            self.assertEqual([(item["hall_id"], item["line_source_key"]) for item in results], [("hall-a", "@line-a"), ("hall-a", "@line-b")])
            self.assertEqual([item["messages"]["types"] for item in results], [["rich_card"], ["text"]])
            self.assertNotEqual(observation_filename(results[0]), observation_filename(results[1]))

    def test_passive_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("passive-01", "success", adapter_type="passive")],
                [{"message_type": "rich_card", "line_display_time": "21:05"}],
                collector_key="m_and_m_mizoguchi",
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["line_update"], "present")
            self.assertFalse(result["trigger"]["required"])

    def test_passive_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(root, [self.record("passive-02", "success", adapter_type="passive")], [])
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["line_update"], "absent")
            self.assertEqual(result["summary"]["status"], "not_applicable")

    def test_text_trigger_success_rich_card_is_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("pia-01", "success", triggered_at="2026-09-23T12:00:01+00:00")],
                [{"message_id": "message-1", "message_type": "rich_card", "line_display_time": "21:05"}],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["line_update"], "present")
            self.assertEqual(result["trigger"]["result"], "sent")

    def test_response_timeout_is_unknown_not_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("pia-02", "response_timeout", triggered_at="2026-09-23T12:00:01+00:00", error_code="response_timeout")],
                [],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["collection"]["failure_code"], "response_timeout")
            self.assertEqual(result["line_update"], "unknown")
            self.assertEqual(result["summary"]["status"], "not_applicable")

    def test_not_checked_is_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = make_not_checked(
                "hall-a",
                "2026-09-23",
                repo_root=Path(temporary),
                line_source_key="@line-a",
            )
            self.assertEqual(result["collection"]["status"], "not_checked")
            self.assertEqual(result["line_update"], "unknown")
            self.assertEqual(result["summary"]["status"], "not_applicable")
            validate_observation(result, known_hall_ids={"hall-a"})

    def test_skipped_statuses_and_success_run_priority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = [
                self.record("pia-01", "success", triggered_at="2026-09-23T12:00:01+00:00"),
                self.record("pia-02", "response_timeout", triggered_at="2026-09-23T13:00:01+00:00", error_code="response_timeout"),
                self.record("pia-05", "trigger_failed", error_code="trigger_failed"),
                self.record("pia-03", "skipped_already_successful"),
                {**self.record("pia-04", "skipped_already_attempted"), "previous_status": "response_timeout"},
            ]
            raw = self.write_raw(
                root,
                records,
                [{"message_id": "message-1", "message_type": "rich_card", "line_display_time": "21:05"}],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["collection"]["status"], "success")
            self.assertIsNone(result["collection"]["failure_code"])
            self.assertEqual(result["line_update"], "present")
            self.assertEqual(result["trigger"]["result"], "sent")

    def test_multiple_sources_can_attribute_message_by_run_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [
                    self.record("line-a-01", "success", line_source_key="@line-a", adapter_type="passive"),
                    self.record("line-b-01", "success", line_source_key="@line-b", adapter_type="passive"),
                ],
                [{"run_id": "line-a-01", "message_type": "text", "line_display_time": "21:01"}],
            )
            results = convert_raw_directory_all(raw, repo_root=root)
            self.assertEqual(results[0]["line_source_key"], "@line-a")
            self.assertEqual(results[0]["line_update"], "present")
            self.assertEqual(results[1]["line_source_key"], "@line-b")
            self.assertEqual(results[1]["line_update"], "absent")

    def test_unmatched_message_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [
                    self.record("line-a-01", "success", line_source_key="@line-a"),
                    self.record("line-b-01", "success", line_source_key="@line-b"),
                ],
                [{"line_source_key": "@line-unknown", "message_type": "text", "line_display_time": "21:01"}],
            )
            with self.assertRaises(LineDailyIdentityError):
                convert_raw_directory_all(raw, repo_root=root)

    def test_raw_traceability(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = self.write_raw(
                root,
                [self.record("pia-01", "success")],
                [{"message_id": "message-1", "message_type": "rich_card", "line_display_time": "21:05"}],
            )
            result = convert_raw_directory(raw, repo_root=root)
            self.assertEqual(result["raw_refs"]["run_ids"], ["pia-01"])
            self.assertEqual(result["raw_refs"]["record_refs"], ["manifest.json#0"])
            self.assertEqual(result["raw_refs"]["message_refs"], ["message-1"])

    def test_summary_statuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = make_not_checked("hall-a", "2026-09-23", repo_root=root, line_source_key="@line-a")
            generated = json.loads(json.dumps(pending))
            generated["summary"] = {
                "status": "generated",
                "text": "最新情報あり",
                "generated_at": "2026-09-23T12:00:00+09:00",
                "generator": "test-generator-v1",
            }
            validate_observation(generated, known_hall_ids={"hall-a"})
            not_applicable = json.loads(json.dumps(pending))
            not_applicable["collection"]["status"] = "success"
            not_applicable["line_update"] = "absent"
            not_applicable["summary"]["status"] = "not_applicable"
            validate_observation(not_applicable, known_hall_ids={"hall-a"})

    def test_schema_output_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = make_not_checked("hall-a", "2026-09-23", repo_root=root, line_source_key="@line-a")
            output = root / "observation.json"
            write_observation(value, output, known_hall_ids={"hall-a"})
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), value)

    def test_normalized_output_requires_canonical_master(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = make_not_checked("hall-a", "2026-09-23", repo_root=root, line_source_key="@line-a")
            with self.assertRaises(LineDailyValidationError):
                write_observation(value, root / "observation.json")

    def test_existing_pia_raw_needs_external_canonical_identity_and_is_read_only(self):
        repo_root = Path(__file__).resolve().parents[1]
        raw_dir = repo_root / "data" / "raw" / "2026-09-21" / "pia_machida"
        before = (raw_dir / "manifest.json").read_bytes()
        with self.assertRaises(LineDailyIdentityError):
            convert_raw_directory(raw_dir, repo_root=repo_root)
        result = convert_raw_directory(
            raw_dir,
            repo_root=repo_root,
            hall_id="hall-a",
            line_source_key="@030pwlwx",
        )
        self.assertEqual(result["line_update"], "present")
        self.assertEqual(result["messages"]["types"], ["image", "rich_card"])
        self.assertEqual(result["raw_refs"]["run_ids"], [])
        self.assertEqual(result["raw_refs"]["record_refs"], [
            "manifest.json#0",
            "manifest.json#1",
            "manifest.json#2",
            "manifest.json#3",
        ])
        self.assertEqual(before, (raw_dir / "manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
