# 先読みの A/B 比較を 3 ラウンド無人で回す（疑似モード --file --no-artnet・灯体/PrefLight/RDP に依存しない）
#   ① 要約 a/b/c（採用は strict）→ ② 勝った要約で採用 strict/lowok → ③ 勝者と基準（a-strict）を 2 回目の走行で確認
# 正解は仮（tools/pseudo_sections.py・librosa の新規性の山）。勝敗は「暫定」。
# 走行済み（ログに summary 行がある）は飛ばすので、落ちても同じコマンドで続きから再開できる。
# 使い方: py -3.12 tools/ab_run.py --music <wav のフォルダ> [--songs 03_idol_dance,05_mixture_funk,07_guitar_pop_rock] [--tol 2.0]
import argparse
import glob
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "logs", "ab")


def _truth_file(music: str, song: str, kind: str) -> list[float]:
    p = os.path.join(ROOT, "sections", "pseudo" if kind == "timbre" else "pseudo2", f"{song}.json")
    if not os.path.isfile(p):
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "pseudo_sections.py"), os.path.join(music, f"{song}.wav"), "--out", p, "--feats", kind],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return [b["t"] for b in json.load(open(p, encoding="utf-8"))["boundaries"]]


def truth_for(music: str, song: str, which: str = "timbre") -> list[float]:
    """timbre=主の仮正解 / agree=音色系と勢い系の 2 方式が ±2 秒で一致した切れ目だけ（少ないが信頼度が高い）/ human=作者の耳の正解（tools/annotate_sections.py の sections/<曲>.json）"""
    if which == "human":
        p = os.path.join(ROOT, "sections", f"{song}.json")
        if not os.path.isfile(p):
            sys.exit(f"耳の正解がまだ無い: {p}（py -3.12 tools/annotate_sections.py で作る）")
        return [b["t"] for b in json.load(open(p, encoding="utf-8"))["boundaries"]]
    t1 = _truth_file(music, song, "timbre")
    if which == "timbre":
        return t1
    t2 = _truth_file(music, song, "energy")
    return [round((a + min(t2, key=lambda b: abs(a - b))) / 2, 2) for a in t1 if t2 and min(abs(a - b) for b in t2) <= 2.0]


ROOT_KB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")


