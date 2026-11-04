"""③改 の見せ方（2026-11-04 第 1 段の判定を受けた改良・--profile new＝既定）。--profile old では呼ばない（改良前の ③ のまま）。

第 1 段の自由記述: 「メリハリが無い」「調光卓に記憶させたキューに見える（人の操作に見えない）」「普段は青・盛り上がりでカラフルは良い」。
照明の素人が見て分かるよう、明暗と色の差を大げさにし、人が卓を触っているように見せる。5 つの改良:
  1. verse は暗く少数（Par 中央 2 台・35% 以下）、サビで全灯 100%
  2. pre_chorus の溜めを積み上げに（Par を 1 拍ごとに 2→8 台・スポットは減らす・サビ頭の 1 拍前は暗転→サビ頭で全灯）
  3. キメ（大きなドラムのアクセント）に 1 拍だけ全灯で反応（2.5 小節に 1 回まで）
  4. 切り替えに人の手の速さ（区間ごとに 0.3〜1.5 秒のフェード。サビ頭とキメは瞬時）
  5. サビの色を回ごとに変える（2 回目は組を替え、3 回目以降・ブレイク明けは白を足す）。ムービングはサビだけ大きく速く・verse は止めて白で人を抜く
拍・安全（Safety のスルーレートと上限）は既存のまま。ここは Par・スポット・Stinger の値を後から書き換えるだけ。
"""
from __future__ import annotations

import math
from collections import deque

from .fixtures import PAR_PAIR, PAR_RGB

QUIET = ("intro", "verse", "bridge", "outro")
FADE_S = {"verse": 1.0, "intro": 1.2, "outro": 1.5, "bridge": 1.2, "pre_chorus": 0.15, "chorus": 0.3, "break": 0.4, "interlude": 0.8}


