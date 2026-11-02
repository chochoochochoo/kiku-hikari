# A/B の判定（敵対レビュー 2 体の判定規則を機械化・logs/ab/ の既存ログだけで計算）
#   比べる 2 腕を同じ曲・同じ反復で組にし、F の勝ち負けを数える（符号検定・片側）
#   「暫定勝者」と言うのは: 組の 8/9 以上で勝ち（同点は負け扱い）、かつ Claude 由来の的中が基準より多く、かつ 3 曲すべてで曲別平均 F が基準以上。
#   その判定が、許容幅 1.5/2.0/2.5 秒 × 仮正解 timbre/agree の 6 通りすべてで同じ時だけ「頑健」
#   採点対象の正解は、最初の Claude 応答が届く 12 秒より後の切れ目だけ（誰も届かない点で全腕を薄めない）
# 使い方: py -3.12 tools/ab_judge.py --music <wav のフォルダ> --win d-strict --base a-strict [--reps 4,5,6] [--truth human]
#   --truth human: 作者の耳の正解（sections/<曲>.json）で判定。走り直しは不要（既存ログを採点し直すだけ）
import argparse
import glob
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ab_run import OUT, score, truth_for  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def f_of(arm, rep, song, music, which, tol):
    fs = [x for x in glob.glob(os.path.join(OUT, f"{arm}-rep{rep}", song, "*.jsonl")) if '"kind":"summary"' in open(x, encoding="utf-8").read()]
    if not fs:
        return None
    truth = [t for t in truth_for(music, song, which) if t >= 12.0]
    sc = score(fs[0], truth, tol)
    sc["F"] = 2 * sc["hit"] / max(1, sc["truth"] + sc["opens"])
    sc["F_pred"] = 2 * sc["pred_hit"] / max(1, sc["truth"] + sc["pred_opens"])
    return sc


def sign_p(k, n):
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def judge(music, win, base, reps, songs, which, tol):
    wins = n = 0; pw = pb = 0; per_song = {}
    for s in songs:
        fw, fb = [], []
        for r in reps:
            a, b = f_of(win, r, s, music, which, tol), f_of(base, r, s, music, which, tol)
            if a is None or b is None:
                continue
            n += 1; wins += a["F"] > b["F"]; pw += a["pred_hit"]; pb += b["pred_hit"]
            fw.append(a["F"]); fb.append(b["F"])
        if fw:
            per_song[s] = (sum(fw) / len(fw), sum(fb) / len(fb))
    ok = n > 0 and wins >= math.ceil(n * 8 / 9) and pw > pb and all(w >= b for w, b in per_song.values())
    return {"wins": wins, "n": n, "p": round(sign_p(wins, n), 3) if n else None, "pred_hit": (pw, pb), "per_song": per_song, "ok": ok}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--music", required=True); ap.add_argument("--win", required=True); ap.add_argument("--base", default="a-strict")
    ap.add_argument("--reps", default="4,5,6"); ap.add_argument("--truth", choices=["pseudo", "human"], default="pseudo", help="human=作者の耳の正解で判定（tools/annotate_sections.py）"); ap.add_argument("--songs", default="03_idol_dance,05_mixture_funk,07_guitar_pop_rock")
    a = ap.parse_args(); reps = [int(x) for x in a.reps.split(",")]; songs = a.songs.split(",")
    res = []
    for which in (("human",) if a.truth == "human" else ("timbre", "agree")):
        for tol in (1.5, 2.0, 2.5):
            j = judge(a.music, a.win, a.base, reps, songs, which, tol); res.append(j["ok"])
            ps = " ".join(f"{s[:2]} {w:.2f}/{b:.2f}" for s, (w, b) in j["per_song"].items())
            print(f"{which:6} ±{tol}: 勝ち {j['wins']}/{j['n']}（p={j['p']}）Claude由来の的中 {j['pred_hit'][0]} 対 {j['pred_hit'][1]}｜曲別F {ps}｜{'○' if j['ok'] else '×'}")
    verdict = ("勝者（頑健）" if a.truth == "human" else "暫定勝者（頑健）") if all(res) else (f"条件つきの勝者（{sum(res)}/{len(res)} 通り）" if any(res) else "差なし")
    print(f"判定: {a.win} 対 {a.base} → {verdict}")


if __name__ == "__main__":
    main()
