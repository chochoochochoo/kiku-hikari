# A/B 比較の交絡チェック（logs/ab/ の既存ログだけで計算・走り直さない）
#   腕ごと: Claude が low 以外を言った回数・開き方つき予測の回数・Claude 由来の開き・遅延・入力トークン・遅れフレーム・追従テンポ
#   曲ごと: 腕どうしで救済（変化検出）の時刻がどれだけ一致するか＝ F 差のうち救済由来の偶然の大きさ
# 使い方: py -3.12 tools/ab_diag.py
import glob
import json
import os
import statistics as st
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(f):
    return [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]


def main():
    arms = defaultdict(list); rescues = defaultdict(dict)
    for f in sorted(glob.glob(os.path.join(ROOT, "logs", "ab", "*", "*", "*.jsonl"))):
        rows = load(f)
        if not any(r["kind"] == "summary" for r in rows):
            continue
        arm = os.path.basename(os.path.dirname(os.path.dirname(f))); song = os.path.basename(os.path.dirname(f))
        resp = [r for r in rows if r["kind"] == "claude_resp"]
        opens = [r["at"] for r in rows if r["kind"] == "engine_event" and r["what"] == "open"]
        resc = [r["at"] for r in rows if r["kind"] == "engine_event" and r["what"] == "rescue"]
        tempos = [r["tempo_bpm"] for r in rows if r["kind"] == "beat" and r["t"] > 20]
        arms[arm.rsplit("-rep", 1)[0]].append({
            "song": song, "resp": len(resp), "req": sum(r["kind"] == "claude_req" for r in rows),
            "not_low": sum(r["confidence"] != "low" for r in resp),
            "styled": sum(r["open_style"] != "none" for r in resp),
            "styled_not_low": sum(r["open_style"] != "none" and r["confidence"] != "low" for r in resp),
            "pred_opens": sum(1 for o in opens if not any(0 <= o - x < 2.5 for x in resc)),
            "opens": len(opens), "rescues": len(resc),
            "lat": st.median([r["latency"] for r in resp]) if resp else 0, "in_tok": st.mean([r["in_tokens"] for r in resp]) if resp else 0,
            "late_ms": sum(r["by_ms"] for r in rows if r["kind"] == "late"),
            "tempo": st.median(tempos) if tempos else 0,
            "sections": len(set(r["section_now"] for r in resp)),
        })
        rescues[song][arm] = resc
    print("腕 | 走行 | 応答/要求 | low以外 | 開き方つき | 両方 | Claude由来の開き | 開き | 救済 | 遅延中央 | 入力tok | 遅れms | 区間の種類")
    for a, rs in sorted(arms.items()):
        s = lambda k: sum(r[k] for r in rs)
        print(f"{a} | {len(rs)} | {s('resp')}/{s('req')} | {s('not_low')} | {s('styled')} | {s('styled_not_low')} | {s('pred_opens')} | {s('opens')} | {s('rescues')} | "
              f"{st.median(r['lat'] for r in rs):.2f} | {st.mean(r['in_tok'] for r in rs):.0f} | {s('late_ms'):.0f} | {st.mean(r['sections'] for r in rs):.1f}")
    print("\n曲 | 追従テンポの中央値（全走行の範囲）")
    by_song = defaultdict(list)
    for rs in arms.values():
        for r in rs:
            by_song[r["song"]].append(r["tempo"])
    for s_, ts in sorted(by_song.items()):
        print(f"{s_} | {st.median(ts):.1f}（{min(ts):.1f}〜{max(ts):.1f}）")
    print("\n曲 | 救済の時刻が腕どうしで ±0.5 秒以内に一致する割合（高いほど救済はどの腕でも同じ＝差は Claude 由来か偶然）")
    for s_, d in sorted(rescues.items()):
        ks = list(d); agree = tot = 0
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                for x in d[ks[i]]:
                    tot += 1; agree += any(abs(x - y) <= 0.5 for y in d[ks[j]])
        print(f"{s_} | {agree}/{tot}")


if __name__ == "__main__":
    main()
