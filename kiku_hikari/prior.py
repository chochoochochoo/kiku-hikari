"""曲構成の型（事前分布）。--structure-prior <json> で渡す。未指定なら何もしない（既定の動作は不変）。

学習が公式ライブ映像の統計から出す数字だけの JSON（曲名・アーティスト名は入れない）。形:
  {"first_chorus_bars": [24, 40],      # 最初のサビの頭は曲頭から何小節目か（範囲）
   "chorus_spacing_bars": [32, 40],    # サビの頭からサビの頭までの小節数（範囲）
   "section_bars": [8, 16],            # 区間の単位
   "pre_chorus_bars": 8,               # 任意
   "note": "出典の説明（1 行）"}      # 任意
使い所は 2 つ（同じファイルから読む）:
  (a) 案 C の点数の閾値（kiku_hikari/look.py の rule=cue・tools/chorus_replay.py の det_hybrid）: 型に合う小節頭は閾値 −w、外れは離れた分だけ +（最大 +w）
  (b) Claude の要約の構成規則（kiku_hikari/claude_worker.py の system の固定部）に 1 行足す
"""
from __future__ import annotations

import json
from typing import Optional


def load_prior(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    for k in ("first_chorus_bars", "chorus_spacing_bars"):
        if k in d and not (isinstance(d[k], list) and len(d[k]) == 2 and d[k][0] <= d[k][1]):
            raise ValueError(f"{path}: {k} は [min, max]")
    return d


def prior_adjust(prior: Optional[dict], bar: int, last_chorus_bar: Optional[int], n_chorus: int, w: float = 1.0) -> float:
    """閾値に足す量（負なら入りやすく・正なら入りにくく）。bar は曲頭からの小節番号（0 起点）"""
    if not prior:
        return 0.0
    if n_chorus == 0 or last_chorus_bar is None:
        rng = prior.get("first_chorus_bars"); x = bar
    else:
        rng = prior.get("chorus_spacing_bars"); x = bar - last_chorus_bar
    if not rng:
        return 0.0
    lo, hi = rng
    if lo <= x <= hi:
        return -w
    d = min((lo - x) if x < lo else (x - hi), 8)
    return w * d / 8.0


def prior_text(prior: Optional[dict]) -> str:
    if not prior:
        return ""
    parts = []
    if prior.get("first_chorus_bars"):
        parts.append(f"最初のサビの頭は曲頭から {prior['first_chorus_bars'][0]}〜{prior['first_chorus_bars'][1]} 小節目に来ることが多い")
    if prior.get("chorus_spacing_bars"):
        parts.append(f"サビの頭からサビの頭までは {prior['chorus_spacing_bars'][0]}〜{prior['chorus_spacing_bars'][1]} 小節")
    if prior.get("section_bars"):
        parts.append("区間は " + "／".join(str(b) for b in prior["section_bars"]) + " 小節単位")
    if prior.get("pre_chorus_bars"):
        parts.append(f"サビの手前に {prior['pre_chorus_bars']} 小節の溜め（B メロ）が入ることが多い")
    if not parts:
        return ""
    return "\n一般的な曲構成の型（ライブ映像の統計）: " + "。".join(parts) + "。これは目安で、音の特徴量が明らかに違えば音を優先する。"
