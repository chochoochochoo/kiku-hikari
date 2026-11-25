"""事前学習モードの再生（2026-11-08・本人の実験・提出物ではない・既定の走行は変えない）: tools/prelearn.py が書いたキューシート JSON を
曲の時刻で辿り、キューが変わる瞬間に Foresight（色・動き・溜め・開き方）を engine に渡し、次のキューの秒を境界にして小節頭で開かせる。
Claude のリアルタイムの読みは使わない。区間名（lsec）もキューシートのもの。look.py の形（verse 中央 2 台・サビ全灯・キメ・フェード）はそのまま掛かる。"""
from __future__ import annotations

import json
import math
import os

from .claude_worker import Arousal, Color, Confidence, Foresight, Movement, OpenStyle, Section, Tame, Valence

# キューの最短間隔（秒）。これより細かく刻んだキューシートは読み込まない（2026-11-25）。
# 手で作った 0.1 秒刻みのキューで Par の赤の点滅が毎秒 4.9 回、0.17 秒刻みで毎秒 3 回になった。光感受性発作の目安は毎秒 3 回以下。
# fixtures.py の上限が抑えるのはストロボのチャンネルだけなので、キューによる色の切り替えの速さはここで止める。
# tools/prelearn.py が作るキューは小節単位。同じ時刻に重なったキューは後ろの 1 つだけが効くので、そのまま通す。
MIN_CUE_GAP_S = 1.0


class CuePlayer:
    def __init__(self, path: str):
        d = json.load(open(path, encoding="utf-8"))
        self.method = d.get("method", "?"); self.song = d.get("song", "?")
        self.cues = sorted(d["cues"], key=lambda c: c["t"])
        if not self.cues:
            raise ValueError("キューシートが空")
        ts = [c["t"] for c in self.cues]
        if not all(isinstance(t, (int, float)) and math.isfinite(t) for t in ts):
            raise ValueError("キューシートの t が数値でない")
        for a, b in zip(ts, ts[1:]):
            if 0 < b - a < MIN_CUE_GAP_S - 1e-6:   # 1e-6 は小数の誤差の分（0.13 秒と 1.13 秒の差は 1 に届かない）
                raise ValueError(f"キューの間隔が {MIN_CUE_GAP_S} 秒未満（{a} 秒と {b} 秒）。速い点滅になるので読み込まない")
        self.i = -1
        self.armed = -1                 # 境界（開き）を engine に渡した次のキューの番号（1 キュー 1 回）
        self.events = []                # ("cue", 曲の秒, キュー) を main.py がログに書く

    def _fs(self, i: int, tsong: float) -> Foresight:
        c = self.cues[i]; n = self.cues[min(i + 1, len(self.cues) - 1)]
        secs = max(0, min(60, int(round(n["t"] - tsong)))) if i + 1 < len(self.cues) else 60
        return Foresight(section_now=Section(c["section"]), section_next=Section(n["section"]), seconds_to_boundary=secs,
                         open_style=OpenStyle(n["open_style"]) if i + 1 < len(self.cues) else OpenStyle.none,
                         color=Color(c["color"]), next_color=Color(n["color"]), movement=Movement(c["movement"]), tame=Tame(c["tame"]),
                         valence=Valence(c["valence"]), arousal=Arousal(c["arousal"]), scene_word="", confidence=Confidence.high, reason="prelearn")

    def tick(self, tsong: float, now: float, engine) -> dict:
        """曲の秒 tsong で現在のキューを返す。キューが変わった時だけ engine に Foresight と境界を渡す"""
        i = 0
        while i + 1 < len(self.cues) and self.cues[i + 1]["t"] <= tsong:
            i += 1
        if i != self.i:
            self.i = i
            fs = self._fs(i, tsong)
            engine.on_foresight(fs, now, asked_at=now)
            engine.color = fs.color.value       # 開きが無い境目でも色はキューどおりに
            if i + 1 < len(self.cues) and self.cues[i + 1]["open_style"] != "none" and self.armed != i + 1:
                engine.boundary_at = now + (self.cues[i + 1]["t"] - tsong)   # 秒の丸め無しの境界。engine.step が直近の小節頭に合わせて開く
                self.armed = i + 1
            else:
                engine.boundary_at = None
            self.events.append(("cue", tsong, self.cues[i]))
        return self.cues[i]

    def section(self) -> str:
        return self.cues[self.i]["section"] if self.i >= 0 else self.cues[0]["section"]

    def to_boundary(self, tsong: float):
        """pre_chorus の積み上げ用: 次のキューまでの秒（次が無ければ None）"""
        if 0 <= self.i < len(self.cues) - 1:
            return max(0.0, self.cues[self.i + 1]["t"] - tsong)
        return None
