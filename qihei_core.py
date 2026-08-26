from __future__ import annotations

import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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


def get_openai_api_key() -> str:
    """Read the API key from this process or the current Windows user profile."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key or os.name != "nt":
        return key
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as environment:
            value, _value_type = winreg.QueryValueEx(environment, "OPENAI_API_KEY")
        return str(value).strip()
    except (OSError, TypeError, ValueError):
        return ""


class APIUsageStore:
    """Thread-safe local ledger for API calls made by this desktop pet only."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    @staticmethod
    def empty() -> dict[str, Any]:
        return {
            "api_calls": 0, "successful_calls": 0, "failed_calls": 0,
            "local_fallbacks": 0, "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "last_request_at": None, "recent": [],
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                loaded = {}
            data = self.empty()
            if isinstance(loaded, dict):
                data.update(loaded)
            if not isinstance(data.get("recent"), list):
                data["recent"] = []
            return data

    def record(
        self, status: str, model: str, *, input_tokens: int = 0,
        output_tokens: int = 0, total_tokens: int | None = None,
        latency_ms: int = 0, error: str | None = None,
    ) -> None:
        with self._lock:
            data = self.snapshot()
            now = datetime.now().isoformat(timespec="seconds")
            if status == "local":
                data["local_fallbacks"] = int(data.get("local_fallbacks", 0)) + 1
            else:
                data["api_calls"] = int(data.get("api_calls", 0)) + 1
                key = "successful_calls" if status == "success" else "failed_calls"
                data[key] = int(data.get(key, 0)) + 1
                data["input_tokens"] = int(data.get("input_tokens", 0)) + max(0, input_tokens)
                data["output_tokens"] = int(data.get("output_tokens", 0)) + max(0, output_tokens)
                counted_total = total_tokens if total_tokens is not None else input_tokens + output_tokens
                data["total_tokens"] = int(data.get("total_tokens", 0)) + max(0, counted_total)
                data["last_request_at"] = now
            entry = {
                "at": now, "status": status, "model": model,
                "input_tokens": max(0, input_tokens),
                "output_tokens": max(0, output_tokens),
                "latency_ms": max(0, latency_ms),
            }
            if error:
                entry["error"] = error
            data["recent"] = ([entry] + list(data.get("recent", [])))[:30]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)

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

    def task_hints(self) -> list[str]:
        """Build chatter lines from the latest synchronized campaign state."""
        data = self.load()
        hints: list[str] = []
        scene = str(data.get("current_scene", "")).strip()
        if scene:
            hints.append(f"当前现场：{scene}。先别急着跳场景，眼前的证据还没说完。")

        templates = (
            ("next_actions", "下一步建议：{} 嘎，别让线索在桌上落灰。"),
            ("active_clues", "线索复盘：{} 这条值得继续盯。"),
            ("open_questions", "还欠一份答案：{} 没证据以前，谁都别替真相招供。"),
        )
        for key, template in templates:
            values = data.get(key, [])
            if not isinstance(values, list):
                continue
            for value in values:
                text = str(value).strip()
                if text:
                    hints.append(template.format(text))
        return hints

    def mission_compass(self) -> dict[str, str]:
        """Condense the live archive into one actionable, evidence-backed objective."""
        data = self.load()

        def first(key: str, fallback: str) -> str:
            values = data.get(key, [])
            if isinstance(values, list):
                for value in values:
                    text = str(value).strip()
                    if text:
                        return text
            return fallback

        scene = str(data.get("current_scene", "")).strip() or "当前场景尚未同步"
        objective = first("next_actions", "先观察现场，等待一条已确认的行动建议。")
        clue = first("active_clues", "当前没有足够可靠的活跃线索。")
        question = first("open_questions", "当前没有登记中的未解谜团。")
        combined = " ".join((scene, objective, clue, question))
        danger_words = ("敌", "风险", "暗门", "机关", "追踪", "潜行", "返回", "死亡", "陷阱")
        caution_words = ("调查", "确认", "检查", "未解", "尚待", "选择")
        danger = sum(word in combined for word in danger_words)
        caution = sum(word in combined for word in caution_words)
        if danger >= 3:
            risk, posture = "高", "保持隐匿，先确认退路，再触碰机关。"
        elif danger or caution >= 2:
            risk, posture = "中", "先验证关键物证，避免一次推进多个未知区域。"
        else:
            risk, posture = "低", "可以稳步推进，但仍要记录新证据。"
        return {
            "scene": scene,
            "objective": objective,
            "clue": clue,
            "question": question,
            "risk": risk,
            "posture": posture,
            "updated_at": str(data.get("updated_at") or "尚未同步"),
        }

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