class Look:
    def __init__(self):
        self.chorus_n = 0              # これまでに入ったサビの回数
        self.t_chorus = -99.0          # いまのサビの頭
        self.prev_sec = ""
        self.after_break = False       # 直前に break（暗転区間）を通ったか
        self.sm_par = None             # フェード中の Par [(r,g,b,dim)]
        self.sm_spot = None
        self.sm_dim = 0.0
        self.onsets = deque(maxlen=160)  # 約 4 秒（40 Hz）
        self.t_hit = -99.0             # 直近のキメ反応の時刻
        self.hit_until = -99.0
        self.sweep = 0.0
        self.e_db = None               # 平滑した音量（dB）
        self.e_hist = []               # 曲のそれまでの音量（0.25 秒ごと）
        self.n_e = 0

    # --- サビ判定の手当て（③改のみ） ---
    def section(self, sec: str, rms_db: float, dt: float) -> str:
        """改良前は「Claude の境界の後 8 小節＝サビ」で、intro→verse の境界でもサビ扱いになり、1 曲のほぼ全部がサビになっていた
        （11/4 の A/B: 曲 14 で 275 フレーム中 272 がサビ）。③改では音量で絞る: 曲のそれまでの音量（約 1.5 秒で平滑）の中央値−2 dB 以上の時だけサビ、
        中央値より 6 dB 以上低ければブレイク、それ以外は暗い verse。pre_chorus（境界の手前 2 小節）はそのまま"""
        self.e_db = rms_db if self.e_db is None else self.e_db + (rms_db - self.e_db) * (1 - math.exp(-dt / 1.5))
        self.n_e += 1
        if self.n_e % 10 == 0 and self.e_db > -70:      # 0.25 秒ごとに履歴へ（無音は除く）
            self.e_hist.append(self.e_db)
        if sec == "pre_chorus" or len(self.e_hist) < 20:  # 最初の 5 秒は判断しない
            return sec
        xs = sorted(self.e_hist); thr = xs[len(xs) // 2]
        if self.e_db < thr - 6:
            return "break"
        if sec == "chorus" and self.e_db >= thr - 2:   # 曲全体が大きい曲（差 2〜3 dB）では中央値ちょうどで切ると五分五分になるため 2 dB 緩める
            return "chorus"
        return "verse"

    # --- 3. キメ ---
    def push_onset(self, onset: float, beat: bool, level: float, now: float, bar_s: float, sec: str):
        self.onsets.append(float(onset))
        if not beat or len(self.onsets) < 80 or sec == "break":
            return False
        xs = list(self.onsets)[:-1]
        m = sum(xs) / len(xs); sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) or 1e-6
        if onset > m + 3.0 * sd and level > 0.45 and now - self.t_hit >= 2.5 * bar_s and now - self.t_chorus > bar_s:
            self.t_hit = now
            self.hit_until = now + bar_s / 4   # 1 拍
            return True
        return False

    def apply(self, *, sec: str, now: float, dt: float, period_s: float, bar: int, color: str, next_color: str,
              params: dict, pat: list, spots: list, to_boundary: float | None):
        """params（Stinger）・pat（Par の [(rgb, k)]）・spots（スポットの明るさ）を書き換えて返す。
        to_boundary=Claude が小節数で答えた境界までの秒（pre_chorus の積み上げ用・無ければ None）"""
        bar_s = period_s * 4
        n, ns = len(pat), len(spots)
        # サビの入り
        if sec == "chorus" and self.prev_sec != "chorus":
            self.chorus_n += 1; self.t_chorus = now
        if sec == "break":
            self.after_break = True
        elif sec == "chorus" and self.prev_sec != "chorus":
            pass
        elif sec in QUIET:
            self.after_break = False
        snap = (sec == "chorus" and now - self.t_chorus < 0.05) or now < self.hit_until or (sec == "pre_chorus" and to_boundary is not None and to_boundary < period_s)   # 暗転は瞬時
        p = dict(params)
        nxt = next_color if next_color and next_color != color else PAR_PAIR.get(color, "white")
        out = [(tuple(rgb), k) for rgb, k in pat]
        sp = list(spots)
        if sec in QUIET:                                  # 1. 暗く少数・ムービングは止めて白で人を抜く
            lo = (n - 2) // 2
            out = [(rgb, min(k, 0.35) if lo <= i < lo + 2 else 0.0) for i, (rgb, k) in enumerate(out)]
            p["pan"], p["tilt"] = 0.5, 0.55
            p["color"] = "white"
            p["dimmer"] = min(p["dimmer"], 0.5)
        elif sec == "pre_chorus":                         # 2. 積み上げ（中央から外へ）・最後の 1 拍は暗転
            frac = 0.0 if to_boundary is None else max(0.0, min(1.0, 1 - to_boundary / (2 * bar_s)))
            lit = 2 + 2 * min(3, int(frac * 4))           # 2→4→6→8
            c = (n - 1) / 2
            order = sorted(range(n), key=lambda i: abs(i - c))[:lit]
            out = [(rgb, 1.0 if i in order else 0.0) for i, (rgb, k) in enumerate(out)]
            keep = max(0, round(ns * (1 - frac)))
            lo = (ns - keep) // 2
            sp = [v if lo <= i < lo + keep else 0.0 for i, v in enumerate(sp)]
            p["dimmer"] = max(p["dimmer"], 0.4 + 0.5 * frac)   # 台数と一緒に明るさも上げていく
            if to_boundary is not None and to_boundary < period_s:
                out = [(rgb, 0.0) for rgb, _ in out]; sp = [0.0] * ns; p["dimmer"] = 0.0
        elif sec == "break":                              # ブレイクは暗く（サビとの差を見せる）
            out = [(rgb, 0.0) for rgb, _ in out]; sp = [0.0] * ns
            p["dimmer"] = min(p["dimmer"], 0.2)
        elif sec == "chorus":                             # 5. 回ごとの色・全灯・大きく速く振る
            if self.chorus_n <= 1 and not self.after_break:
                cols = [color, nxt]
            elif self.chorus_n == 2 and not self.after_break:
                cols = [nxt, PAR_PAIR.get(nxt, "white")]
            else:
                cols = ["white", color, nxt]
            out = [(PAR_RGB.get(cols[(i + bar) % len(cols)], PAR_RGB["white"]), 1.0) for i in range(n)]
            sp = [1.0] * ns
            p["dimmer"] = 1.0
            self.sweep += dt / max(0.4, bar_s) * 2 * math.pi
            p["pan"] = 0.5 + 0.45 * math.sin(self.sweep)
            p["tilt"] = 0.55 + 0.2 * math.sin(2 * self.sweep)
        if now < self.hit_until:                          # 3. キメ: 1 拍だけ全台白で全灯
            out = [(PAR_RGB["white"], 1.0)] * n
            sp = [1.0] * ns
            p["dimmer"] = 1.0
        # 4. 人の手の速さ（明るさと色をフェード。サビ頭とキメは瞬時）
        tau = FADE_S.get(sec, 0.8)
        a = 1.0 if snap else 1.0 - math.exp(-dt / tau)
        tgt = [(rgb[0], rgb[1], rgb[2], k) for rgb, k in out]
        if self.sm_par is None or len(self.sm_par) != n:
            self.sm_par = [list(map(float, t)) for t in tgt]
        else:
            self.sm_par = [[s + (t - s) * a for s, t in zip(sv, tv)] for sv, tv in zip(self.sm_par, tgt)]
        if self.sm_spot is None or len(self.sm_spot) != ns:
            self.sm_spot = list(sp)
        else:
            self.sm_spot = [s + (t - s) * a for s, t in zip(self.sm_spot, sp)]
        self.sm_dim += (p["dimmer"] - self.sm_dim) * a
        p["dimmer"] = self.sm_dim
        self.prev_sec = sec
        par_out = [((int(round(r)), int(round(g)), int(round(b))), k) for r, g, b, k in self.sm_par]
        return p, par_out, list(self.sm_spot)
