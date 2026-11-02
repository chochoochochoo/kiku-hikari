"""音響変化検出（事後の救済）。Claude の先読みが外れたり来なかったりした時に、Python が境界を「後から」見つけて開くための番人。

短期（4 秒）と長期（16 秒）の特徴量の比を見て、CUSUM で持続的なずれを検出する。40 Hz で呼ぶ。
検出は「音量（rms_db）」「明るさ（centroid）」「オンセット密度」の 3 本のうち 2 本以上が同時に閾値を越えた時。
検出後は 8 秒間は再検出しない（同じ境界を二度数えない）。
"""
from __future__ import annotations

from collections import deque

RATE = 40


class ChangeDetector:
    def __init__(self, short_s: float = 4.0, long_s: float = 16.0, k: float = 0.5, h: float = 6.0, refractory_s: float = 8.0):
        self.ns, self.nl = int(short_s * RATE), int(long_s * RATE)
        self.buf = {name: deque(maxlen=self.nl) for name in ("rms_db", "centroid", "onset")}
        self.cusum = {name: 0.0 for name in self.buf}
        self.k, self.h = k, h
        self.refractory = int(refractory_s * RATE)
        self.cooldown = 0
        self.frames = 0
        self.last_z = {}

    def push(self, rms_db: float, centroid: float, onset: float) -> dict | None:
        """変化を検出したら {"frame":..., "z": {...}} を返す。なければ None"""
        self.frames += 1
        for name, v in (("rms_db", rms_db), ("centroid", centroid), ("onset", onset)):
            self.buf[name].append(float(v))
        if self.cooldown > 0:
            self.cooldown -= 1
        if len(self.buf["rms_db"]) < self.nl:
            return None
        hits = 0
        z = {}
        for name, b in self.buf.items():
            arr = list(b)
            long_part, short_part = arr[:-self.ns], arr[-self.ns:]
            mu = sum(long_part) / len(long_part)
            var = sum((x - mu) ** 2 for x in long_part) / max(1, len(long_part) - 1)
            sd = max(var ** 0.5, 1e-6)
            zs = (sum(short_part) / len(short_part) - mu) / sd
            z[name] = round(zs, 2)
            # 両側 CUSUM（上がっても下がっても）
            self.cusum[name] = max(0.0, self.cusum[name] + abs(zs) - self.k)
            if self.cusum[name] > self.h:
                hits += 1
        self.last_z = z
        if hits >= 2 and self.cooldown == 0:
            self.cooldown = self.refractory
            for name in self.cusum:
                self.cusum[name] = 0.0
            return {"frame": self.frames, "z": z}
        return None