class RavenKeepsakeStore:
    """Small local collection and diary for shared desktop-pet moments."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    @staticmethod
    def empty() -> dict[str, list[dict[str, str]]]:
        return {"keepsakes": [], "journal": []}

    def _load(self) -> dict[str, list[dict[str, str]]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "keepsakes": list(data.get("keepsakes", [])),
                    "journal": list(data.get("journal", [])),
                }
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        return self.empty()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def unlock(self, key: str, name: str, description: str, source: str) -> bool:
        if any(item.get("key") == key for item in self.data["keepsakes"]):
            return False
        self.data["keepsakes"].append({
            "key": key, "name": name, "description": description, "source": source,
            "time": datetime.now().isoformat(timespec="minutes"),
        })
        self.save()
        return True

    def write_journal(self, text: str, category: str = "共同经历", unique_key: str = "") -> bool:
        text = text.strip()
        if not text:
            return False
        if unique_key and any(item.get("key") == unique_key for item in self.data["journal"]):
            return False
        self.data["journal"].append({
            "key": unique_key, "time": datetime.now().isoformat(timespec="minutes"),
            "category": category, "text": text,
        })
        self.data["journal"] = self.data["journal"][-120:]
        self.save()
        return True

    def summary(self) -> dict[str, list[dict[str, str]]]:
        self.data = self._load()
        return {
            "keepsakes": list(self.data["keepsakes"]),
            "journal": list(reversed(self.data["journal"])),
        }


CHINESE_NUMBERS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def parse_number(text: str) -> int:
    if text.isdigit():
        return int(text)
    if text in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[text]
    if text.startswith("十"):
        return 10 + CHINESE_NUMBERS.get(text[1:], 0)
    if text.endswith("十"):
        return CHINESE_NUMBERS.get(text[:-1], 1) * 10
    if "十" in text:
        tens, ones = text.split("十", 1)
        return CHINESE_NUMBERS.get(tens, 1) * 10 + CHINESE_NUMBERS.get(ones, 0)
    raise ValueError(f"无法识别数字：{text}")


def parse_natural_reminder(command: str, now: datetime | None = None) -> dict[str, str]:
    """Parse common Chinese reminder phrases into MemoStore fields."""
    now = now or datetime.now()
    raw = command.strip()
    text = re.sub(r"^(请)?(漆黑)?(帮我)?(记得)?提醒我?", "", raw).strip(" ，,：:")
    repeat = ""
    target: datetime | None = None

    relative = re.search(r"(半|\d+|[一二两三四五六七八九十]+)(分钟|小时|天)后", raw)
    if relative:
        value = 0.5 if relative.group(1) == "半" else parse_number(relative.group(1))
        unit = relative.group(2)
        delta = timedelta(minutes=value if unit == "分钟" else value * 60 if unit == "小时" else value * 1440)
        target = now + delta
        text = text.replace(relative.group(0), "").strip(" ，,：:")

    weekday = re.search(r"每周([一二三四五六日天])", raw)
    if weekday:
        weekday_index = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}[weekday.group(1)]
        repeat = f"weekly:{weekday_index}"
        text = text.replace(weekday.group(0), "").strip(" ，,：:")

    time_match = re.search(
        r"(?:(上午|早上|明早|下午|晚上|中午)\s*)?"
        r"(\d{1,2}|[一二两三四五六七八九十]+)\s*[点时](半|\d{1,2}\s*分?)?",
        raw,
    )
    hour, minute = 9, 0
    if time_match:
        period = time_match.group(1) or ""
        hour = parse_number(time_match.group(2))
        minute_token = (time_match.group(3) or "").replace("分", "").strip()
        minute = 30 if minute_token == "半" else int(minute_token or 0)
        if period in {"下午", "晚上"} and hour < 12:
            hour += 12
        if period == "中午" and hour < 11:
            hour += 12
        text = text.replace(time_match.group(0), "").strip(" ，,：:")

    if weekday:
        days = (weekday_index - now.weekday()) % 7
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days)
        if candidate <= now:
            candidate += timedelta(days=7)
        target = candidate
        repeat += f":{hour:02d}:{minute:02d}"
    elif target is None:
        day_offset = 2 if "后天" in raw else 1 if any(word in raw for word in ("明天", "明早")) else 0
        if time_match or day_offset:
            target = (now + timedelta(days=day_offset)).replace(
                hour=hour, minute=minute, second=0, microsecond=0,
            )
            if day_offset == 0 and target <= now:
                target += timedelta(days=1)

    for token in ("今天", "明天", "明早", "后天", "每天"):
        text = text.replace(token, "")
    text = re.sub(r"(请)?(漆黑)?(帮我)?(记得)?提醒我?", "", text)
    if "每天" in raw:
        repeat = f"daily:{hour:02d}:{minute:02d}"
    text = re.sub(r"\s+", " ", text).strip(" ，,：:")
    if not text:
        raise ValueError("提醒内容不能为空")
    if target is None:
        raise ValueError("没有识别出提醒时间，例如“半小时后”或“明早九点”")
    return {
        "text": text,
        "remind_at": target.isoformat(timespec="minutes"),
        "repeat": repeat,
    }


class CharacterSheet:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def answer(self, question: str) -> str:
        data = self.load()
        stats = data.get("skills", {}) if isinstance(data.get("skills"), dict) else {}
        aliases = {
            "隐匿": "stealth", "潜行": "stealth", "察觉": "perception", "感知": "perception",
            "调查": "investigation", "侦察": "scouting", "先攻": "initiative",
        }
        for label, key in aliases.items():
            if label in question and key in stats:
                value = int(stats[key])
                return f"{label}加值是 {value:+d}。这是本地角色卡记录，不消耗API。"
        if any(word in question for word in ("角色卡", "能力", "属性")):
            rendered = "　".join(
                f"{name} {int(stats[key]):+d}" for name, key in (
                    ("隐匿", "stealth"), ("察觉", "perception"), ("调查", "investigation"),
                    ("先攻", "initiative"),
                ) if key in stats
            )
            return rendered or "本地角色卡还没有录入可靠数值。"
        return ""


class CombatTrackerStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {"round": max(1, int(data.get("round", 1))),
                        "turn": max(0, int(data.get("turn", 0))),
                        "combatants": list(data.get("combatants", []))}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return {"round": 1, "turn": 0, "combatants": []}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, name: str, initiative: int, hp: int = 0, status: str = "") -> None:
        if not name.strip():
            raise ValueError("参战者名称不能为空")
        self.data["combatants"].append({
            "name": name.strip(), "initiative": int(initiative), "hp": max(0, int(hp)),
            "status": status.strip(),
        })
        self.data["combatants"].sort(key=lambda item: (-int(item["initiative"]), item["name"]))
        self.save()

    def next_turn(self) -> None:
        count = len(self.data["combatants"])
        if not count:
            return
        self.data["turn"] = (int(self.data["turn"]) + 1) % count
        if self.data["turn"] == 0:
            self.data["round"] = int(self.data["round"]) + 1
        self.save()

    def adjust_hp(self, index: int, delta: int) -> None:
        item = self.data["combatants"][index]
        item["hp"] = max(0, int(item.get("hp", 0)) + int(delta))
        self.save()

    def set_status(self, index: int, status: str) -> None:
        self.data["combatants"][index]["status"] = status.strip()
        self.save()

    def remove(self, index: int) -> None:
        self.data["combatants"].pop(index)
        count = len(self.data["combatants"])
        self.data["turn"] = min(int(self.data["turn"]), max(0, count - 1))
        self.save()

    def reset(self) -> None:
        self.data = {"round": 1, "turn": 0, "combatants": []}
        self.save()


def search_everything(
    query: str,
    wheel_path: Path,
    max_results: int = 5,
    instance: str | None = None,
) -> list[dict[str, Any]]:
    """Query the local Everything IPC index through the vendored pure-Python client."""
    query = query.strip()
    if not query:
        return []
    wheel = str(wheel_path)
    if wheel not in sys.path:
        sys.path.insert(0, wheel)
    try:
        from everyfile.sdk.api import EverythingAPI  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("Everything IPC 客户端缺失") from error
    api = EverythingAPI(instance=instance)
    return list(api.search(
        query, fields=["name", "path", "full_path", "is_file", "is_folder"],
        max_results=max(1, min(50, int(max_results))),
    ))


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

    @property
    def personality_profile(self) -> dict[str, Any]:
        if self.bond >= 80:
            return {
                "stance": "并肩守望", "cursor_distance": 290, "startle_patience": 4,
                "line": "我会靠近一点。不是依赖，只是这个位置视野更好。",
            }
        if self.bond >= 55:
            return {
                "stance": "默契观察", "cursor_distance": 255, "startle_patience": 3,
                "line": "你负责决定方向，我负责指出哪里像陷阱。",
            }
        if self.bond >= 30:
            return {
                "stance": "保持戒备", "cursor_distance": 225, "startle_patience": 2,
                "line": "合作可以。先让我看看你会不会踩中同一个机关两次。",
            }
        return {
            "stance": "远距审视", "cursor_distance": 190, "startle_patience": 1,
            "line": "先保持这个距离。信任不是默认选项。",
        }

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


def explain_openai_http_error(status: int, error_data: Any) -> tuple[str, str]:
    """Return a user-facing explanation and a safe machine-readable error code."""
    details = error_data.get("error", {}) if isinstance(error_data, dict) else {}
    details = details if isinstance(details, dict) else {}
    code = str(details.get("code") or details.get("type") or f"http_{status}")
    if code == "insufficient_quota":
        return (
            "在线密钥已经接通，但这个 API 项目没有可用额度。请在 OpenAI Platform 的 Billing 页面启用计费或补充余额。",
            code,
        )
    if code in {"invalid_api_key", "authentication_error"} or status == 401:
        return ("这个 API 密钥无效、已撤销或不属于可用项目。请在“API 密钥设置”里更换密钥。", code)
    if code in {"rate_limit_exceeded", "requests"} or status == 429:
        return ("在线请求过于频繁或触发了项目速率限制。稍等片刻再问一次。", code)
    if code in {"model_not_found", "permission_denied"} or status == 403:
        return ("当前 API 项目无权使用设定的模型。请检查项目权限或更换可用模型。", code)
    if status >= 500:
        return ("OpenAI 服务暂时异常。稍后重试，我先查本地冒险档案。", code)
    return (f"在线情报请求失败（HTTP {status}，{code}）。", code)


def ask_openai(
    question: str, history: list[dict[str, str]] | None = None,
    usage_store: APIUsageStore | None = None,
) -> str:
    api_key = get_openai_api_key()
    model = os.getenv("QIHEI_OPENAI_MODEL", "gpt-5.4-mini")

    def record_usage(status: str, **details: Any) -> None:
        if not usage_store:
            return
        try:
            usage_store.record(status, model, **details)
        except OSError:
            # A locked/read-only usage ledger must never break the conversation.
            pass

    if not api_key:
        record_usage("local")
        return answer_local(question)
    conversation = "\n".join(
        f"{turn.get('role', 'user')}: {turn.get('content', '')}" for turn in (history or [])[-6:]
    )
    payload = {
        "model": model,
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
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise TypeError("API response was not an object")
        if data.get("error"):
            error_data = data["error"]
            error_code = error_data.get("code", "api_error") if isinstance(error_data, dict) else "api_error"
            raise ValueError(str(error_code))
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        if usage_store:
            raw_total = usage.get("total_tokens")
            record_usage(
                "success",
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                total_tokens=int(raw_total) if raw_total is not None else None,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        parts = []
        for output in data.get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "output_text":
                    parts.append(content.get("text", ""))
        return "\n".join(parts).strip() or answer_local(question)
    except urllib.error.HTTPError as error:
        try:
            error_data = json.loads(error.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            error_data = {}
        explanation, error_code = explain_openai_http_error(int(error.code), error_data)
        record_usage(
            "error", latency_ms=round((time.perf_counter() - started) * 1000),
            error=error_code,
        )
        return f"{explanation}\n\n本地档案答复：{answer_local(question)}"
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        record_usage(
            "error", latency_ms=round((time.perf_counter() - started) * 1000),
            error=type(error).__name__,
        )
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

    def add(self, text: str, remind_at: str = "", repeat: str = "") -> None:
        text = text.strip()
        if not text:
            raise ValueError("备忘内容不能为空")
        reminder = None
        if remind_at.strip():
            raw_reminder = remind_at.strip()
            try:
                parsed = datetime.fromisoformat(raw_reminder)
            except ValueError:
                parsed = datetime.strptime(raw_reminder, "%Y-%m-%d %H:%M")
            reminder = parsed.isoformat(timespec="minutes")
        self.items.append({
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "text": text,
            "created": datetime.now().isoformat(timespec="seconds"),
            "remind_at": reminder,
            "repeat": repeat.strip(),
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
                    result.append(item)
                    repeat = str(item.get("repeat", ""))
                    if repeat.startswith("weekly:"):
                        item["remind_at"] = (datetime.fromisoformat(remind_at) + timedelta(days=7)).isoformat(timespec="minutes")
                        item["notified"] = False
                    elif repeat.startswith("daily:"):
                        item["remind_at"] = (datetime.fromisoformat(remind_at) + timedelta(days=1)).isoformat(timespec="minutes")
                        item["notified"] = False
                    else:
                        item["notified"] = True
        if result:
            self.save()
        return result
