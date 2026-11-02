# 区間の正解づけ（作者が耳で）。WAV をヘッドホンで鳴らしながら、境界（サビ頭・Bメロ頭・ブレイク等）で Enter を押す。
# 使い方: py -3.12 tools/annotate_sections.py song.wav [--out sections/song.json] [--out-device Realtek]
#   Enter = 境界を打つ（直後に区間名を聞く。空なら "boundary"）、q = 終了
# 出力: {"wav": ..., "boundaries": [{"t": 秒, "section": 名}]}（Claude には渡さない。検証にだけ使う）
import argparse
import json
import os
import sys
import threading
import time

import sounddevice as sd
import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("wav"); ap.add_argument("--out"); ap.add_argument("--out-device", default="Realtek")
    a = ap.parse_args()
    y, fs = sf.read(a.wav, dtype="float32", always_2d=True)
    dev = next(i for i, d in enumerate(sd.query_devices()) if d["max_output_channels"] >= 2 and a.out_device in d["name"] and "WASAPI" in sd.query_hostapis()[d["hostapi"]]["name"])
    out = a.out or os.path.join("sections", os.path.splitext(os.path.basename(a.wav))[0] + ".json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    marks = []
    print(f"再生します（{len(y)/fs:.0f} 秒）。境界で Enter、終わったら q + Enter")
    t0 = time.perf_counter()
    sd.play(y, fs, device=dev)
    while True:
        s = input()
        t = time.perf_counter() - t0
        if s.strip().lower() == "q":
            break
        name = input(f"  {t:6.2f}s 区間名（intro/verse/pre_chorus/chorus/bridge/break/interlude/outro・空=boundary）: ").strip() or "boundary"
        marks.append({"t": round(t, 2), "section": name})
        print(f"  記録 {t:6.2f}s {name}")
        if not sd.get_stream().active:
            break
    sd.stop()
    json.dump({"wav": os.path.basename(a.wav), "boundaries": marks}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("保存", out, len(marks), "件")


if __name__ == "__main__":
    main()
