from __future__ import annotations

import json
import math
import os
import random
import threading
import time
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageOps, ImageTk

from qihei_core import APIUsageStore, AdventureArchive, CompanionProgress, MemoStore, ask_openai, roll_dice

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "pet_state.json"
TRANSPARENT = "#010203"
PET_SIZE = 112
IMAGE_SIZE = 94
UI = {
    "void": "#0C0F16", "raven": "#11131B", "panel": "#1B2030",
    "panel_2": "#242A3B", "gold": "#C79A45", "gold_dim": "#745B31",
    "blood": "#A83232", "paper": "#ECE8DC", "muted": "#9A9CAB",
}
STYLES = {
    "pixel": BASE_DIR / "assets" / "raven_pixel_concept_v1.png",
    "realistic": BASE_DIR / "assets" / "raven_2d_concept_v4.png",
}
ANIMATION_SHEETS = {
    "pixel": {
        "idle": (BASE_DIR / "assets" / "raven_pixel_idle_sheet_v2.png", 6),
        "flight": (BASE_DIR / "assets" / "raven_pixel_flight_sheet_v2.png", 8),
        "sleep": (BASE_DIR / "assets" / "raven_pixel_sleep_sheet_v1.png", 6),
    },
    "realistic": {
        "idle": (BASE_DIR / "assets" / "raven_realistic_idle_sheet.png", 4),
        "flight": (BASE_DIR / "assets" / "raven_realistic_flight_sheet.png", 6),
    },
}

IDLE_LINES = [
    "嘎。你忙你的，我只是在监督。", "这个窗口还没招供？效率堪忧。",
    "霍恩说观察要有耐心。没说要无聊。", "今日情报：你该喝水了。",
    "我不是话多，这是持续情报播报。", "嘎——有人摸鱼。我不说是谁。",
    "我在想那只母乌鸦……我是说，在规划航线。", "桌面这么乱，线索很好藏。",
]
ACTION_FPS = {
    "flight": 11.0, "takeoff": 9.0, "landing": 9.0,
    "sleep": 1.35, "sleep_enter": 5.0, "sleep_exit": 5.0,
}


