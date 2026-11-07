"""③改 の見せ方（2026-11-04 第 1 段の判定を受けた改良・--profile new＝既定）。--profile old では呼ばない（改良前の ③ のまま）。

第 1 段の自由記述: 「メリハリが無い」「調光卓に記憶させたキューに見える（人の操作に見えない）」「普段は青・盛り上がりでカラフルは良い」。
照明の素人が見て分かるよう、明暗と色の差を大げさにし、人が卓を触っているように見せる。5 つの改良:
  1. verse は暗く少数（Par 中央 2 台・35% 以下）、サビで全灯 100%
  2. pre_chorus の溜めを積み上げに（Par を 1 拍ごとに 2→8 台・スポットは減らす・サビ頭の 1 拍前は暗転→サビ頭で全灯）
  3. キメ（大きなドラムのアクセント）に 1 拍だけ全灯で反応（2.5 小節に 1 回まで）
  4. 切り替えに人の手の速さ（区間ごとのフェード・verse 1.0 秒など。サビ中は拍の明滅を残すため 0.06 秒。キメ・暗転は瞬時。サビ頭は 11/8 から既定 8 拍のフェードイン（進捗の二乗の曲線・フェード中はキメを出さない）・--open-fade-beats 0 で瞬時）
  5. サビの色を回ごとに変える（2 回目は組を替え、3 回目以降・ブレイク明けは白を足す）。ムービングはサビだけ大きく速く・verse は止めて白で人を抜く
拍・安全（Safety のスルーレートと上限）は既存のまま。ここは Par・スポット・Stinger の値を後から書き換えるだけ。
"""
from __future__ import annotations

import math
from collections import deque

from .fixtures import PAR_PAIR, PAR_RGB, PAR_ROW

QUIET = ("intro", "verse", "bridge", "outro")
FADE_S = {"verse": 1.0, "intro": 1.2, "outro": 1.5, "bridge": 1.2, "pre_chorus": 0.15, "chorus": 0.06, "break": 0.4, "interlude": 0.8}


