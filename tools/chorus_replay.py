# サビ判定のオフライン評価・その 2（Claude の答えを走行ログから再生して、音響の手がかりと組み合わせる＝案 C の作業台）
#   走行ログ（claude_resp・light_chorus・engine_event）から「Claude の境界に達した時刻（窓の始まり）」「直前の答え（bars_to_boundary・section_next）」を取り、
#   WAV の特徴量（tools/chorus_eval.py のキャッシュ）に重ねて、案ごとのサビ入りの時刻を出し、正解と比べる。Claude は呼ばない（費用 0・何百回も回せる）。
#   基準値（今の ③改）は、ログに残った look_chorus の時刻そのもの。
# 使い方: py -3.12 tools/chorus_replay.py --music "<dir>;<dir>" --logs "<glob>;<glob>" [--det hybrid] [--params '{...}'] [--dump]
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import chorus_eval as ce  # noqa: E402
from kiku_hikari.prior import load_prior, prior_adjust  # noqa: E402

WIN_SRC = {"", "chorus"}   # 再生に使う窓の種類（--windows で絞る: boundary=境界の窓だけ・chorus=サビの頭の窓だけ・both）
SONG_OF = {"tabi": "tabi_mastinchannel", "song14": "14_dance_rock", "show-tabi": "tabi_mastinchannel", "show-14": "14_dance_rock", "new-14": "14_dance_rock",
           "viz": "tabi_mastinchannel", "pars": "tabi_mastinchannel"}


def song_of(path: str) -> str | None:
    parts = path.replace("\\", "/").split("/")
    for s in ("03_idol_dance", "05_mixture_funk", "07_guitar_pop_rock", "11_enka", "14_dance_rock", "tabi_mastinchannel"):
        if s in parts or s in parts[-1]:
            return s
    for k, v in SONG_OF.items():
        if k in parts[-1] or (len(parts) > 1 and parts[-2] == k):
            return v
    try:                                                                   # 疑似モードのログ: audio_start の WAV 名から（m01 など名前に曲が無いログ）
        for l in open(path, encoding="utf-8"):
            if '"kind":"audio_start"' in l:
                dev = json.loads(l).get("device", "")
                if dev.startswith("file:"):
                    return os.path.splitext(os.path.basename(dev[5:]))[0]
                break
    except Exception:
        pass
    try:                                                                   # 名前に曲が無いログ（撮影の実機テイク）: 曲のテンポで判別
        tempo = [json.loads(l)["tempo_bpm"] for l in open(path, encoding="utf-8") if '"kind":"summary"' in l]
        if tempo and abs(tempo[0] - 126.8) < 2: return "tabi_mastinchannel"
        if tempo and abs(tempo[0] - 146) < 4: return "14_dance_rock"
    except Exception:
        pass
    return None


def parse_log(path: str) -> dict:
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    t0 = next((r["t"] for r in rows if r["kind"] == "loop_start"), 0.0)
    resp = [(r["t"] - t0, r.get("bars_to_boundary"), r.get("section_next"), r.get("confidence")) for r in rows if r["kind"] == "claude_resp"]
    windows = [r["at"] for r in rows if r["kind"] == "light_chorus" and r.get("src", "") in WIN_SRC]   # Claude の境界に達した時刻（窓の始まり）。src="chorus" は --chorus-hints の「サビの頭」の窓
    tempo = [r["tempo_bpm"] for r in rows if r["kind"] == "dmx" and r.get("tempo_bpm")]
    bar_s = 240 / float(np.median(tempo)) if tempo else 2.0
    if not windows:                                                             # 古いログ（light_chorus が無い）: 依頼時刻＋答えの小節数から境界を近似（low は採らない＝strict）
        req = {r["gen"]: r["t"] - t0 for r in rows if r["kind"] == "claude_req"}
        for r in rows:
            if r["kind"] == "claude_resp" and (r.get("bars_to_boundary") or 0) >= 1 and r.get("confidence") != "low" and r["gen"] in req:
                windows.append(round(req[r["gen"]] + (r["bars_to_boundary"] - 0.5) * bar_s, 2))
    opens = [r["at"] for r in rows if r["kind"] == "engine_event" and r.get("what") == "open"]
    look = [(r["why"], r["at"]) for r in rows if r["kind"] == "look_chorus"]
    return {"resp": resp, "windows": sorted(windows), "opens": opens, "look": look, "bar_s": bar_s}


