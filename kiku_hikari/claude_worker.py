"""遅い輪: Claude API に「構造の先読み」を頼む（別スレッド・同時 1 件・世代番号で古い返答を捨てる）。

入力: 直近 30 秒の特徴量の要約（1 秒ごとの音量・明るさ・オンセット密度・テンポ・これまでの区間の履歴）
出力: Enum 固定の JSON（次の境界まで何秒・次の区間・開き方・色・語彙・溜め・感情 2 軸・情景一語・確信度・理由）
知識ファイル knowledge/lighting_knowledge.json を system の固定部に置き、プロンプトキャッシュで毎回の入力を小さくする。
鍵は .env か環境変数 ANTHROPIC_API_KEY からだけ読む。ログには応答の本文と遅延を残し、ヘッダは残さない。
"""
from __future__ import annotations

import json
import os
import threading
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

MODEL_DEFAULT = "claude-opus-5-5"
KNOWLEDGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "lighting_knowledge.json")


class Section(str, Enum):
    intro = "intro"; verse = "verse"; pre_chorus = "pre_chorus"; chorus = "chorus"; bridge = "bridge"
    break_ = "break"; interlude = "interlude"; outro = "outro"; unknown = "unknown"


class OpenStyle(str, Enum):
    hard_cut = "hard_cut"; ramp = "ramp"; bloom = "bloom"; blackout_then_burst = "blackout_then_burst"; none = "none"


class Color(str, Enum):
    white = "white"; red = "red"; orange = "orange"; yellow = "yellow"; green = "green"; blue = "blue"; light_blue = "light_blue"; pink = "pink"


class Movement(str, Enum):
    hold = "hold"; sweep = "sweep"; chase = "chase"; bounce = "bounce"


class Tame(str, Enum):
    none = "none"; dim_hold = "dim_hold"; slow_close = "slow_close"; freeze = "freeze"


class Valence(str, Enum):
    positive = "positive"; neutral = "neutral"; negative = "negative"


class Arousal(str, Enum):
    low = "low"; mid = "mid"; high = "high"


class Confidence(str, Enum):
    low = "low"; mid = "mid"; high = "high"


class Foresight(BaseModel):
    """Claude の 1 回の返答（すべて列挙か短い文字列。Python 側はこれ以外を受け付けない）"""
    section_now: Section = Field(description="いま鳴っている区間")
    section_next: Section = Field(description="次に来る区間")
    seconds_to_boundary: int = Field(ge=0, le=60, description="次の境界までの秒数の予測（0〜60）")
    open_style: OpenStyle = Field(description="境界での開き方")
    color: Color = Field(description="いまの区間の主色")
    next_color: Color = Field(description="次の区間の主色")
    movement: Movement = Field(description="いまの動きの語彙")
    tame: Tame = Field(description="境界前の溜め")
    valence: Valence = Field(description="感情の快・不快")
    arousal: Arousal = Field(description="感情の覚醒度")
    scene_word: str = Field(max_length=12, description="浮かぶ情景を一語（日本語）")
    confidence: Confidence
    reason: str = Field(max_length=80, description="判断の根拠を一文（日本語）")


SYSTEM_FIXED = """あなたはライブの照明オペレーターの判断を肩代わりする。入力は直近 30 秒の音の特徴量の要約（1 秒ごと）と、これまでの区間の履歴。
仕事は「構造の先読み」: 次の境界（サビ頭・ブレイク・間奏など）が何秒後に来るか、どんな区間か、どう開くかを予測し、いまの色・動き・溜め・感情を決める。
原則: 位相や拍は Python が担当する。あなたは秒単位の判断だけをする。確信が無いときは confidence を low にし、seconds_to_boundary は大きめにする（早すぎる開きより遅い開きのほうが安全）。
色は灯体の色ホイールにある 8 色から選ぶ。点滅は使わない（安全は Python が担う）。
以下は照明家の知識ファイル（JSON）。規則に根拠がある場合はそれに従う。"""


def load_knowledge() -> str:
    if os.path.isfile(KNOWLEDGE_PATH):
        with open(KNOWLEDGE_PATH, encoding="utf-8") as f:
            return f.read()
    return json.dumps({"note": "知識ファイル未作成。一般的な判断で答える"}, ensure_ascii=False)


