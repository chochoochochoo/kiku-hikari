"""時刻つきの実行ログ（1 回の実行＝1 ファイル・JSON Lines）。

拍位相・境界・Claude の要求/応答・DMX 出力を同じ時計（time.perf_counter 起点＋壁時計）で 1 本に残す。
動画の字幕やブラインド判定の照合はこのファイルから作る。鍵・個人情報は書かない（API 応答の本文は書くがヘッダは書かない）。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time


class RunLog:
    def __init__(self, logdir: str = "logs", tag: str = "run"):
        os.makedirs(logdir, exist_ok=True)
        self.t0_perf = time.perf_counter()
        self.t0_wall = time.time()
        stamp = _dt.datetime.fromtimestamp(self.t0_wall).strftime("%Y%m%d-%H%M%S")
        self.path = os.path.join(logdir, f"{stamp}-{tag}.jsonl")
        self._f = open(self.path, "a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()
        self.event("run_start", wall=_dt.datetime.fromtimestamp(self.t0_wall).isoformat(timespec="milliseconds"))

    def now(self) -> float:
        """実行開始からの秒（単調時計）"""
        return time.perf_counter() - self.t0_perf

    def event(self, kind: str, **fields) -> None:
        rec = {"t": round(self.now(), 4), "kind": kind}
        rec.update(fields)
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._f.write(line + "\n")

    def close(self) -> None:
        self.event("run_end")
        self._f.close()


def read(path: str):
    """ログを読む（解析用）"""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
