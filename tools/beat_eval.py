# 拍追従のオフライン評価。WAV を 25 ms ずつ流して、目標 BPM（曲の .txt の「N bpm」）と librosa の拍（参照・製品では使わない）に対して採点する
# 使い方: py -3.12 tools/beat_eval.py <wav または フォルダ> [--limit N]
# 出力: 曲ごとに 推定テンポ（中央値）/ 目標 / 倍半分も正解扱いの一致 / 拍の F 値（±70 ms）/ ロックまでの秒
import argparse
import glob
import os
import re
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kiku_hikari.beat import BeatTracker, HOP, FS  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def target_bpm(wav):
    txt = os.path.splitext(wav)[0] + ".txt"
    if os.path.isfile(txt):
        m = re.search(r"(\d{2,3})\s*bpm", open(txt, encoding="utf-8").read(), re.I)
        if m:
            return float(m.group(1))
    return None


def run(wav):
    x, fs = sf.read(wav, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if fs != FS:
        raise SystemExit(f"{wav}: {fs} Hz（48 kHz 前提）")
    bt = BeatTracker()
    tempos, beats, confs = [], [], []
    for i in range(0, len(x) - HOP, HOP):
        r = bt.process(x[i:i + HOP])
        t = (i + HOP) / fs
        if r["tempo_bpm"] > 0:
            tempos.append((t, r["tempo_bpm"])); confs.append(r["confidence"])
        if r["beat"]:
            beats.append(t)
    return np.array(tempos), np.array(beats), np.array(confs), x, fs


def f_measure(est, ref, tol=0.07):
    if len(est) == 0 or len(ref) == 0:
        return 0.0
    hit = 0; used = np.zeros(len(ref), bool)
    for e in est:
        j = np.argmin(np.abs(ref - e))
        if not used[j] and abs(ref[j] - e) <= tol:
            used[j] = True; hit += 1
    p = hit / len(est); r = hit / len(ref)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("path"); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--no-librosa", action="store_true")
    a = ap.parse_args()
    wavs = sorted(glob.glob(os.path.join(a.path, "*.wav"))) if os.path.isdir(a.path) else [a.path]
    if a.limit:
        wavs = wavs[:a.limit]
    print("曲 | 目標BPM | 推定(中央値) | 一致(±4%/倍半分) | 拍F値 vs librosa | ロック秒 | 信頼度")
    for w in wavs:
        tempos, beats, confs, x, fs = run(w)
        tb = target_bpm(w)
        med = float(np.median(tempos[:, 1])) if len(tempos) else 0.0
        ok = "-"
        if tb:
            ratio = med / tb
            ok = "○" if abs(ratio - 1) < 0.04 else ("倍" if abs(ratio - 2) < 0.08 else ("半" if abs(ratio - 0.5) < 0.04 else "×"))
        lock = "-"
        if tb and len(tempos):
            good = np.abs(tempos[:, 1] / tb - 1) < 0.04
            # 連続 5 秒以上一致した最初の時刻
            for i in range(len(good) - 5):
                if good[i:i + 5].all():
                    lock = f"{tempos[i, 0]:.0f}"; break
        fm = "-"
        if not a.no_librosa:
            import librosa
            _, ref = librosa.beat.beat_track(y=x, sr=fs, units="time")
            fm = f"{f_measure(beats, np.asarray(ref)):.2f}"
            # 半拍ずれ（オフビート）も参考に
            fm_off = f_measure(beats + (30.0 / med if med else 0), np.asarray(ref))
            fm += f"（半拍ずらし {fm_off:.2f}）"
        print(f"{os.path.basename(w)} | {tb} | {med:.1f} | {ok} | {fm} | {lock} | {np.mean(confs):.2f}" if len(confs) else f"{os.path.basename(w)} | {tb} | 推定なし")


if __name__ == "__main__":
    main()