def load_env_key() -> Optional[str]:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    p = os.path.join(os.path.dirname(KNOWLEDGE_PATH), "..", ".env")
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8-sig"):
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


class ClaudeWorker:
    def __init__(self, model: str = MODEL_DEFAULT, effort: str = "low", log=None):
        import anthropic
        key = load_env_key()
        self.client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        self.model, self.effort, self.log = model, effort, log
        self.system = [
            {"type": "text", "text": SYSTEM_FIXED},
            {"type": "text", "text": load_knowledge(), "cache_control": {"type": "ephemeral"}},
        ]
        self.generation = 0
        self.inflight = False
        self.latest: Optional[Foresight] = None
        self.latest_gen = -1
        self.latest_at = 0.0
        self.last_latency = 0.0
        self.errors = 0
        self._lock = threading.Lock()

    def request(self, summary: dict) -> bool:
        """同時 1 件。送れたら True。"""
        with self._lock:
            if self.inflight:
                return False
            self.inflight = True
            self.generation += 1
            gen = self.generation
        threading.Thread(target=self._run, args=(gen, summary), daemon=True).start()
        return True

    def _run(self, gen: int, summary: dict):
        t0 = time.perf_counter()
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=1024,
                system=self.system,
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": json.dumps(summary, ensure_ascii=False)}],
                output_format=Foresight,
            )
            dt = time.perf_counter() - t0
            if resp.stop_reason == "refusal":
                self.errors += 1
                if self.log: self.log.event("claude_refusal", gen=gen, latency=round(dt, 3))
                return
            fs: Foresight = resp.parsed_output
            u = resp.usage
            with self._lock:
                if gen > self.latest_gen:          # 古い世代の返答は捨てる
                    self.latest, self.latest_gen, self.latest_at = fs, gen, time.perf_counter()
                self.last_latency = dt
            if self.log:
                self.log.event("claude_resp", gen=gen, latency=round(dt, 3), model=self.model,
                               in_tokens=u.input_tokens, out_tokens=u.output_tokens,
                               cache_read=getattr(u, "cache_read_input_tokens", 0), cache_write=getattr(u, "cache_creation_input_tokens", 0),
                               **json.loads(fs.model_dump_json()))
        except Exception as e:  # ネットワーク・レート制限・検証失敗はすべて「返答なし」として扱い、速い輪は止めない
            self.errors += 1
            if self.log: self.log.event("claude_error", gen=gen, error=repr(e)[:200], latency=round(time.perf_counter() - t0, 3))
        finally:
            with self._lock:
                self.inflight = False


class FeatureSummarizer:
    """40 Hz の特徴量を 1 秒ごとに丸め、直近 30 秒分と区間履歴を Claude 向けの要約にする"""

    def __init__(self, window_s: int = 30):
        self.window_s = window_s
        self.rows: list[dict] = []     # 1 秒ごと
        self._acc: list[dict] = []
        self._sec = -1
        self.history: list[dict] = []  # Claude が宣言した区間の履歴 [{"t":秒,"section":...}]

    def push(self, t: float, feat: dict, onset: float):
        sec = int(t)
        if sec != self._sec and self._acc:
            n = len(self._acc)
            self.rows.append({
                "t": self._sec,
                "rms_db": round(sum(a["rms_db"] for a in self._acc) / n, 1),
                "centroid": int(sum(a["centroid"] for a in self._acc) / n),
                "onset": round(sum(a["onset"] for a in self._acc) / n, 2),
            })
            self.rows = self.rows[-self.window_s:]
            self._acc = []
        self._sec = sec
        self._acc.append({"rms_db": feat["rms_db"], "centroid": feat["centroid"], "onset": onset})

    def summary(self, t: float, tempo_bpm: float, last: Optional[Foresight]) -> dict:
        return {
            "now_s": round(t, 1),
            "tempo_bpm": round(tempo_bpm, 1),
            "last_30s": self.rows,
            "sections_so_far": self.history[-12:],
            "previous_answer": json.loads(last.model_dump_json()) if last else None,
        }
