# 実行ログ（JSONL）から動画用の字幕（SRT）を作る。Claude の判断・境界の開き・救済・テンポを時刻つきで出す
# 使い方: py -3.12 tools/subtitles.py logs/public/xxx.jsonl > out.srt   （時刻は loop_start＝曲の頭 基準）
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


def ts(sec: float) -> str:
    ms = int(round(sec * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main(path: str):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    t0 = next((r["t"] for r in rows if r["kind"] == "loop_start"), 0.0)
    cues = []
    for r in rows:
        t = r["t"] - t0
        if t < 0:
            continue
        if r["kind"] == "claude_resp":
            cues.append((t, 3.5, f"Claude: {r['section_now']}→{r['section_next']} あと{r['seconds_to_boundary']}s / {r['color']}→{r['next_color']} / {r['movement']} / 溜め {r['tame']} / 「{r['scene_word']}」({r['confidence']})\n{r['reason']}"))
        elif r["kind"] == "engine_event" and r["what"] == "open":
            cues.append((r["at"], 1.5, "▶ 境界で開く（小節頭）"))
        elif r["kind"] == "engine_event" and r["what"] == "rescue":
            cues.append((r["at"], 1.5, "⚑ 音響変化を検出 → 救済"))
        elif r["kind"] == "tap":
            cues.append((t, 1.0, "拍頭を合わせ直し"))
    cues.sort()
    for i, (t, dur, text) in enumerate(cues, 1):
        end = min(t + dur, cues[i][0] - 0.05) if i < len(cues) else t + dur
        print(f"{i}\n{ts(t)} --> {ts(max(end, t + 0.5))}\n{text}\n")


if __name__ == "__main__":
    main(sys.argv[1])
