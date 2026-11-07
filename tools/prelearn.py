# 事前学習（2026-11-08・本人の実験「曲を先に全部聴かせた時の演出」・提出物ではない・既定の走行は変えない）
#   曲全体を本番と同じ特徴量（tools/chorus_eval.extract・25 ms・拍追従）に通し、小節ごとの数値の表を 1 回だけ Claude に渡して、
#   区間の境界（小節）と各区間の色・動き・溜め・開き方のキューシート JSON を書かせる。本番は `--prelearn <json>` でそのキューシートどおりに
#   小節頭で開き、色もそれに従う（Claude のリアルタイムの読みは使わない・kiku_hikari/prelearn.py）。
#   予備（--truth）: Claude を呼ばず、sections/ の正解の秒（耳の正解か allin1 の仮正解）をそのままキューシートにする。method 欄に残す。
# 使い方: py -3.12 tools/prelearn.py <wav> --out <json> [--model claude-opus-5-5] [--knowledge knowledge/lighting_knowledge_v2.json]
#         py -3.12 tools/prelearn.py <wav> --out <json> --truth sections/chorus/<曲>.json
# 曲名・アーティスト名は書かない。ログと JSON には basename だけ。
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
from chorus_eval import extract, bars  # noqa: E402
from kiku_hikari.claude_worker import (Arousal, Color, Movement, OpenStyle, Section, Tame, Valence, load_env_key, load_knowledge, MODEL_DEFAULT)  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class Cue(BaseModel):
    bar: int = Field(ge=1, description="この区間が始まる小節番号（表の bar）")
    section: Section
    color: Color = Field(description="この区間の主色")
    movement: Movement
    tame: Tame = Field(description="この区間の終わり（次の境界の前 1 小節）の溜め")
    open_style: OpenStyle = Field(description="この区間の頭での開き方。verse・outro・intro は none が普通")
    arousal: Arousal
    valence: Valence
    reason: str = Field(max_length=60, description="表のどの数値からそう決めたか一文（日本語）")


class CueSheet(BaseModel):
    cues: list[Cue] = Field(min_length=2, max_length=32)
    note: str = Field(max_length=160, description="曲の構成の見立てを一文（日本語）")


SYSTEM = """あなたはライブの照明オペレーター。今回はリハーサルで曲を先に全部聴ける。
入力は曲全体を小節ごとに数えた表（bar=小節番号・t=秒・level=音量 dB の曲の中央値との差・hi=高域 2〜8 kHz の中央値との差・flat=スペクトル平坦度・onset=打音の強さの平均）。
仕事: 区間の境界を小節で切り、各区間の色・動き・溜め・開き方・感情を決めたキューシートを書く。本番は Python がこの表のとおり小節頭で開く。
決め方:
- 最初のキューは bar 1。bar は増える順。区間は 2 小節以上。区間の数は 24 まで。
- サビ（chorus）は level と hi が同時に上がって何小節も続く所。境目は 4 の倍数の小節に揃う事が多い。pre_chorus はサビの 2〜4 小節前。
- ブレイク（break）は level が中央値より 6 dB 以上落ちる所。間奏（interlude）・ブリッジ（bridge）・アウトロ（outro）も表から見立てる。
- 色は 8 色から。知識ファイルの規則に従う（サビは白を主役に・1 曲に 3〜4 色・サビの回ごとに色を変える・直前と同じ組み合わせを続けない）。
- open_style はサビの頭と大きな境目だけ none 以外。verse・outro は none。点滅は使わない。
以下は照明家の知識ファイル（JSON）。"""


