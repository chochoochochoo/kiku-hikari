"""③改 の見せ方（2026-11-04 第 1 段の判定を受けた改良・--profile new＝既定）。--profile old では呼ばない（改良前の ③ のまま）。

第 1 段の自由記述: 「メリハリが無い」「調光卓に記憶させたキューに見える（人の操作に見えない）」「普段は青・盛り上がりでカラフルは良い」。
照明の素人が見て分かるよう、明暗と色の差を大げさにし、人が卓を触っているように見せる。5 つの改良:
  1. verse は暗く少数（Par 中央 2 台・35% 以下）、サビで全灯 100%
  2. pre_chorus の溜めを積み上げに（Par を 1 拍ごとに 2→8 台・スポットは減らす・サビ頭の 1 拍前は暗転→サビ頭で全灯）
  3. キメ（大きなドラムのアクセント）に 1 拍だけ全灯で反応（2.5 小節に 1 回まで）
  4. 切り替えに人の手の速さ（区間ごとのフェード・verse 1.0 秒など。サビ中は拍の明滅を残すため 0.06 秒。サビ頭・キメ・暗転は瞬時）
  5. サビの色を回ごとに変える（2 回目は組を替え、3 回目以降・ブレイク明けは白を足す）。ムービングはサビだけ大きく速く・verse は止めて白で人を抜く
拍・安全（Safety のスルーレートと上限）は既存のまま。ここは Par・スポット・Stinger の値を後から書き換えるだけ。
"""
from __future__ import annotations

import math
from collections import deque

from .fixtures import PAR_PAIR, PAR_RGB

QUIET = ("intro", "verse", "bridge", "outro")
FADE_S = {"verse": 1.0, "intro": 1.2, "outro": 1.5, "bridge": 1.2, "pre_chorus": 0.15, "chorus": 0.06, "break": 0.4, "interlude": 0.8}


