"""モーションエンジン（40 Hz）: 拍位相とレベルから Pan/Tilt/色/明るさの「意味のある値」を作る。

ここは計画の比較 3 段の ①拍連動のみ（白・開ゴボ・固定の振り）に相当する基礎。
② ルール表・③ Claude は、この上で「色・語彙・展開・溜め」を差し替える形で載せる。
- 拍頭で Pan の目標を左右に切り替え、Tilt は 2 拍で上下。移動はスルーレート制限（fixtures.Safety）に任せる
- 明るさは拍頭でパルス（立ち上がり即・減衰は拍の長さに合わせる）
- 位相リセットはしない（拍が外れても流れを止めない）
"""
from __future__ import annotations

import math


class BeatEngine:
    def __init__(self):
        self.beat_count = 0
        self.level = 0.0
        self.pan_side = 1

    def on_beat(self):
        self.beat_count += 1
        self.pan_side = -self.pan_side
        self.level = 1.0

    def step(self, dt: float, phase: float, period_s: float, loudness: float) -> dict:
        """dt=フレーム間隔(s)・phase=拍位相 0..1・period_s=拍の長さ・loudness=0..1 の音量"""
        # 拍の長さに応じた減衰（1 拍で 15% まで落ちる）
        decay = math.exp(math.log(0.15) * dt / max(0.2, period_s))
        self.level *= decay
        pan = 0.5 + 0.30 * self.pan_side
        tilt = 0.55 + 0.15 * math.cos(math.pi * ((self.beat_count % 2) + phase))
        dimmer = 0.25 + 0.75 * max(self.level, 0.5 * loudness)
        return {"pan": pan, "tilt": tilt, "dimmer": min(1.0, dimmer), "color": "white", "gobo": "open", "shutter": "open", "strobe": 0.0, "speed": 0.0}
