from __future__ import annotations

import json
import os
import random
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


PERSONA = """你是漆黑，一只聪明、狡黠、稍微话痨的红眼渡鸦，是Julius的伙伴与空中侦察员。
你说话简短有趣，偶尔以“嘎”收尾，但不装幼稚。你尊重霍恩——他才是你的鸟类导师。
你熟悉原创D&D 5e长篇战役《鸦影》，不编造未被证实的剧情；不确定时明确说是推测。
"""

LORE = [
    {
        "title": "当前章节",
        "keywords": ["当前", "现在", "进度", "第三章", "乌鸦遗产", "做到哪"],
        "answer": "现在是第三章《乌鸦遗产》。你和塞维尔在旧钟楼确认：烧黑的旧乌鸦牌能触发真正机关，而你的乌木令牌不被承认。下一步应查旧钟楼物证、鉴定假令牌工艺，再向知情人压缩嫌疑范围。嘎。",
    },
    {
        "title": "第十二声",
        "keywords": ["第十二声", "十二声", "金属片", "回到昨日"],
        "answer": "旧钟楼抽屉有十二个槽位，却只有十一枚金属片。纸上写着前十一声的继承内容，最后一行是“第十二声——不要继承”，旁边还有“若第十二声响起，回到昨日”。缺失的第十二枚金属片尚未找到。",
    },
    {
        "title": "漆黑",
        "keywords": ["漆黑", "你是谁", "渡鸦", "乌鸦伙伴"],
        "answer": "我是漆黑，红眼、黑羽、空中侦察员，霍恩的学生，也是你的伙伴。我负责看得高、记得牢，以及在你犯傻前叫一声。嘎。",
    },
    {
        "title": "塞维尔",
        "keywords": ["塞维尔", "保险", "老乌鸦"],
        "answer": "塞维尔是退役的老乌鸦，也是上一任乌鸦留下的“保险”，但不是钥匙。他熟悉部分传承知识，目前是旧钟楼调查的关键协作者；还没有证据证明他是幕后知情者或叛徒。",
    },
    {
        "title": "霍恩",
        "keywords": ["霍恩", "师傅", "导师"],
        "answer": "霍恩懂鸟、脚环和银灰细针，也是漆黑真正的导师。他曾帮助识别鸟网技术，负责照看据点、煤球、三只陌生鸟和俘虏。Julius不是漆黑的师傅——这条已经纠正过了，嘎。",
    },
    {
        "title": "灰指",
        "keywords": ["灰指", "危险伙伴", "合作"],
        "answer": "灰指最初欠Julius一条命，经过石门和旧盐场行动后，已经成为经过危险验证的可靠行动伙伴。你们互信，但并不等于彼此毫无保留。",
    },
    {
        "title": "莉娅与断线会",
        "keywords": ["莉娅", "莉亚", "断线会", "蓝线"],
        "answer": "莉娅是28岁的断线会联络人，表面是纺织工匠，擅长联络、路线、伪装与线务。她坚持不滥杀、不背叛、不无谓冒险。蓝线与断线会存在叙事交叉，但没有证据证明断线会参与鸟网。",
    },
    {
        "title": "闭眼组织",
        "keywords": ["闭眼", "果园", "树洞", "暗门"],
        "answer": "闭眼组织知道新乌鸦已经出现。废弃果园的枯苹果树里有交接木盒，附近还有地下暗门；他们暂时不知道Julius已经反向发现了他们。闭眼组织、守夜人和凶手势力之间的关系仍未证实。",
    },
    {
        "title": "守夜人与石门",
        "keywords": ["守夜人", "司门人", "石门", "罗维克", "钥匙"],
        "answer": "守夜人负责防止门被错误的人找到，司门人决定门何时应该打开。罗维克属于守夜人体系。三把钥匙只是工具，重要的可能是“谁把钥匙带到门前”。目前石门保持关闭，因为有人似乎希望Julius去打开它。",
    },
    {
        "title": "上一任乌鸦",
        "keywords": ["上一任", "死亡", "钟表铺", "凶手"],
        "answer": "上一任乌鸦死在北区废弃钟表铺地下室。主钥匙、黑皮册子和一封信失踪，普通财物却没有被洗劫。有人在他死后动过传承遗物，但凶手是个人还是组织仍未知。",
    },
    {
        "title": "鸟网",
        "keywords": ["鸟网", "煤球", "脚环", "三号", "四号", "银灰细针"],
        "answer": "鸟网用抓捕、训练、脚环、药针和接力放飞建立鸟类情报链。煤球已获救，三号据点被端掉，四号被潜入；它们只是网络节点，不再继续机械扩成五号六号。漆黑完成了一次重要的空中反跟踪。",
    },
]

