"""サビの頭の「らしさ」の点数（2026-11-06・本人指示「サビの判定がまだ甘い」）。本番（look.py）と評価（tools/chorus_eval.py・chorus_replay.py）で同じ式を使う。

学習の材料（~/Claude 側・非公開・gakushu/sabi-cues-v1）から採った手がかりを、拍の時刻 b で因果に（b + lat 秒までしか見ずに）点数にする:
  F3 小節頭の高域（2〜8 kHz）の立ち上がりと音量の段差（直前 2 小節との差・dB）
  F1 直前 1 小節のオンセット（ドラムのフィル）が、その前 3 小節の何倍か
  S04 直前 1 小節の休み（音量が落ちていた）
  曲のそれまでの中央値より明るいか・大きいか（サビは曲の中で一番鳴っている所）
  平坦度（スペクトルの平らさ・全部鳴ると上がる）の跳ね
点数の重みは tools/chorus_eval.py の再生試験で決める。式を変えたらここだけを変える。
"""
from __future__ import annotations

import math

import numpy as np

DEFAULTS = {"lat": 0.3, "w_hf": 1.0, "w_lv": 0.6, "w_fl": 1.0, "w_fill": 1.0, "w_drop": 0.3, "w_bright": 0.5, "w_loud": 0.3}


def cue_score(t: np.ndarray, rms: np.ndarray, hi: np.ndarray, flat: np.ndarray, onset: np.ndarray,
              b: float, bar_s: float, p: dict | None = None):
    """t（秒・昇順）と同じ長さの特徴量の列から、拍の時刻 b の点数と内訳を返す。材料が足りなければ (None, None)。
    参照: 直前 2 小節（b−2 小節 〜 b−0.1 秒）。窓: b 〜 b+lat。曲全体: t>3 秒から b まで。"""
    p = {**DEFAULTS, **(p or {})}
    lat = p["lat"]
    w = (t >= b) & (t < b + lat)
    pr = (t >= b - 2 * bar_s) & (t < b - 0.1)
    if not w.any() or not pr.any():
        return None, None
    hf_step = float(hi[w].mean() - hi[pr].mean())
    lv_step = float(rms[w].mean() - np.median(rms[pr]))
    fl_ratio = float(flat[w].mean() / max(1e-6, flat[pr].mean()))
    m1 = (t >= b - bar_s) & (t < b); m3 = (t >= b - 4 * bar_s) & (t < b - bar_s)
    fill = float(onset[m1].mean() / max(1e-6, onset[m3].mean())) if m1.any() and m3.any() else 1.0
    drop_prev = float(np.median(rms[m1]) - np.median(rms[m3])) if m1.any() and m3.any() else 0.0
    song = (t > 3.0) & (t < b)
    bright_song = float(hi[w].mean() - np.median(hi[song])) if song.any() else 0.0
    loud_song = float(rms[w].mean() - np.median(rms[song])) if song.any() else 0.0
    s = (p["w_hf"] * max(0.0, hf_step) + p["w_lv"] * max(0.0, lv_step)
         + p["w_fl"] * max(0.0, math.log2(max(fl_ratio, 1e-3)))
         + p["w_fill"] * max(0.0, math.log2(max(fill, 1e-3)))
         + p["w_drop"] * max(0.0, -drop_prev)
         + p["w_bright"] * max(0.0, bright_song) + p["w_loud"] * max(0.0, loud_song))
    return s, {"hf_step": hf_step, "lv_step": lv_step, "fl_ratio": fl_ratio, "fill": fill, "drop_prev": drop_prev,
               "bright_song": bright_song, "loud_song": loud_song}
