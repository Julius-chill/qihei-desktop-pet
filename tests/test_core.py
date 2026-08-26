import io
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
from pathlib import Path

from PIL import Image

from qihei_core import (
    APIUsageStore, AdventureArchive, CompanionProgress, MemoStore, RavenKeepsakeStore,
    answer_local, ask_openai, explain_openai_http_error, get_openai_api_key, roll_dice,
)
from pet import ANIMATION_SHEETS, QiheiPet


class DiceTests(unittest.TestCase):
    def test_standard_d20_shorthand(self):
        result = roll_dice("d20")
        self.assertEqual(len(result["rolls"]), 1)
        self.assertEqual(result["expression"], "d20")

    def test_standard_expression(self):
        result = roll_dice("2d6+3")
        self.assertEqual(len(result["rolls"]), 2)
        self.assertEqual(result["modifier"], 3)
        self.assertEqual(result["total"], sum(result["rolls"]) + 3)

    def test_rejects_unsupported_dice(self):
        with self.assertRaises(ValueError):
            roll_dice("1d7")

    def test_rejects_too_many_dice(self):
        with self.assertRaises(ValueError):
            roll_dice("21d6")


class LoreTests(unittest.TestCase):
    def test_known_clue(self):
        self.assertIn("十二", answer_local("第十二声是什么"))

    def test_unknown_clue_is_honest(self):
        self.assertIn("没找到", answer_local("蓝色巨龙叫什么"))


class MemoTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            store = MemoStore(path)
            store.add("检查旧钟楼")
            loaded = MemoStore(path)
            self.assertEqual(loaded.items[0]["text"], "检查旧钟楼")


class AdventureArchiveTests(unittest.TestCase):
    def test_reload_and_append_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.json"
            archive = AdventureArchive(path)
            data = archive.load()
            data["current_scene"] = "测试场景"
            archive.save(data)
            archive.append_event("发现一枚羽毛", "侦察")
            rendered = archive.render()
            self.assertIn("测试场景", rendered)
            self.assertIn("发现一枚羽毛", rendered)

    def test_task_hints_follow_latest_campaign_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.json"
            archive = AdventureArchive(path)
            data = archive.load()
            data.update({
                "current_scene": "钟室木匣前",
                "next_actions": ["检查黄铜钟锤的磨损"],
                "active_clues": ["第十二声不在钟里"],
                "open_questions": ["空槽里原本是什么？"],
            })
            archive.save(data)
            hints = archive.task_hints()
            joined = "\n".join(hints)
            self.assertIn("钟室木匣前", joined)
            self.assertIn("检查黄铜钟锤的磨损", joined)
            self.assertIn("第十二声不在钟里", joined)
            self.assertIn("空槽里原本是什么", joined)

    def test_mission_compass_uses_first_live_action_and_rates_risk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.json"
            archive = AdventureArchive(path)
            data = archive.load()
            data.update({
                "current_scene": "潜行中的地下暗门前，守卫可能返回",
                "next_actions": ["检查暗门机关", "调查名字墙"],
                "active_clues": ["闭眼钥匙尚未试用"],
                "open_questions": ["灰衣人去了哪里？"],
            })
            archive.save(data)
            compass = archive.mission_compass()
            self.assertEqual(compass["objective"], "检查暗门机关")
            self.assertIn(compass["risk"], {"中", "高"})
            self.assertIn("隐匿", compass["posture"])


class RavenKeepsakeTests(unittest.TestCase):
    def test_unlock_is_unique_and_journal_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memories.json"
            store = RavenKeepsakeStore(path)
            self.assertTrue(store.unlock("feather", "羽毛", "一枚羽毛", "测试"))
            self.assertFalse(store.unlock("feather", "另一枚", "不应重复", "测试"))
            self.assertTrue(store.write_journal("完成第一次测试", unique_key="first-test"))
            self.assertFalse(store.write_journal("重复事件", unique_key="first-test"))
            loaded = RavenKeepsakeStore(path).summary()
            self.assertEqual(len(loaded["keepsakes"]), 1)
            self.assertEqual(len(loaded["journal"]), 1)