class QiheiPet:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("漆黑")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT)
        self.root.wm_attributes("-transparentcolor", TRANSPARENT)
        self.canvas = tk.Canvas(
            self.root, width=PET_SIZE, height=PET_SIZE, bg=TRANSPARENT,
            highlightthickness=0, cursor="hand2",
        )
        self.canvas.pack()

        state = self.load_state()
        self.style = tk.StringVar(value=state.get("style", "pixel"))
        if self.style.get() not in STYLES:
            self.style.set("pixel")
        self.started = time.perf_counter()
        self.idle_motion_started: float | None = None
        self.next_idle_motion = self.started + random.uniform(8.0, 16.0)
        self.facing_left = False
        self.flight: dict[str, float] | None = None
        self.action: dict[str, float | str] | None = None
        self.sleeping = False
        progress_data = state.get("companion", {})
        if not progress_data:
            progress_data = {"affection": state.get("affection", 80), "energy": state.get("energy", 82)}
        self.progress = CompanionProgress.from_dict(progress_data)
        self.last_vitals_update = time.time()
        self.drag_origin: tuple[int, int] | None = None
        self.dragged = False
        self.quiet = False
        self.animation_paused = tk.BooleanVar(value=False)
        self.follow_cursor = tk.BooleanVar(value=False)
        self.bubble_timer: str | None = None
        self.bubble_type_timer: str | None = None
        self.frames: dict[str, list[Image.Image]] = {}
        self.tk_image: ImageTk.PhotoImage | None = None
        self.last_render: tuple[str, int, bool] | None = None
        self.image_item = self.canvas.create_image(PET_SIZE // 2, PET_SIZE // 2)
        self.memo_store = MemoStore(BASE_DIR / "notes.json")
        self.adventure_archive = AdventureArchive(BASE_DIR / "adventure_archive.json")
        self.api_usage = APIUsageStore(BASE_DIR / "api_usage.json")
        self.api_usage_baseline = self.api_usage.snapshot()
        self.chat_history: list[dict[str, str]] = []

        self.bubble = tk.Toplevel(self.root)
        self.bubble.withdraw()
        self.bubble.overrideredirect(True)
        self.bubble.attributes("-topmost", True)
        self.bubble.configure(bg=TRANSPARENT)
        self.bubble.wm_attributes("-transparentcolor", TRANSPARENT)
        self.bubble_canvas = tk.Canvas(self.bubble, width=310, height=130, bg=TRANSPARENT, highlightthickness=0)
        self.bubble_canvas.pack()
        self.bubble_text_item: int | None = None
        self.draw_bubble(130)

        self.menu = tk.Menu(
            self.root, tearoff=False, font=("Microsoft YaHei UI", 9),
            bg=UI["raven"], fg=UI["paper"], activebackground=UI["blood"],
            activeforeground="#ffffff", selectcolor=UI["gold"], bd=0,
        )
        self.menu.add_command(label="出去飞一圈", command=lambda: self.start_flight(True))
        self.menu.add_command(label="休息 / 醒来", command=self.toggle_sleep)
        self.menu.add_command(label="状态", command=self.show_status)
        self.menu.add_command(label="羁绊与养成", command=self.open_companion_window)
        self.menu.add_command(label="DND侦察行动", command=self.open_scout_window)
        self.menu.add_command(label="专注计时", command=self.open_focus_window)
        self.menu.add_command(label="向漆黑提问", command=self.open_question_window)
        self.menu.add_command(label="API 使用情况", command=self.open_api_usage_window)
        self.menu.add_command(label="备忘录与提醒", command=self.open_memo_window)
        self.menu.add_command(label="DND骰子", command=self.open_dice_window)
        self.menu.add_command(label="冒险档案", command=self.open_story_window)
        self.menu.add_separator()
        style_menu = tk.Menu(
            self.menu, tearoff=False, font=("Microsoft YaHei UI", 9),
            bg=UI["raven"], fg=UI["paper"], activebackground=UI["blood"],
            activeforeground="#ffffff", selectcolor=UI["gold"], bd=0,
        )
        style_menu.add_radiobutton(label="像素版", variable=self.style, value="pixel", command=self.switch_style)
        style_menu.add_radiobutton(label="写实版", variable=self.style, value="realistic", command=self.switch_style)
        self.menu.add_cascade(label="切换外观", menu=style_menu)
        self.menu.add_checkbutton(label="暂停活动", variable=self.animation_paused, command=self.toggle_animation)
        self.menu.add_checkbutton(label="在鼠标附近巡航", variable=self.follow_cursor)
        self.menu.add_command(label="隐藏5分钟", command=self.hide_temporarily)
        self.menu.add_command(label="现在几点", command=self.tell_time)
        self.quiet_menu_index = self.menu.index("end") + 1
        self.menu.add_command(label="安静一会儿", command=self.toggle_quiet)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.close)

        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.end_drag)
        self.canvas.bind("<Double-Button-1>", lambda _event: self.start_flight(True))
        self.canvas.bind("<Button-3>", self.show_menu)
        self.restore_position(state)
        self.load_style_image()
        self.tick()
        self.root.after(900, lambda: self.say("小一点，精神一点。这样总算像我了。嘎。", 4300))
        self.root.after(random.randint(9000, 15000), self.start_flight)
        self.schedule_chatter()
        self.root.after(5000, self.check_reminders)
        self.root.after(60000, self.update_vitals)

    @property
    def affection(self) -> int:
        return self.progress.bond

    @affection.setter
    def affection(self, value: int) -> None:
        self.progress.bond = max(0, min(100, value))

    @property
    def energy(self) -> float:
        return self.progress.energy

    @energy.setter
    def energy(self, value: float) -> None:
        self.progress.energy = max(0.0, min(100.0, value))

    def load_state(self) -> dict[str, object]:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def load_style_image(self) -> None:
        style = self.style.get()
        self.frames = {
            state: self.load_sheet(path, count, airborne=state == "flight")
            for state, (path, count) in ANIMATION_SHEETS[style].items()
        }
        idle, flight = self.frames["idle"][0], self.frames["flight"][0]
        flight_cycle = self.frames["flight"]
        # VPet-inspired Start -> Loop -> End transitions. Reusing real frames keeps
        # pixel edges clean; blending pixel art produced the old floating specks.
        self.frames["takeoff"] = [idle, self.frames["idle"][1], flight_cycle[1], flight]
        self.frames["landing"] = [flight_cycle[-2], flight_cycle[-1], self.frames["idle"][-1], idle]
        if "sleep" not in self.frames:
            self.frames["sleep"] = self.make_sleep_frames(idle)
        sleep_cycle = self.frames["sleep"]
        settle = self.frames["idle"][min(3, len(self.frames["idle"]) - 1)]
        # Short authored-pose transitions keep sleep from snapping straight from
        # a tall standing silhouette into the low tucked pose.
        self.frames["sleep_enter"] = [idle, settle, sleep_cycle[0], sleep_cycle[1]]
        self.frames["sleep_exit"] = [sleep_cycle[1], sleep_cycle[0], settle, idle]
        self.last_render = None
        self.render_image("idle", 0)

    def load_sheet(self, path: Path, count: int, airborne: bool) -> list[Image.Image]:
        sheet = Image.open(path).convert("RGBA")
        cells: list[Image.Image] = []
        for index in range(count):
            left = round(index * sheet.width / count)
            right = round((index + 1) * sheet.width / count)
            cell = sheet.crop((left, 0, right, sheet.height))
            cells.append(self.clean_specks(cell))

        if not airborne:
            cells = self.align_grounded_cells(cells)

        # Never crop and centre frames independently: changing silhouettes would
        # move their visual centre and make the entire pet jitter. A shared union
        # box preserves the coordinates authored inside every sprite-sheet cell.
        bounds = [cell.getchannel("A").getbbox() for cell in cells]
        visible = [box for box in bounds if box]
        if visible:
            shared_box = (
                min(box[0] for box in visible), min(box[1] for box in visible),
                max(box[2] for box in visible), max(box[3] for box in visible),
            )
            cropped = [cell.crop(shared_box) for cell in cells]
        else:
            cropped = cells

        source_width, source_height = cropped[0].size
        scale = min(IMAGE_SIZE / source_width, IMAGE_SIZE / source_height)
        frames: list[Image.Image] = []
        for image in cropped:
            size = (max(1, round(source_width * scale)), max(1, round(source_height * scale)))
            resample = Image.Resampling.NEAREST if self.style.get() == "pixel" else Image.Resampling.LANCZOS
            image = image.resize(size, resample)
            frame = Image.new("RGBA", (PET_SIZE, PET_SIZE))
            x = (PET_SIZE - image.width) // 2
            y = (PET_SIZE - image.height) // 2 if airborne else PET_SIZE - image.height - 3
            frame.alpha_composite(image, (x, y))
            frames.append(self.clean_specks(frame))
        return frames

    @staticmethod
    def align_grounded_cells(cells: list[Image.Image]) -> list[Image.Image]:
        """Register standing frames by the centre and baseline of their feet."""
        anchors: list[tuple[float, int]] = []
        for cell in cells:
            alpha = cell.getchannel("A")
            box = alpha.getbbox()
            if not box:
                anchors.append((cell.width / 2, cell.height))
                continue
            # The lowest 6% of the visible character contains the contact claws,
            # while excluding nearly all tail/body silhouette changes.
            band_top = max(box[1], box[3] - max(6, round((box[3] - box[1]) * 0.06)))
            points = [
                (x, y) for y in range(band_top, box[3]) for x in range(box[0], box[2])
                if alpha.getpixel((x, y)) >= 40
            ]
            if points:
                anchors.append((sum(x for x, _y in points) / len(points), max(y for _x, y in points)))
            else:
                anchors.append(((box[0] + box[2]) / 2, box[3] - 1))

        target_x = sorted(anchor[0] for anchor in anchors)[len(anchors) // 2]
        target_y = max(anchor[1] for anchor in anchors)
        padding = 24
        aligned: list[Image.Image] = []
        for cell, (anchor_x, anchor_y) in zip(cells, anchors):
            canvas = Image.new("RGBA", (cell.width + padding * 2, cell.height + padding * 2))
            dx = padding + round(target_x - anchor_x)
            dy = padding + target_y - anchor_y
            canvas.alpha_composite(cell, (dx, dy))
            aligned.append(canvas)
        return aligned

    @staticmethod
    def make_sleep_frames(idle: Image.Image) -> list[Image.Image]:
        frames: list[Image.Image] = []
        for squash in (0.88, 0.84, 0.88):
            body = idle.resize((idle.width, round(idle.height * squash)), Image.Resampling.NEAREST)
            frame = Image.new("RGBA", idle.size)
            frame.alpha_composite(body, (0, idle.height - body.height))
            frames.append(frame)
        return frames

    @staticmethod
    def clean_specks(image: Image.Image) -> Image.Image:
        """Keep the pet body and remove disconnected fragments from adjacent cells."""
        result = image.copy()
        alpha = result.getchannel("A").point(lambda value: 0 if value < 40 else value)
        pixels = alpha.load()
        width, height = alpha.size
        visited: set[tuple[int, int]] = set()
        components: list[list[tuple[int, int]]] = []
        for start_y in range(height):
            for start_x in range(width):
                if not pixels[start_x, start_y] or (start_x, start_y) in visited:
                    continue
                stack = [(start_x, start_y)]
                component: list[tuple[int, int]] = []
                visited.add((start_x, start_y))
                while stack:
                    x, y = stack.pop()
                    component.append((x, y))
                    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                        if 0 <= nx < width and 0 <= ny < height and pixels[nx, ny] and (nx, ny) not in visited:
                            visited.add((nx, ny))
                            stack.append((nx, ny))
                components.append(component)

        if components:
            largest = max(components, key=len)
            # A generated sheet can leak a sizeable piece of the neighbouring
            # frame into a cell, so a fixed four-pixel threshold is insufficient.
            # Qihei's body, eye and feather accents share one alpha component.
            for component in components:
                if component is largest:
                    continue
                for x, y in component:
                    pixels[x, y] = 0
        result.putalpha(alpha)
        return result

    def render_image(self, state: str, frame_index: int) -> None:
        render_key = (state, frame_index, self.facing_left)
        if render_key == self.last_render:
            return
        frame = self.frames[state][frame_index]
        frame = ImageOps.mirror(frame) if self.facing_left else frame
        self.tk_image = ImageTk.PhotoImage(frame)
        self.canvas.itemconfigure(self.image_item, image=self.tk_image)
        self.last_render = render_key

    def switch_style(self) -> None:
        self.load_style_image()
        self.save_state()
        name = "像素版" if self.style.get() == "pixel" else "写实版"
        self.say(f"已切换到{name}。两套羽毛，我都要。")

    def tick(self) -> None:
        now = time.perf_counter()
        if self.action and now >= float(self.action["until"]):
            self.action = None
        flight_progress: float | None = None
        if self.flight and not self.animation_paused.get():
            elapsed = now - self.flight["start"]
            progress = min(1.0, elapsed / self.flight["duration"])
            flight_progress = progress
            smooth = progress * progress * (3 - 2 * progress)
            x = self.flight["sx"] + (self.flight["tx"] - self.flight["sx"]) * smooth
            y = (self.flight["sy"] + (self.flight["ty"] - self.flight["sy"]) * smooth
                 - math.sin(math.pi * progress) * self.flight["arc"])
            self.root.geometry(f"+{int(x)}+{int(y)}")
            if progress >= 1:
                if self.flight.get("reward"):
                    unlock = self.progress.record("flight")
                    if unlock:
                        self.say(unlock, 5200)
                self.flight = None
                self.save_state()
                self.root.after(random.randint(24000, 45000), self.start_flight)
        if self.animation_paused.get():
            state, frame_index = "idle", 0
        elif self.action:
            state = str(self.action["name"])
            frame_index = int((now - float(self.action["started"])) * ACTION_FPS[state]) % len(self.frames[state])
        elif self.sleeping:
            state = "sleep"
            frame_index = int((now - self.started) * ACTION_FPS[state]) % len(self.frames[state])
        elif self.flight and flight_progress is not None and flight_progress < .12:
            state = "takeoff"
            frame_index = min(len(self.frames[state]) - 1, int(flight_progress / .12 * len(self.frames[state])))
        elif self.flight and flight_progress is not None and flight_progress > .84:
            state = "landing"
            frame_index = min(len(self.frames[state]) - 1, int((flight_progress - .84) / .16 * len(self.frames[state])))
        else:
            state = "flight" if self.flight else "idle"
            if self.flight:
                frame_index = int((now - self.started) * ACTION_FPS[state]) % len(self.frames[state])
            else:
                frame_index = self.idle_frame(now)
        self.render_image(state, frame_index)
        bob = math.sin((now - self.started) * 8) * 2 if self.flight else 0
        self.canvas.coords(self.image_item, PET_SIZE // 2, PET_SIZE // 2 + bob)
        # Follow every kind of movement, including dragging, style changes and
        # autonomous flight. Previously this only ran inside the flight branch.
        if self.bubble.state() == "normal":
            self.place_bubble()
        self.root.after(33, self.tick)

    def idle_frame(self, now: float) -> int:
        """Mostly hold a calm pose, with occasional non-periodic idle gestures."""
        frame_count = len(self.frames["idle"])
        if self.idle_motion_started is None and now >= self.next_idle_motion:
            self.idle_motion_started = now

        if self.idle_motion_started is not None:
            # Play the full sheet forward and gently return to neutral once.
            sequence = list(range(frame_count)) + list(range(frame_count - 2, 0, -1)) + [0]
            index = int((now - self.idle_motion_started) * 3.2)
            if index < len(sequence):
                return sequence[index]
            self.idle_motion_started = None
            self.next_idle_motion = now + random.uniform(10.0, 22.0)

        # A five-second, heavily held breathing cycle. Frame zero occupies 80%
        # of it so Qihei looks watchful instead of constantly fidgeting.
        breath = (0, 0, 0, 0, min(1, frame_count - 1), min(1, frame_count - 1), 0, 0, 0, 0)
        return breath[int((now - self.started) * 2) % len(breath)]

    def start_flight(self, reward: bool = False) -> None:
        if self.flight or self.sleeping or self.action or self.drag_origin is not None or self.animation_paused.get():
            return
        if self.energy < 10:
            if reward:
                self.say("今天的翅膀已经提交休整申请。让我睡一会儿再侦察。", 5200)
            return
        sx, sy = self.root.winfo_x(), self.root.winfo_y()
        max_x = max(15, self.root.winfo_screenwidth() - PET_SIZE - 15)
        max_y = max(15, self.root.winfo_screenheight() - PET_SIZE - 55)
        if self.follow_cursor.get():
            tx = min(max(15, self.root.winfo_pointerx() - PET_SIZE // 2), max_x)
            ty = min(max(15, self.root.winfo_pointery() - PET_SIZE - 25), max_y)
        else:
            tx, ty = random.randint(15, max_x), random.randint(15, max_y)
        if abs(tx - sx) < 260:
            tx = 15 if sx > max_x / 2 else max_x
        # The generated pixel sheet faces left, while the realistic sheet faces
        # right. Each appearance therefore needs its own mirroring rule.
        should_mirror = self.should_mirror_for_flight(self.style.get(), sx, tx)
        if should_mirror != self.facing_left:
            self.facing_left = should_mirror
            self.last_render = None
        self.flight = {
            "start": time.perf_counter(), "duration": random.uniform(2.4, 3.8),
            "sx": sx, "sy": sy, "tx": tx, "ty": ty, "arc": random.randint(55, 120),
            "reward": reward,
        }

    @staticmethod
    def should_mirror_for_flight(style: str, source_x: float, target_x: float) -> bool:
        source_faces_left = style == "pixel"
        return (target_x > source_x) if source_faces_left else (target_x < source_x)

    def restore_position(self, state: dict[str, object]) -> None:
        max_x = max(0, self.root.winfo_screenwidth() - PET_SIZE)
        max_y = max(0, self.root.winfo_screenheight() - PET_SIZE - 35)
        try:
            x, y = int(state["x"]), int(state["y"])
        except (ValueError, KeyError, TypeError):
            x, y = max_x - 25, max_y - 25
        self.root.geometry(f"{PET_SIZE}x{PET_SIZE}+{min(max(0, x), max_x)}+{min(max(0, y), max_y)}")

    def save_state(self) -> None:
        data = {"x": self.root.winfo_x(), "y": self.root.winfo_y(), "style": self.style.get(),
                "companion": self.progress.to_dict()}
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def say(self, text: str, duration: int = 4800) -> None:
        if self.bubble_timer:
            self.root.after_cancel(self.bubble_timer)
        if self.bubble_type_timer:
            self.root.after_cancel(self.bubble_type_timer)
        height = max(112, min(190, 78 + ((len(text) + 18) // 19) * 20))
        self.draw_bubble(height)
        self.bubble.update_idletasks()
        self.place_bubble()
        self.bubble.deiconify()
        index = 0

        def type_next() -> None:
            nonlocal index
            index = min(len(text), index + 2)
            self.bubble_canvas.itemconfigure(self.bubble_text_item, text=text[:index])
            if index < len(text):
                self.bubble_type_timer = self.root.after(22, type_next)
            else:
                self.bubble_type_timer = None

        type_next()
        self.bubble_timer = self.root.after(duration, self.hide_bubble)

    def draw_bubble(self, height: int) -> None:
        width = 310
        self.bubble_canvas.configure(width=width, height=height)
        self.bubble_canvas.delete("all")
        bubble_x = min(
            max(8, self.root.winfo_x() - width + PET_SIZE // 2 + 25),
            self.root.winfo_screenwidth() - width - 8,
        )
        pet_center_x = self.root.winfo_x() + PET_SIZE // 2
        tail_tip = min(width - 25, max(30, pet_center_x - bubble_x))
        tail_left = max(18, tail_tip - 25)
        tail_right = min(width - 15, tail_tip + 16)
        points = [
            15, 8, width - 15, 8, width - 5, 18, width - 5, height - 34,
            width - 15, height - 24, tail_right, height - 24, tail_tip, height - 5,
            tail_left, height - 24, 15, height - 24, 5, height - 34, 5, 18,
        ]
        self.bubble_canvas.create_polygon(
            points, smooth=True, splinesteps=18, fill="#171923",
            outline="#b63a32", width=2,
        )
        self.bubble_canvas.create_line(18, 34, width - 18, 34, fill="#6f542c", width=1)
        self.bubble_canvas.create_oval(18, 17, 25, 24, fill="#d43b32", outline="")
        self.bubble_canvas.create_text(
            31, 21, text=f"漆黑 · {self.progress.mood}", anchor="w",
            fill="#d5aa53", font=("Microsoft YaHei UI", 8, "bold"),
        )
        self.bubble_text_item = self.bubble_canvas.create_text(
            18, 45, text="", anchor="nw", width=274, justify="left",
            fill="#f0ede4", font=("Microsoft YaHei UI", 9),
        )

    def place_bubble(self) -> None:
        width, height = int(self.bubble_canvas["width"]), int(self.bubble_canvas["height"])
        x = min(max(8, self.root.winfo_x() - width + PET_SIZE // 2 + 25),
                self.root.winfo_screenwidth() - width - 8)
        self.bubble.geometry(f"+{x}+{max(8, self.root.winfo_y() - height + 20)}")

    def hide_bubble(self) -> None:
        self.bubble.withdraw()
        self.bubble_timer = None

    def make_tool_window(self, title: str, geometry: str) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry(geometry)
        window.minsize(390, 230)
        window.attributes("-topmost", True)
        window.configure(bg=UI["raven"])

        dossier = tk.Frame(window, bg=UI["raven"])
        dossier.pack(fill="x", padx=14, pady=(11, 0))
        tk.Label(
            dossier, text="RAVEN DOSSIER", bg=UI["raven"], fg=UI["gold"],
            font=("Consolas", 8, "bold"),
        ).pack(side="left")
        tk.Label(
            dossier, text=title, bg=UI["raven"], fg=UI["paper"],
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right")
        rule = tk.Canvas(window, height=5, bg=UI["raven"], highlightthickness=0)
        rule.pack(fill="x", padx=14, pady=(5, 2))
        rule.create_line(0, 1, 1000, 1, fill=UI["gold_dim"], width=1)
        rule.create_line(0, 3, 115, 3, fill=UI["blood"], width=2)
        self.root.after_idle(lambda: self.style_tool_children(window) if window.winfo_exists() else None)
        return window

    def style_tool_children(self, parent: tk.Misc) -> None:
        """Apply one Raven Dossier visual system to legacy Tk tool widgets."""
        primary_actions = {"投掷", "提问", "新增", "开始专注", "开始", "保存"}
        for widget in parent.winfo_children():
            if isinstance(widget, tk.Button):
                primary = str(widget.cget("text")).split("\n", 1)[0] in primary_actions
                widget.configure(
                    relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
                    bg=UI["gold"] if primary else UI["panel_2"],
                    fg=UI["void"] if primary else UI["paper"],
                    activebackground=UI["blood"], activeforeground="#ffffff",
                    font=("Microsoft YaHei UI", 9, "bold" if primary else "normal"),
                )
            elif isinstance(widget, tk.Entry):
                widget.configure(
                    relief="flat", bd=0, bg=UI["void"], fg=UI["paper"],
                    insertbackground=UI["gold"], highlightthickness=1,
                    highlightbackground="#343A4D", highlightcolor=UI["gold"],
                )
            elif isinstance(widget, tk.Text):
                widget.configure(
                    relief="flat", bd=0, bg=UI["panel"], fg=UI["paper"],
                    insertbackground=UI["gold"], selectbackground=UI["blood"],
                    highlightthickness=1, highlightbackground="#30364A",
                )
            elif isinstance(widget, tk.Listbox):
                widget.configure(
                    relief="flat", bd=0, bg=UI["panel"], fg=UI["paper"],
                    selectbackground=UI["blood"], selectforeground="#ffffff",
                    highlightthickness=1, highlightbackground="#30364A",
                )
            elif isinstance(widget, tk.Frame):
                old_bg = str(widget.cget("bg")).lower()
                widget.configure(bg=UI["panel"] if old_bg in {"#202433", "#202334"} else UI["raven"])
            elif isinstance(widget, tk.Label):
                old_bg = str(widget.cget("bg")).lower()
                widget.configure(
                    bg=UI["panel"] if old_bg in {"#202433", "#202334"} else UI["raven"],
                    fg=UI["paper"] if str(widget.cget("fg")).lower() not in {"#d4a348", "#d5aa53"} else UI["gold"],
                )
            elif isinstance(widget, tk.Scale):
                widget.configure(
                    bg=UI["raven"], fg=UI["paper"], troughcolor=UI["void"],
                    activebackground=UI["gold"], highlightthickness=0,
                )
            self.style_tool_children(widget)

    def open_story_window(self) -> None:
        self.progress.record("story")
        self.save_state()
        window = self.make_tool_window("漆黑的冒险档案", "720x620")
        status = tk.Label(
            window, text="", bg=UI["raven"], fg=UI["muted"], anchor="w",
            font=("Consolas", 8),
        )
        status.pack(fill="x", padx=16, pady=(5, 2))
        text = tk.Text(
            window, bg=UI["panel"], fg=UI["paper"], insertbackground=UI["gold"],
            wrap="word", font=("Microsoft YaHei UI", 10), padx=14, pady=12,
        )
        text.pack(fill="both", expand=True, padx=16, pady=(4, 8))

        def reload_archive() -> None:
            data = self.adventure_archive.load()
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", self.adventure_archive.render())
            text.configure(state="disabled")
            status.configure(text=f"LIVE ARCHIVE  //  {data.get('source', '本地')}  //  {data.get('updated_at') or '等待首次同步'}")

        tk.Button(window, text="重新载入最新档案", command=reload_archive).pack(fill="x", padx=16, pady=(0, 14))
        reload_archive()
        last_mtime = self.adventure_archive.path.stat().st_mtime if self.adventure_archive.path.exists() else 0.0

        def watch_archive() -> None:
            nonlocal last_mtime
            if not window.winfo_exists():
                return
            current_mtime = self.adventure_archive.path.stat().st_mtime if self.adventure_archive.path.exists() else 0.0
            if current_mtime != last_mtime:
                last_mtime = current_mtime
                reload_archive()
            window.after(3000, watch_archive)

        window.after(3000, watch_archive)

    def open_question_window(self) -> None:
        window = self.make_tool_window("向漆黑提问", "570x430")
        transcript = tk.Text(
            window, bg="#202433", fg="#eee9dc", insertbackground="#eee9dc",
            wrap="word", font=("Microsoft YaHei UI", 10), padx=12, pady=10,
        )
        transcript.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        transcript.insert("end", "漆黑：问吧。剧情、人物、线索，或者别的。联网密钥存在时我会调用在线模型。\n\n")
        row = tk.Frame(window, bg="#181b27")
        row.pack(fill="x", padx=10, pady=(5, 10))
        question = tk.Entry(row, font=("Microsoft YaHei UI", 10), bg="#f5f2ea", fg="#22242c")
        question.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ask_button = tk.Button(row, text="提问", width=8)
        ask_button.pack(side="right")

        def append_answer(user_text: str, answer: str) -> None:
            if not window.winfo_exists():
                return
            transcript.insert("end", f"漆黑：{answer}\n\n")
            transcript.see("end")
            ask_button.configure(state="normal")
            self.chat_history.extend([
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": answer},
            ])
            unlock = self.progress.record("conversation")
            self.save_state()
            if unlock:
                self.say(unlock, 5200)

        def ask() -> None:
            user_text = question.get().strip()
            if not user_text:
                return
            question.delete(0, "end")
            transcript.insert("end", f"你：{user_text}\n")
            transcript.see("end")
            ask_button.configure(state="disabled")

            def worker() -> None:
                answer = ask_openai(user_text, self.chat_history, self.api_usage)
                self.root.after(0, lambda: append_answer(user_text, answer))

            threading.Thread(target=worker, daemon=True).start()

        ask_button.configure(command=ask)
        question.bind("<Return>", lambda _event: ask())
        question.focus_set()

    def open_api_usage_window(self) -> None:
        window = self.make_tool_window("API 使用情况", "680x545")
        window.minsize(590, 500)

        has_key = bool(os.getenv("OPENAI_API_KEY", "").strip())
        model = os.getenv("QIHEI_OPENAI_MODEL", "gpt-5.4-mini")
        status_row = tk.Frame(window, bg=UI["raven"])
        status_row.pack(fill="x", padx=18, pady=(8, 12))
        tk.Label(
            status_row, text="●  在线 API 已配置" if has_key else "○  当前使用本地档案",
            bg=UI["raven"], fg="#72B887" if has_key else UI["muted"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        tk.Label(
            status_row, text=model, bg=UI["raven"], fg=UI["gold"],
            font=("Consolas", 10, "bold"),
        ).pack(side="right")

        cards = tk.Frame(window, bg=UI["raven"])
        cards.pack(fill="x", padx=18)
        values: dict[str, tk.Label] = {}

        def add_card(key: str, title: str) -> None:
            card = tk.Frame(cards, bg=UI["panel"], padx=14, pady=10)
            card.pack(side="left", fill="both", expand=True, padx=(0, 8) if key != "tokens" else 0)
            tk.Label(
                card, text=title, bg=UI["panel"], fg=UI["muted"],
                font=("Microsoft YaHei UI", 8),
            ).pack(anchor="w")
            values[key] = tk.Label(
                card, text="0", bg=UI["panel"], fg=UI["paper"],
                font=("Consolas", 18, "bold"),
            )
            values[key].pack(anchor="w", pady=(3, 0))

        add_card("calls", "API 调用")
        add_card("success", "成功 / 失败")
        add_card("tokens", "累计 TOKEN")

        detail = tk.Label(
            window, text="", justify="left", anchor="w", bg=UI["raven"],
            fg=UI["paper"], font=("Microsoft YaHei UI", 9),
        )
        detail.pack(fill="x", padx=18, pady=(14, 8))

        tk.Label(
            window, text="最近请求 // 不保存问题与回答正文", anchor="w",
            bg=UI["raven"], fg=UI["gold"], font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(fill="x", padx=18, pady=(2, 5))
        recent = tk.Text(
            window, height=10, bg=UI["void"], fg=UI["paper"], wrap="none",
            font=("Consolas", 9), padx=10, pady=8, state="disabled",
        )
        recent.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        tk.Label(
            window,
            text="这里只统计漆黑自身产生的请求；账户账单与组织总用量请以 OpenAI 官方 Usage 页面为准。",
            bg=UI["raven"], fg=UI["muted"], wraplength=630, justify="left",
            font=("Microsoft YaHei UI", 8),
        ).pack(fill="x", padx=18, pady=(0, 12))

        def refresh() -> None:
            if not window.winfo_exists():
                return
            data = self.api_usage.snapshot()
            baseline = self.api_usage_baseline
            calls = int(data.get("api_calls", 0))
            successes = int(data.get("successful_calls", 0))
            failures = int(data.get("failed_calls", 0))
            tokens = int(data.get("total_tokens", 0))
            session_calls = calls - int(baseline.get("api_calls", 0))
            session_tokens = tokens - int(baseline.get("total_tokens", 0))
            values["calls"].configure(text=f"{calls:,}")
            values["success"].configure(text=f"{successes:,} / {failures:,}")
            values["tokens"].configure(text=f"{tokens:,}")
            detail.configure(
                text=(
                    f"本次运行：{session_calls:,} 次调用 · {session_tokens:,} tokens\n"
                    f"输入 {int(data.get('input_tokens', 0)):,} · 输出 {int(data.get('output_tokens', 0)):,} · "
                    f"本地档案回答 {int(data.get('local_fallbacks', 0)):,}\n"
                    f"上次在线请求：{data.get('last_request_at') or '尚无'}"
                )
            )
            lines = []
            status_names = {"success": "成功", "error": "失败", "local": "本地"}
            for item in list(data.get("recent", []))[:12]:
                token_text = f"{int(item.get('input_tokens', 0))}+{int(item.get('output_tokens', 0))} tok"
                latency = f"{int(item.get('latency_ms', 0))} ms" if item.get("latency_ms") else "—"
                error = f" · {item.get('error')}" if item.get("error") else ""
                lines.append(
                    f"{str(item.get('at', ''))[5:19]}  {status_names.get(item.get('status'), item.get('status')):<4}  "
                    f"{token_text:>13}  {latency:>8}  {item.get('model', '')}{error}"
                )
            recent.configure(state="normal")
            recent.delete("1.0", "end")
            recent.insert("1.0", "\n".join(lines) if lines else "尚无 API 请求记录。")
            recent.configure(state="disabled")
            window.after(1500, refresh)

        refresh()

    def open_dice_window(self) -> None:
        window = self.make_tool_window("漆黑的骰盅", "620x570")
        window.minsize(540, 510)
        tk.Label(
            window, text="命运记录 // 输入骰式，或从常用骰中选择",
            bg=UI["raven"], fg=UI["muted"], anchor="w",
            font=("Microsoft YaHei UI", 9),
        ).pack(fill="x", padx=18, pady=(8, 5))

        top = tk.Frame(window, bg=UI["raven"])
        top.pack(fill="x", padx=18, pady=(0, 10))
        expression = tk.Entry(top, font=("Consolas", 15), bg=UI["void"], fg=UI["paper"])
        expression.insert(0, "d20")
        expression.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 10))

        result_card = tk.Frame(window, bg=UI["panel"], padx=16, pady=12)
        result_card.pack(fill="x", padx=18)
        result_number = tk.Label(
            result_card, text="—", width=5, bg=UI["panel"], fg=UI["gold"],
            font=("Consolas", 30, "bold"), anchor="center",
        )
        result_number.pack(side="left", padx=(0, 14))
        result_label = tk.Label(
            result_card, text="等待投掷\n示例：d20、2d6+3、d100-10",
            bg=UI["panel"], fg=UI["paper"], font=("Microsoft YaHei UI", 10),
            wraplength=400, justify="left", anchor="w",
        )
        result_label.pack(side="left", fill="x", expand=True)

        quick = tk.Frame(window, bg=UI["raven"])
        quick.pack(fill="x", padx=18, pady=10)
        for column, sides in enumerate((4, 6, 8, 10, 12, 20, 100)):
            quick.columnconfigure(column, weight=1)
            tk.Button(quick, text=f"d{sides}", command=lambda s=sides: roll(f"d{s}"), width=5).grid(
                row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0)
            )

        tk.Label(
            window, text="ROLL LOG / 本次记录", bg=UI["raven"], fg=UI["gold"],
            anchor="w", font=("Consolas", 8, "bold"),
        ).pack(fill="x", padx=18, pady=(2, 4))
        history = tk.Listbox(
            window, bg=UI["panel"], fg=UI["paper"], selectbackground=UI["blood"],
            font=("Consolas", 10), height=7,
        )
        history.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        def roll(value: str | None = None) -> None:
            if value:
                expression.delete(0, "end")
                expression.insert(0, value)
            try:
                outcome = roll_dice(expression.get())
            except ValueError as error:
                result_number.configure(text="!")
                result_label.configure(text=f"骰式无法识别\n{error}", fg="#E97870")
                expression.focus_set()
                return
            modifier = outcome["modifier"]
            detail = f"{outcome['rolls']}" + (f" {modifier:+d}" if modifier else "")
            line = f"{outcome['expression']} → {outcome['total']}  {detail}"
            history.insert(0, line)
            result_number.configure(text=str(outcome["total"]), fg=UI["gold"])
            result_label.configure(text=f"{outcome['expression']}  //  {detail}\n{outcome['comment']}", fg=UI["paper"])
            self.say(f"{outcome['expression']}：{outcome['total']}。{outcome['comment']}", 5200)

        tk.Button(top, text="投掷", width=9, command=roll).pack(side="right", fill="y")

        def roll_intel_advantage() -> None:
            if self.progress.intel_tokens <= 0:
                result_number.configure(text="0", fg="#E97870")
                result_label.configure(text="没有可用的情报优势\n先让漆黑完成一次成功侦察。", fg="#E97870")
                return
            first, second = roll_dice("d20"), roll_dice("d20")
            kept = max(first["total"], second["total"])
            self.progress.intel_tokens -= 1
            self.save_state()
            line = f"情报优势 d20 → {kept}  [{first['total']}, {second['total']}]"
            history.insert(0, line)
            result_number.configure(text=str(kept), fg=UI["gold"])
            result_label.configure(text=f"情报优势 // {first['total']} 与 {second['total']}，取高\n剩余 {self.progress.intel_tokens} 次", fg=UI["paper"])
            self.say(f"情报优势：{first['total']}、{second['total']}，取 {kept}。我看见的路不会白看。", 6200)

        tk.Button(
            window, text=f"使用情报优势  ·  剩余 {self.progress.intel_tokens}",
            command=roll_intel_advantage, bg=UI["blood"], fg="#ffffff",
        ).pack(fill="x", padx=18, pady=(0, 14))
        expression.bind("<Return>", lambda _event: roll())
        expression.focus_set()

    def open_memo_window(self) -> None:
        window = self.make_tool_window("漆黑的备忘录", "620x450")
        listbox = tk.Listbox(
            window, bg="#202433", fg="#eee9dc", selectbackground="#6e2632",
            font=("Microsoft YaHei UI", 10), height=12,
        )
        listbox.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        input_frame = tk.Frame(window, bg="#181b27")
        input_frame.pack(fill="x", padx=10, pady=5)
        memo_text = tk.Entry(input_frame, font=("Microsoft YaHei UI", 10), bg="#f5f2ea", fg="#22242c")
        memo_text.pack(fill="x", pady=(0, 5))
        reminder = tk.Entry(input_frame, font=("Consolas", 10), bg="#f5f2ea", fg="#555")
        reminder.insert(0, "")
        reminder.pack(fill="x")
        tk.Label(
            input_frame, text="提醒时间可留空，格式：2026-08-16 09:30",
            bg="#181b27", fg="#aaa7a0", anchor="w",
        ).pack(fill="x")

        def refresh() -> None:
            listbox.delete(0, "end")
            for item in self.memo_store.items:
                status = "✓" if item.get("done") else "·"
                alarm = f"  ⏰{item['remind_at'].replace('T', ' ')}" if item.get("remind_at") else ""
                listbox.insert("end", f"{status} {item['text']}{alarm}")

        def selected_index() -> int | None:
            selection = listbox.curselection()
            return selection[0] if selection else None

        def add() -> None:
            try:
                self.memo_store.add(memo_text.get(), reminder.get())
            except ValueError as error:
                messagebox.showerror("备忘录", str(error), parent=window)
                return
            memo_text.delete(0, "end")
            reminder.delete(0, "end")
            refresh()

        def toggle_done() -> None:
            index = selected_index()
            if index is None:
                return
            item = self.memo_store.items[index]
            item["done"] = not item.get("done", False)
            self.memo_store.save()
            refresh()

        def delete() -> None:
            index = selected_index()
            if index is None:
                return
            del self.memo_store.items[index]
            self.memo_store.save()
            refresh()

        buttons = tk.Frame(window, bg="#181b27")
        buttons.pack(fill="x", padx=10, pady=(5, 10))
        tk.Button(buttons, text="新增", command=add, width=9).pack(side="left")
        tk.Button(buttons, text="完成/恢复", command=toggle_done, width=11).pack(side="left", padx=6)
        tk.Button(buttons, text="删除", command=delete, width=9).pack(side="left")
        refresh()

    def toggle_sleep(self) -> None:
        self.flight = None
        self.action = None
        self.sleeping = not self.sleeping
        now = time.perf_counter()
        if self.sleeping:
            self.action = {"name": "sleep_enter", "started": now, "until": now + 0.8}
            self.say("进入低功耗监听。重要线索叫醒我。", 4300)
        else:
            self.action = {"name": "sleep_exit", "started": now, "until": now + 0.8}
            self.energy = min(100, self.energy + 8)
            self.started = now
            self.say("醒了。桌面在我睡着时有招供吗？", 4300)
        self.save_state()

    def update_vitals(self) -> None:
        now = time.time()
        minutes = max(0.0, (now - self.last_vitals_update) / 60)
        self.last_vitals_update = now
        if self.sleeping:
            self.energy = min(100, self.energy + minutes * 1.8)
            self.progress.morale = min(100, self.progress.morale + round(minutes * 0.25))
        else:
            self.energy = max(0, self.energy - minutes * 0.12)
        if self.energy < 18 and not self.sleeping and random.random() < 0.35:
            self.say("情报员申请休整。我的眼睛还红，不代表精神很好。")
        self.save_state()
        self.root.after(60000, self.update_vitals)

    def show_status(self) -> None:
        mode = "休息中" if self.sleeping else "巡查中"
        self.say(
            f"{mode} · {self.progress.mood}\n"
            f"羁绊 Lv.{self.progress.level}「{self.progress.bond_rank}」 · 亲密 {self.progress.bond}\n"
            f"侦察 Lv.{self.progress.scout_level}「{self.progress.ability}」 · 精力 {round(self.energy)}",
            7600,
        )

    def open_companion_window(self) -> None:
        window = self.make_tool_window("漆黑 · 羁绊与养成", "640x470")
        window.minsize(560, 440)
        title = tk.Label(window, text=f"漆黑  Lv.{self.progress.level}　{self.progress.bond_rank}",
                         bg="#181b27", fg="#d5aa53", font=("Microsoft YaHei UI", 15, "bold"))
        title.pack(pady=(18, 4))
        tk.Label(window, text=f"当前心情：{self.progress.mood}　|　侦察能力：{self.progress.ability}",
                 bg="#181b27", fg="#eee9dc", font=("Microsoft YaHei UI", 10)).pack(pady=(0, 14))

        panel = tk.Frame(window, bg="#202433", padx=18, pady=14)
        panel.pack(fill="x", padx=18)
        panel.columnconfigure(1, weight=1)

        def meter(label: str, value: float, color: str) -> None:
            row = panel.grid_size()[1]
            tk.Label(panel, text=label, width=8, anchor="w", bg="#202433", fg="#eee9dc").grid(
                row=row, column=0, sticky="w", pady=6, padx=(0, 8)
            )
            canvas = tk.Canvas(panel, height=15, width=360, bg="#11131b", highlightthickness=0)
            canvas.grid(row=row, column=1, sticky="ew", pady=6)
            value_label = tk.Label(
                panel, text=f"{round(value):>3}/100", width=9, anchor="e",
                bg="#202433", fg="#d8d4ca", font=("Consolas", 10),
            )
            value_label.grid(row=row, column=2, sticky="e", pady=6, padx=(12, 2))

            def redraw(event: tk.Event) -> None:
                canvas.delete("fill")
                width = max(1, event.width)
                canvas.create_rectangle(0, 0, width * max(0, min(100, value)) / 100, 15,
                                        fill=color, outline="", tags="fill")

            canvas.bind("<Configure>", redraw)

        meter("亲密度", self.progress.bond, "#b63a32")
        meter("精力", self.progress.energy, "#4f7893")
        meter("士气", (self.progress.morale + 100) / 2, "#d5aa53")
        tk.Label(
            window,
            text=(f"羁绊经验：{self.progress.experience}　|　侦察经验：{self.progress.scout_xp}\n"
                  f"可用情报优势：{self.progress.intel_tokens}/3\n\n"
                  "互动、共同专注、讨论冒险会提升羁绊；飞行与侦察提升侦察能力。\n"
                  "重复互动有每日成长上限，休息会恢复精力与士气。"),
            bg="#181b27", fg="#d8d4ca", justify="left", wraplength=500,
            font=("Microsoft YaHei UI", 10),
        ).pack(padx=22, pady=18, anchor="w")

    def open_scout_window(self) -> None:
        window = self.make_tool_window("漆黑 · DND侦察行动", "600x470")
        tk.Label(window, text="选择侦察目标", bg="#181b27", fg="#d5aa53",
                 font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(16, 8))
        result = tk.Text(window, height=10, bg="#202433", fg="#eee9dc", wrap="word",
                         font=("Microsoft YaHei UI", 10), padx=12, pady=10)
        result.pack(fill="both", expand=True, padx=14, pady=10)
        missions = [
            ("旧钟楼外围", 11, "检查脚印、窗沿、钟绳和近期进入痕迹。"),
            ("鸟网残余路线", 13, "追踪脚环、放飞点和可能仍在工作的接力节点。"),
            ("石门监视者", 16, "高风险监视：确认谁在等待新乌鸦接近石门。"),
        ]

        def scout(name: str, dc: int, description: str) -> None:
            outcome = self.progress.scout(dc)
            result.delete("1.0", "end")
            if not outcome["ok"]:
                result.insert("end", outcome["text"])
                self.say(outcome["text"], 5200)
                return
            narrative = {
                "关键线索": "漆黑锁定了可交叉验证的异常细节。下一次相关剧情判定可使用情报优势。",
                "可靠情报": "路线和时间点能够相互印证。获得一次情报优势。",
                "模糊迹象": "发现异常，但尚不足以下结论；这是一条待复查线索。",
                "无功而返": "没有找到可靠痕迹。漆黑拒绝把猜测伪装成情报。",
            }[outcome["quality"]]
            self.adventure_archive.append_event(
                f"{name}：{outcome['text']} {narrative}", category="漆黑侦察",
            )
            result.insert("end", f"目标：{name}\n{description}\n\n{outcome['text']}\n\n{narrative}")
            self.save_state()
            self.say(f"{name}：{outcome['quality']}。{narrative}", 7600)

        buttons = tk.Frame(window, bg="#181b27")
        buttons.pack(fill="x", padx=12, pady=(2, 14))
        for name, dc, description in missions:
            tk.Button(buttons, text=f"{name}\nDC {dc}", width=17, height=2,
                      command=lambda n=name, d=dc, desc=description: scout(n, d, desc)).pack(side="left", padx=4)

    def open_focus_window(self) -> None:
        window = self.make_tool_window("漆黑的专注哨", "430x245")
        tk.Label(window, text="专注多久？漆黑替你守住时间。", bg="#181b27", fg="#eee9dc",
                 font=("Microsoft YaHei UI", 11)).pack(pady=(18, 10))
        minutes = tk.IntVar(value=25)
        scale = tk.Scale(window, from_=5, to=90, resolution=5, orient="horizontal", variable=minutes,
                         bg="#181b27", fg="#eee9dc", troughcolor="#6e2632", highlightthickness=0,
                         length=330)
        scale.pack()
        status = tk.Label(window, text="", bg="#181b27", fg="#d4a348", font=("Microsoft YaHei UI", 10))
        status.pack(pady=8)

        def start() -> None:
            duration = minutes.get()
            status.configure(text=f"计时 {duration} 分钟。开始，别切窗口。")
            self.say(f"专注哨开始：{duration} 分钟。我盯着时间，你盯着任务。", 5200)
            def complete() -> None:
                unlock = self.progress.record("focus")
                self.save_state()
                message = "专注时间到。停手，伸展，喝水。命令，不是建议。"
                if unlock:
                    message += "\n" + unlock
                self.say(message, 10000)
            self.root.after(duration * 60 * 1000, complete)

        tk.Button(window, text="开始专注", command=start, width=14).pack(pady=6)

    def check_reminders(self) -> None:
        for item in self.memo_store.due():
            self.say(f"提醒：{item['text']}\n时间到了。别装没看见，嘎。", 9000)
        self.root.after(30000, self.check_reminders)

    def schedule_chatter(self) -> None:
        self.root.after(random.randint(45000, 90000), self.idle_chatter)

    def idle_chatter(self) -> None:
        if not self.quiet:
            mood_lines = {
                "疲惫": ["我不是闭眼。我是在降低视觉频道功耗。", "今天先别开石门。连我都困了。"],
                "振奋": ["空域清晰，脑子也清晰。今天适合抓住一条大线索。", "嘎。给我一个方向，我能把秘密从屋顶上揪出来。"],
                "愉快": ["今日情报：和你搭档，暂时不算坏差事。", "桌面很安静。我喜欢安静里藏着线索。"],
                "烦躁": ["先说好，我心情不好时仍然专业，只是评论会更诚实。", "今天的风向和某些人的判断一样糟。"],
                "冷静": IDLE_LINES,
            }
            self.say(random.choice(mood_lines[self.progress.mood]))
        self.schedule_chatter()

    def toggle_quiet(self) -> None:
        self.quiet = not self.quiet
        self.menu.entryconfigure(self.quiet_menu_index, label="恢复碎碎念" if self.quiet else "安静一会儿")
        self.say("收到。静默侦察。" if self.quiet else "情报频道恢复。")

    def toggle_animation(self) -> None:
        if self.animation_paused.get():
            self.flight = None
            self.last_render = None
            self.say("暂停活动。终于有人理解保持安静也是一种才能。")
        else:
            self.started = time.perf_counter()
            self.say("恢复活动。空域仍然安全，暂时。")

    def hide_temporarily(self) -> None:
        self.hide_bubble()
        self.root.withdraw()
        self.root.after(5 * 60 * 1000, self.root.deiconify)

    def tell_time(self) -> None:
        self.say(f"现在是 {datetime.now():%H:%M}。时间没有失踪，只是你没看它。")

    def show_menu(self, event: tk.Event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def start_drag(self, event: tk.Event) -> None:
        if not self.flight:
            self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
            self.dragged = False

    def drag(self, event: tk.Event) -> None:
        if self.drag_origin:
            self.dragged = True
            self.root.geometry(f"+{event.x_root - self.drag_origin[0]}+{event.y_root - self.drag_origin[1]}")

    def end_drag(self, _event: tk.Event) -> None:
        if not self.drag_origin:
            return
        if self.dragged:
            self.save_state()
        self.drag_origin = None

    def close(self) -> None:
        self.save_state()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    try:
        required = list(STYLES.values()) + [
            path for style in ANIMATION_SHEETS.values() for path, _count in style.values()
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError("Missing pet assets: " + ", ".join(missing))
        QiheiPet().run()
    except Exception:
        (BASE_DIR / "launcher.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
