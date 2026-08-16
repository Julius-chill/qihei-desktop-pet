import tempfile
import unittest
from pathlib import Path

from qihei_core import CompanionProgress, MemoStore, answer_local, roll_dice


class DiceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