def anchors_of(feat: dict, p: dict) -> list[float]:
    """格子の引き直し（--grid-anchor・look.py の grid_anchor と同じ条件）: 高域 ga_hf dB と音量 ga_lv dB が同時に段差で上がり曲のそれまでより ga_bright dB 明るい拍（前の境目から ga_gap 小節以上）"""
    t = feat["t"]; bt = [float(x) for x in t[feat["beat"] > 0]]
    beat_s = float(np.median(np.diff(bt))); bar_s = beat_s * 4; out = []
    for i in range(16, len(bt) - 1):
        b = bt[i]; s, parts = ce.cue_score(feat, b, bar_s, p.get("lat", 0.3), p)
        if s is None:
            continue
        if parts["hf_step"] >= p.get("ga_hf", 3.0) and parts["lv_step"] >= p.get("ga_lv", 1.5) and parts["bright_song"] >= p.get("ga_bright", 1.0) and (not out or b - out[-1] >= p.get("ga_gap", 4) * bar_s):
            out.append(b)
    return out


def shift_windows(windows: list[float], anchors: list[float], bar_s: float, resp: list) -> list[float]:
    """Claude の窓 w を、w より前（半小節以上）に分かっていた直近の境目を通る 8 小節格子の位相へずらす（[-4,4) 小節）。
    ずらした先がその窓を生んだ答えの届いた時刻より前なら、届いた時刻に置く（本番の look.shift_window の max(now, ...) と同じ）"""
    out = []
    for w in windows:
        past = [a for a in anchors if a <= w - 0.5 * bar_s]
        if not past:
            out.append(w); continue
        d = (w - past[-1]) % (8 * bar_s)
        d = d if d < 4 * bar_s else d - 8 * bar_s
        w2 = w - d
        arr = [r[0] for r in resp if r[0] <= w]
        if arr and w2 < arr[-1]:
            w2 = arr[-1]
        out.append(w2)
    return sorted(set(round(x, 2) for x in out))


