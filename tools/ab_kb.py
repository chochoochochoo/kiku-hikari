# 知識ファイルを差し替えた A/B を 1 コマンドで（走行 → 採点）。既定の腕は a と e（色の変種は --arms で足す）
# 使い方: py -3.12 tools/ab_kb.py --knowledge knowledge/v2.json [--arms a-strict,e-strict] [--reps 3] [--logroot logs/ab-v2]
#   色の変種も試す: --arms a-strict,e-strict,e-strict-p1,e-strict-p2,e-strict-p3
#   v1 のまま色の変種だけ試す: --knowledge knowledge/lighting_knowledge.json --logroot logs/ab-color
#   走行済みは飛ばすので、落ちても同じコマンドで続きから。採点は tools/ab_h.py（耳の正解 2 通り・偶然との比較・間に合った率・色の変化）
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC = r"C:\Users\pc\Claude\bwc-japan2026\music\jpop"
SONGS = "03_idol_dance,05_mixture_funk,07_guitar_pop_rock,11_enka"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--knowledge", required=True); ap.add_argument("--arms", default="a-strict,e-strict")
    ap.add_argument("--reps", type=int, default=3); ap.add_argument("--logroot", default=os.path.join("logs", "ab-v2")); ap.add_argument("--music", default=MUSIC)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    if not os.path.isfile(a.knowledge):
        sys.exit(f"知識ファイルが無い: {a.knowledge}")
    py = sys.executable
    subprocess.run([py, os.path.join(ROOT, "tools", "ab_run.py"), "--music", a.music, "--songs", SONGS, "--arms", a.arms, "--rep-from", "1", "--reps", str(a.reps),
                    "--workers", str(a.workers), "--knowledge", os.path.abspath(a.knowledge), "--logroot", a.logroot], cwd=ROOT, check=True)
    subprocess.run([py, os.path.join(ROOT, "tools", "ab_h.py"), "--music", a.music, "--arms", a.arms, "--reps", ",".join(str(i) for i in range(1, a.reps + 1)),
                    "--logroot", a.logroot], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