class Look:
    def __init__(self, chorus_max: int = 16, first_bars: int = 0, show: bool = False, rule: str = "rise", cue_params: dict | None = None):
        self.chorus_max = chorus_max   # サビの上限（小節）。11/4 夜に 8→16（一般的なサビの長さ・本人決定）
        self.first_bars = first_bars   # 曲の冒頭この小節数はサビに入らない（0=オフ・第 2 段で比較中）
        self.rule = rule               # サビ入りの条件: rise=第 2 段の判定版（音量の立ち上がり 1.5 dB・タグ blind2-kai）／cue=11/6 の改良（kiku_hikari/cue.py の点数・拍ごと・Claude の格子の上で判定）
        self.cp = {"thr_win": 3.0, "thr_alone": 9.0, "grid_only": True, "bright_min": 1.0, "early_bars_all": 0, "win_bars": 1.0,
                   "sup_min_bars": 2, "sup_win": 1.0, "sup_slack": 0.0, "sup_margin": 3.0, "rest_bars": 8, "rest_extra": 3.0, "drop_db": 5.0, "min_gap_bars": 4, **(cue_params or {})}
        self.hist = deque(maxlen=40 * 14)  # cue: 直近 14 秒の (t, rms_db, b_high, flat, onset)
        self.pend = deque()                # cue: まだ採点していない拍の時刻
        self.ch_start = -99.0; self.s_start = 0.0; self.low_run = 0; self.last_det = -99.0; self.win_from = -99.0; self.win_next_chorus = False
        self.show = show               # 全灯版（--profile show・11/5 本人決定・動画の見せ場用）: サビで上段スポット 6 台とムービングを 100% に、verse はさらに暗く少数。サビの判定（section）は new と同じ
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
        self.e_fast = None             # 速い平滑（約 0.4 秒）の音量（サビの入りの判定用）
        self.f_hist = deque(maxlen=200)  # (時刻, 速い音量)・0.25 秒ごと・約 50 秒
        self.state = "free"            # free / chorus / rest
        self.ch_end = self.rest_until = self.cand_until = -1.0
        self.cand_near = False
        self.rest_e = []
        self.events = []               # (サビに入った理由 rise/near/jump, 時刻)

    # --- サビ判定（③改のみ・11/4 夜 本人決定） ---
    def section(self, sec: str, rms_db: float, dt: float, now: float = 0.0, bar_s: float = 2.0,
                window_start: bool = False, near: bool = False, bar_now: int = 10**6,
                feat: dict | None = None, beat: bool = False, next_chorus: bool = False) -> str:
        if self.rule == "cue" and feat is not None:
            return self._section_cue(sec, feat, dt, now, bar_s, window_start, beat, next_chorus, bar_now)
        """改良前は「Claude の境界の後 8 小節＝サビ」で、境界は 8 小節おきに来るので窓が途切れずにつながり、1 曲のほぼ全部がサビになった
        （撮影の 11/4 17:07 のテイクで曲 14 の 17〜69 秒がずっとサビ＝全灯）。③改では Look がサビを持つ:
          - サビに入るのは、Claude の境界に達してから 1 小節の間に「境界の直前（4 小節）より音量が 1.5 dB 以上上がった」か、
            その境界を Claude が直前に「次の小節頭」（bars_to_boundary=1＝あと 0 小節）と答えていた時（near）
          - サビは最長 chorus_max 小節（既定 16）で打ち切り、その後の最低 8 小節は暗い verse（休み）。休みの間でも、休みの平均より音量が 3 dB 跳ねたらサビに戻す
          - それ以外: 曲のそれまでの音量（約 1.5 秒で平滑）の中央値より 6 dB 以上低ければブレイク、pre_chorus（境界の手前 2 小節）はそのまま、他は verse"""
        k_slow = 1 - math.exp(-dt / 1.5); k_fast = 1 - math.exp(-dt / 0.4)
        self.e_db = rms_db if self.e_db is None else self.e_db + (rms_db - self.e_db) * k_slow
        self.e_fast = rms_db if self.e_fast is None else self.e_fast + (rms_db - self.e_fast) * k_fast
        self.n_e += 1
        if self.n_e % 10 == 0 and self.e_db > -70:      # 0.25 秒ごとに履歴へ（無音は除く）
            self.e_hist.append(self.e_db)
            self.f_hist.append((now, self.e_fast))
        if window_start:
            self.cand_until = now + bar_s; self.cand_near = near
        if self.state == "chorus" and now >= self.ch_end:
            self.state = "rest"; self.rest_until = now + 8 * bar_s; self.rest_e = []
        early = bar_now < self.first_bars              # 冒頭 N 小節はサビに入らない
        if self.state == "rest":
            if self.n_e % 10 == 0:
                self.rest_e.append(self.e_fast)
            if not early and len(self.rest_e) >= 4 and self.e_fast >= sum(self.rest_e) / len(self.rest_e) + 3.0:
                self._start_chorus(now, bar_s, "jump")
            elif now >= self.rest_until:
                self.state = "free"
        if self.state == "free" and now < self.cand_until and not early:
            before = [e for t, e in self.f_hist if now - 1.0 - 4 * bar_s <= t < now - 1.0]
            rise = self.e_fast - sum(before) / len(before) if before else 0.0
            if rise >= 1.5 or self.cand_near:
                self._start_chorus(now, bar_s, "near" if self.cand_near and rise < 1.5 else "rise")
        if self.state == "chorus":
            return "chorus"
        if len(self.e_hist) >= 20:
            xs = sorted(self.e_hist); thr = xs[len(xs) // 2]
            if self.e_db < thr - 6:
                return "break"
        if sec == "pre_chorus" and self.state == "free":
            return "pre_chorus"
        return "verse"

    def _start_chorus(self, now: float, bar_s: float, why: str):
        self.state = "chorus"; self.ch_end = now + self.chorus_max * bar_s; self.cand_until = -1.0
        self.events.append((why, now))

    # --- サビ判定（11/6 の改良・rule="cue"）: tools/chorus_replay.py の det_hybrid と同じ手順 ---
    def _section_cue(self, sec, feat, dt, now, bar_s, window_start, beat, next_chorus, bar_now) -> str:
        """拍ごとに kiku_hikari/cue.py の点数を出し、Claude の境界（8 小節の格子）に達してから win_bars 小節の間（手前 1 拍も）は閾値 thr_win、
        それ以外は thr_alone（grid_only なら入らない）。曲のそれまでの中央値より bright_min dB 明るくない所は入らない。
        サビ中は、格子の上でより強い段差（sup_win）が sup_min_bars 小節以上あとに来たら入り直す（B メロの入りを先にサビと取った時の乗り換え）。
        サビは chorus_max 小節で終わる（曲の中央値より drop_db 低い小節が 2 つ続けば早く終わる）。その後 rest_bars 小節は閾値 +rest_extra。"""
        import numpy as np
        from .cue import cue_score
        p = self.cp
        self.hist.append((now, feat["rms_db"], feat.get("b_high", 0.0), feat.get("flat", 0.0), feat.get("onset", 0.0)))
        k_slow = 1 - math.exp(-dt / 1.5)
        self.e_db = feat["rms_db"] if self.e_db is None else self.e_db + (feat["rms_db"] - self.e_db) * k_slow
        self.n_e += 1
        if self.n_e % 10 == 0 and self.e_db > -70:
            self.e_hist.append(self.e_db)
        if window_start:
            self.win_from = now; self.win_next_chorus = next_chorus
        if beat:
            self.pend.append(now)
        lat = p.get("lat", 0.3)
        while self.pend and now >= self.pend[0] + lat:
            b = self.pend.popleft()
            if len(self.hist) < 40 * 3:
                continue
            arr = np.array(self.hist, dtype=np.float64)
            s, parts = cue_score(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], b, bar_s, p)
            if s is None:
                continue
            in_win = -bar_s / 4 <= b - self.win_from < p["win_bars"] * bar_s
            if in_win:
                thr = p["thr_win"] - (1.0 if self.win_next_chorus else 0.0)
                if parts["bright_song"] < p["bright_min"]:
                    thr += 100
            else:
                thr = p["thr_alone"] + (100 if p["grid_only"] else 0)
            if bar_now < max(self.first_bars, p["early_bars_all"]):
                thr += 100
            if self.state == "chorus":
                if b - self.ch_start >= p["sup_min_bars"] * bar_s and ((in_win and s >= max(thr + p["sup_win"], self.s_start - p["sup_slack"])) or s >= self.s_start + p["sup_margin"]):
                    self.ch_start = b; self.s_start = s; self.ch_end = b + self.chorus_max * bar_s; self.low_run = 0; self.last_det = b
                    self.events.append(("cue_again", b))
                    continue
                if b >= self.ch_end:
                    self.state = "rest"; self.rest_until = b + p["rest_bars"] * bar_s; self.low_run = 0
                elif parts["loud_song"] < -p["drop_db"]:
                    self.low_run += 1
                    if self.low_run >= 2 * 4:              # 2 小節（拍 8 つ）続けて静か
                        self.state = "rest"; self.rest_until = b + p["rest_bars"] * bar_s
                else:
                    self.low_run = 0
                continue
            if self.state == "rest":
                if b >= self.rest_until:
                    self.state = "free"
                else:
                    thr += p["rest_extra"]
            if s >= thr and b - self.last_det >= p["min_gap_bars"] * bar_s:
                self.state = "chorus"; self.ch_start = b; self.s_start = s; self.ch_end = b + self.chorus_max * bar_s; self.last_det = b
                self.t_chorus = b
                self.events.append(("cue", b))
        if self.state == "chorus":
            return "chorus"
        if len(self.e_hist) >= 20:
            xs = sorted(self.e_hist); thr_b = xs[len(xs) // 2]
            if self.e_db < thr_b - 6:
                return "break"
        if sec == "pre_chorus" and self.state == "free":
            return "pre_chorus"
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
              params: dict, pat: list, spots: list, to_boundary: float | None, pulse: float = 1.0):
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
            cap = 0.2 if self.show else 0.35
            out = [(rgb, min(k, cap) if lo <= i < lo + 2 else 0.0) for i, (rgb, k) in enumerate(out)]
            p["pan"], p["tilt"] = 0.5, 0.55
            p["color"] = "white"
            p["dimmer"] = min(p["dimmer"], 0.3 if self.show else 0.5)
            if self.show:                                 # 全灯版: 上段スポットも中央 2 台だけ・30% 以下
                slo = (ns - 2) // 2
                sp = [min(v, 0.3) if slo <= i < slo + 2 else 0.0 for i, v in enumerate(sp)]
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
            p["dimmer"] = 0.75 + 0.25 * max(0.0, min(1.0, pulse))   # サビ中も拍の明滅を残す（75〜100%）
            sp = [p["dimmer"]] * ns
            if self.show:                                 # 全灯版: 上段スポット 6 台は 100% 固定・ムービングは 90〜100%
                sp = [1.0] * ns
                p["dimmer"] = 0.9 + 0.1 * max(0.0, min(1.0, pulse))
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