def det_hybrid(feat: dict, p: dict, lg: dict) -> list[float]:
    """案 C: 音響の点数（chorus_eval.det_cue と同じ式）＋ Claude の窓。
       - Claude の境界に達してから win_bars 小節の間（手前 1 拍も含む）は閾値 thr_win（既定 3）。直前の答えが section_next=chorus なら更に −1
       - 窓の外は thr_alone（既定 9・曲の頭 early_bars 小節は +early_pen）
       - サビ中の乗り換えは、窓の中で thr_win+2 以上か、始めた時の点数 +sup_margin 以上（2 小節以上あと）
       - grid_anchor=1 なら窓を音の境目の位相へずらす（shift_windows・本番の --grid-anchor）"""
    t = feat["t"]; lat = p.get("lat", 0.3)
    bt = [float(x) for x in t[feat["beat"] > 0]]; bpb = 4
    resp = lg["resp"]; windows = lg["windows"]
    if p.get("grid_anchor"):
        windows = shift_windows(windows, anchors_of(feat, p), float(np.median(np.diff(bt))) * bpb, resp)
    out = []; state = "free"; ch_end = rest_until = -1.0; ch_start = -1.0; s_start = 0.0; low_run = 0
    prior = p.get("_prior"); ch_bar = None   # 曲構成の型（--prior・kiku_hikari/prior.py）。本番の look.py と同じ増減
    pend = None                              # confirm_bars>0 のとき: (候補の拍, 点数) を持って確認待ち
    for i in range(4 * bpb, len(bt) - 1):
        b = bt[i]; beat_s = bt[i] - bt[i - 1]
        if beat_s <= 0.2 or beat_s > 1.1:
            continue
        bar_s = beat_s * bpb
        s, parts = ce.cue_score(feat, b, bar_s, lat, p)
        if s is None:
            continue
        pre = max(beat_s, p.get("win_pre_bars", 0.0) * bar_s)             # 窓を手前にも広げる（既定は手前 1 拍）
        w = next((w for w in windows if -pre <= b - w < p.get("win_bars", 1.0) * bar_s), None)
        in_win = w is not None
        if pend is not None:                                               # 確認待ち（confirm_bars）: 候補から confirm_bars 小節あとも曲の中央値より明るく大きければ、そこで入る
            if b >= pend[0] + p["confirm_bars"] * bar_s:
                pb, ps = pend; pend = None
                if parts["bright_song"] >= p.get("bright_min", -99.0) and parts["loud_song"] >= p.get("confirm_loud", 0.0):
                    state = "chorus"; ch_start = pb; s_start = ps; ch_end = pb + p.get("chorus_max", 16) * bar_s; out.append(b if p.get("confirm_late", True) else pb); ch_bar = int(pb / bar_s)
                    continue
            else:
                continue
        last = next((r for r in reversed(resp) if r[0] <= b), None)
        next_chorus = bool(last and last[2] == "chorus")
        if in_win:
            thr = p.get("thr_win", 3.0) - (1.0 if next_chorus else 0.0)
            if parts["bright_song"] < p.get("bright_min", -99.0):
                thr += 100                                                 # 曲のそれまでより明るくない所はサビにしない
        else:
            thr = p.get("thr_alone", 9.0) + (100 if p.get("grid_only") else 0)
            if b < p.get("early_bars", 20) * bar_s:
                thr += p.get("early_pen", 3.0)
        if b < p.get("early_bars_all", 0) * bar_s:
            thr += 100
        bar_i = int(b / bar_s)
        if prior is not None:
            thr += prior_adjust(prior, bar_i, ch_bar, len(out), p.get("prior_w", 1.0))
        if state == "chorus":
            if p.get("sup_min_bars", 2) * bar_s <= b - ch_start <= p.get("sup_max_bars", 99) * bar_s and ((in_win and s >= max(thr + p.get("sup_win", 2.0), s_start - p.get("sup_slack", 2.0))) or s >= s_start + p.get("sup_margin", 3.0)):
                ch_start = b; s_start = s; ch_end = b + p.get("chorus_max", 16) * bar_s; out.append(b); low_run = 0; ch_bar = bar_i
                continue
            if b >= ch_end:
                state = "rest"; rest_until = b + p.get("rest_bars", 8) * bar_s; low_run = 0
            elif i % bpb == 0:
                if parts["loud_song"] < -p.get("drop_db", 5.0):
                    low_run += 1
                    if low_run >= 2:
                        state = "rest"; rest_until = b + p.get("rest_bars", 8) * bar_s
                else:
                    low_run = 0
            continue
        if state == "rest":
            if b >= rest_until:
                state = "free"
            else:
                thr += p.get("rest_extra", 3.0)
        if s >= thr and (not out or b - out[-1] >= p.get("min_gap_bars", 4) * bar_s):
            if p.get("confirm_bars", 0):
                pend = (b, s); continue
            state = "chorus"; ch_start = b; s_start = s; ch_end = b + p.get("chorus_max", 16) * bar_s; out.append(b); ch_bar = bar_i
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", required=True); ap.add_argument("--logs", required=True, help="ログの glob（; 区切り）")
    ap.add_argument("--det", default="hybrid", choices=["hybrid", "baseline", "cue"]); ap.add_argument("--params", default="{}"); ap.add_argument("--dump", action="store_true")
    ap.add_argument("--windows", default="both", choices=["both", "boundary", "chorus"], help="再生に使う窓（light_chorus の src）")
    ap.add_argument("--prior", default=None, help="曲構成の型の JSON（kiku_hikari/prior.py・本番の --structure-prior と同じファイル）")
    a = ap.parse_args(); p = json.loads(a.params)
    global WIN_SRC
    WIN_SRC = {"both": {"", "chorus"}, "boundary": {""}, "chorus": {"chorus"}}[a.windows]
    if a.prior:
        p["_prior"] = load_prior(a.prior)
    dirs = a.music.split(";")
    logs = sorted(x for g in a.logs.split(";") for x in glob.glob(g))
    agg = {"F0": [], "F1": [], "hit": 0, "n": 0, "miss": 0, "fp": 0, "errs": []}
    for lp in logs:
        song = song_of(lp)
        if song is None:
            print("曲名が分からない:", lp); continue
        wav = next((os.path.join(d, song + ".wav") for d in dirs if os.path.isfile(os.path.join(d, song + ".wav"))), None)
        if wav is None:
            continue
        feat = ce.extract(wav); lg = parse_log(lp)
        if a.det == "baseline":
            dets = [at for _, at in lg["look"]]
        elif a.det == "cue":
            dets = ce.det_cue(feat, p)
        else:
            dets = det_hybrid(feat, p, lg)
        chorus, bounds = ce.load_truth(song)
        bar_s = lg["bar_s"]
        sc = ce.score(dets, chorus, bounds, bar_s)
        sc0 = ce.score(sorted(lg["opens"]), [], bounds, bar_s) if bounds else {}
        merged = sorted(lg["opens"]) + [d for d in dets if all(abs(d - o) > 1.0 for o in lg["opens"])]   # 既にある開きの ±1 秒は数えない
        sc1 = ce.score(sorted(merged), [], bounds, bar_s) if bounds else {}
        prec = (sum(any(abs(d - b) <= 2.0 for b in bounds) for d in dets) / len(dets)) if (bounds and dets) else None   # サビ入りが耳の境界点に乗る割合
        name = os.path.basename(lp)[:34]
        print(f"{song:20s} {name:34s} dets={len(dets)} " + " ".join(f"{k}={v}" for k, v in sc.items() if k.startswith("ch_") and k != "ch_signed_bar")
              + (f" | F(ログの開きのみ)={sc0.get('F')} F(開き+サビ入り)={sc1.get('F')} 境界に乗ったサビ入り={prec}" if bounds else ""))
        if a.dump:
            print(f"     det={[round(d, 1) for d in dets]} windows={[round(w, 1) for w in lg['windows']]} look={lg['look']} err={sc.get('ch_signed_bar')}")
        if bounds:
            agg["F0"].append(sc0["F"]); agg["F1"].append(sc1["F"])
            agg.setdefault("prec", []).append(prec if prec is not None else 0.0); agg.setdefault("nd", []).append(len(dets))
        if sc.get("ch_n"):
            agg["n"] += sc["ch_n"]; agg["hit"] += sc["ch_hit"]; agg["miss"] += sc["ch_miss"]; agg["fp"] += sc["ch_fp"]; agg["errs"] += [abs(e) for e in sc["ch_signed_bar"]]
    print(f"== {a.det} {a.params}: サビ {agg['hit']}/{agg['n']}・取り逃し {agg['miss']}・空振り {agg['fp']}・|誤差| 中央値 {np.median(agg['errs']) if agg['errs'] else None} 小節"
          + (f" | F 開きのみ {np.mean(agg['F0']):.3f} → 開き+サビ入り {np.mean(agg['F1']):.3f} (n={len(agg['F1'])})・耳の境界に乗ったサビ入り {np.mean(agg['prec']):.2f}（1 曲 {np.mean(agg['nd']):.1f} 回）" if agg["F1"] else ""))


if __name__ == "__main__":
    main()
