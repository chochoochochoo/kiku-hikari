# サビ判定のオフライン評価（2026-11-06・本人指示「サビの判定がまだ甘い」の作業台）
#   WAV を実時間待ちなしで本番と同じ特徴量（audio_in.AudioIn.features・25 ms）と拍追従（beat.BeatTracker）に通し、
#   サビの頭の検出器（下の DETECTORS）を当てて、正解（サビの頭の秒）と比べる。Claude は呼ばない（音響の条件だけを何百回も採点するため）。
#   正解: sections/chorus/<曲>.json {"chorus_starts":[秒...], "source":"human|gemini"}（非公開・.gitignore の sections/* に含まれる）
#   採点: (b) サビ入り誤差＝正解のサビの頭ごとに最も近い検出との差（小節）。±2 小節に無ければ取り逃し。余った検出は空振り
#         (a) 境界 F＝検出を「開き」と見て、作者の耳の正解点（sections/<曲>.json・6 秒未満は間引き・12 秒以降）と ±2 秒で 1 対 1 照合
# 使い方: py -3.12 tools/chorus_eval.py --music <wav のフォルダ> --songs 03_idol_dance,... [--det base,grid] [--dump]
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
from kiku_hikari.audio_in import AudioIn          # noqa: E402
from kiku_hikari.beat import FS, HOP, BeatTracker  # noqa: E402

FEAT_DIR = os.path.join(ROOT, "logs", "feat")      # 特徴量のキャッシュ（logs/ は非公開）


