# 知識 v3 ＝ v2 ＋ 作者の規則（2026-11-07 本人決定「今夜自分で規則を書き足す」）を作る
#   入力 1: knowledge/lighting_knowledge_v2.json（既定・文面は変えない）
#   入力 2: 作者の規則の JSON。形は 2 通りを受ける
#     (a) 規則の配列: [{"id": "R35", "when": "...", "then": "...", "why": "...", "source"?: "..."}, ...]
#     (b) 辞書: {"decisions": {"R24": {"adopt": true, "when"?, "then"?, "why"?}, "R25": {"adopt": false}}, "rules": [ (a) と同じ ]}
#   既存の id（R24・R25 など）は本文を差し替え、新しい id（R35〜）は末尾に足す。adopt=false の既存規則は外す
#   作者の規則の source は既定で「作者の現場の判断（劇団・コンサートでの照明操作の経験）」、v2 欄は「作者」
# 使い方: py -3.12 tools/merge_knowledge.py <作者の規則.json> [--base knowledge/lighting_knowledge_v2.json] [--out knowledge/lighting_knowledge_v3.json] [--dry-run]
import argparse
import datetime
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTHOR_SOURCE = "作者の現場の判断（劇団・コンサートでの照明操作の経験）"
REQUIRED = ("when", "then", "why")


def load_author(path: str):
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, list):
        return {}, d
    if isinstance(d, dict):
        return d.get("decisions", {}) or {}, d.get("rules", []) or []
    sys.exit("作者の規則の形が違う（配列か {decisions, rules} の辞書）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("author")
    ap.add_argument("--base", default=os.path.join(ROOT, "knowledge", "lighting_knowledge_v2.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "knowledge", "lighting_knowledge_v3.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    base = json.load(open(a.base, encoding="utf-8"))
    decisions, new_rules = load_author(a.author)
    rules = [dict(r) for r in base["rules"]]
    by_id = {r["id"]: r for r in rules}
    log = []
    # 1. 既存規則の採否と本文（R24・R25 の判断待ちなど）
    for rid, dec in decisions.items():
        if rid not in by_id:
            sys.exit(f"decisions の {rid} は v2 に無い")
        if not dec.get("adopt", True):
            rules = [r for r in rules if r["id"] != rid]; log.append(f"{rid} 外す"); continue
        r = by_id[rid]
        for k in REQUIRED:
            if dec.get(k):
                r[k] = dec[k]
        r["source"] = dec.get("source") or AUTHOR_SOURCE
        r["v2"] = "作者"
        log.append(f"{rid} 採用（作者の本文）")
    # 2. 新規（R35〜）と、配列で渡された既存 id の差し替え
    for nr in new_rules:
        rid = nr.get("id")
        if not rid or not re.fullmatch(r"R\d{2,3}", rid):
            sys.exit(f"id が無いか形が違う: {nr}")
        missing = [k for k in REQUIRED if not str(nr.get(k, "")).strip()]
        if missing:
            sys.exit(f"{rid}: {'・'.join(missing)} が空")
        out = {"id": rid, "when": nr["when"], "then": nr["then"], "why": nr["why"], "source": nr.get("source") or AUTHOR_SOURCE, "v2": "作者"}
        if rid in by_id:
            i = next(i for i, r in enumerate(rules) if r["id"] == rid); rules[i] = out; log.append(f"{rid} 差し替え（作者の本文）")
        else:
            rules.append(out); log.append(f"{rid} 追加")
    ids = [r["id"] for r in rules]
    if len(ids) != len(set(ids)):
        sys.exit("id が重複")
    n_author = sum(1 for r in rules if r.get("v2") == "作者")
    d = dict(base)
    d["version"] = "0.3（v2 第 3 版＋作者の規則）"
    d["written"] = datetime.date.today().isoformat()
    d["note"] = base.get("note", "") + f" ／v3: 作者が自分の現場の判断で規則を書き足した（{n_author} 本・source は「{AUTHOR_SOURCE}」・v2 欄は「作者」）。v2 の規則の文面は変えていない。測定（docs/eval-*.md）は v2 で行った。"
    d["rules"] = rules
    s = json.dumps(d, ensure_ascii=False, indent=2)
    for bad in ("~/Claude", "gakushu/", ":\\", "Users/"):
        if bad in s:
            sys.exit(f"リポジトリ外の場所が残った: {bad}")
    deny_path = os.path.expanduser("~/.kiku-hikari-denylist.txt")
    if os.path.exists(deny_path):
        for w in open(deny_path, encoding="utf-8"):
            w = w.strip()
            if w and not w.startswith("#") and w in s:
                sys.exit("拒否語リストの語が含まれる（値は出さない）")
    print("\n".join(log))
    print(f"規則 {len(base['rules'])} → {len(rules)} 本（作者 {n_author} 本）")
    if a.dry_run:
        return
    open(a.out, "w", encoding="utf-8", newline="\n").write(s + "\n")
    print(f"書き出し: {os.path.relpath(a.out, ROOT)}")


if __name__ == "__main__":
    main()