class APIUsageTests(unittest.TestCase):
    def test_api_key_reads_environment(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key-from-environment"}, clear=True):
            self.assertEqual(get_openai_api_key(), "test-key-from-environment")

    def test_quota_error_has_actionable_explanation(self):
        message, code = explain_openai_http_error(
            429, {"error": {"type": "insufficient_quota", "code": "insufficient_quota"}},
        )
        self.assertEqual(code, "insufficient_quota")
        self.assertIn("没有可用额度", message)
        self.assertIn("Billing", message)

    def test_invalid_key_error_has_actionable_explanation(self):
        message, code = explain_openai_http_error(401, {"error": {"code": "invalid_api_key"}})
        self.assertEqual(code, "invalid_api_key")
        self.assertIn("更换密钥", message)

    def test_records_calls_tokens_and_recent_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store = APIUsageStore(Path(directory) / "api_usage.json")
            store.record(
                "success", "test-model", input_tokens=12,
                output_tokens=7, total_tokens=19, latency_ms=245,
            )
            store.record("error", "test-model", latency_ms=300, error="TimeoutError")
            data = store.snapshot()
            self.assertEqual(data["api_calls"], 2)
            self.assertEqual(data["successful_calls"], 1)
            self.assertEqual(data["failed_calls"], 1)
            self.assertEqual(data["total_tokens"], 19)
            self.assertNotIn("question", data["recent"][0])

    def test_local_answer_is_counted_without_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            store = APIUsageStore(Path(directory) / "api_usage.json")
            with patch.dict("os.environ", {}, clear=True):
                answer = ask_openai("第十二声是什么", usage_store=store)
            self.assertIn("十二", answer)
            self.assertEqual(store.snapshot()["local_fallbacks"], 1)

    def test_response_usage_tokens_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = APIUsageStore(Path(directory) / "api_usage.json")
            response_data = {
                "model": "test-model",
                "usage": {"input_tokens": 21, "output_tokens": 8, "total_tokens": 29},
                "output": [{"content": [{"type": "output_text", "text": "收到。"}]}],
            }
            response = MagicMock()
            response.__enter__.return_value.read.return_value = __import__("json").dumps(response_data).encode()
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "QIHEI_OPENAI_MODEL": "test-model"}, clear=True):
                with patch("qihei_core.urllib.request.urlopen", return_value=response):
                    answer = ask_openai("测试", usage_store=store)
            self.assertEqual(answer, "收到。")
            self.assertEqual(store.snapshot()["total_tokens"], 29)

    def test_api_error_object_falls_back_instead_of_breaking_chat(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"error":{"code":"bad_request"}}'
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch("qihei_core.urllib.request.urlopen", return_value=response):
                answer = ask_openai("第十二声是什么")
        self.assertIn("本地档案答复", answer)
        self.assertIn("十二", answer)

    def test_http_quota_error_is_decoded_for_chat(self):
        body = b'{"error":{"type":"insufficient_quota","code":"insufficient_quota"}}'
        error = urllib.error.HTTPError(
            "https://api.openai.com/v1/responses", 429, "Too Many Requests", {}, io.BytesIO(body),
        )
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch("qihei_core.urllib.request.urlopen", side_effect=error):
                answer = ask_openai("第十二声是什么")
        self.assertIn("没有可用额度", answer)
        self.assertIn("本地档案答复", answer)

    def test_usage_ledger_failure_does_not_break_local_answer(self):
        store = MagicMock()
        store.record.side_effect = OSError("locked")
        with patch.dict("os.environ", {}, clear=True):
            answer = ask_openai("第十二声是什么", usage_store=store)
        self.assertIn("十二", answer)


class CompanionTests(unittest.TestCase):
    def test_progress_round_trip(self):
        progress = CompanionProgress(bond=56, experience=48, scout_xp=34)
        loaded = CompanionProgress.from_dict(progress.to_dict())
        self.assertEqual(loaded.bond_rank, "默契搭档")
        self.assertEqual(loaded.level, 3)
        self.assertEqual(loaded.scout_level, 3)

    def test_scout_uses_bond_mood_and_skill(self):
        progress = CompanionProgress(bond=85, energy=80, morale=60, scout_xp=70)
        result = progress.scout(dc=13, natural=10)
        self.assertEqual(result["modifier"], 7)
        self.assertTrue(result["success"])

    def test_tired_companion_cannot_scout(self):
        result = CompanionProgress(energy=5).scout()
        self.assertFalse(result["ok"])


class AnimationDirectionTests(unittest.TestCase):
    def test_pixel_sleep_sheet_has_six_transparent_cells(self):
        path, frame_count = ANIMATION_SHEETS["pixel"]["sleep"]
        with Image.open(path) as sheet:
            self.assertEqual(frame_count, 6)
            self.assertEqual(sheet.mode, "RGBA")
            self.assertEqual(sheet.width % frame_count, 0)
            self.assertEqual(sheet.getchannel("A").getextrema(), (0, 255))

    def test_pixel_sheet_faces_left(self):
        self.assertFalse(QiheiPet.should_mirror_for_flight("pixel", 500, 100))
        self.assertTrue(QiheiPet.should_mirror_for_flight("pixel", 100, 500))

    def test_realistic_sheet_faces_right(self):
        self.assertFalse(QiheiPet.should_mirror_for_flight("realistic", 100, 500))
        self.assertTrue(QiheiPet.should_mirror_for_flight("realistic", 500, 100))

    def test_grounded_bird_action_sheets_have_six_transparent_cells(self):
        for style in ("pixel", "realistic"):
            for action in ("look", "peck", "preen", "stretch"):
                path, frame_count = ANIMATION_SHEETS[style][action]
                with self.subTest(style=style, action=action), Image.open(path) as sheet:
                    self.assertEqual(frame_count, 6)
                    self.assertEqual(sheet.mode, "RGBA")
                    self.assertEqual(sheet.width % frame_count, 0)
                    self.assertEqual(sheet.getchannel("A").getextrema()[0], 0)


class ExternalToolTests(unittest.TestCase):
    def test_external_app_launcher_starts_configured_executable(self):
        pet = MagicMock()
        executable = MagicMock()
        executable.is_file.return_value = True
        with patch("pet.os.startfile") as startfile:
            QiheiPet.launch_external_app(pet, executable, "Everything")
        startfile.assert_called_once_with(executable)
        pet.say.assert_not_called()

    def test_everything_menu_action_uses_portable_executable(self):
        pet = MagicMock()
        with patch("pet.EVERYTHING_EXE") as executable:
            QiheiPet.launch_everything(pet)
        pet.launch_external_app.assert_called_once_with(executable, "Everything")


class MenuBehaviorTests(unittest.TestCase):
    def test_quiet_label_updates_inside_settings_menu(self):
        pet = MagicMock()
        pet.quiet = False
        pet.quiet_menu_index = 3
        QiheiPet.toggle_quiet(pet)
        pet.settings_menu.entryconfigure.assert_called_once_with(3, label="恢复碎碎念")
        pet.say.assert_called_once_with("收到。静默侦察。")


if __name__ == "__main__":
    unittest.main()