def run_once(music: str, song: str, summary: str, adopt: str, rep: int, seconds: float, color: str = "", knowledge: str = "") -> str:
    """color=色の変種（p1/p2/p3・空=v1）。knowledge=知識ファイル（空=v1）。腕のフォルダ名は <要約>-<採用>[-<色>]-rep<k>"""
    d = os.path.join(OUT, f"{summary}-{adopt}{'-' + color if color else ''}-rep{rep}", song)
    for f in glob.glob(os.path.join(d, "*.jsonl")):
        if '"kind":"summary"' in open(f, encoding="utf-8").read():
            return f                                         # 走行済み
        os.remove(f)                                         # 途中で落ちた分は捨てて走り直す
    os.makedirs(d, exist_ok=True)
    cmd = [sys.executable, "-m", "kiku_hikari.main", "--mode", "claude", "--file", os.path.join(music, f"{song}.wav"), "--no-artnet",
           "--seconds", str(seconds), "--summary", summary, "--adopt", adopt, "--effort", "low", "--logdir", d]
    # 製品の既定（e・p2・v2）が変わっても A/B の腕の意味が変わらないよう、色と知識は毎回明示する（空=v1）
    cmd += ["--color", color or "v1", "--knowledge", knowledge or os.path.join(ROOT_KB, "lighting_knowledge.json")]
    print("走行", summary, adopt, f"rep{rep}", song, flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    return glob.glob(os.path.join(d, "*.jsonl"))[0]


def score(log: str, truth: list[float], tol: float) -> dict:
    rows = [json.loads(l) for l in open(log, encoding="utf-8") if l.strip()]
    opens = [r["at"] for r in rows if r["kind"] == "engine_event" and r["what"] == "open"]
    rescues = [r["at"] for r in rows if r["kind"] == "engine_event" and r["what"] == "rescue"]
    pred_opens = [o for o in opens if not any(0 <= o - rs < 2.5 for rs in rescues)]   # 直前 2.5 秒に救済が無い開き＝Claude の予測による
    resp = sum(r["kind"] == "claude_resp" for r in rows); err = sum(r["kind"] == "claude_error" for r in rows)
    req = sum(r["kind"] == "claude_req" for r in rows)

    def match(cands):
        used, hit = set(), 0
        for b in truth:                                      # 1 対 1 で近い順に
            best = min((i for i in range(len(cands)) if i not in used and abs(cands[i] - b) <= tol), key=lambda i: abs(cands[i] - b), default=None)
            if best is not None:
                used.add(best); hit += 1
        return hit
    hit, phit = match(opens), match(pred_opens)
    sections = [r.get("section_now") for r in rows if r["kind"] == "claude_resp"]
    return {"hit": hit, "truth": len(truth), "opens": len(opens), "pred_opens": len(pred_opens), "pred_hit": phit,
            "fp": len(opens) - hit, "req": req, "resp": resp, "err": err,
            "low_conf": sum(r.get("confidence") == "low" for r in rows if r["kind"] == "claude_resp"),
            "sections": sorted(set(s for s in sections if s))}


def arm_score(music, songs, summary, adopt, rep, tol, which):
    per = {}
    for s_ in songs:
        d = os.path.join(OUT, f"{summary}-{adopt}-rep{rep}", s_)
        f = [x for x in glob.glob(os.path.join(d, "*.jsonl")) if '"kind":"summary"' in open(x, encoding="utf-8").read()]
        if not f:
            return None
        per[s_] = score(f[0], truth_for(music, s_, which), tol)
    tot = {k: sum(p[k] for p in per.values()) for k in ("hit", "truth", "opens", "pred_opens", "pred_hit", "fp", "req", "resp", "err", "low_conf")}
    tot["F"] = round(2 * tot["hit"] / max(1, tot["truth"] + tot["opens"]), 3)
    return {"summary": summary, "adopt": adopt, "rep": rep, "truth": which, "total": tot, "per_song": per}


def mean_arm(music, songs, summary, adopt, reps, tol, which):
    rs = [r for r in (arm_score(music, songs, summary, adopt, k, tol, which) for k in reps) if r]
    if not rs:
        return None
    keys = rs[0]["total"].keys()
    return {"summary": summary, "adopt": adopt, "truth": which, "n_reps": len(rs), "F_reps": [r["total"]["F"] for r in rs],
            "mean": {k: round(sum(r["total"][k] for r in rs) / len(rs), 3) for k in keys}, "reps": rs}


def best(cands):
    """平均 F が高い方。同点なら余計な開きが少ない方、それも同じなら先に並べた方（基準・単純な方）"""
    return max(cands, key=lambda r: (r["mean"]["F"], -r["mean"]["fp"], -cands.index(r)))


RESULTS: dict = {}


def save():
    os.makedirs(OUT, exist_ok=True)
    json.dump(RESULTS, open(os.path.join(OUT, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    from concurrent.futures import ThreadPoolExecutor
    ap = argparse.ArgumentParser(); ap.add_argument("--music", required=True)
    ap.add_argument("--songs", default="03_idol_dance,05_mixture_funk,07_guitar_pop_rock"); ap.add_argument("--tol", type=float, default=2.0)
    ap.add_argument("--seconds", type=float, default=80.0); ap.add_argument("--reps", type=int, default=3); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--summaries", default="a,b,c"); ap.add_argument("--adopts", default="strict,lowok"); ap.add_argument("--rep-from", type=int, default=1)
    ap.add_argument("--knowledge", default="", help="知識ファイル（空=v1）。v2 の A/B は --logroot も分ける")
    ap.add_argument("--logroot", default="", help="ログの置き場（既定 logs/ab）。知識ファイルを変えた A/B は別にする（例 logs/ab-v2）")
    ap.add_argument("--arms", help="腕を直接指定（例 d-lowok,a-strict）。指定時は --summaries/--adopts より優先・集計はしない（tools/ab_judge.py で判定）")
    a = ap.parse_args(); songs = a.songs.split(",")
    global OUT
    if a.logroot:
        OUT = os.path.abspath(a.logroot)
    for s_ in songs:
        truth_for(a.music, s_, "agree")                       # 仮正解を先に作る（並列で取り合わない）
    # 総当たり（要約 3 × 採用 2 × 反復 × 曲）を並列で走らせ、ラウンドの判定は後から同じデータで行う
    pairs = [tuple((x.split("-") + ["", ""])[:3]) for x in a.arms.split(",")] if a.arms else [(v, ad, "") for v in a.summaries.split(",") for ad in a.adopts.split(",")]
    grid = [(v, ad, k, s_, c) for k in range(a.rep_from, a.rep_from + a.reps) for (v, ad, c) in pairs for s_ in songs]
    print(f"走行 {len(grid)} 本（並列 {a.workers}）", flush=True)
    fails = []

    def job(g):
        if len(fails) >= 3:                                   # 失敗が続いたら残りは走らせない
            return
        try:
            f = run_once(a.music, g[3], g[0], g[1], g[2], a.seconds, g[4], a.knowledge)
            sc = score(f, truth_for(a.music, g[3]), a.tol)
            if sc["req"] and sc["err"] > sc["req"] / 2:
                fails.append((g, sc["err"], sc["req"])); print(f"API の失敗が多い {g} {sc['err']}/{sc['req']}", flush=True)
        except Exception as e:
            fails.append((g, repr(e)[:120])); print("失敗", g, repr(e)[:120], flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for g in grid:
            ex.submit(job, g)
    if len(fails) >= 3:
        print("失敗が 3 本を超えたので止めた（API 制限か残高の疑い）", flush=True); sys.exit(3)
    if a.arms or a.summaries != "a,b,c" or a.adopts != "strict,lowok" or a.rep_from != 1:
        print("走行のみ完了（判定は tools/ab_judge.py）", flush=True); return
    reps = list(range(1, a.reps + 1))
    for which in ("timbre", "agree"):
        arms = {f"{v}-{ad}": mean_arm(a.music, songs, v, ad, reps, a.tol, which) for v in ("a", "b", "c") for ad in ("strict", "lowok")}
        r1 = [arms["a-strict"], arms["b-strict"], arms["c-strict"]]; w1 = best(r1)
        r2 = [arms[f"{w1['summary']}-strict"], arms[f"{w1['summary']}-lowok"]]; w2 = best(r2)
        base = arms["a-strict"]
        RESULTS[which] = {"arms": arms, "round1": w1["summary"], "round2": f"{w2['summary']}-{w2['adopt']}",
                          "confirm": {"winner_F_reps": w2["F_reps"], "baseline_F_reps": base["F_reps"],
                                      "winner_beats_baseline_in_reps": sum(x > y for x, y in zip(w2["F_reps"], base["F_reps"]))}}
        print(which, "① 勝者", w1["summary"], "② 勝者", RESULTS[which]["round2"], "F", w2["F_reps"], "基準", base["F_reps"], flush=True)
        for k, v in arms.items():
            print(f"  {k}: F平均 {v['mean']['F']} {v['F_reps']} 的中 {v['mean']['hit']}/{v['mean']['truth']} 予測的中 {v['mean']['pred_hit']} 余計 {v['mean']['fp']} 応答 {v['mean']['resp']} 失敗 {v['mean']['err']} low {v['mean']['low_conf']}", flush=True)
    RESULTS["_meta"] = {"tol": a.tol, "songs": songs, "reps": a.reps, "truth": "pseudo（暫定）",
                        "claude_calls": sum(r["total"]["resp"] + r["total"]["err"] for arm_ in RESULTS["timbre"]["arms"].values() for r in arm_["reps"])}
    save()
    print("完了 Claude 呼び出し", RESULTS["_meta"]["claude_calls"], flush=True)


if __name__ == "__main__":
    main()
