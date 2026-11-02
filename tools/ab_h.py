# 仮説 1〜3（基準時刻の修正・小節数で答える e・早めに聞く f）の採点（logs/ab/ の既存ログだけで計算・走り直さない）
#   正解は作者の耳の正解（sections/<曲>.json）を 2 通りに読む:
#     区間境界版 = 6 秒未満の間隔の点を間引いたもの ／ 照明の変わり目版 = 全点
#   腕ごとに: 色の種類と変化回数（DMX の色スロット・「青一定」の確認）・平均 F（全開き）・Claude 由来の開きの的中と「時刻をランダムにずらした偶然」との比較（p）・間に合った率・API 回数
# 使い方: py -3.12 tools/ab_h.py --music <wav のフォルダ> [--arms a-strict,d-strict,e-strict,f-strict] [--reps 7,8,9] [--tol 2.0]
import argparse
import glob
import json
import os
import random
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ab_run  # noqa: E402
from ab_run import truth_for  # noqa: E402
from ab_judge import thin  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
SONGS = ["03_idol_dance", "05_mixture_funk", "07_guitar_pop_rock", "11_enka"]


def match(c, tr, tol):
    used, h = set(), 0
    for b in tr:
        best = min((i for i in range(len(c)) if i not in used and abs(c[i] - b) <= tol), key=lambda i: abs(c[i] - b), default=None)
        if best is not None:
            used.add(best); h += 1
    return h


def load(arm, rep, song):
    fs = [x for x in glob.glob(os.path.join(ab_run.OUT, f"{arm}-rep{rep}", song, "*.jsonl")) if '"kind":"summary"' in open(x, encoding="utf-8").read()]
    if not fs:
        return None
    rows = [json.loads(l) for l in open(fs[0], encoding="utf-8") if l.strip()]
    ev = [r for r in rows if r["kind"] == "engine_event"]
    resc = [r["at"] for r in ev if r["what"] == "rescue"]
    opens = [r["at"] for r in ev if r["what"] == "open"]
    pred = [o for o in opens if not any(0 <= o - x < 2.5 for x in resc)]
    ap = [r for r in rows if r["kind"] == "foresight_applied" and r.get("late") is not None]
    cols = [r["color"] for r in rows if r["kind"] == "dmx"]
    return {"ncolor": len(set(cols)), "cchg": sum(1 for x, y in zip(cols, cols[1:]) if x != y),
            "opens": opens, "pred": pred, "adopted": len(ap), "late": sum(r["late"] for r in ap),
            "calls": sum(r["kind"] in ("claude_resp", "claude_error") for r in rows), "err": sum(r["kind"] == "claude_error" for r in rows)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--music", required=True); ap.add_argument("--arms", default="a-strict,d-strict,e-strict,f-strict")
    ap.add_argument("--reps", default="7,8,9"); ap.add_argument("--tol", type=float, default=2.0); ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--logroot", default="", help="ログの置き場（既定 logs/ab）")
    a = ap.parse_args(); reps = [int(x) for x in a.reps.split(",")]; random.seed(0)
    if a.logroot:
        ab_run.OUT = os.path.abspath(a.logroot)
    truths = {"区間境界版（6 秒未満を間引き）": 6.0, "照明の変わり目版（全点）": 0.0}
    for tname, gap in truths.items():
        T = {s: thin([t for t in truth_for(a.music, s, "human") if t >= 12.0], gap) for s in SONGS}
        print(f"== {tname} ±{a.tol} 秒")
        for arm in a.arms.split(","):
            runs = [(s, load(arm, r, s)) for s in SONGS for r in reps]
            runs = [(s, d) for s, d in runs if d]
            if not runs:
                print(f"{arm}: 走行なし"); continue
            F = st.mean(2 * match(d["opens"], T[s], a.tol) / max(1, len(T[s]) + len(d["opens"])) for s, d in runs)
            obs = sum(match(d["pred"], T[s], a.tol) for s, d in runs); npred = sum(len(d["pred"]) for _, d in runs)
            sims = [sum(match([12 + ((p - 12 + random.uniform(0, 68)) % 68) for p in d["pred"]], T[s], a.tol) for s, d in runs) for _ in range(a.sims)]
            p = sum(v >= obs for v in sims) / len(sims)
            adopted = sum(d["adopted"] for _, d in runs); late = sum(d["late"] for _, d in runs)
            calls = sum(d["calls"] for _, d in runs); err = sum(d["err"] for _, d in runs)
            ontime = f"{(adopted - late) / adopted:.0%}（{adopted - late}/{adopted}）" if adopted else "—"
            print(f"{arm}: 走行 {len(runs)}｜F {F:.2f}｜Claude 由来の開き {npred}・的中 {obs}（偶然 {st.mean(sims):.1f}・p={p:.2f}）｜間に合った率 {ontime}｜API {calls} 回（失敗 {err}）｜色 1 曲平均 {st.mean(d["ncolor"] for _, d in runs):.1f} 種・変化 {st.mean(d["cchg"] for _, d in runs):.1f} 回")


if __name__ == "__main__":
    main()
