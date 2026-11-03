# 学習側の知識ファイルをリポジトリに取り込む（v2 第 2 版などの差し替えも同じコマンドで上書き）
#   中身（規則・出典 URL・引用）はそのまま。リポジトリ外の場所を指す部分（~/Claude/・gakushu/）だけを取り除く
# 使い方: py -3.12 tools/import_knowledge.py <学習側の rules-v2.json> [--out knowledge/lighting_knowledge_v2.json]
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def clean(s: str) -> str:
    s = s.replace("~/Claude/research/", "research/")
    s = re.sub(r"観察 gakushu/[\w./-]*:\s*", "観察: ", s)
    s = re.sub(r"gakushu/[\w./-]+", "学習側の集計", s)
    return s


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("--out", default=os.path.join(ROOT, "knowledge", "lighting_knowledge_v2.json"))
    a = ap.parse_args()
    s = clean(open(a.src, encoding="utf-8").read())   # 文面は元のまま（A/B で試したものと同じ）
    d = json.loads(s)
    for k in ("version", "sections", "emotion_color", "vocabulary", "safety", "rules"):
        if k not in d:
            sys.exit(f"形が違う（{k} が無い）: {a.src}")
    for bad in ("~/Claude", "gakushu/", ":\\", "Users/"):
        if bad in s:
            sys.exit(f"リポジトリ外の場所が残った: {bad}")
    open(a.out, "w", encoding="utf-8", newline="\n").write(s + "\n")
    print(f"取り込み: {os.path.relpath(a.out, ROOT)}｜版 {d['version']}｜規則 {len(d['rules'])} 本｜出典 URL {len(re.findall(r'https?://', s))} 件")


if __name__ == "__main__":
    main()
