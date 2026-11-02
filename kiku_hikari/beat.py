"""自前の拍追従（numpy だけ）。40 Hz（25 ms）で呼ぶ。因果（未来を見ない）。

流れ: 直近 2048 サンプルの対数スペクトル → 低域を重くしたスペクトラルフラックス（オンセット強度）
      → 12 秒の自己相関を倍音加算（lag, 2lag, 3lag）してテンポ（60–180 BPM・前のテンポ ±8% を優先）
      → 拍頭を越えるたびに、直近 4 拍のオンセット列と「櫛」を照合して位相を少し寄せる（位相リセットはしない）
出力: tempo_bpm / phase(0..1) / beat(このブロックで拍頭を越えたか) / confidence
aubio・madmom は Windows の Python 3.12 に入らないため自前。評価は tools/beat_eval.py（librosa は参照にだけ使う）。
"""
from __future__ import annotations

import numpy as np

FS = 48000
HOP = 1200          # 25 ms
NFFT = 2048
RATE = FS / HOP     # 40 frames/s
BPM_MIN, BPM_MAX = 60.0, 180.0
LAG_MIN = int(np.floor(60 / BPM_MAX * RATE))   # 13
LAG_MAX = int(np.ceil(60 / BPM_MIN * RATE))    # 40


class BeatTracker:
    def __init__(self, fs: int = FS, hop: int = HOP, history_s: float = 12.0, kp: float = 0.5, kt: float = 0.08):
        self.fs, self.hop = fs, hop
        self.buf = np.zeros(NFFT, dtype=np.float32)
        self.win = np.hanning(NFFT).astype(np.float32)
        freqs = np.fft.rfftfreq(NFFT, 1 / fs)
        self.wband = (np.where(freqs < 250, 3.0, 1.0) * (freqs <= 8000)).astype(np.float32)
        self.prev_spec = None
        self.n_hist = int(history_s * RATE)
        self.onset = np.zeros(self.n_hist, dtype=np.float32)   # 古い→新しい
        self.frame = 0
        self.period: float | None = None
        self.confidence = 0.0
        self.tempo_bpm = 0.0
        self.next_beat: float | None = None
        self.last_beat: float | None = None
        self.phase = 0.0
        self.kp, self.kt = kp, kt
        self.last_corr = 0.0

    # ---- 1) オンセット強度 ----
    def _onset_strength(self, x: np.ndarray) -> float:
        self.buf = np.concatenate([self.buf[len(x):], x.astype(np.float32)])
        spec = np.abs(np.fft.rfft(self.buf * self.win))
        logspec = np.log1p(spec * 10.0) * self.wband
        if self.prev_spec is None:
            self.prev_spec = logspec
            return 0.0
        flux = float(np.sum(np.maximum(logspec - self.prev_spec, 0.0)))
        self.prev_spec = logspec
        return flux

    # ---- 2) テンポ（自己相関＋倍音加算）----
    def _estimate_tempo(self):
        o = self.onset - np.mean(self.onset)
        sd = np.std(o)
        if sd < 1e-6:
            return
        o = o / sd
        n = len(o)
        maxlag = min(3 * LAG_MAX + 1, n // 2)
        ac = np.array([np.dot(o[:-lag], o[lag:]) / (n - lag) for lag in range(1, maxlag)])  # ac[lag-1]

        def acv(lag: float) -> float:
            i = int(round(lag)) - 1
            return float(ac[i]) if 0 <= i < len(ac) else 0.0

        lags = np.arange(LAG_MIN, LAG_MAX + 1, dtype=float)
        score = np.array([acv(l) + 0.5 * acv(2 * l) + 0.33 * acv(3 * l) for l in lags])
        bpm = 60 * RATE / lags
        prior = np.exp(-0.5 * ((np.log2(bpm / 115.0)) / 0.8) ** 2)   # 100〜135 を少し優先
        score = score * prior
        if self.period is not None:
            cont = np.exp(-0.5 * ((lags - self.period) / (0.08 * self.period)) ** 2)
            score = score * (0.35 + 0.65 * cont)
        i = int(np.argmax(score))
        if 0 < i < len(score) - 1:
            y0, y1, y2 = score[i - 1], score[i], score[i + 1]
            d = float(np.clip(0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12), -0.5, 0.5))
        else:
            d = 0.0
        lag = float(lags[i] + d)
        self.confidence = float(np.clip(acv(lag), 0.0, 1.0))
        self.period = lag if self.period is None else (0.8 * self.period + 0.2 * lag)
        self.tempo_bpm = 60 * RATE / self.period

    # ---- 3) 位相（櫛の照合）----
    def _comb_offset(self) -> float:
        """直近 4 拍分のオンセット列に、周期 P の櫛（4 本）を −P/2..P/2 ずらして当て、最も合う ずれ を返す（フレーム）"""
        P = self.period
        o = self.onset
        now = self.n_hist - 1  # 現在フレームのインデックス
        best, best_d = -1e9, 0.0
        span = int(P / 2)
        for d in range(-span, span + 1):
            s = 0.0
            for k in range(4):
                idx = now - (self.frame - self.last_beat) + d - k * P  # last_beat + d − kP を履歴の添字で
                i = int(round(idx))
                if 0 <= i < self.n_hist:
                    s += o[i] * (1.0 - 0.15 * k)
            if s > best:
                best, best_d = s, float(d)
        self.last_corr = best
        return best_d

    def _update_phase(self, f: int) -> bool:
        if self.period is None:
            return False
        if self.next_beat is None:
            self.next_beat = f + self.period
            self.last_beat = float(f)
        beat = False
        if f >= self.next_beat:
            self.last_beat = self.next_beat
            self.next_beat += self.period
            beat = True
            # 拍頭を越えた直後に位相を照合して寄せる（1 拍に 1 回・位相は連続）
            d = self._comb_offset()
            if abs(d) < 0.4 * self.period:
                self.next_beat += self.kp * d
                self.last_beat += self.kp * d
                self.period = float(np.clip(self.period + self.kt * d / 4.0, 60 / BPM_MAX * RATE, 60 / BPM_MIN * RATE))
        self.phase = float(((f - self.last_beat) / self.period) % 1.0)
        return beat

    def process(self, x: np.ndarray) -> dict:
        o = self._onset_strength(x)
        self.onset = np.roll(self.onset, -1); self.onset[-1] = o
        self.frame += 1
        if self.frame % int(RATE) == 0 and self.frame >= 3 * RATE:
            self._estimate_tempo()
        beat = self._update_phase(self.frame)
        return {"onset": round(o, 3), "tempo_bpm": round(self.tempo_bpm, 1), "phase": round(self.phase, 3), "beat": beat, "confidence": round(self.confidence, 3)}
