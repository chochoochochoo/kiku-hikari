# ②' 判断 API（Jev）で候補選択式を再生試験する（2026-11-07・入口の提案）: 走行ログの Claude 窓・音の境目・cue の内訳を「小さな整数と yes/no」の手がかり表にして、
#   拍ごとに「この拍はサビの 1 小節目の頭か」の確率（noul）を取り、閾値を越えたらサビ入り（サビ 16 小節・休み 16 小節・頭どうし 22 小節以上は look.py と同じ）。
#   答えは logs/judge/ に JSON でキャッシュ（閾値の掃引は無料）。鍵は kiku_hikari/judge.py（環境変数 TYPESAFE_API_KEY か .env）。
#   使い方: py -3.12 tools/judge_replay.py "<logs glob>" [--thr 0.25] [--variant=short|full] [--gate] [--union] [--onlycue] [--songs=m01,m02] [--dump] [--nocall]
#   実測（11/7）: 測定 5 曲 15 本で short・閾値 0.25 は 11/27・空振り 8（cue 新版の再生 5〜8/27・空振り 16〜22）だが、閾値決めに使わなかった m01/m02/m04/m05 では 1/12・空振り 8。本番には繋いでいない
import glob, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import chorus_eval as ce  # noqa: E402
import chorus_replay as cr  # noqa: E402
from kiku_hikari import judge  # noqa: E402
MU = [d for d in next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--music=")), "").split(";") if d]
CDIR = os.path.join(ROOT, "logs", "judge"); os.makedirs(CDIR, exist_ok=True)
VARIANT = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--variant=")), "short"); CACHE = os.path.join(CDIR, f"answers-{VARIANT}.json")
INSTR = judge.INSTRUCTIONS

def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default

def yn(x): return "yes" if x else "no"

def build_rows(feat, lg, p):
    """拍ごとの手がかり表（過去の値だけ）。返す: [(b, state, s, parts, in_win)]"""
    t = feat["t"]; bt = [float(x) for x in t[feat["beat"] > 0]]; bpb = 4
    beat_s = float(np.median(np.diff(bt))); bar_s = beat_s * bpb
    anchors = cr.anchors_of(feat, p); windows = lg["windows"]; resp = lg["resp"]
    rows = []
    for i in range(4 * bpb, len(bt) - 1):
        b = bt[i]; bs = bt[i] - bt[i - 1]
        if bs <= 0.2 or bs > 1.1: continue
        s, parts = ce.cue_score(feat, b, bar_s, 0.3, p)
        if s is None: continue
        past = [a for a in anchors if a <= b - 0.5 * bar_s]
        a = past[-1] if past else None
        w = next((w for w in windows if -beat_s <= b - w < 1.0 * bar_s), None)
        last = next((r for r in reversed(resp) if r[0] <= b), None)
        bar_i = int(b / bar_s)
        sb = None if a is None else int(round((b - a) / bar_s))
        state = {
            "bars_since_song_start": bar_i,
            "bars_since_last_section_boundary": "none" if sb is None else sb,
            "on_8_bar_grid_from_boundary": yn(a is not None and min((b - a) % (8 * bar_s), 8 * bar_s - (b - a) % (8 * bar_s)) <= beat_s),
            "on_claude_8_bar_grid": yn(w is not None),
            "claude_said_next_section_is_chorus": yn(bool(last and last[2] == "chorus")),
            "high_band_step_db": int(round(parts["hf_step"])), "level_step_db": int(round(parts["lv_step"])),
            "drum_fill_ratio_previous_bar": round(float(parts["fill"]), 1),
            "quiet_bar_just_before": yn(parts["drop_prev"] <= -3.0),
            "brighter_than_song_so_far_db": int(round(parts["bright_song"])), "louder_than_song_so_far_db": int(round(parts["loud_song"])),
            "spectral_flatness_jump": round(float(parts["fl_ratio"]), 1),
        }
        if VARIANT == "short":   # 手がかりを 8 つに絞り、小さな整数と yes/no だけにする
            state = {k: state[k] for k in ("bars_since_song_start", "bars_since_last_section_boundary", "on_8_bar_grid_from_boundary", "on_claude_8_bar_grid",
                                           "high_band_step_db", "level_step_db", "quiet_bar_just_before", "brighter_than_song_so_far_db")}
            state["drum_fill_in_previous_bar"] = yn(parts["fill"] >= 1.3)
        rows.append((b, state, s, parts, w is not None, bar_i))
    return rows, bar_s

def ask_one(key_state):
    key, state = key_state
    return key, judge.ask_sync(state)

def main():
    logs_glob = sys.argv[1]; THR = arg("--thr", 0.8); PRE = arg("--pre", 1.0); GATE = "--gate" in sys.argv; dump = "--dump" in sys.argv; nocall = "--nocall" in sys.argv
    p = {"grid_anchor": 1}
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.isfile(CACHE) else {}
    todo = []; per_log = {}
    songs_only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--songs=")), None)   # ログ無し（Claude の窓無し）で曲だけ採点＝検証用
    items = [(f"nolog-{s}.jsonl", s) for s in songs_only] if songs_only else [(lp, cr.song_of(lp)) for lp in sorted(glob.glob(logs_glob))]
    for lp, song in items:
        wav = next((os.path.join(d, song + ".wav") for d in MU if os.path.isfile(os.path.join(d, song + ".wav"))), None)
        if wav is None: continue
        feat = ce.extract(wav)
        if songs_only:
            bt = feat["t"][feat["beat"] > 0]; lg = {"resp": [], "windows": [], "opens": [], "look": [], "bar_s": float(np.median(np.diff(bt))) * 4}
        else:
            lg = cr.parse_log(lp)
        rows, bar_s = build_rows(feat, lg, p)
        per_log[lp] = (song, rows, bar_s, lg)
        for b, state, s, parts, in_win, bar_i in rows:
            if bar_i < 16 or (s < PRE and not in_win): continue
            key = f"{os.path.basename(lp)}|{b:.2f}"
            if key not in cache: todo.append((key, state))
    print(f"Jev に聞く拍 {len(todo)}（キャッシュ {len(cache)}）")
    if todo and not nocall and not judge.load_key():
        print("鍵が無い（TYPESAFE_API_KEY）: キャッシュだけで採点する"); nocall = True
    if todo and not nocall:
        t0 = time.time(); n_fail = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for key, v in ex.map(ask_one, todo):
                if v is None: n_fail += 1
                else: cache[key] = v
        json.dump(cache, open(CACHE, "w", encoding="utf-8"))
        print(f"  往復 {time.time() - t0:.0f} 秒・失敗 {n_fail}")
    agg = {"hit": 0, "n": 0, "fp": 0, "errs": []}; per = {}
    UNION = "--union" in sys.argv; REL = arg("--rel", 0.0); ONLYCUE = "--onlycue" in sys.argv; VETO = "--veto" in sys.argv
    if VETO: ONLYCUE = True
    H = {"thr_win": 4, "thr_alone": 9, "grid_only": True, "bright_min": 1.0, "early_bars_all": 16, "win_bars": 1.0, "sup_min_bars": 4, "sup_max_bars": 8,
         "sup_win": 1.0, "sup_slack": 99, "sup_margin": 99, "rest_bars": 16, "rest_extra": 3.0, "drop_db": 5.0, "min_gap_bars": 22, "chorus_max": 16}
    for lp, (song, rows, bar_s, lg) in per_log.items():
        cue_dets = []
        if UNION or ONLYCUE:
            wav = next(os.path.join(d, song + ".wav") for d in MU if os.path.isfile(os.path.join(d, song + ".wav")))
            cue_dets = cr.det_hybrid(ce.extract(wav), H, lg)
        dets = []; state = "free"; ch_end = rest_until = -1.0; last = -99.0; recent = []
        for b, st, s, parts, in_win, bar_i in rows:
            key = f"{os.path.basename(lp)}|{b:.2f}"
            v = cache.get(key)
            if v is not None: recent.append(v); recent = recent[-16:]
            cue_now = any(abs(c - b) < 0.01 for c in cue_dets)
            if state == "chorus":
                if b >= ch_end: state = "rest"; rest_until = b + 16 * bar_s
                continue
            if state == "rest" and b >= rest_until: state = "free"
            if bar_i < 16: continue
            thr = THR + (0.1 if state == "rest" else 0.0)
            jev_ok = v is not None and not (GATE and not in_win) and v >= thr and (REL <= 0 or len(recent) < 8 or v >= REL * float(np.median(recent)))
            if ONLYCUE: jev_ok = False
            if VETO:   # cue のサビ入りを Jev が止める（noul が閾値未満なら入らない・答え無しは素通し＝fail-open）
                jev_ok = False; cue_now = cue_now and (v is None or v >= THR)
            if (jev_ok or cue_now) and b - last >= 22 * bar_s:
                state = "chorus"; ch_end = b + 16 * bar_s; last = b; dets.append(b)
        chorus, bounds = ce.load_truth(song)
        sc = ce.score(dets, chorus, bounds, lg["bar_s"])
        print(f"{song:20s} {os.path.basename(lp)[:28]:28s} dets={len(dets)} " + " ".join(f"{k}={v}" for k, v in sc.items() if k.startswith("ch_") and k != "ch_signed_bar") + (f" F={sc['F']}" if "F" in sc else ""))
        if dump:
            top = sorted(((cache.get(f"{os.path.basename(lp)}|{b:.2f}"), round(b, 1)) for b, *_ in rows if cache.get(f"{os.path.basename(lp)}|{b:.2f}") is not None), reverse=True)[:10]
            print(f"     det={[round(d, 1) for d in dets]} truth={chorus} err={sc.get('ch_signed_bar')} noul上位={[(round(v, 2), b) for v, b in sorted(top, key=lambda x: x[1])]}")
        if sc.get("ch_n"):
            agg["n"] += sc["ch_n"]; agg["hit"] += sc["ch_hit"]; agg["fp"] += sc["ch_fp"]; agg["errs"] += [abs(e) for e in sc["ch_signed_bar"]]
            q = per.setdefault(song, [0, 0, 0]); q[0] += sc["ch_hit"]; q[1] += sc["ch_n"]; q[2] += sc["ch_fp"]
    print(f"== jev {VARIANT} union={UNION} onlycue={ONLYCUE} veto={VETO} rel={REL} thr={THR} pre={PRE} gate={GATE}: サビ {agg['hit']}/{agg['n']}・空振り {agg['fp']}・|誤差| 中央値 {np.median(agg['errs']) if agg['errs'] else None} 小節  曲別: "
          + " ".join(f"{s}={q[0]}/{q[1]}/{q[2]}" for s, q in per.items()))

if __name__ == "__main__":
    main()
