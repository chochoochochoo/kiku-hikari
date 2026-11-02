# 先読みの的中率: 実行ログの「開き」（予測・救済）と、作者が付けた区間の正解（sections/*.json）を突き合わせる
# 使い方: py -3.12 tools/foresight_eval.py logs/public/xxx-claude.jsonl sections/song.json [--tol 1.0]
#   的中 = 正解の境界から ±tol 秒以内に「開き」がある。予測（Claude の boundary）と救済（変化検出）を分けて数える
import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("log"); ap.add_argument("sections"); ap.add_argument("--tol", type=float, default=1.0)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.log, encoding="utf-8") if l.strip()]
    truth = json.load(open(a.sections, encoding="utf-8"))["boundaries"]
    opens, rescues, preds = [], [], []
    for r in rows:
        if r["kind"] == "engine_event" and r["what"] == "open":
            opens.append(r["at"])
        if r["kind"] == "engine_event" and r["what"] == "rescue":
            rescues.append(r["at"])
        if r["kind"] == "foresight_applied" and r.get("boundary_in") is not None:
            preds.append(r["t"] + r["boundary_in"])
    hit = 0
    print("正解境界 | 最寄りの開き | 差 | 種別")
    for b in truth:
        near = min(opens, key=lambda t: abs(t - b["t"]), default=None)
        d = (near - b["t"]) if near is not None else None
        kind = "-"
        if near is not None:
            kind = "救済" if any(abs(rs - near) < 2.5 and rs <= near for rs in rescues) else "予測"
        ok = d is not None and abs(d) <= a.tol
        hit += ok
        print(f"{b['t']:6.2f}s {b['section']:10} | {near if near is not None else '-':>8} | {('%+.2f' % d) if d is not None else '-':>6} | {kind} {'○' if ok else '×'}")
    fp = sum(1 for o in opens if all(abs(o - b["t"]) > a.tol for b in truth))
    print(f"的中 {hit}/{len(truth)}（±{a.tol}s）・余計な開き {fp}・開き合計 {len(opens)}・予測の提示 {len(preds)} 回")


if __name__ == "__main__":
    main()
