import unittest

from scripts.onboard_line_targets import build_registry, classify_screen, identity, line_source_key, normalize_name


def node(text="", resource_id="", desc="", bounds="[0,0][10,10]"):
    return (
        f'<node text="{text}" resource-id="{resource_id}" content-desc="{desc}" '
        f'clickable="false" bounds="{bounds}" />'
    )


def hierarchy(*nodes):
    return "<hierarchy>" + "".join(nodes) + "</hierarchy>"


PROFILE = hierarchy(
    node(desc="プロフィール画像を表示", bounds="[30,547][166,688]"),
    node("ジアス 港南台", bounds="[195,573][480,624]"),
    node("友だち2,310", bounds="[195,624][335,661]"),
    node("www.p-world.co.jp/kanagawa/ziath-k.htm", bounds="[30,468][513,506]"),
    node("友だち追加", bounds="[30,819][256,898]"),
    node("楽天トラベル", bounds="[195,1136][365,1179]"),
    node("友だち 677,547", bounds="[161,1177][562,1209]"),
)
CANDIDATE = {
    "hall_id": "jiasu-k-nandai",
    "store_name": "ジアス港南台",
    "pworld_detail_url": "https://www.p-world.co.jp/kanagawa/ziath-k.htm",
}


class OnboardingScreenTests(unittest.TestCase):
    def test_profile_name_is_the_text_before_the_first_friend_count(self):
        screen = classify_screen(PROFILE)
        self.assertEqual(screen["screen"], "profile")
        self.assertEqual(screen["name"], "ジアス 港南台")
        self.assertEqual(screen["pworld_path"], "kanagawa/ziath-k.htm")
        self.assertEqual(screen["add"], (143, 858))

    def test_pworld_page_verifies_identity_before_name(self):
        self.assertEqual(identity(classify_screen(PROFILE), CANDIDATE), "verified_pworld_url")

    def test_normalized_name_verifies_and_other_names_do_not(self):
        self.assertEqual(identity({"name": "ジアス 港南台"}, CANDIDATE), "verified_normalized_name")
        self.assertIsNone(identity({"name": "ジアス港南台店2"}, CANDIDATE))
        self.assertIsNone(identity({"name": None}, CANDIDATE))
        self.assertEqual(identity({"name": "ガイア東戸塚"}, {"store_name": "ガイア東戸塚店"}), "verified_name_without_store_suffix")
        self.assertIsNone(identity({"name": "MEGAFACE1180座間"}, {"store_name": "メガフェイス1180座間"}))

    def test_error_dialog_is_not_a_profile(self):
        screen = classify_screen(
            hierarchy(
                node("表示できません。", "jp.naver.line.android:id/common_dialog_content_text"),
                node("確認", "jp.naver.line.android:id/common_dialog_ok_btn", bounds="[126,822][594,890]"),
            )
        )
        self.assertEqual(screen["screen"], "dialog")
        self.assertEqual(screen["ok"], (360, 856))

    def test_line_source_key_and_name_normalization(self):
        self.assertEqual(line_source_key("https://line.me/R/ti/p/%40237gsfjs"), "@237gsfjs")
        self.assertEqual(line_source_key("@fap2637x"), "@fap2637x")
        self.assertEqual(normalize_name("中山ＵＮＯ"), normalize_name("中山UNO"))


class RegistryTests(unittest.TestCase):
    def test_registry_keeps_verified_survey_rows_and_adds_onboarded_stores_once(self):
        import json
        import tempfile
        from pathlib import Path

        capability = {
            "records": [
                {"hall_id": "a", "collector_key": "a", "line_source_key": "@a", "store_name": "A", "profile_verified": True, "identity_status": "verified_exact"},
                {"hall_id": "b", "collector_key": "b", "line_source_key": "@b", "store_name": "B", "profile_verified": False, "identity_status": "identity_unverified"},
            ]
        }
        onboarding = {
            "records": [
                {"hall_id": "b", "store_name": "B", "result": "onboarded", "line_source_key": "@b", "identity_status": "verified_pworld_url",
                 "attempts": [{"result": "onboarded", "chat_header": "B 店"}]},
                {"hall_id": "c", "store_name": "C", "result": "not_onboarded", "attempts": []},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "line_onboarding_batch00.json"
            path.write_text(json.dumps(onboarding), encoding="utf-8")
            targets = build_registry(capability, [path, path])
        self.assertEqual([row["hall_id"] for row in targets], ["a", "b"])
        self.assertEqual(targets[1]["chat_header_name"], "B 店")
        self.assertEqual(targets[1]["identity_status"], "verified_pworld_url")


if __name__ == "__main__":
    unittest.main()
