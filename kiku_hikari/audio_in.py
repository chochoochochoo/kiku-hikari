"""音声入力（sounddevice・WASAPI・48 kHz・1ch）と 1 秒窓の特徴量。

入力デバイスは番号でなく名前で選ぶ（USB I/O の番号は挿し直すと変わる）。
特徴量（1 ブロック = 25 ms ごとに更新）:
  rms_db   … 音量（dBFS）
  centroid … スペクトル重心（Hz）＝明るさ
  flux_low … 低域（40–250 Hz）のスペクトラルフラックス＝拍のエネルギー立ち上がり（拍追従の材料）
"""
from __future__ import annotations

import queue
import threading

import numpy as np
import sounddevice as sd

FS = 48000
BLOCK = 1200  # 25 ms（40 Hz）


def find_input_device(name_part: str = "USB Audio CODEC", hostapi_part: str = "WASAPI") -> int:
    apis = sd.query_hostapis()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] >= 1 and name_part in d["name"] and hostapi_part in apis[d["hostapi"]]["name"]:
            return i
    raise RuntimeError(f"入力デバイスが見つからない: {name_part} / {hostapi_part}")


class AudioIn:
    def __init__(self, device: int | None = None, fs: int = FS, block: int = BLOCK):
        self.device = find_input_device() if device is None else device
        self.fs = fs
        self.block = block
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self.dropped = 0
        self._win = np.hanning(block).astype(np.float32)
        self._freqs = np.fft.rfftfreq(block, 1 / fs)
        self._low = (self._freqs >= 40) & (self._freqs <= 250)
        self._prev_low = None
        self._stream = None

    def _cb(self, indata, frames, t, status):
        if status:
            self.dropped += 1
        try:
            self.q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            self.dropped += 1

    def start(self):
        self._stream = sd.InputStream(device=self.device, channels=1, samplerate=self.fs, blocksize=self.block, dtype="float32", callback=self._cb)
        self._stream.start()
        return self

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()

    def features(self, x: np.ndarray) -> dict:
        """1 ブロック（25 ms）の特徴量"""
        rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
        spec = np.abs(np.fft.rfft(x * self._win))
        power = spec * spec
        centroid = float(np.sum(self._freqs * power) / (np.sum(power) + 1e-12))
        low = spec[self._low]
        flux = 0.0 if self._prev_low is None else float(np.sum(np.maximum(low - self._prev_low, 0.0)))
        self._prev_low = low
        if not hasattr(self, "_high"):                        # サビの手がかり（kiku_hikari/cue.py）: 高域 2〜8 kHz のパワー（dB）と平坦度
            self._high = (self._freqs >= 2000) & (self._freqs < 8000)
        pw = power + 1e-12
        b_high = float(10 * np.log10(pw[self._high].sum()))
        flat = float(np.exp(np.mean(np.log(pw))) / np.mean(pw))
        return {"rms_db": round(float(20 * np.log10(rms)), 2), "centroid": round(centroid, 1), "flux_low": round(flux, 4), "peak": round(float(np.max(np.abs(x))), 4),
                "b_high": round(b_high, 2), "flat": round(flat, 5)}


class FileIn:
    """マイクの代わりに WAV を 25 ms ずつ実時間で流す（灯体もマイクも無い人・審査員向けの疑似モード）。AudioIn と同じ q / features を持つ"""

    def __init__(self, path: str, fs: int = FS, block: int = BLOCK):
        import threading
        import time as _t
        import soundfile as sf
        y, sr = sf.read(path, dtype="float32", always_2d=True)
        if sr != fs:
            raise RuntimeError(f"{path}: {sr} Hz（48 kHz の WAV にしてください）")
        self.y = y.mean(axis=1); self.fs = fs; self.block = block; self.device = f"file:{path}"
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self.dropped = 0
        self._inner = AudioIn.__new__(AudioIn)
        self._inner.fs, self._inner.block = fs, block
        self._inner._win = np.hanning(block).astype(np.float32)
        self._inner._freqs = np.fft.rfftfreq(block, 1 / fs)
        self._inner._low = (self._inner._freqs >= 40) & (self._inner._freqs <= 250)
        self._inner._prev_low = None
        self._stop = False
        self._thr = threading.Thread(target=self._feed, args=(_t,), daemon=True)

    def _feed(self, _t):
        t0 = _t.perf_counter(); i = 0
        while not self._stop and i + self.block <= len(self.y):
            target = t0 + (i / self.fs)
            d = target - _t.perf_counter()
            if d > 0:
                _t.sleep(d)
            try:
                self.q.put_nowait(self.y[i:i + self.block].copy())
            except queue.Full:
                self.dropped += 1
            i += self.block

    def start(self):
        self._thr.start(); return self

    def stop(self):
        self._stop = True

    def features(self, x):
        return AudioIn.features(self._inner, x)


if __name__ == "__main__":
    import time
    a = AudioIn().start()
    print("device", a.device, sd.query_devices(a.device)["name"])
    t0 = time.perf_counter()
    n = 0
    while time.perf_counter() - t0 < 3:
        x = a.q.get()
        f = a.features(x)
        n += 1
        if n % 20 == 0:
            print(f"{time.perf_counter() - t0:5.2f}s", f)
    a.stop()
    print("blocks", n, "dropped", a.dropped)
