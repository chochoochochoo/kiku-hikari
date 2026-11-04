"""モーションエンジン（40 Hz）: 拍位相・レベル・Claude の先読みから Pan/Tilt/色/明るさの「意味のある値」を作る。

比較 3 段:
  ① BeatEngine      拍連動のみ（白・開ゴボ・固定の振り）
  ③ ForesightEngine ①の上に Claude の先読み（色・語彙・溜め・境界での開き）を載せる。境界は予測時刻の直後の小節頭にクオンタイズ
（② ルール表は main.py 側で色だけ差し替える）
- 位相リセットはしない。Pan/Tilt の急変は fixtures.Safety のスルーレート制限に任せる
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
        decay = math.exp(math.log(0.15) * dt / max(0.2, period_s))
        self.level *= decay
        pan = 0.5 + 0.30 * self.pan_side
        tilt = 0.55 + 0.15 * math.cos(math.pi * ((self.beat_count % 2) + phase))
        dimmer = 0.25 + 0.75 * max(self.level, 0.5 * loudness)
        return {"pan": pan, "tilt": tilt, "dimmer": min(1.0, dimmer), "color": "white", "gobo": "open", "shutter": "open", "strobe": 0.0, "speed": 0.0}


class ForesightEngine(BeatEngine):
    """Claude の先読み（Foresight）を受け取り、語彙・色・溜め・開きを拍の上に載せる"""

    def __init__(self, beats_per_bar: int = 4, adopt: str = "strict"):
        super().__init__()
        self.bpb = beats_per_bar
        self.adopt = adopt          # strict=確信度 low の予測は捨てる（従来）／lowok=low でも開き方の指定があれば採る
        self.fs = None              # 最新の Foresight
        self.boundary_at = None     # 予測した境界の時刻（秒・単調時計）
        self.open_at = None         # 小節頭にクオンタイズした開きの時刻
        self.opened_until = -1.0    # 開き演出の終了時刻
        self.sweep_phase = 0.0
        self.color = "white"
        self.next_color = "white"
        self.events = []
        self.period_s = 0.5         # 直近の拍周期（step で更新）
        self.phase = 0.0
        self.last_late = None       # 直近に採った予測が、届いた時点で既に境界を過ぎていたか

    def on_foresight(self, fs, now: float, asked_at: float | None = None, bar_at_ask: int | None = None):
        """asked_at=依頼を出した時刻。seconds_to_boundary は Claude が見た要約（依頼の時点）からの秒数なので、そこから数える
        （2026-11-03 までは届いた時刻から数えていて、往復の遅延 約 2.6 秒ぶん開きが遅れていた・docs/eval-beat.md）"""
        self.fs = fs
        self.color, self.next_color = fs.color.value, fs.next_color.value
        self.last_late = None
        if fs.open_style.value != "none" and (fs.confidence.value != "low" or self.adopt == "lowok"):
            k = getattr(fs, "bars_to_boundary", None)
            if k is not None and bar_at_ask is not None:      # e/f: 小節数で答えた境界（この拍数の小節頭）
                target = (bar_at_ask + k - 1) * self.bpb + 1
                self.boundary_at = now + (target - self.beat_count - self.phase) * self.period_s
            else:
                self.boundary_at = (asked_at if asked_at is not None else now) + fs.seconds_to_boundary
            self.last_late = self.boundary_at < now
        elif fs.confidence.value == "low":
            self.boundary_at = None

    def on_change(self, now: float):
        """音響変化検出からの救済: 予測が無い（または遠い）のに変化が来たら、次の小節頭で開く"""
        if self.open_at is None and (self.boundary_at is None or self.boundary_at - now > 2.0):
            self.boundary_at = now
            self.events.append(("rescue", round(now, 2)))

    def on_beat(self):
        super().on_beat()
        # 小節頭で、予測境界がこの小節の中に入っていれば「次の小節頭で開く」を確定する
        if self.boundary_at is not None and self.beat_count % self.bpb == 1:
            self.events.append(("bar", self.beat_count))

    def step(self, dt: float, phase: float, period_s: float, loudness: float, now: float = 0.0) -> dict:
        base = super().step(dt, phase, period_s, loudness)
        fs = self.fs
        self.period_s, self.phase = period_s, phase   # 予測が無い間も更新する（最初の予測を秒に直す時に既定の 0.5 秒・位相 0 が使われていた）
        if fs is None:
            return {**base, "tame": "none", "opened": False}
        bar_s = period_s * self.bpb
        # 開き: 予測境界の直前の小節頭〜直後の小節頭のうち、境界に近い方
        if self.boundary_at is not None and self.open_at is None and now >= self.boundary_at - bar_s:
            beats_into_bar = (self.beat_count - 1) % self.bpb + phase
            to_next_bar = (self.bpb - beats_into_bar) * period_s
            self.open_at = now + to_next_bar
        if self.open_at is not None and now >= self.open_at:
            self.opened_until = now + 2 * bar_s
            self.color = self.next_color
            self.boundary_at = None
            self.open_at = None
            self.events.append(("open", round(now, 2)))
        # 溜め: 境界の 1 小節前から
        taming = self.boundary_at is not None and now >= self.boundary_at - bar_s
        tame = fs.tame.value if taming else "none"
        opened = now < self.opened_until
        # 語彙
        mv = fs.movement.value
        if mv == "hold":
            pan, tilt = 0.5, 0.55
        elif mv == "sweep":
            self.sweep_phase += dt / max(0.5, 2 * bar_s) * 2 * math.pi
            pan, tilt = 0.5 + 0.35 * math.sin(self.sweep_phase), 0.55 + 0.05 * math.cos(self.sweep_phase)
        elif mv == "chase":
            pan, tilt = base["pan"], base["tilt"]
        else:  # bounce
            pan, tilt = 0.5 + 0.2 * self.pan_side, 0.55 + 0.2 * (1 - phase)
        # 明るさ: 感情の覚醒度で床を変え、溜めで落とし、開きで一杯に
        floor = {"low": 0.15, "mid": 0.3, "high": 0.45}[fs.arousal.value]
        dimmer = floor + (1 - floor) * max(self.level, 0.5 * loudness)
        shutter = "open"
        if tame == "dim_hold":
            dimmer = min(dimmer, 0.25)
        elif tame == "slow_close":
            frac = max(0.0, min(1.0, (self.boundary_at - now) / bar_s)) if self.boundary_at else 1.0
            dimmer = dimmer * frac
        elif tame == "freeze":
            pan, tilt = 0.5, 0.55
        if opened:
            dimmer = max(dimmer, 0.9)
            if fs.open_style.value == "blackout_then_burst" and now < self.opened_until - 2 * bar_s + 0.12:
                shutter = "closed"
        return {"pan": pan, "tilt": tilt, "dimmer": min(1.0, dimmer), "color": self.color, "gobo": "open", "shutter": shutter, "strobe": 0.0, "speed": 0.0,
                "tame": tame, "opened": opened}
