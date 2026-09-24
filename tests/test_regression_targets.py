import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.line_daily import convert_raw_directory, observation_filename
from scripts.raw_storage import RawStore, evaluate_trigger_guard
from scripts.run_daily import ADAPTERS
from scripts.run_regression_targets import (
    REGRESSION_TARGETS,
    build_command,
    main,
    validate_target_configs,
)


class RegressionTargetsTests(unittest.TestCase):
    def test_pia_configs_are_distinct_and_valid(self):
        validate_target_configs()
        by_name = {target["name"]: target for target in REGRESSION_TARGETS}
        self.assertEqual(by_name["pia_machida"]["collector_key"], "pia_machida")
        self.assertEqual(by_name["pia_machida"]["line_source_key"], "@030pwlwx")
        self.assertEqual(by_name["pia-keiky-kawasaki"]["collector_key"], "pia-keiky-kawasaki")
        self.assertEqual(by_name["pia-keiky-kawasaki"]["line_source_key"], "@rmh1818e")
        self.assertNotEqual(
            by_name["pia_machida"]["collector_key"],
            by_name["pia-keiky-kawasaki"]["collector_key"],
        )

    def test_production_runner_does_not_include_regression_targets(self):
        production_collectors = {adapter["store_id"] for adapter in ADAPTERS}
        regression_collectors = {target["collector_key"] for target in REGRESSION_TARGETS}
        self.assertEqual(production_collectors, {"m_and_m_mizoguchi"})
        self.assertTrue(production_collectors.isdisjoint(regression_collectors))

    def test_commands_are_source_specific_and_never_force(self):
        commands = [build_command(Path("/repo"), target, 90) for target in REGRESSION_TARGETS]
        self.assertEqual(len(commands), 2)
        self.assertNotIn("--force-trigger", commands[0])
        self.assertNotIn("--force-trigger", commands[1])
        self.assertIn("@030pwlwx", commands[0])
        self.assertIn("@rmh1818e", commands[1])
        self.assertNotEqual(commands[0][commands[0].index("--collector-key") + 1], commands[1][commands[1].index("--collector-key") + 1])

    def test_guard_state_is_independent_per_collector_and_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stores = [
                RawStore(root, "2026-09-24", "pia_machida", "official_line", "text_trigger", "@030pwlwx"),
                RawStore(root, "2026-09-24", "pia-keiky-kawasaki", "official_line", "text_trigger", "@rmh1818e"),
            ]
            for store in stores:
                store.initialize()
            record = stores[0].new_manifest_record("machida-success", "2026-09-24T00:00:00+00:00", {"type": "text_trigger"})
            record.update({"status": "success", "triggered_at": "2026-09-24T00:00:01+00:00"})
            stores[0].persist_manifest(record)
            self.assertEqual(
                evaluate_trigger_guard(stores[0].load_manifest_records(), "text_trigger", "text_trigger")["status"],
                "skipped_already_successful",
            )
            self.assertIsNone(
                evaluate_trigger_guard(stores[1].load_manifest_records(), "text_trigger", "text_trigger")
            )
            self.assertTrue((stores[0].root / "manifest.json").parent.name == "pia_machida")
            self.assertTrue((stores[1].root / "manifest.json").parent.name == "pia-keiky-kawasaki")

    def test_normalized_identity_and_output_path_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (
                ("pia_machida", "hall-pia-machida", "@030pwlwx", "machida-run"),
                ("pia-keiky-kawasaki", "pia-keiky-kawasaki", "@rmh1818e", "keiky-run"),
            )
            observations = []
            for collector_key, hall_id, source_key, run_id in cases:
                raw = root / "data" / "raw" / "2026-09-24" / collector_key
                raw.mkdir(parents=True)
                (raw / "manifest.json").write_text(
                    json.dumps(
                        [
                            {
                                "collector_key": collector_key,
                                "source": "official_line",
                                "adapter_type": "text_trigger",
                                "run_id": run_id,
                                "started_at": "2026-09-24T12:00:00+00:00",
                                "finished_at": "2026-09-24T12:01:00+00:00",
                                "triggered_at": "2026-09-24T12:00:01+00:00",
                                "status": "success",
                                "line_source_key": source_key,
                            }
                        ]
                    ),
                    encoding="utf-8",
                )
                (raw / "messages.json").write_text(
                    json.dumps(
                        [{"run_id": run_id, "line_source_key": source_key, "message_type": "rich_card"}]
                    ),
                    encoding="utf-8",
                )
                observations.append(
                    convert_raw_directory(
                        raw,
                        repo_root=root,
                        hall_id=hall_id,
                        line_source_key=source_key,
                    )
                )
            self.assertEqual(
                [(item["hall_id"], item["line_source_key"]) for item in observations],
                [("hall-pia-machida", "@030pwlwx"), ("pia-keiky-kawasaki", "@rmh1818e")],
            )
            self.assertNotEqual(observation_filename(observations[0]), observation_filename(observations[1]))

    def test_default_is_plan_and_does_not_spawn_child(self):
        with patch("scripts.run_regression_targets.subprocess.run") as run:
            with patch("sys.argv", ["run_regression_targets.py"]):
                self.assertEqual(main(), 0)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
