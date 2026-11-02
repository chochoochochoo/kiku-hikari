# 区間の正解づけ（作者が耳で）。WAV を鳴らしながら、区間が変わった瞬間に Enter を押す。
# 使い方: py -3.12 tools/annotate_sections.py song.wav [--out sections/song.json] [--out-device 名前の一部]
#   Enter だけ   = 境界を打つ（区間名なし）
#   文字＋Enter  = 区間名つきで打つ: v=verse p=pre_chorus c=chorus b=bridge k=break i=interlude o=outro
#   u＋Enter     = 直前の 1 件を取り消す ／ q＋Enter = 保存して終了（曲が終わったら q）
# 出力: {"wav": ..., "boundaries": [{"t": 秒, "section": 名}]}（Claude には渡さない。検証にだけ使う）
# 音は Windows の既定の出力から出る（リモートデスクトップ越しでも手元で聞こえる）。押した時刻から --lag 秒（既定 0.2＝反応の遅れ）を引いて記録する
import argparse
import json
import os
import sys
import time

import sounddevice as sd
import soundfile as sf

sys.stdout.reconfigure(encoding="utf-8")
KEYS = {"v": "verse", "p": "pre_chorus", "c": "chorus", "b": "bridge", "k": "break", "i": "interlude", "o": "outro"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("wav"); ap.add_argument("--out"); ap.add_argument("--out-device", default=None)
    ap.add_argument("--lag", type=float, default=0.2)
    a = ap.parse_args()
    y, fs = sf.read(a.wav, dtype="float32", always_2d=True)
    dev = None
    if a.out_device:
        dev = next(i for i, d in enumerate(sd.query_devices()) if d["max_output_channels"] >= 2 and a.out_device in d["name"])
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = a.out or os.path.join(root, "sections", os.path.splitext(os.path.basename(a.wav))[0] + ".json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    lyr = os.path.splitext(a.wav)[0] + ".txt"
    if os.path.isfile(lyr):   # 生成時の構成（参考・実際の秒は分からない）
        order = [l.strip("[] \n") for l in open(lyr, encoding="utf-8") if l.startswith("[")]
        print("参考: 生成時の構成 →", " / ".join(order))
    print("キー: Enter=境界  v=verse p=pre_chorus c=chorus b=bridge k=break i=interlude o=outro（文字＋Enter）  u=取り消し  q=保存して終了")
    input(f"準備ができたら Enter で再生開始（{len(y) / fs:.0f} 秒）")
    marks = []
    t0 = time.perf_counter()
    sd.play(y, fs, device=dev)
    while True:
        s = input().strip().lower()
        t = max(0.0, time.perf_counter() - t0 - a.lag)
        if s == "q":
            break
        if s == "u":
            if marks:
                print("  取り消し", marks.pop())
            continue
        name = KEYS.get(s[:1], "boundary") if s else "boundary"
        marks.append({"t": round(t, 2), "section": name})
        print(f"  記録 {t:6.2f}s {name}（{len(marks)} 件）")
    sd.stop()
    json.dump({"wav": os.path.basename(a.wav), "lag": a.lag, "boundaries": marks}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("保存", out, len(marks), "件")


if __name__ == "__main__":
    main()
