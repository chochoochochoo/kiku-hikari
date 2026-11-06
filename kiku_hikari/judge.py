"""②' 候補の判定を外の「判断 API」に聞く口（2026-11-07・本人の問い「Jev は使えない？」→入口の見立て→実測）。

Jev（TypeSafe の判断 API）は文章を生成せず、質問に 0〜1 の確率（noul）だけを返す。1 回 約 0.2〜0.5 秒・約 0.002 円なので拍ごとに聞ける。
ここでは、拍ごとに Python が数えた手がかり（小さな整数と yes/no だけ・音は送らない）を渡し、「この拍はサビの 1 小節目の頭か」の確率を取る。
鍵は環境変数 TYPESAFE_API_KEY か .env の TYPESAFE_API_KEY= からだけ読む（.env は .gitignore 済み）。無ければ使わない（fail-open）。
API の失敗はすべて「答え無し」として扱い、速い輪（40 Hz）は止めない。呼び出しは別スレッド・同時 1 件。
標準ライブラリだけで書く（本イベント中に新規に書いたもの・外部ライブラリの複写ではない）。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# 手がかりの読み方（英語・Jev への指示。数字は kiku_hikari/look.py の cue の門と同じ統計）
INSTRUCTIONS = ("You judge whether the current beat is the first beat of a CHORUS (the loudest, most memorable section) in a Japanese pop/rock song, "
                "from a table of cues computed by code. Typical structure: the first chorus starts 21-47 bars from the song start (most often 28-34); "
                "a bar count under 16 is almost never a chorus. Later choruses start 24-58 bars after the previous chorus head, never under 22. "
                "Sections are mostly 8 or 16 bars, so a chorus head is usually 8 or 16 bars after the last section boundary (on the 8-bar grid). "
                "A chorus often follows a pre-chorus of 8 bars and is announced by a drum fill in the previous bar (fill ratio above 1.3) and by a step up "
                "in the high band and in level at the head; it is brighter and louder than the song so far. A quiet bar just before is a weaker sign. "
                "A step without being on the grid, or in the first 16 bars, is usually a verse or pre-chorus start, not a chorus. Answer the probability.")


def load_key() -> Optional[str]:
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8-sig"):
            line = line.strip()
            if line.startswith("TYPESAFE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def yn(x) -> str:
    return "yes" if x else "no"


def cue_state(parts: dict, bar_i: int, bars_since_boundary: Optional[int], on_grid: bool, in_claude_window: bool) -> dict:
    """tools の再生試験（11/7・jev short）と同じ 9 項目。数値は丸めた整数・判定は yes/no（Jev は数え上げと計算が苦手なので Python 側で済ませる）"""
    return {
        "bars_since_song_start": int(bar_i),
        "bars_since_last_section_boundary": "none" if bars_since_boundary is None else int(bars_since_boundary),
        "on_8_bar_grid_from_boundary": yn(on_grid),
        "on_claude_8_bar_grid": yn(in_claude_window),
        "high_band_step_db": int(round(parts["hf_step"])), "level_step_db": int(round(parts["lv_step"])),
        "quiet_bar_just_before": yn(parts["drop_prev"] <= -3.0),
        "brighter_than_song_so_far_db": int(round(parts["bright_song"])),
        "drum_fill_in_previous_bar": yn(parts["fill"] >= 1.3),
    }


def ask_sync(state: dict, key: Optional[str] = None, timeout: float = 20.0, retries: int = 3) -> Optional[float]:
    """同期版（tools/judge_replay.py 用）。失敗は None"""
    key = key or load_key()
    if not key:
        return None
    body = json.dumps({"state": state, "model": MODEL, "questions": {"chorus": {"type": "noul", "instructions": INSTRUCTIONS}}}, ensure_ascii=False).encode("utf-8")
    for _ in range(retries):
        req = urllib.request.Request(URL, data=body, method="POST", headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "kiku-hikari/1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return float(json.loads(r.read().decode("utf-8"))["answers"]["chorus"]["noul"])
        except Exception:
            time.sleep(1.0)
    return None


class Judge:
    """拍ごとの問い合わせ（同時 1 件・別スレッド）。ask(b, state) → あとで poll() が [(b, noul)] を返す。
    11/7 の再生試験では測定 5 曲で 11/27・空振り 8 だったが、閾値決めに使わなかった 4 曲で 1/12・空振り 8 と伸びず、本番（look.py）には繋いでいない（docs/eval-chorus.md）"""

    def __init__(self, log=None, timeout: float = 3.0):
        self.key = load_key()
        self.log = log; self.timeout = timeout
        self.inflight = False; self.done: list = []; self.errors = 0; self.n = 0; self.latency = []
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.key)

    def ask(self, b: float, state: dict) -> bool:
        if not self.key:
            return False
        with self._lock:
            if self.inflight:
                return False      # 前の問いが返っていなければ、この拍は聞かない
            self.inflight = True
        threading.Thread(target=self._run, args=(b, state), daemon=True).start()
        return True

    def _run(self, b: float, state: dict):
        t0 = time.perf_counter()
        body = json.dumps({"state": state, "model": MODEL, "questions": {"chorus": {"type": "noul", "instructions": INSTRUCTIONS}}}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(URL, data=body, method="POST", headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json", "User-Agent": "kiku-hikari/1"})
        v = None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                v = float(json.loads(r.read().decode("utf-8"))["answers"]["chorus"]["noul"])
        except Exception as e:   # 失敗は答え無し（fail-open）
            self.errors += 1
            if self.log: self.log.event("judge_error", error=type(e).__name__)
        dt = time.perf_counter() - t0
        with self._lock:
            self.n += 1; self.latency.append(dt)
            if v is not None:
                self.done.append((b, v, dt))
            self.inflight = False

    def poll(self) -> list:
        with self._lock:
            out = self.done; self.done = []
        return out
