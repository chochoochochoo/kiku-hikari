# 事前学習モード（--prelearn）のキューシートの読み込み試験。使い方: python tools/test_prelearn.py
# 細かく刻んだキュー（速い色の点滅になる）と、数値でない時刻を読み込まないことを確かめる。灯体にも API にもつながない。
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
from kiku_hikari.prelearn import MIN_CUE_GAP_S, CuePlayer  # noqa: E402

T = tempfile.mkdtemp(prefix="kh-prelearn-")


def load(ts):
    cues = [{"t": t, "bar": i + 1, "section": "chorus", "open_style": "none", "color": "red" if i % 2 == 0 else "blue",
             "movement": "hold", "tame": "none", "valence": "positive", "arousal": "high"} for i, t in enumerate(ts)]
    p = os.path.join(T, "cue.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"method": "test", "song": "test", "cues": cues}, f)
    try:
        return len(CuePlayer(p).cues)
    except ValueError as e:
        return "ValueError: " + str(e)[:60]


res = []
for name, ts, want_ok in [
    ("0.1 秒刻みは読み込まない", [i * 0.1 for i in range(50)], False),
    ("0.17 秒刻みは読み込まない", [i * 0.17 for i in range(50)], False),
    ("並べ替えると近い 2 つも読み込まない", [0.0, 8.0, 4.0, 8.5], False),
    ("時刻が NaN なら読み込まない", [0.0, float("nan"), 8.0], False),
    (f"ちょうど {MIN_CUE_GAP_S} 秒刻みは読み込む", [i * MIN_CUE_GAP_S for i in range(10)], True),
    ("小数の誤差が出る 1 秒差（0.13 と 1.13）は読み込む", [0.13, 1.13, 2.13], True),
    ("同じ時刻に重なったキューは読み込む", [0.0, 8.0, 8.0, 16.0], True),
    ("小節単位（2 秒刻み）は読み込む", [i * 2.0 for i in range(20)], True),
]:
    got = load(ts)
    ok = isinstance(got, int) if want_ok else isinstance(got, str)
    res.append(ok)
    print(("OK  " if ok else "NG  ") + name + f"  ({got})")
shutil.rmtree(T, ignore_errors=True)
print("NG =", res.count(False))
sys.exit(1 if False in res else 0)