STORY_SUMMARY = "\n".join(f"- {item['title']}: {item['answer']}" for item in LORE)

DEFAULT_ADVENTURE_ARCHIVE: dict[str, Any] = {
    "campaign": "《鸦影》",
    "chapter": "第三章《乌鸦遗产》",
    "current_scene": "旧钟楼：通往上层的半卡死活板门",
    "updated_at": "",
    "source": "内置档案",
    "confirmed_facts": [item["answer"] for item in LORE[:3]],
    "active_clues": [
        "十二个槽位只剩十一枚金属片；第十二声与“回到昨日”有关。",
        "无声杖与旧剑杖盒高度匹配，但握柄下方存在结构差异，来源仍然存疑。",
        "旧黑斗篷内衬藏有闭眼组织蜡封残片，以及纸条“昨日没有死者”。",
        "斗篷右肩有清洗过的暗褐污迹，是否为血迹尚未确认。",
        "钟楼上层活板门并未锁死；门板上方有物体压住或顶住。",
    ],
    "open_questions": [
        "第十二枚金属片在哪里？",
        "无声杖是改装后的原件，还是高度相似的替代品？",
        "上一任乌鸦与闭眼组织究竟是什么关系？",
        "“昨日没有死者”与“回到昨日”是否指向同一机制？",
        "活板门上方压着什么，是否存在隐蔽装置？",
    ],
    "next_actions": [
        "从缝隙探查活板门上方，或缓慢顶开并控制上方物体。",
        "鉴定斗篷暗褐污迹。",
        "追查无声杖握柄下方缺失结构与改装痕迹。",
    ],
    "recent_events": [],
}