def load_wav(path: str) -> np.ndarray:
    import soundfile as sf
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    if sr != FS:
        from scipy.signal import resample_poly
        g = math.gcd(sr, FS)
        y = resample_poly(y, FS // g, sr // g).astype(np.float32)
    return y


def extract(path: str) -> dict:
    """本番と同じ 25 ms ブロックの特徴量と拍（因果）。キャッシュがあればそれを返す"""
    os.makedirs(FEAT_DIR, exist_ok=True)
    cache = os.path.join(FEAT_DIR, os.path.splitext(os.path.basename(path))[0] + ".npz")
    if os.path.isfile(cache) and os.path.getmtime(cache) >= os.path.getmtime(path):
        return dict(np.load(cache))
    y = load_wav(path)
    ai = AudioIn.__new__(AudioIn)
    ai.fs, ai.block = FS, HOP
    ai._win = np.hanning(HOP).astype(np.float32); ai._freqs = np.fft.rfftfreq(HOP, 1 / FS)
    ai._low = (ai._freqs >= 40) & (ai._freqs <= 250); ai._prev_low = None
    # 追加の帯域（サビの手がかり候補）: 低域 40–250 / 中域 250–2k / 高域 2k–8k のパワー（dB）
    bands = [(40, 250), (250, 2000), (2000, 8000)]
    masks = [(ai._freqs >= lo) & (ai._freqs < hi) for lo, hi in bands]
    tr = BeatTracker()
    n = len(y) // HOP
    cols = {k: np.zeros(n, dtype=np.float32) for k in ("t", "rms_db", "centroid", "flux_low", "onset", "tempo", "phase", "beat", "conf", "b_low", "b_mid", "b_high", "flat")}
    for i in range(n):
        x = y[i * HOP:(i + 1) * HOP]
        f = AudioIn.features(ai, x)
        st = tr.process(x)
        spec = np.abs(np.fft.rfft(x * ai._win)); p = spec * spec + 1e-12
        cols["t"][i] = (i + 1) * HOP / FS
        cols["rms_db"][i] = f["rms_db"]; cols["centroid"][i] = f["centroid"]; cols["flux_low"][i] = f["flux_low"]
        cols["onset"][i] = st["onset"]; cols["tempo"][i] = st["tempo_bpm"]; cols["phase"][i] = st["phase"]; cols["beat"][i] = 1.0 if st["beat"] else 0.0; cols["conf"][i] = st["confidence"]
        for k, m in zip(("b_low", "b_mid", "b_high"), masks):
            cols[k][i] = 10 * np.log10(float(p[m].sum()))
        cols["flat"][i] = float(np.exp(np.mean(np.log(p))) / np.mean(p))   # スペクトル平坦度（歪んだギター・全部鳴る＝高い）
    np.savez(cache, **cols)
    return cols


def bars(feat: dict, bpb: int = 4) -> list[float]:
    """拍頭の時刻から小節頭の時刻（bpb 拍ごと・最初の拍を 1 拍目とみなす）"""
    bt = feat["t"][feat["beat"] > 0]
    return [float(bt[i]) for i in range(0, len(bt), bpb)]


# ---- 検出器（WAV 全体の特徴量を受け、サビの頭の時刻の一覧を返す。因果の規則だけで書く＝未来の値を使わない） ----
def det_base(feat: dict, p: dict) -> list[float]:
    """今の ③改 の音響条件を Claude の窓なしで再現: 小節頭ごとに、速い平滑（0.4 秒）の音量が直前 4 小節の平均より rise_db 以上高ければサビ入り。
    サビは chorus_max 小節で終わり、その後 rest 小節は入らない（休み中の 3 dB の跳ねだけ例外）。"""
    t, e = feat["t"], feat["rms_db"]
    fast = ema(e, t, 0.4)
    out = []; state = "free"; ch_end = rest_until = -1.0; rest_e = []
    bs = bars(feat)
    for i, b in enumerate(bs):
        if b < p.get("warmup", 8.0):
            continue
        j = int(np.searchsorted(t, b))
        if j >= len(t):
            break
        bar_s = (bs[i] - bs[i - 1]) if i else 2.0
        if state == "chorus" and b >= ch_end:
            state = "rest"; rest_until = b + p.get("rest_bars", 8) * bar_s; rest_e = []
        if state == "rest":
            rest_e.append(fast[j])
            if len(rest_e) >= 2 and fast[j] >= np.mean(rest_e[:-1]) + p.get("jump_db", 3.0):
                state = "chorus"; ch_end = b + p.get("chorus_max", 16) * bar_s; out.append(b); continue
            if b >= rest_until:
                state = "free"
        if state == "free":
            before = fast[(t >= b - 1.0 - 4 * bar_s) & (t < b - 1.0)]
            rise = fast[j] - before.mean() if len(before) else 0.0
            if rise >= p.get("rise_db", 1.5):
                state = "chorus"; ch_end = b + p.get("chorus_max", 16) * bar_s; out.append(b)
    return out


def ema(x: np.ndarray, t: np.ndarray, tau: float) -> np.ndarray:
    out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        k = 1 - math.exp(-(t[i] - t[i - 1]) / tau)
        out[i] = out[i - 1] + (x[i] - out[i - 1]) * k
    return out


def _win(feat, lo, hi, key):
    t = feat["t"]; m = (t >= lo) & (t < hi)
    return feat[key][m] if m.any() else None


def cue_score(feat: dict, b: float, bar_s: float, lat: float, p: dict):
    """拍の時刻 b での「サビの頭らしさ」（kiku_hikari/cue.py と同じ式）"""
    from kiku_hikari.cue import cue_score as _cs
    return _cs(feat["t"], feat["rms_db"], feat["b_high"], feat["flat"], feat["onset"], b, bar_s, {**p, "lat": lat})


def det_cue(feat: dict, p: dict) -> list[float]:
    """学習の手がかり（gakushu/sabi-cues-v1: F1 フィル・F3 小節頭の高域の立ち上がり＋音量の段差・S04 直前の休み・S08 句は 4/8 小節・S09 冒頭は少ない）を
    拍ごとの点数にして、閾値を越えたらサビ入り（拍追従の小節頭は本当の小節頭と 1〜2 拍ずれることがあるので、判断は拍ごと）。
    判断は拍の時刻から lat 秒（既定 0.3）で行う（因果）。参照は直前 2 小節（最後の 0.1 秒は除く）。
    句の格子: 最初の強い段差（anchor）から 4 小節の倍数の拍に乗る候補は閾値を下げる（S08）。曲の頭から early_bars までは閾値を上げる（S09）。
    サビは chorus_max 小節で終わる（途中で曲の中央値より drop_db 低い小節が 2 つ続けば早く終わる）。その後 rest_bars は閾値を上げる。"""
    t = feat["t"]
    lat = p.get("lat", 0.3)
    bt = [float(x) for x in t[feat["beat"] > 0]]
    bpb = 4
    out = []; state = "free"; ch_end = rest_until = -1.0; low_run = 0; anchor = None; ch_start = -1.0; s_start = 0.0
    scores = []
    for i in range(4 * bpb, len(bt) - 1):
        b = bt[i]; beat_s = bt[i] - bt[i - 1]
        if beat_s <= 0.2 or beat_s > 1.1:
            continue
        bar_s = beat_s * bpb
        s, parts = cue_score(feat, b, bar_s, lat, p)
        if s is None:
            continue
        hf_step, lv_step, fl_ratio, fill, drop_prev, bright_song, loud_song = (parts[k] for k in ("hf_step", "lv_step", "fl_ratio", "fill", "drop_prev", "bright_song", "loud_song"))
        thr = p.get("thr", 6.0)
        if b < p.get("early_bars", 20) * bar_s:
            thr += p.get("early_pen", 3.0)                                 # S09: 曲の頭寄りは少ない
        on_grid = False
        if anchor is not None:
            nb = round((b - anchor) / beat_s)
            on_grid = (nb % (4 * bpb) == 0) and abs((b - anchor) - nb * beat_s) < 0.6 * beat_s
            if on_grid:
                thr -= p.get("grid_bonus", 1.5)                            # S08: 句（4 小節）の頭に乗る
            elif p.get("grid_only"):
                thr += 100
        if anchor is None and s >= p.get("anchor_thr", 4.0):
            anchor = b
        scores.append((i, b, s, hf_step, lv_step, fl_ratio, fill, drop_prev, bright_song, int(on_grid)))
        if state == "chorus":
            # 乗り換え（S05: サビの直前は B メロが 54%・B メロの入りで先にサビ扱いになった時、より強い段差が 2 小節以上あとに来たら本当のサビとして入り直す）
            if s >= max(thr, s_start + p.get("sup_margin", 1.0)) and b - ch_start >= p.get("sup_min_bars", 2) * bar_s:
                ch_start = b; s_start = s; ch_end = b + p.get("chorus_max", 16) * bar_s; out.append(b); anchor = b; low_run = 0
                continue
            if b >= ch_end:
                state = "rest"; rest_until = b + p.get("rest_bars", 8) * bar_s; low_run = 0
            elif loud_song < -p.get("drop_db", 5.0) and i % bpb == 0:
                low_run += 1
                if low_run >= 2:
                    state = "rest"; rest_until = b + p.get("rest_bars", 8) * bar_s
            else:
                low_run = 0 if i % bpb == 0 and loud_song >= -p.get("drop_db", 5.0) else low_run
            continue
        if state == "rest":
            if b >= rest_until:
                state = "free"
            else:
                thr += p.get("rest_extra", 3.0)
        if s >= thr:
            state = "chorus"; ch_start = b; s_start = s; ch_end = b + p.get("chorus_max", 16) * bar_s; out.append(b); anchor = b
    if p.get("verbose"):
        for row in scores:
            if row[2] >= p.get("verbose_min", 3.0):
                print("   i=%3d t=%6.1f s=%5.2f hf=%5.2f lv=%5.2f fl=%4.2f fill=%4.2f drop=%5.2f bright=%5.2f grid=%d" % row)
    return out


DETECTORS = {"base": det_base, "cue": det_cue}


# ---- 採点 ----
def load_truth(song: str) -> tuple[list[float], list[float]]:
    """(サビの頭の秒, 耳の正解の境界点)。無ければ空"""
    ch = os.path.join(ROOT, "sections", "chorus", f"{song}.json")
    bd = os.path.join(ROOT, "sections", f"{song}.json")
    bl = json.load(open(bd, encoding="utf-8"))["boundaries"] if os.path.isfile(bd) else []
    bs = [b["t"] for b in bl]
    human = [b["t"] for b in bl if b.get("section") == "chorus"]              # 耳の正解（cue.html の「サビ chorus」）が最優先
    if human:
        return sorted(human), bs
    cs = json.load(open(ch, encoding="utf-8"))["chorus_starts"] if os.path.isfile(ch) else []   # 無ければ sections/chorus/（作者メモ・Gemini の仮正解）
    return cs, bs


def thin(ts, gap=6.0):
    out = []
    for x in sorted(ts):
        if not out or x - out[-1] >= gap:
            out.append(x)
    return out


def score(dets: list[float], chorus: list[float], bounds: list[float], bar_s: float, tol_s: float = 2.0) -> dict:
    r = {}
    if chorus:
        errs = []; miss = 0; used = set()
        for c in chorus:
            cand = [(abs(d - c), i) for i, d in enumerate(dets) if i not in used and abs(d - c) <= 2 * bar_s]
            if cand:
                e, i = min(cand); used.add(i); errs.append((dets[i] - c) / bar_s)
            else:
                miss += 1
        r.update(ch_n=len(chorus), ch_hit=len(errs), ch_miss=miss, ch_fp=len(dets) - len(errs),
                 ch_med_abs_bar=float(np.median(np.abs(errs))) if errs else None, ch_signed_bar=[round(e, 2) for e in errs])
    if bounds:
        tr = thin([b for b in bounds if b >= 12.0]); used = set(); hit = 0
        for b in tr:
            cand = [(abs(d - b), i) for i, d in enumerate(dets) if i not in used and abs(d - b) <= tol_s]
            if cand:
                used.add(min(cand)[1]); hit += 1
        r.update(bd_truth=len(tr), bd_hit=hit, bd_opens=len(dets), F=round(2 * hit / max(1, len(tr) + len(dets)), 3))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", required=True, help="wav のフォルダ（複数は ; 区切り）")
    ap.add_argument("--songs", required=True, help="曲名（拡張子なし・, 区切り）")
    ap.add_argument("--det", default="base")
    ap.add_argument("--params", default="{}", help='検出器のパラメータ JSON（例 {"rise_db":2.0}）')
    ap.add_argument("--dump", action="store_true", help="検出時刻と正解を曲ごとに出す")
    a = ap.parse_args()
    p = json.loads(a.params)
    dirs = a.music.split(";")
    tot = {"F": [], "med": [], "miss": 0, "hit": 0, "fp": 0, "n": 0}
    for song in a.songs.split(","):
        wav = next((os.path.join(d, song + ".wav") for d in dirs if os.path.isfile(os.path.join(d, song + ".wav"))), None)
        if wav is None:
            print(f"{song}: wav が無い"); continue
        feat = extract(wav)
        bs = bars(feat); bar_s = float(np.median(np.diff(bs))) if len(bs) > 2 else 2.0
        dets = DETECTORS[a.det](feat, p)
        chorus, bounds = load_truth(song)
        sc = score(dets, chorus, bounds, bar_s)
        print(f"{song:22s} bar={bar_s:.2f}s dets={len(dets):2d} " + " ".join(f"{k}={v}" for k, v in sc.items() if k != "ch_signed_bar"))
        if a.dump:
            print(f"   det={[round(d, 1) for d in dets]}\n   chorus={chorus}\n   err_bar={sc.get('ch_signed_bar')}")
        if "F" in sc: tot["F"].append(sc["F"])
        if sc.get("ch_n"):
            tot["n"] += sc["ch_n"]; tot["hit"] += sc["ch_hit"]; tot["miss"] += sc["ch_miss"]; tot["fp"] += sc["ch_fp"]
            if sc["ch_med_abs_bar"] is not None: tot["med"].append(sc["ch_med_abs_bar"])
    print(f"== {a.det} {a.params}: F 平均 {np.mean(tot['F']):.3f} (n={len(tot['F'])}) | サビ {tot['hit']}/{tot['n']} 当たり・取り逃し {tot['miss']}・空振り {tot['fp']}・誤差中央値(小節) {np.median(tot['med']) if tot['med'] else None}")


if __name__ == "__main__":
    main()
