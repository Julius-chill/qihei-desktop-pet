from __future__ import annotations

import json
import math
import random
import threading
import time
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageOps, ImageTk

from qihei_core import MemoStore, STORY_SUMMARY, ask_openai, roll_dice

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "pet_state.json"
TRANSPARENT = "#010203"
PET_SIZE = 112
IMAGE_SIZE = 94
STYLES = {
    "pixel": BASE_DIR / "assets" / "raven_pixel_concept_v1.png",
    "realistic": BASE_DIR / "assets" / "raven_2d_concept_v4.png",
}
ANIMATION_SHEETS = {
    "pixel": {
        "idle": (BASE_DIR / "assets" / "raven_pixel_idle_sheet_v2.png", 6),
        "flight": (BASE_DIR / "assets" / "raven_pixel_flight_sheet_v2.png", 8),
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
CLICK_LINES = [
    "嘎？有任务？", "别戳，羽毛会乱。", "空中密探不是按钮。",
    "说吧，跟踪谁？", "我一直看着。只是没汇报。",
]

ACTION_FPS = {"flight": 11.0, "takeoff": 9.0, "landing": 9.0, "touch": 8.0, "sleep": 1.2}


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
        self.affection = int(state.get("affection", 20))
        self.energy = float(state.get("energy", 82))
        self.last_vitals_update = time.time()
        self.drag_origin: tuple[int, int] | None = None
        self.dragged = False
        self.quiet = False
        self.animation_paused = tk.BooleanVar(value=False)
        self.follow_cursor = tk.BooleanVar(value=False)
        self.bubble_timer: str | None = None
        self.frames: dict[str, list[Image.Image]] = {}
        self.tk_image: ImageTk.PhotoImage | None = None
        self.last_render: tuple[str, int, bool] | None = None
        self.image_item = self.canvas.create_image(PET_SIZE // 2, PET_SIZE // 2)
        self.memo_store = MemoStore(BASE_DIR / "notes.json")
        self.chat_history: list[dict[str, str]] = []

        self.bubble = tk.Toplevel(self.root)
        self.bubble.withdraw()
        self.bubble.overrideredirect(True)
        self.bubble.attributes("-topmost", True)
        self.bubble.configure(bg="#202334", padx=2, pady=2)
        self.bubble_label = tk.Label(
            self.bubble, bg="#f7f4eb", fg="#242331",
            font=("Microsoft YaHei UI", 9), wraplength=235, padx=11, pady=8,
        )
        self.bubble_label.pack()

        self.menu = tk.Menu(self.root, tearoff=False, font=("Microsoft YaHei UI", 9))
        self.menu.add_command(label="让漆黑说句话", command=lambda: self.say(random.choice(IDLE_LINES)))
        self.menu.add_command(label="出去飞一圈", command=self.start_flight)
        self.menu.add_command(label="摸摸漆黑", command=self.pet_qihei)
        self.menu.add_command(label="休息 / 醒来", command=self.toggle_sleep)
        self.menu.add_command(label="状态", command=self.show_status)
        self.menu.add_command(label="专注计时", command=self.open_focus_window)
        self.menu.add_command(label="向漆黑提问", command=self.open_question_window)
        self.menu.add_command(label="备忘录与提醒", command=self.open_memo_window)
        self.menu.add_command(label="DND骰子", command=self.open_dice_window)
        self.menu.add_command(label="冒险档案", command=self.open_story_window)
        self.menu.add_separator()
        style_menu = tk.Menu(self.menu, tearoff=False, font=("Microsoft YaHei UI", 9))
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
        self.canvas.bind("<Double-Button-1>", lambda _event: self.start_flight())
        self.canvas.bind("<Button-3>", self.show_menu)
        self.restore_position(state)
        self.load_style_image()
        self.tick()
        self.root.after(900, lambda: self.say("小一点，精神一点。这样总算像我了。嘎。", 4300))
        self.root.after(random.randint(9000, 15000), self.start_flight)
        self.schedule_chatter()
        self.root.after(5000, self.check_reminders)
        self.root.after(60000, self.update_vitals)

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
        self.frames["touch"] = self.make_touch_frames(self.frames["idle"])
        self.frames["sleep"] = self.make_sleep_frames(idle)
        self.last_render = None
        self.render_image("idle", 0)

    def load_sheet(self, path: Path, count: int, airborne: bool) -> list[Image.Image]:
        sheet = Image.open(path).convert("RGBA")
        cropped: list[Image.Image] = []
        for index in range(count):
            left = round(index * sheet.width / count)
            right = round((index + 1) * sheet.width / count)
            cell = sheet.crop((left, 0, right, sheet.height))
            bounds = cell.getchannel("A").getbbox()
            cropped.append(cell.crop(bounds) if bounds else cell)

        max_width = max(frame.width for frame in cropped)
        max_height = max(frame.height for frame in cropped)
        scale = min(IMAGE_SIZE / max_width, IMAGE_SIZE / max_height)
        frames: list[Image.Image] = []
        for image in cropped:
            size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            resample = Image.Resampling.NEAREST if self.style.get() == "pixel" else Image.Resampling.LANCZOS
            image = image.resize(size, resample)
            frame = Image.new("RGBA", (PET_SIZE, PET_SIZE))
            x = (PET_SIZE - image.width) // 2
            y = (PET_SIZE - image.height) // 2 if airborne else PET_SIZE - image.height - 3
            frame.alpha_composite(image, (x, y))
            frames.append(self.clean_specks(frame))
        return frames

    @staticmethod
    def make_touch_frames(idle: list[Image.Image]) -> list[Image.Image]:
        base = idle[0]
        frames = [base]
        for offset in (2, 4, 2):
            frame = Image.new("RGBA", base.size)
            frame.alpha_composite(base, (0, offset))
            frames.append(frame)
        frames.append(base)
        return frames

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
            if self.bubble.state() == "normal":
                self.place_bubble()
            if progress >= 1:
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

    def start_flight(self) -> None:
        if self.flight or self.sleeping or self.action or self.drag_origin is not None or self.animation_paused.get():
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
        # Source sheets face left. Mirror only when travelling to the right.
        should_mirror = tx > sx
        if should_mirror != self.facing_left:
            self.facing_left = should_mirror
            self.last_render = None
        self.flight = {
            "start": time.perf_counter(), "duration": random.uniform(2.4, 3.8),
            "sx": sx, "sy": sy, "tx": tx, "ty": ty, "arc": random.randint(55, 120),
        }

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
                "affection": self.affection, "energy": round(self.energy, 1)}
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def say(self, text: str, duration: int = 4800) -> None:
        if self.bubble_timer:
            self.root.after_cancel(self.bubble_timer)
        self.bubble_label.configure(text=text)
        self.bubble.update_idletasks()
        self.place_bubble()
        self.bubble.deiconify()
        self.bubble_timer = self.root.after(duration, self.hide_bubble)

    def place_bubble(self) -> None:
        width, height = self.bubble.winfo_reqwidth(), self.bubble.winfo_reqheight()
        x = min(max(8, self.root.winfo_x() - width + PET_SIZE // 2),
                self.root.winfo_screenwidth() - width - 8)
        self.bubble.geometry(f"+{x}+{max(8, self.root.winfo_y() - height + 20)}")

    def hide_bubble(self) -> None:
        self.bubble.withdraw()
        self.bubble_timer = None

    def make_tool_window(self, title: str, geometry: str) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry(geometry)
        window.attributes("-topmost", True)
        window.configure(bg="#181b27")
        return window

    def open_story_window(self) -> None:
        window = self.make_tool_window("漆黑的冒险档案", "620x520")
        text = tk.Text(
            window, bg="#202433", fg="#eee9dc", insertbackground="#eee9dc",
            wrap="word", font=("Microsoft YaHei UI", 10), padx=14, pady=12,
        )
        text.pack(fill="both", expand=True, padx=10, pady=10)
        text.insert("1.0", "《鸦影》战役档案\n\n" + STORY_SUMMARY)
        text.configure(state="disabled")

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

        def ask() -> None:
            user_text = question.get().strip()
            if not user_text:
                return
            question.delete(0, "end")
            transcript.insert("end", f"你：{user_text}\n")
            transcript.see("end")
            ask_button.configure(state="disabled")

            def worker() -> None:
                answer = ask_openai(user_text, self.chat_history)
                self.root.after(0, lambda: append_answer(user_text, answer))

            threading.Thread(target=worker, daemon=True).start()

        ask_button.configure(command=ask)
        question.bind("<Return>", lambda _event: ask())
        question.focus_set()

    def open_dice_window(self) -> None:
        window = self.make_tool_window("漆黑的骰盅", "500x420")
        top = tk.Frame(window, bg="#181b27")
        top.pack(fill="x", padx=10, pady=10)
        expression = tk.Entry(top, font=("Consolas", 12), bg="#f5f2ea", fg="#22242c")
        expression.insert(0, "d20")
        expression.pack(side="left", fill="x", expand=True, padx=(0, 8))
        result_label = tk.Label(
            window, text="输入骰式，例如 2d6+3", bg="#202433", fg="#eee9dc",
            font=("Microsoft YaHei UI", 10), wraplength=450, justify="left", padx=12, pady=10,
        )
        result_label.pack(fill="x", padx=10)
        history = tk.Listbox(
            window, bg="#202433", fg="#eee9dc", selectbackground="#6e2632",
            font=("Consolas", 10), height=9,
        )
        history.pack(fill="both", expand=True, padx=10, pady=10)

        def roll(value: str | None = None) -> None:
            if value:
                expression.delete(0, "end")
                expression.insert(0, value)
            try:
                outcome = roll_dice(expression.get())
            except ValueError as error:
                result_label.configure(text=str(error))
                return
            modifier = outcome["modifier"]
            detail = f"{outcome['rolls']}" + (f" {modifier:+d}" if modifier else "")
            line = f"{outcome['expression']} → {outcome['total']}  {detail}"
            history.insert(0, line)
            result_label.configure(text=f"结果：{outcome['total']}\n{outcome['comment']}")
            self.say(f"{outcome['expression']}：{outcome['total']}。{outcome['comment']}", 5200)

        tk.Button(top, text="投掷", width=8, command=roll).pack(side="right")
        quick = tk.Frame(window, bg="#181b27")
        quick.pack(fill="x", padx=10)
        for sides in (4, 6, 8, 10, 12, 20, 100):
            tk.Button(quick, text=f"d{sides}", command=lambda s=sides: roll(f"d{s}"), width=5).pack(side="left", padx=2)
        expression.bind("<Return>", lambda _event: roll())

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

    def pet_qihei(self) -> None:
        if self.flight:
            self.say("先等我落地。空中摸鸟属于危险驾驶。")
            return
        if self.sleeping:
            self.say("……我知道是你。别把羽冠摸反了。", 4200)
        else:
            now = time.perf_counter()
            self.action = {"name": "touch", "started": now, "until": now + 0.7}
            self.affection = min(100, self.affection + 1)
            self.say(random.choice([
                "只准一下。……再一下也不是不行。",
                "嘎。手法尚可，勉强记一分。",
                "别碰眼睛。羽冠可以。",
            ]), 3600)
        self.save_state()

    def toggle_sleep(self) -> None:
        self.flight = None
        self.action = None
        self.sleeping = not self.sleeping
        if self.sleeping:
            self.say("进入低功耗监听。重要线索叫醒我。", 4300)
        else:
            self.energy = min(100, self.energy + 8)
            self.started = time.perf_counter()
            self.say("醒了。桌面在我睡着时有招供吗？", 4300)

    def update_vitals(self) -> None:
        now = time.time()
        minutes = max(0.0, (now - self.last_vitals_update) / 60)
        self.last_vitals_update = now
        if self.sleeping:
            self.energy = min(100, self.energy + minutes * 1.8)
        else:
            self.energy = max(0, self.energy - minutes * 0.12)
        if self.energy < 18 and not self.sleeping and random.random() < 0.35:
            self.say("情报员申请休整。我的眼睛还红，不代表精神很好。")
        self.save_state()
        self.root.after(60000, self.update_vitals)

    def show_status(self) -> None:
        mood = "信任你" if self.affection >= 70 else "逐渐熟悉" if self.affection >= 35 else "保持观察"
        mode = "休息中" if self.sleeping else "巡查中"
        self.say(f"状态：{mode}\n精力 {round(self.energy)} / 100 · 默契 {self.affection} / 100\n评价：{mood}", 6500)

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
            self.root.after(duration * 60 * 1000, lambda: self.say("专注时间到。停手，伸展，喝水。命令，不是建议。", 10000))

        tk.Button(window, text="开始专注", command=start, width=14).pack(pady=6)

    def check_reminders(self) -> None:
        for item in self.memo_store.due():
            self.say(f"提醒：{item['text']}\n时间到了。别装没看见，嘎。", 9000)
        self.root.after(30000, self.check_reminders)

    def schedule_chatter(self) -> None:
        self.root.after(random.randint(45000, 90000), self.idle_chatter)

    def idle_chatter(self) -> None:
        if not self.quiet:
            self.say(random.choice(IDLE_LINES))
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
        else:
            self.say(random.choice(CLICK_LINES))
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