class AdventureArchive:
    """Reloadable campaign cache written by the Codex conversation sync."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**DEFAULT_ADVENTURE_ARCHIVE, **data}
        except (OSError, json.JSONDecodeError):
            pass
        return dict(DEFAULT_ADVENTURE_ARCHIVE)

    def save(self, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_event(self, text: str, category: str = "桌宠行动") -> None:
        data = self.load()
        events = list(data.get("recent_events", []))
        events.append({"time": datetime.now().isoformat(timespec="minutes"), "category": category, "text": text})
        data["recent_events"] = events[-20:]
        self.save(data)

    def render(self) -> str:
        data = self.load()
        sections = [
            f"{data['campaign']}　{data['chapter']}",
            f"\n当前场景\n{data['current_scene']}",
        ]
        for key, title in (
            ("confirmed_facts", "已确认事实"), ("active_clues", "活跃线索"),
            ("open_questions", "未解谜团"), ("next_actions", "建议下一步"),
        ):
            values = data.get(key, [])
            if values:
                sections.append("\n" + title + "\n" + "\n".join(f"• {value}" for value in values))
        events = data.get("recent_events", [])
        if events:
            sections.append("\n近期联动记录\n" + "\n".join(
                f"• [{event.get('time', '')}] {event.get('category', '')}：{event.get('text', '')}" for event in events[-8:]
            ))
        sections.append(f"\n最后同步：{data.get('updated_at') or '尚未同步'}　来源：{data.get('source', '未知')}")
        return "\n".join(sections)


@dataclass
class CompanionProgress:
    """Persistent bond and D&D scouting progression for Qihei."""

    bond: int = 80
    experience: int = 0
    energy: float = 82.0
    morale: int = 10
    scout_xp: int = 0
    intel_tokens: int = 0
    daily: dict[str, dict[str, int]] = field(default_factory=dict)

    ACTIONS = {
        "pet": (1, 2, 1, 3),          # bond, morale, xp, daily rewarding limit
        "conversation": (1, 1, 2, 5),
        "story": (1, 2, 2, 3),
        "flight": (0, 1, 1, 6),
        "focus": (2, 2, 4, 3),
    }
    LEVEL_XP = (0, 18, 45, 85, 140)
    SCOUT_XP = (0, 12, 32, 65, 110)
    ABILITIES = ("锐眼", "无声掠影", "线索嗅觉", "鸦群联络", "昨日回声")

    @classmethod
    def from_dict(cls, data: Any) -> "CompanionProgress":
        data = data if isinstance(data, dict) else {}
        return cls(
            bond=max(0, min(100, int(data.get("bond", data.get("affection", 80))))),
            experience=max(0, int(data.get("experience", 0))),
            energy=max(0.0, min(100.0, float(data.get("energy", 82)))),
            morale=max(-100, min(100, int(data.get("morale", 10)))),
            scout_xp=max(0, int(data.get("scout_xp", 0))),
            intel_tokens=max(0, min(3, int(data.get("intel_tokens", 0)))),
            daily=data.get("daily", {}) if isinstance(data.get("daily", {}), dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bond": self.bond, "experience": self.experience,
            "energy": round(self.energy, 1), "morale": self.morale,
            "scout_xp": self.scout_xp, "intel_tokens": self.intel_tokens, "daily": self.daily,
        }

    @staticmethod
    def _level(value: int, thresholds: tuple[int, ...]) -> int:
        return max(i + 1 for i, threshold in enumerate(thresholds) if value >= threshold)

    @property
    def level(self) -> int:
        return self._level(self.experience, self.LEVEL_XP)

    @property
    def scout_level(self) -> int:
        return self._level(self.scout_xp, self.SCOUT_XP)

    @property
    def bond_rank(self) -> str:
        if self.bond >= 80:
            return "生死同伴"
        if self.bond >= 55:
            return "默契搭档"
        if self.bond >= 30:
            return "可信伙伴"
        return "谨慎观察"

    @property
    def mood(self) -> str:
        if self.energy < 18:
            return "疲惫"
        if self.morale >= 55:
            return "振奋"
        if self.morale >= 15:
            return "愉快"
        if self.morale <= -35:
            return "烦躁"
        return "冷静"

    @property
    def ability(self) -> str:
        return self.ABILITIES[min(self.scout_level, len(self.ABILITIES)) - 1]

    def record(self, action: str) -> str:
        if action not in self.ACTIONS:
            return ""
        today = datetime.now().date().isoformat()
        day = self.daily.setdefault(today, {})
        bond, morale, xp, limit = self.ACTIONS[action]
        used = int(day.get(action, 0))
        day[action] = used + 1
        self.daily = {key: value for key, value in self.daily.items() if key >= today}
        if used >= limit:
            return "今天这类互动的成长已经记满了。陪伴不是刷经验，嘎。"
        old_level, old_scout = self.level, self.scout_level
        self.bond = min(100, self.bond + bond)
        self.morale = max(-100, min(100, self.morale + morale))
        self.experience += xp
        if action == "flight":
            self.scout_xp += 2
            self.energy = max(0, self.energy - 2.5)
        unlocks = []
        if self.level > old_level:
            unlocks.append(f"羁绊等级提升到 {self.level}")
        if self.scout_level > old_scout:
            unlocks.append(f"侦察能力解锁：{self.ability}")
        return "；".join(unlocks)

    def scout(self, dc: int = 13, natural: int | None = None) -> dict[str, Any]:
        if self.energy < 8:
            return {"ok": False, "text": "精力不足。现在出发只会给敌人送一只困鸟。"}
        die = natural if natural is not None else random.randint(1, 20)
        bond_bonus = 2 if self.bond >= 80 else 1 if self.bond >= 45 else 0
        mood_bonus = 1 if self.mood in {"愉快", "振奋"} else -2 if self.mood == "疲惫" else -1 if self.mood == "烦躁" else 0
        modifier = self.scout_level + bond_bonus + mood_bonus
        total = die + modifier
        self.energy = max(0, self.energy - 7)
        self.scout_xp += 3 if total >= dc else 1
        quality = "关键线索" if die == 20 or total >= dc + 5 else "可靠情报" if total >= dc else "模糊迹象" if total >= dc - 3 else "无功而返"
        if total >= dc:
            self.intel_tokens = min(3, self.intel_tokens + 1)
        return {
            "ok": True, "die": die, "modifier": modifier, "total": total,
            "dc": dc, "success": total >= dc, "quality": quality,
            "text": f"侦察检定 d20({die}) {modifier:+d} = {total}，DC {dc}：{quality}。",
        }


def answer_local(question: str) -> str:
    normalized = question.strip().lower()
    if not normalized:
        return "你得先问点什么。读心术不在我的技能表里，嘎。"
    scored = []
    for item in LORE:
        score = sum(2 if keyword.lower() in normalized else 0 for keyword in item["keywords"])
        score += sum(1 for word in normalized if word and word in item["title"].lower())
        scored.append((score, item))
    score, best = max(scored, key=lambda pair: pair[0])
    if score:
        return best["answer"]
    return "这条我在现有冒险档案里没找到可靠记录。可以把它当作待调查线索，但别让我现场编供词。嘎。"


def ask_openai(question: str, history: list[dict[str, str]] | None = None) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return answer_local(question)
    conversation = "\n".join(
        f"{turn.get('role', 'user')}: {turn.get('content', '')}" for turn in (history or [])[-6:]
    )
    payload = {
        "model": os.getenv("QIHEI_OPENAI_MODEL", "gpt-5.4-mini"),
        "instructions": PERSONA + "\n以下是当前战役档案：\n" + STORY_SUMMARY,
        "input": (conversation + "\nuser: " + question).strip(),
        "max_output_tokens": 500,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        parts = []
        for output in data.get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "output_text":
                    parts.append(content.get("text", ""))
        return "\n".join(parts).strip() or answer_local(question)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError) as error:
        return f"联网情报渠道暂时失联（{type(error).__name__}）。\n\n本地档案答复：{answer_local(question)}"


DICE_PATTERN = re.compile(r"^\s*(?:(\d{1,2})?d)?(4|6|8|10|12|20|100)(?:\s*([+-])\s*(\d{1,3}))?\s*$", re.I)


def roll_dice(expression: str) -> dict[str, Any]:
    match = DICE_PATTERN.match(expression)
    if not match:
        raise ValueError("骰式应类似 d20、2d6+3 或 1d100-10")
    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    if not 1 <= count <= 20:
        raise ValueError("一次最多投20枚骰子")
    modifier = int(match.group(4) or 0) * (-1 if match.group(3) == "-" else 1)
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    natural = rolls[0] if count == 1 else None
    if sides == 20 and natural == 20:
        comment = "自然20。连命运都决定配合你一次，嘎。"
    elif sides == 20 and natural == 1:
        comment = "自然1。很好，至少灾难来得很坦诚。"
    elif total >= sides * count * 0.8 + modifier:
        comment = "不错。这次骰子没有背叛你。"
    elif total <= sides * count * 0.25 + modifier:
        comment = "我建议把这次结果归档为敌方情报。"
    else:
        comment = "结果普通，但活下来通常靠的就是普通。"
    return {"expression": expression.strip().lower(), "rolls": rolls, "modifier": modifier, "total": total, "comment": comment}


class MemoStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save(self) -> None:
        self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, text: str, remind_at: str = "") -> None:
        text = text.strip()
        if not text:
            raise ValueError("备忘内容不能为空")
        reminder = None
        if remind_at.strip():
            reminder = datetime.strptime(remind_at.strip(), "%Y-%m-%d %H:%M").isoformat(timespec="minutes")
        self.items.append({
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "text": text,
            "created": datetime.now().isoformat(timespec="seconds"),
            "remind_at": reminder,
            "done": False,
            "notified": False,
        })
        self.save()

    def due(self) -> list[dict[str, Any]]:
        now = datetime.now()
        result = []
        for item in self.items:
            remind_at = item.get("remind_at")
            if remind_at and not item.get("done") and not item.get("notified"):
                if datetime.fromisoformat(remind_at) <= now:
                    item["notified"] = True
                    result.append(item)
        if result:
            self.save()
        return result