def bar_table(feat: dict) -> tuple[list[float], list[dict], float]:
    bt = bars(feat)
    t = feat["t"]; rms = feat["rms_db"]; hi = feat["b_high"]; flat = feat["flat"]; onset = feat["onset"]
    ok = t > 3.0
    med_rms = float(np.median(rms[ok])); med_hi = float(np.median(hi[ok]))
    rows = []
    for i, b0 in enumerate(bt):
        b1 = bt[i + 1] if i + 1 < len(bt) else float(t[-1])
        m = (t >= b0) & (t < b1)
        if not m.any():
            continue
        rows.append({"bar": i + 1, "t": round(b0, 1), "level": round(float(rms[m].mean() - med_rms), 1), "hi": round(float(hi[m].mean() - med_hi), 1),
                     "flat": round(float(flat[m].mean()), 2), "onset": round(float(onset[m].mean()), 2)})
    tempo = feat["tempo"][feat["tempo"] > 0]
    bpm = float(np.median(tempo)) if len(tempo) else 0.0
    return bt, rows, bpm


def ask_claude(rows: list[dict], song_s: float, bpm: float, model: str, knowledge: str | None) -> tuple[CueSheet, dict]:
    import anthropic
    key = load_env_key()
    client = anthropic.Anthropic(api_key=key, timeout=120.0, max_retries=1) if key else anthropic.Anthropic(timeout=120.0, max_retries=1)
    table = "\n".join(f"{r['bar']} {r['t']} {r['level']} {r['hi']} {r['flat']} {r['onset']}" for r in rows)
    user = f"曲の長さ {song_s:.0f} 秒・テンポ {bpm:.0f} BPM・小節数 {len(rows)}。\n列: bar t level hi flat onset\n{table}"
    resp = client.messages.parse(model=model, max_tokens=4096, system=[{"type": "text", "text": SYSTEM}, {"type": "text", "text": load_knowledge(knowledge)}],
                                 messages=[{"role": "user", "content": user}], output_format=CueSheet)
    if resp.parsed_output is None:
        sys.exit(f"Claude の構造化出力が取れなかった（stop_reason={resp.stop_reason}）")
    u = resp.usage
    return resp.parsed_output, {"in_tokens": u.input_tokens, "out_tokens": u.output_tokens}