class Look:
    def __init__(self, chorus_max: int = 16, first_bars: int = 0, show: bool = False, rule: str = "rise", cue_params: dict | None = None, prior: dict | None = None, quantize: int = 0, open_fade_beats: float = 8.0, hit_quiet: bool = False):
        self.prior = prior             # 曲構成の型（kiku_hikari/prior.py・--structure-prior）。None なら閾値に触らない
        self.n_cue = 0; self.ch_bar = None   # cue: これまでのサビ入りの回数と、直近のサビ入りの小節番号（型の照合用）
        self.chorus_max = chorus_max   # サビの上限（小節）。11/4 夜に 8→16（一般的なサビの長さ・本人決定）
        self.first_bars = first_bars   # 曲の冒頭この小節数はサビに入らない（0=オフ・第 2 段で比較中）
        self.rule = rule               # サビ入りの条件: rise=第 2 段の判定版（音量の立ち上がり 1.5 dB・タグ blind2-kai）／cue=11/6 の改良（kiku_hikari/cue.py の点数・拍ごと・Claude の格子の上で判定）
        # 既定は tools/chorus_replay.py の再生試験（11/6 03:4x・走行ログ 22 本・正解は作者メモの仮）で サビ入り 9/10・空振り 1 曲 1.2 回 だった組（docs/eval-chorus.md）
        # cue の既定（11/6 13:5x・学習の手がかり 15 行の 3・4・5 から）: 曲頭 16 小節は入らない・乗り換えは入りから 8 小節以内で格子の上だけ（sup_margin 99＝格子の外の乗り換え無し）・
        # サビの頭どうしは 22 小節以上あける・サビ 16 小節のあと 16 小節は入りにくく。11/6 午前の組（early 12・sup_margin 3・sup_max 99・gap 4・rest 8）は測定 5 曲×3 で 10/21・空振り 53、この組は 7/21・空振り 19
        self.cp = {"thr_win": 4.0, "thr_alone": 9.0, "grid_only": True, "bright_min": 1.0, "early_bars_all": 16, "win_bars": 1.0,
                   "sup_min_bars": 4, "sup_max_bars": 8, "sup_win": 1.0, "sup_slack": 99.0, "sup_margin": 99.0, "rest_bars": 16, "rest_extra": 3.0, "drop_db": 5.0, "min_gap_bars": 22,
                   # 格子の引き直し（11/7・--grid-anchor・学習の手がかり 1「小節を数える起点は直前に確かめた区間の境目」）: 小節頭で高域 ga_hf dB・音量 ga_lv dB が同時に段差で上がり
                   # 曲のそれまでより ga_bright dB 明るい拍を「境目」とし（前の境目から ga_gap 小節以上）、Claude の 8 小節格子の窓を直近の境目を通る位相にずらす（shift_window）。0=しない（既定）
                   "grid_anchor": 0, "ga_hf": 3.0, "ga_lv": 1.5, "ga_bright": 1.0, "ga_gap": 4,
                   # song_med=1: 「曲のそれまでより明るい・大きい」の基準を曲全体の中央値にする（評価の tools/ と同じ。0＝既定＝直近 14 秒の中央値・タグ chorus-v2 の挙動）。--grid-anchor で 1
                   "song_med": 0,
                   # jev_veto=1（--jev-veto・11/7 本人決定 b・main.py の既定は ON＝タグ chorus-v3・--no-jev-veto で 0）: cue が入ろうとした拍で判断 API（kiku_hikari/judge.py）に「サビの 1 小節目か」の確率を聞き、veto_thr 未満なら入らない。
                   # 答えが veto_timeout 秒以内に来なければ入る（fail-open）。鍵が無ければ聞かない＝今どおり
                   "jev_veto": 0, "veto_thr": 0.15, "veto_timeout": 1.0, **(cue_params or {})}
        self.judge = None                  # kiku_hikari.judge.Judge（main.py が --jev-veto の時に入れる）
        # 量子化（11/8 本人決定・--quantize-bars N・既定 0＝従来どおり）: 第 3 段の回答者 D「2.8（ツーエイト）や 4.8 等に限って明かりを作れるようになれば」。
        # N>0 なら、サビの入り・キメ・ブレイクと verse の切替を「拍カウントの N 小節の頭」の拍に限る（候補は頭まで保留・N 小節で捨てる）。
        # 頭は拍追従の数え（engine.beat_count % (4N) == 1）で、曲の 1 拍目と一致する保証は無い。開きと拍の明滅は engine.py と apply で止める
        self.q = int(quantize or 0)
        # サビ頭のフェードイン（11/8 本人決定「カットインだとドンピシャでないと気持ちよくない。フェードインなら多少ごまかせる」・--open-fade-beats・既定 8 拍。最初の 2 拍は v5e を見て「早い。3〜4 秒かければ判断のタイムラグをごまかせそう」で 8 拍に）:
        # サビの入りの白足し・全灯・ムービングの明るさ・色の切替を、cue の拍から open_fade_beats 拍かけて直線で上げる（上がり始めは cue の拍のまま）。0＝従来のカットイン。キメの 1 拍白は瞬時のまま
        self.ofb = float(open_fade_beats or 0.0)
        self.hit_quiet = bool(hit_quiet)   # 11/8 本人決定「静かな区間（verse・intro・outro・bridge）ではキメを出さない」。--hit-in-quiet で 11/7 までの動き（どの区間でも出す）に戻る
        self.fade_until = -99.0            # フェードの到達予定時刻
        self.q_pend = None                 # 量子化で頭まで保留しているサビ入りの候補 (b, s)
        self.q_sec = None                  # 量子化で保持している break/verse
        self.beat_head = False             # 直近の拍が量子化の頭だったか（push_onset が見る）
        self.pend_veto = None              # 判断待ちのサビ入り (b, s, bar_now, asked_at)
        self.anchor = None                 # cue: 直近の境目（拍の時刻・grid_anchor）
        self.song_hi = []; self.song_rms = []; self.t_first = None   # cue: 曲のそれまでの高域と音量（0.25 秒ごと・3 秒以降）。中央値を cue_score に渡す（評価の tools/ と同じ基準・11/7）
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
                feat: dict | None = None, beat: bool = False, next_chorus: bool = False, beat_n: int = 0) -> str:
        if beat:
            self.beat_head = self.q > 0 and beat_n % (4 * self.q) == 1
        if self.rule == "cue" and feat is not None:
            return self._section_cue(sec, feat, dt, now, bar_s, window_start, beat, next_chorus, bar_now, beat_n)
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
    def _section_cue(self, sec, feat, dt, now, bar_s, window_start, beat, next_chorus, bar_now, beat_n=0) -> str:
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
        if self.t_first is None:
            self.t_first = now
        if self.n_e % 10 == 0 and self.e_db > -70:
            self.e_hist.append(self.e_db)
        if self.n_e % 10 == 0 and now - self.t_first > 3.0:
            self.song_hi.append(feat.get("b_high", 0.0)); self.song_rms.append(feat["rms_db"])
        if window_start:
            self.win_from = now; self.win_next_chorus = next_chorus
        if beat:
            self.pend.append((now, self.q > 0 and beat_n % (4 * self.q) == 1))
        lat = p.get("lat", 0.3)
        head_now = False                                   # 量子化: この呼び出しで N 小節の頭の拍を採点したか
        while self.pend and now >= self.pend[0][0] + lat:
            b, on_q = self.pend.popleft()
            head_now = head_now or on_q
            if len(self.hist) < 40 * 3:
                continue
            arr = np.array(self.hist, dtype=np.float64)
            song_med = (float(np.median(self.song_hi)), float(np.median(self.song_rms))) if (p["song_med"] and len(self.song_hi) >= 8) else None
            s, parts = cue_score(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], b, bar_s, p, song_med=song_med)
            if s is None:
                continue
            if (p["grid_anchor"] or p["jev_veto"]) and parts["hf_step"] >= p["ga_hf"] and parts["lv_step"] >= p["ga_lv"] and parts["bright_song"] >= p["ga_bright"] \
                    and (self.anchor is None or b - self.anchor >= p["ga_gap"] * bar_s):
                self.anchor = b
                if p["grid_anchor"]:
                    self.events.append(("anchor", b))
            in_win = -bar_s / 4 <= b - self.win_from < p["win_bars"] * bar_s
            if self.pend_veto is not None:      # 判断待ちの間は次の候補を見ない（答えか時間切れで決める・_resolve_veto）
                continue
            if in_win:
                thr = p["thr_win"] - (1.0 if self.win_next_chorus else 0.0)
                if parts["bright_song"] < p["bright_min"]:
                    thr += 100
            else:
                thr = p["thr_alone"] + (100 if p["grid_only"] else 0)
            if bar_now < max(self.first_bars, p["early_bars_all"]):
                thr += 100
            if self.prior is not None:                 # 曲構成の型: 型に合う小節頭は入りやすく、外れは離れた分だけ入りにくく（prior.py）
                from .prior import prior_adjust
                thr += prior_adjust(self.prior, bar_now, self.ch_bar, self.n_cue, p.get("prior_w", 1.0))
            if self.state == "chorus":
                if p["sup_min_bars"] * bar_s <= b - self.ch_start <= p.get("sup_max_bars", 99) * bar_s and ((in_win and s >= max(thr + p["sup_win"], self.s_start - p["sup_slack"])) or s >= self.s_start + p["sup_margin"]):
                    self.ch_start = b; self.s_start = s; self.ch_end = b + self.chorus_max * bar_s; self.low_run = 0; self.last_det = b
                    self.ch_bar = bar_now
                    self.events.append(("cue_again", b))
                    continue
                if b >= self.ch_end:
                    self.state = "rest"; self.rest_until = b + p["rest_bars"] * bar_s; self.low_run = 0
                elif parts["loud_song"] < -p["drop_db"]:
                    self.low_run += 1
                    if self.low_run >= 2 * 4 and (self.q == 0 or on_q):   # 2 小節（拍 8 つ）続けて静か（量子化なら N 小節の頭まで待つ）
                        self.state = "rest"; self.rest_until = b + p["rest_bars"] * bar_s
                else:
                    self.low_run = 0
                continue
            if self.state == "rest":
                if b >= self.rest_until:
                    self.state = "free"
                else:
                    thr += p["rest_extra"]
            cand = s >= thr and b - self.last_det >= p["min_gap_bars"] * bar_s
            if self.q > 0:                                 # 量子化: 候補は N 小節の頭まで保留し、頭の拍で入る（N 小節過ぎた候補は捨てる）
                if cand:
                    self.q_pend = (b, s)
                if self.q_pend is not None and b - self.q_pend[0] > self.q * bar_s:
                    self.q_pend = None
                cand = self.q_pend is not None and on_q
                if cand:
                    s = max(s, self.q_pend[1]); self.q_pend = None
                    self.events.append(("quantized", b))
            if cand:
                if p["jev_veto"] and self.judge is not None and self.judge.available:
                    from .judge import cue_state
                    sb = None if self.anchor is None or b - self.anchor < 0.5 * bar_s else int(round((b - self.anchor) / bar_s))
                    on_grid = sb is not None and min((b - self.anchor) % (8 * bar_s), 8 * bar_s - (b - self.anchor) % (8 * bar_s)) <= bar_s / 4
                    if self.judge.ask(b, cue_state(parts, bar_now, sb, on_grid, in_win)):
                        self.pend_veto = (b, s, bar_now, now)
                        self.events.append(("ask", b))
                        continue
                self._enter_cue(b, s, bar_now, bar_s)
        if self.pend_veto is not None:
            self._resolve_veto(now, bar_s)
        if self.state == "chorus":
            return "chorus"
        out = "verse"
        if len(self.e_hist) >= 20:
            xs = sorted(self.e_hist); thr_b = xs[len(xs) // 2]
            if self.e_db < thr_b - 6:
                out = "break"
        if out == "verse" and sec == "pre_chorus" and self.state == "free":
            out = "pre_chorus"
        if self.q > 0 and out in ("break", "verse"):     # 量子化: break と verse の切替は N 小節の頭の拍でだけ
            if self.q_sec not in ("break", "verse") or head_now:
                self.q_sec = out
            return self.q_sec
        self.q_sec = None
        return out

    def _enter_cue(self, b: float, s: float, bar_now: int, bar_s: float, why: str = "cue"):
        self.state = "chorus"; self.ch_start = b; self.s_start = s; self.ch_end = b + self.chorus_max * bar_s; self.last_det = b
        self.t_chorus = b; self.n_cue += 1; self.ch_bar = bar_now
        self.events.append((why, b))

    def _resolve_veto(self, now: float, bar_s: float):
        """判断待ちのサビ入りを、答え（noul）か時間切れで決める。noul >= veto_thr か時間切れ（fail-open）なら入る・未満なら入らない"""
        p = self.cp; b, s, bar_now, asked = self.pend_veto
        ans = [(v, dt) for bb, v, dt in self.judge.poll() if abs(bb - b) < 1e-6]
        if ans:
            v, dt = ans[-1]
            self.events.append(("judge", b, round(v, 3), round(dt, 3)))
            self.pend_veto = None
            if v >= p["veto_thr"]:
                self._enter_cue(b, s, bar_now, bar_s)
            else:
                self.events.append(("veto", b))      # 入らない（次の拍から改めて見る・min_gap は数え直さない）
        elif now - asked >= p["veto_timeout"]:
            self.events.append(("judge_timeout", b))
            self.pend_veto = None
            self._enter_cue(b, s, bar_now, bar_s)

    def shift_window(self, w: float, now: float, bar_s: float) -> float:
        """格子の引き直し（grid_anchor）: Claude の境界の時刻 w を、直近の境目 anchor を通る 8 小節の格子の位相にずらす（ずれは [-4, 4) 小節）。
        ずらした先が過去なら今（置ける最も早い所）。境目が無ければそのまま。tools/chorus_replay.py の shift_windows と同じ"""
        if not self.cp["grid_anchor"] or self.anchor is None or bar_s <= 0:
            return w
        d = (w - self.anchor) % (8 * bar_s)
        d = d if d < 4 * bar_s else d - 8 * bar_s
        return max(now, w - d)

    # --- 3. キメ ---
    def push_onset(self, onset: float, beat: bool, level: float, now: float, bar_s: float, sec: str):
        self.onsets.append(float(onset))
        if not beat or len(self.onsets) < 80 or sec == "break" or (self.q > 0 and not self.beat_head):   # 量子化: キメは N 小節の頭の拍だけ
            return False
        if now < self.fade_until:                         # 11/8 本人決定: サビ頭のフェードイン中はキメを出さない（v5g でフェードの終わり際 0.5 秒前のキメが 255 へ飛ばしていた）
            return False
        if sec in QUIET and not self.hit_quiet:           # 11/8 本人決定: 静かな区間ではキメを出さない（v5g の 19.5・23.5 小節目の全灯白フラッシュ）
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
        nr = min(n, PAR_ROW)                              # 列の Par の台数。9 台目以降はサイド（11/7 配置 v2e）: 中央 2 台・中央から外への規則は列にだけ掛け、サイドはサビとキメで 100%・他は消灯
        # サビの入り
        if sec == "chorus" and self.prev_sec != "chorus":
            self.chorus_n += 1; self.t_chorus = now
        if sec == "break":
            self.after_break = True
        elif sec == "chorus" and self.prev_sec != "chorus":
            pass
        elif sec in QUIET:
            self.after_break = False
        if sec == "chorus" and now - self.t_chorus < 0.05 and self.ofb > 0 and self.fade_until < self.t_chorus:   # サビ頭: フェードインの到達時刻を決める（cue の拍から ofb 拍・1 回だけ）
            self.fade_until = self.t_chorus + self.ofb * period_s
            self.events.append(("fade_start", now, round(self.ofb * period_s, 3)))
        fading = sec == "chorus" and self.ofb > 0 and now < self.fade_until and now >= self.hit_until
        snap = (sec == "chorus" and now - self.t_chorus < 0.05 and self.ofb <= 0) or now < self.hit_until or (sec == "pre_chorus" and to_boundary is not None and to_boundary < period_s)   # 暗転は瞬時
        p = dict(params)
        nxt = next_color if next_color and next_color != color else PAR_PAIR.get(color, "white")
        out = [(tuple(rgb), k) for rgb, k in pat]
        sp = list(spots)
        if sec in QUIET:                                  # 1. 暗く少数・ムービングは止めて白で人を抜く（サイドは範囲外＝消灯）
            lo = (nr - 2) // 2
            cap = 0.12 if self.show else 0.35             # 全灯版は 11/7 本人決定で 0.2 → 0.12（verse を沈めてサビとの対比を最大に・値だけ・配置とアドレスは不変）
            out = [(rgb, min(k, cap) if lo <= i < lo + 2 else 0.0) for i, (rgb, k) in enumerate(out)]
            p["pan"], p["tilt"] = 0.5, 0.55
            p["color"] = "white"
            p["dimmer"] = min(p["dimmer"], 0.2 if self.show else 0.5)
            if self.q > 0:                                # 量子化: verse のムービングは拍で明滅させず一定
                p["dimmer"] = 0.2 if self.show else 0.5
            if self.show:                                 # 全灯版: 上段スポットも中央 2 台だけ・20% 以下（11/7: 30% → 20%）
                slo = (ns - 2) // 2
                sp = [min(v, 0.2) if slo <= i < slo + 2 else 0.0 for i, v in enumerate(sp)]
        elif sec == "pre_chorus":                         # 2. 積み上げ（中央から外へ）・最後の 1 拍は暗転
            frac = 0.0 if to_boundary is None else max(0.0, min(1.0, 1 - to_boundary / (2 * bar_s)))
            lit = 2 + 2 * min(3, int(frac * 4))           # 2→4→6→8
            c = (nr - 1) / 2
            order = sorted(range(nr), key=lambda i: abs(i - c))[:lit]
            if lit >= nr:                                 # 列が全部点いたらサイドも点ける
                order += list(range(nr, n))
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
            if self.show:                                 # 全灯版（11/7 本人決定「開いた時の明るさと色そのものを強く」）: Par は白を主体（2/3 が白・残りがサビの色）・全台 100%
                cols = ["white", "white", color if color != "white" else nxt]
            out = [(PAR_RGB.get(cols[(i + bar) % len(cols)], PAR_RGB["white"]), 1.0) for i in range(n)]
            p["dimmer"] = 1.0 if self.q > 0 else 0.75 + 0.25 * max(0.0, min(1.0, pulse))   # サビ中も拍の明滅を残す（75〜100%）。量子化なら一定
            sp = [p["dimmer"]] * ns
            if self.show:                                 # 全灯版: 上段スポット 6 台 100% 固定・ムービングは 100% 固定で明るい色（暗い色 red/blue は yellow に）
                sp = [1.0] * ns
                p["dimmer"] = 1.0
                p["color"] = color if color in ("white", "yellow", "orange", "green", "light_blue", "pink") else "yellow"
            self.sweep += dt / max(0.4, bar_s) * 2 * math.pi * (1.5 if self.show else 1.0)   # 全灯版は 1.5 倍速く
            amp_p, amp_t = (0.5, 0.3) if self.show else (0.45, 0.2)                            # 全灯版は振り幅を最大に
            p["pan"] = 0.5 + amp_p * math.sin(self.sweep)
            p["tilt"] = 0.55 + amp_t * math.sin(2 * self.sweep)
        if now < self.hit_until:                          # 3. キメ: 1 拍だけ全台白で全灯
            out = [(PAR_RGB["white"], 1.0)] * n
            sp = [1.0] * ns
            p["dimmer"] = 1.0
        # 4. 人の手の速さ（明るさと色をフェード。キメは瞬時。サビ頭は fade_until まで直線で到達）
        tau = FADE_S.get(sec, 0.8)
        a = 1.0 if snap else 1.0 - math.exp(-dt / tau)
        if fading:                                        # 11/8 本人決定: 直線でなく知覚曲線（進捗 u の二乗・出だしをゆっくり）。R/G/B・dim・スポット・ムービングの明るさを同じ曲線で
            fade_s = max(dt, self.fade_until - self.t_chorus)
            u0 = max(0.0, min(1.0, (now - dt - self.t_chorus) / fade_s)); u1 = max(0.0, min(1.0, (now - self.t_chorus) / fade_s))
            a = 1.0 if u0 >= 1.0 else min(1.0, (u1 * u1 - u0 * u0) / (1.0 - u0 * u0))   # 平滑化の 1 歩で u0²→u1² に進む係数（出発値に依らず全チャンネル共通）
            if self.fade_until - now <= dt:
                self.events.append(("fade_end", now))
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
