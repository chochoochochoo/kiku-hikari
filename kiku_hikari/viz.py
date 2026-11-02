"""画面上の仮想灯体（灯体が無い人・審査員向けの疑似モード）。tkinter だけで動く。

DMX の値そのもの（Stinger Spot 11ch）を読んで描く: Pan/Tilt の位置に色つきの丸、明るさは丸の大きさと濃さ、
シャッター閉は黒、右下に拍・テンポ・Claude の最新判断（区間・色・情景一語・理由）。
40 Hz の本流を止めないよう、描画は別スレッドの tkinter に状態だけ渡す。
"""
from __future__ import annotations

import queue
import threading

from .fixtures import STINGER_COLORS

RGB = {"white": "#ffffff", "red": "#ff2020", "orange": "#ff8c1a", "yellow": "#ffe41a", "green": "#2aff5a", "blue": "#2a5aff", "light_blue": "#66ccff", "pink": "#ff66cc"}
_WHEEL = {v: k for k, v in STINGER_COLORS.items()}


def color_name(v: int) -> str:
    best = min(STINGER_COLORS.items(), key=lambda kv: abs(kv[1] - v))
    return best[0]


class Viz:
    def __init__(self, title: str = "kiku-hikari 仮想灯体"):
        self.q: queue.Queue[dict] = queue.Queue(maxsize=4)
        self.title = title
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def update(self, dmx: bytearray, address: int, info: dict):
        a = address - 1
        pan = dmx[a] / 255; tilt = dmx[a + 2] / 255
        state = {"pan": pan, "tilt": tilt, "color": color_name(dmx[a + 4]), "shutter": dmx[a + 6], "dimmer": dmx[a + 7] / 255, **info}
        try:
            self.q.put_nowait(state)
        except queue.Full:
            pass

    def _run(self):
        import tkinter as tk
        root = tk.Tk(); root.title(self.title); root.configure(bg="#000")
        W, H = 720, 480
        cv = tk.Canvas(root, width=W, height=H, bg="#000", highlightthickness=0); cv.pack()
        text = tk.Label(root, text="", fg="#ccc", bg="#000", font=("Yu Gothic UI", 11), justify="left", anchor="w"); text.pack(fill="x")
        ver = tk.Label(root, text="v1 20261102 143000", fg="#555", bg="#000", font=("Consolas", 9)); ver.place(x=6, y=6)
        state = {}

        def tick():
            nonlocal state
            try:
                while True:
                    state = self.q.get_nowait()
            except queue.Empty:
                pass
            cv.delete("all")
            cv.create_rectangle(40, 40, W - 40, H - 40, outline="#222")  # ステージ
            if state:
                x = 40 + state["pan"] * (W - 80); y = 40 + (1 - state["tilt"]) * (H - 80)
                r = 18 + 70 * state["dimmer"]
                col = RGB.get(state["color"], "#fff")
                if state["shutter"] < 8 or state["dimmer"] <= 0.01:
                    cv.create_oval(x - 18, y - 18, x + 18, y + 18, outline="#333")
                else:
                    for k in (3, 2, 1):
                        cv.create_oval(x - r * k / 2, y - r * k / 2, x + r * k / 2, y + r * k / 2, fill=col, outline="", stipple="gray25" if k > 1 else "")
                text.config(text=f"拍 {state.get('beat', '')}  テンポ {state.get('tempo', 0):.0f}  位相 {state.get('phase', 0):.2f}   色 {state['color']}  明るさ {state['dimmer']:.2f}  {state.get('mode', '')}\n"
                                 f"Claude: {state.get('section', '-')} → {state.get('next', '-')} あと{state.get('boundary', '-')}s  溜め {state.get('tame', '-')}  「{state.get('scene', '')}」 {state.get('reason', '')[:40]}")
            root.after(25, tick)

        tick(); root.mainloop()