def from_truth(path: str, bt: list[float], song_s: float) -> CueSheet:
    """予備: 正解ファイルの秒をキューシートに。chorus_starts があればサビの頭、boundaries/points があれば境目（区間名は verse と chorus を交互）"""
    d = json.load(open(path, encoding="utf-8"))
    starts = d.get("chorus_starts")
    cues = [Cue(bar=1, section=Section.intro, color=Color.blue, movement=Movement.hold, tame=Tame.none, open_style=OpenStyle.none, arousal=Arousal.low, valence=Valence.neutral, reason="正解ファイル")]
    cols = [Color.white, Color.pink, Color.yellow, Color.light_blue]
    if starts:
        for k, s in enumerate(starts):
            b = int(np.argmin([abs(x - s) for x in bt])) + 1
            pre = max(2, b - 2)
            if pre > cues[-1].bar:
                cues.append(Cue(bar=pre, section=Section.pre_chorus, color=Color.blue, movement=Movement.sweep, tame=Tame.dim_hold, open_style=OpenStyle.none, arousal=Arousal.mid, valence=Valence.neutral, reason="正解ファイル"))
            cues.append(Cue(bar=b, section=Section.chorus, color=cols[k % len(cols)], movement=Movement.sweep, tame=Tame.none, open_style=OpenStyle.hard_cut, arousal=Arousal.high, valence=Valence.positive, reason="正解ファイル"))
            after = b + 16
            if after <= len(bt):
                cues.append(Cue(bar=after, section=Section.verse, color=Color.blue, movement=Movement.hold, tame=Tame.none, open_style=OpenStyle.none, arousal=Arousal.low, valence=Valence.neutral, reason="正解ファイル"))
    else:
        pts = d.get("boundaries") or d.get("points") or []
        if pts and isinstance(pts[0], dict):            # 耳の正解 sections/<曲>.json: [{"section": "verse", "t": 16.3}, ...]（区間名つき）
            k = 0
            for e in sorted(pts, key=lambda e: e["t"]):
                if e.get("level") == "allin1_continuation":      # 仮正解: 同じ区間の続き（区間の頭ではない）
                    continue
                name = e.get("section", "verse"); name = "intro" if name in ("boundary", "start") else name
                try:
                    sec = Section(name)
                except ValueError:
                    sec = Section.verse
                b = int(np.argmin([abs(x - e["t"]) for x in bt])) + 1
                if b <= cues[-1].bar:
                    continue
                ch = sec == Section.chorus
                if ch: k += 1
                cues.append(Cue(bar=b, section=sec, color=cols[(k - 1) % len(cols)] if ch else (Color.light_blue if sec == Section.pre_chorus else Color.blue),
                                movement=Movement.sweep if ch else Movement.hold, tame=Tame.dim_hold if sec == Section.pre_chorus else Tame.none,
                                open_style=OpenStyle.hard_cut if ch else OpenStyle.none, arousal=Arousal.high if ch else Arousal.low,
                                valence=Valence.positive if ch else Valence.neutral, reason="正解ファイル"))
        else:
            pts = sorted(pts)
            sec = [Section.verse, Section.chorus]
            for k, s in enumerate(pts):
                b = int(np.argmin([abs(x - s) for x in bt])) + 1
                if b <= cues[-1].bar:
                    continue
                ch = sec[k % 2] == Section.chorus
                cues.append(Cue(bar=b, section=sec[k % 2], color=cols[(k // 2) % len(cols)] if ch else Color.blue, movement=Movement.sweep if ch else Movement.hold, tame=Tame.none,
                                open_style=OpenStyle.hard_cut if ch else OpenStyle.none, arousal=Arousal.high if ch else Arousal.low, valence=Valence.positive if ch else Valence.neutral, reason="正解ファイル"))
    return CueSheet(cues=cues, note="予備: 正解ファイルの秒をそのままキューシートにした（Claude は呼んでいない）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav"); ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=MODEL_DEFAULT); ap.add_argument("--knowledge", default=None)
    ap.add_argument("--truth", default=None, help="予備: 正解ファイルの秒をキューシートにする（Claude を呼ばない）")
    a = ap.parse_args()
    feat = extract(a.wav)
    bt, rows, bpm = bar_table(feat)
    song_s = float(feat["t"][-1])
    usage = {}
    if a.truth:
        sheet = from_truth(a.truth, bt, song_s); method = "truth:" + os.path.basename(a.truth)
    else:
        sheet, usage = ask_claude(rows, song_s, bpm, a.model, a.knowledge); method = "claude-prelearn:" + a.model
    cues = []
    for c in sorted(sheet.cues, key=lambda c: c.bar):
        if cues and c.bar <= cues[-1]["bar"]:
            continue
        b = min(c.bar, len(bt))
        cues.append({"bar": c.bar, "t": round(bt[b - 1], 2), **{k: v.value for k, v in c.model_dump().items() if k not in ("bar", "reason")}, "reason": c.reason})
    out = {"method": method, "written": datetime.datetime.now().isoformat(timespec="seconds"), "song": os.path.splitext(os.path.basename(a.wav))[0],
           "song_seconds": round(song_s, 1), "bpm": round(bpm, 1), "bars": len(bt), "knowledge": os.path.basename(a.knowledge) if a.knowledge else "lighting_knowledge_v2.json",
           "usage": usage, "note": sheet.note, "cues": cues}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{out['song']}: {method} / {len(cues)} cues / {bpm:.0f} BPM / {len(bt)} bars / {usage}")
    for c in cues:
        print(f"  bar {c['bar']:3d} {c['t']:6.1f}s {c['section']:10s} {c['color']:10s} {c['movement']:6s} open={c['open_style']:18s} {c['reason']}")


if __name__ == "__main__":
    main()
