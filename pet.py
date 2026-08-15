from __future__ import annotations

import json
import math
import random
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageOps, ImageTk

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "pet_state.json"
TRANSPARENT = "#010203"
PET_SIZE = 112
IMAGE_SIZE = 104
STYLES = {
    "pixel": BASE_DIR / "assets" / "raven_pixel_concept_v1.png",
    "realistic": BASE_DIR / "assets" / "raven_2d_concept_v4.png",
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
        self.facing_left = False
        self.flight: dict[str, float] | None = None
        self.drag_origin: tuple[int, int] | None = None
        self.dragged = False
        self.quiet = False
        self.bubble_timer: str | None = None
        self.source_image: Image.Image | None = None
        self.tk_image: ImageTk.PhotoImage | None = None
        self.image_item = self.canvas.create_image(PET_SIZE // 2, PET_SIZE // 2)

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
        style_menu = tk.Menu(self.menu, tearoff=False, font=("Microsoft YaHei UI", 9))
        style_menu.add_radiobutton(label="像素版", variable=self.style, value="pixel", command=self.switch_style)
        style_menu.add_radiobutton(label="写实版", variable=self.style, value="realistic", command=self.switch_style)
        self.menu.add_cascade(label="切换外观", menu=style_menu)
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

    def load_state(self) -> dict[str, object]:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def load_style_image(self) -> None:
        source = Image.open(STYLES[self.style.get()]).convert("RGBA")
        source.thumbnail((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", (PET_SIZE, PET_SIZE))
        frame.alpha_composite(source, ((PET_SIZE - source.width) // 2, (PET_SIZE - source.height) // 2))
        self.source_image = frame
        self.render_image()

    def render_image(self) -> None:
        if self.source_image is None:
            return
        frame = ImageOps.mirror(self.source_image) if self.facing_left else self.source_image
        self.tk_image = ImageTk.PhotoImage(frame)
        self.canvas.itemconfigure(self.image_item, image=self.tk_image)

    def switch_style(self) -> None:
        self.load_style_image()
        self.save_state()
        name = "像素版" if self.style.get() == "pixel" else "写实版"
        self.say(f"已切换到{name}。两套羽毛，我都要。")

    def tick(self) -> None:
        now = time.perf_counter()
        if self.flight:
            elapsed = now - self.flight["start"]
            progress = min(1.0, elapsed / self.flight["duration"])
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
        bob = math.sin((now - self.started) * (8 if self.flight else 2.2)) * (3 if self.flight else 1.2)
        self.canvas.coords(self.image_item, PET_SIZE // 2, PET_SIZE // 2 + bob)
        self.root.after(33, self.tick)

    def start_flight(self) -> None:
        if self.flight or self.drag_origin is not None:
            return
        sx, sy = self.root.winfo_x(), self.root.winfo_y()
        max_x = max(15, self.root.winfo_screenwidth() - PET_SIZE - 15)
        max_y = max(15, self.root.winfo_screenheight() - PET_SIZE - 55)
        tx, ty = random.randint(15, max_x), random.randint(15, max_y)
        if abs(tx - sx) < 260:
            tx = 15 if sx > max_x / 2 else max_x
        new_facing_left = tx < sx
        if new_facing_left != self.facing_left:
            self.facing_left = new_facing_left
            self.render_image()
        self.flight = {
            "start": time.perf_counter(), "duration": random.uniform(2.0, 3.3),
            "sx": sx, "sy": sy, "tx": tx, "ty": ty, "arc": random.randint(55, 120),
        }

    def restore_position(self, state: dict[str, object]) -> None:
        try:
            x, y = int(state["x"]), int(state["y"])
        except (ValueError, KeyError, TypeError):
            x = self.root.winfo_screenwidth() - PET_SIZE - 25
            y = self.root.winfo_screenheight() - PET_SIZE - 60
        self.root.geometry(f"{PET_SIZE}x{PET_SIZE}+{max(0, x)}+{max(0, y)}")

    def save_state(self) -> None:
        data = {"x": self.root.winfo_x(), "y": self.root.winfo_y(), "style": self.style.get()}
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

    def schedule_chatter(self) -> None:
        self.root.after(random.randint(45000, 90000), self.idle_chatter)

    def idle_chatter(self) -> None:
        if not self.quiet:
            self.say(random.choice(IDLE_LINES))
        self.schedule_chatter()

    def toggle_quiet(self) -> None:
        self.quiet = not self.quiet
        self.menu.entryconfigure(3, label="恢复碎碎念" if self.quiet else "安静一会儿")
        self.say("收到。静默侦察。" if self.quiet else "情报频道恢复。")

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
    missing = [str(path) for path in STYLES.values() if not path.exists()]
    if missing:
        raise SystemExit("Missing pet assets: " + ", ".join(missing))
    QiheiPet().run()
