# 仮の正解（作者の耳の正解づけが無い間の代用）: 曲全体を見て区間の切れ目を出す（librosa・評価専用・製品コードでは使わない）
# 使い方: py -3.12 tools/pseudo_sections.py song.wav [--k 6] [--out sections/pseudo/song.json]
#   拍に同期した特徴（--feats timbre=MFCC＋クロマ＋音量 / energy=音量＋オンセット＋重心＋コントラスト）の自己類似行列から Foote の新規性の山を k-1 個拾う
#   出力は tools/foresight_eval.py が読む形（{"boundaries":[{"t":秒,"section":"?"}]}）。区間名は付けない（"seg2" など）
import argparse
import json
import os
import sys

import librosa
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")


def boundaries(path: str, k: int = 6, feats_kind: str = "timbre") -> list[float]:
    y, sr = librosa.load(path, sr=22050, mono=True)
    _, beats = librosa.beat.beat_track(y=y, sr=sr)
    rms = librosa.feature.rms(y=y)
    if feats_kind == "timbre":   # 音色＋和声（MFCC・クロマ・音量）
        srcs = (librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13), librosa.feature.chroma_cqt(y=y, sr=sr), librosa.amplitude_to_db(rms))
    else:                        # 勢い＋質感（音量・オンセット強度・重心・帯域コントラスト）＝ timbre と別の手がかりで独立に付ける
        srcs = (librosa.amplitude_to_db(rms), librosa.onset.onset_strength(y=y, sr=sr)[None, :], librosa.feature.spectral_centroid(y=y, sr=sr),
                librosa.feature.spectral_contrast(y=y, sr=sr))
    feats = []
    for f in srcs:
        f = librosa.util.sync(f, beats, aggregate=np.median)
        feats.append((f - f.mean(axis=1, keepdims=True)) / (f.std(axis=1, keepdims=True) + 1e-6))
    X = np.vstack(feats)
    # Foote の新規性: 自己類似行列に市松模様の核を沿わせ、山を拾う（山どうしは 16 拍以上離す・上位 k-1 個）
    Xn = X / (np.linalg.norm(X, axis=0, keepdims=True) + 1e-9)
    S = Xn.T @ Xn
    L = 8
    g = np.outer(np.hanning(2 * L), np.hanning(2 * L))
    kern = g * np.block([[np.ones((L, L)), -np.ones((L, L))], [-np.ones((L, L)), np.ones((L, L))]])
    n = S.shape[0]
    Sp = np.pad(S, L, mode="edge")
    nov = np.array([np.sum(Sp[i:i + 2 * L, i:i + 2 * L] * kern) for i in range(n)])
    order = np.argsort(nov)[::-1]
    picked: list[int] = []
    for i in order:
        if nov[i] <= 0 or len(picked) >= k - 1:
            break
        if i < 4 or i > n - 4 or any(abs(i - j) < 16 for j in picked):
            continue
        picked.append(int(i))
    bt = librosa.frames_to_time(librosa.util.fix_frames(beats, x_min=0), sr=sr)
    ts = sorted(float(bt[i]) for i in picked)
    return [t for t in ts if 2.0 < t < len(y) / sr - 2.0]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("wav"); ap.add_argument("--k", type=int, default=6); ap.add_argument("--out"); ap.add_argument("--feats", choices=["timbre", "energy"], default="timbre")
    a = ap.parse_args()
    ts = boundaries(a.wav, a.k, a.feats)
    doc = {"source": f"pseudo:librosa-foote-{a.feats}", "k": a.k, "wav": os.path.basename(a.wav),
           "boundaries": [{"t": round(t, 2), "section": f"seg{i + 2}"} for i, t in enumerate(ts)]}
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump(doc, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(os.path.basename(a.wav), [b["t"] for b in doc["boundaries"]])


if __name__ == "__main__":
    main()
