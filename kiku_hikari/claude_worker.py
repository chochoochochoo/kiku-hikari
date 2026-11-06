"""遅い輪: Claude API に「構造の先読み」を頼む（別スレッド・同時 1 件・世代番号で古い返答を捨てる）。

入力: 直近 30 秒の特徴量の要約（1 秒ごとの音量・明るさ・オンセット密度・テンポ・これまでの区間の履歴）
出力: Enum 固定の JSON（次の境界まで何秒・次の区間・開き方・色・語彙・溜め・感情 2 軸・情景一語・確信度・理由）
知識ファイル knowledge/lighting_knowledge_v2.json（既定・v1 は lighting_knowledge.json） を system の固定部に置き、プロンプトキャッシュで毎回の入力を小さくする。
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
ONSET_FIXED_SCALE = 200.0   # 要約 c の固定尺度（実測: 試験曲 3 本の 1 秒平均が 108〜183）
KNOWLEDGE_V1 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "lighting_knowledge.json")
# 製品の既定は v2（実演映像 87 本で規則を差し替えた版・2026-11-03 本人決定）。差し替えは tools/import_knowledge.py で上書きするだけ
KNOWLEDGE_PATH = os.path.join(os.path.dirname(KNOWLEDGE_V1), "lighting_knowledge_v2.json")


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


class ForesightE(Foresight):
    """要約 e/f 用（仮説 2: 秒でなく小節数で先を答えさせる＝往復の遅延に左右されない）"""
    bars_to_boundary: int = Field(ge=1, le=16, description="次の境界は、いまの小節（bar_now）から何小節先の小節頭か（1〜16）")


class ForesightC(ForesightE):
    """--chorus-hints 用（11/6・サビ判定の精度向上）: 境界とは別に「次のサビの頭」を小節数で直接答えさせる（手がかりは system に貼る文・リポジトリには入れない）"""
    bars_to_chorus: int = Field(ge=0, le=64, description="次のサビの頭は、いまの小節（bar_now）から何小節先の小節頭か（1〜64）。分からない・いまサビの中なら 0")


CHORUS_RULE_C = """

サビの頭（bars_to_chorus）: 境界とは別に、次のサビの頭が bar_now から何小節先の小節頭かを bars_to_chorus に答える（分からない・いまサビの中なら 0）。次の手がかりに従う。確信が低くても、範囲に入る値を答えてよい（reason に「仮」と書く）。
"""

# ② 候補選択式（11/7・--candidates）: 直答（CHORUS_RULE_C）ではなく、Python が数えた構造の手がかりの表から候補を選ばせる
CAND_RULE = """

サビの頭の候補（candidates）: 要約の candidates は、これから来る小節頭 8 つ（k=1〜8 小節先）について Python が数えた構造の手がかり
（bar=曲頭からの小節番号・from_boundary=直前の区間の境目（音量と高域が同時に上がった小節頭）からの小節数・on_grid=その境目から 8 小節の格子に乗るか・from_last_chorus=前のサビの頭からの小節数・level_trend=直近 2 小節の音量の向き）。
この表から「次のサビの 1 小節目」になる小節頭を 1 つ選び、その k を bars_to_chorus に答える。8 小節以内にサビの頭が来そうでなければ 0。
選び方: 境目から 8 か 16 小節目（on_grid=true）の小節頭を優先する。bar が 20 より前の小節頭と、from_last_chorus が 22 未満の小節頭は選ばない。level_trend が rising（B メロの終わり）なら、その流れの先にある格子の小節頭を選ぶ。
"""


SYSTEM_FIXED = """あなたはライブの照明オペレーターの判断を肩代わりする。入力は直近 30 秒の音の特徴量の要約（1 秒ごと）と、これまでの区間の履歴。
仕事は「構造の先読み」: 次の境界（サビ頭・ブレイク・間奏など）が何秒後に来るか、どんな区間か、どう開くかを予測し、いまの色・動き・溜め・感情を決める。
原則: 位相や拍は Python が担当する。あなたは秒単位の判断だけをする。確信が無いときは confidence を low にし、seconds_to_boundary は大きめにする（早すぎる開きより遅い開きのほうが安全）。
色は灯体の色ホイールにある 8 色から選ぶ。点滅は使わない（安全は Python が担う）。
以下は照明家の知識ファイル（JSON）。規則に根拠がある場合はそれに従う。"""

# 要約 d 用の確信度の基準（A/B 比較で、a〜c は 219 応答中 218 が confidence=low＝予測が一度も採られなかったため）
CONFIDENCE_RULE_D = """
確信度の基準: 曲頭からの小節番号が 8 の倍数に近づき、かつ直近 8 小節の level か onset が上がり続けている（または急に下がった）なら、次の境界の予測は confidence=mid 以上・open_style は none 以外にする。どちらか一方だけなら mid、どちらも無ければ low。区間名が分からなくても、境界の時刻の確信で決めてよい。"""


def load_knowledge(path: Optional[str] = None) -> str:
    """path=知識ファイル（JSON でも Markdown でもそのまま渡す）。既定は knowledge/lighting_knowledge_v2.json（v2）"""
    path = path or KNOWLEDGE_PATH
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
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

# 要約 e/f 用（仮説 2）: 境界を小節数で答えさせる。いま起きている変化は「過ぎた境界」なので、その次を答えさせる
BAR_RULE_E = """
境界の小節: bars_to_boundary に「次の境界が bar_now から何小節先の小節頭か」を答える（返答が届くまで 1 小節ほどかかるので 2 以上が望ましい）。ポップスの区間は多くが 8 小節（ときに 4 小節）単位で、曲頭からの小節番号が 8 の倍数＋1 になる小節頭が境界の候補。いま level や onset が急に変わっているなら、それは既に過ぎた境界なので、その次の境界を答える。seconds_to_boundary も同じ境界を秒で答える。"""

# 「青一定」の直し方（A/B の変種・既定は v1＝知識ファイルどおり。docs/eval-beat.md）
COLOR_RULES = {
    "v1": "",
    # p1 区間の配色: intro/verse の配色（blue 系）に縛らず、曲の感情から基調色を選ぶ
    "p1": """
色の決め方（優先）: 曲の基調色は区間名の配色（intro/verse の blue 系）ではなく、valence と arousal から決める（R11〜R14: 明るく速い曲は yellow/orange/white、暗く遅い曲は blue）。blue は暗く遅い曲だけに使う。""",
    # p2 R20 の緩和: 1 曲 2〜3 色の範囲で、区間が変わるたびに色を変えてよい
    "p2": """
色の変え方（優先）: R20「1 曲 1 色」より R01「1 曲 1〜3 色」を優先する。区間（section_now）が変わったら、曲の 2〜3 色のうち別の色に移ってよい。同じ区間が繰り返されたら同じ色に戻す（R02）。""",
    # p3 e の開き: 開くたびに色が変わるようにする（next_color は color と違う色）
    "p3": """
開きの色（優先）: open_style が none 以外のとき、next_color は必ず color と違う色にする（境界で開いた瞬間に色が変わるのが見えるように）。""",
}


class ClaudeWorker:
    def __init__(self, model: str = MODEL_DEFAULT, effort: str = "low", log=None, variant: str = "a", knowledge: Optional[str] = None, color: str = "v1", extra_rules: str = "", chorus_hints: str = "", candidates: bool = False):
        import anthropic
        key = load_env_key()
        # timeout と再試行: 既定（600 秒×2 回）だと回線が詰まった時に最長 30 分 inflight のまま新しい予測が止まる。実測の遅延は中央値 2.5 秒・最大 6.4 秒（189 回）なので 10 秒で切り、再試行はしない（次の依頼は --every 秒後に出る）
        self.client = anthropic.Anthropic(api_key=key, timeout=10.0, max_retries=0) if key else anthropic.Anthropic(timeout=10.0, max_retries=0)
        self.model, self.effort, self.log = model, effort, log
        self.system = [
            {"type": "text", "text": SYSTEM_FIXED + (CONFIDENCE_RULE_D if variant in ("d", "e", "f") else "") + (BAR_RULE_E if variant in ("e", "f") else "") + COLOR_RULES[color] + (extra_rules or "")
             + ((CHORUS_RULE_C + chorus_hints) if chorus_hints else "") + (CAND_RULE if candidates else "")},   # extra_rules: 曲構成の型の 1 行（--structure-prior・既定は空）。chorus_hints: サビの頭の手がかりの文（--chorus-hints・既定は空）。candidates: ② 候補選択式（--candidates・既定は無し）
            {"type": "text", "text": load_knowledge(knowledge), "cache_control": {"type": "ephemeral"}},
        ]
        self.out_model = (ForesightC if (chorus_hints or candidates) else ForesightE) if variant in ("e", "f") else Foresight
        self.generation = 0
        self.latest_asked = None       # 最新の返答の元になった依頼を出した時刻（perf_counter）＝ seconds_to_boundary の基準
        self.latest_bar = None         # その依頼時点の bar_now（e/f）
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
        threading.Thread(target=self._run, args=(gen, summary, time.perf_counter()), daemon=True).start()
        return True

    def _run(self, gen: int, summary: dict, asked_at: float = 0.0):
        t0 = time.perf_counter()
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=1024,
                system=self.system,
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": json.dumps(summary, ensure_ascii=False)}],
                output_format=self.out_model,
            )
            dt = time.perf_counter() - t0
            if resp.stop_reason == "refusal":
                self.errors += 1
                if self.log: self.log.event("claude_refusal", gen=gen, latency=round(dt, 3))
                return
            fs: Foresight = resp.parsed_output
            if fs is None:                     # 構造化出力が取れなかった返答（max_tokens 到達など）は「返答なし」。latest に入れると速い輪で属性参照に失敗して止まる
                self.errors += 1
                if self.log: self.log.event("claude_error", gen=gen, error="parsed_output is None (stop_reason=%s)" % resp.stop_reason, latency=round(dt, 3))
                return
            u = resp.usage
            with self._lock:
                if gen > self.latest_gen:          # 古い世代の返答は捨てる
                    self.latest, self.latest_gen, self.latest_at = fs, gen, time.perf_counter()
                    self.latest_asked, self.latest_bar = asked_at, summary.get("bar_now")
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
    """40 Hz の特徴量を 1 秒ごとに丸め、直近 30 秒分と区間履歴を Claude 向けの要約にする

    variant（A/B 比較・docs/eval-beat.md「先読みの要約 A/B」）:
      a … 従来（相対レベル＝曲中の最大を 1）
      b … a ＋ 各行に拍番号・小節番号、直近 8 小節の小節ごとの level 平均
      d … b と同じ要約＋ system に確信度の基準（CONFIDENCE_RULE_D）
      e … d ＋ 境界を小節数（bars_to_boundary）でも答えさせる（仮説 2）
      f … e ＋ 依頼を句の 2・6 小節目の頭に出す（境界の候補の 3 小節前・仮説 3。main.py）
      c … b の level/onset を固定尺度にする（-60〜0 dBFS を 0〜1・オンセットは生値 / ONSET_FIXED_SCALE）＝曲中最大での正規化をやめる
    """

    def __init__(self, window_s: int = 30, variant: str = "a"):
        self.window_s = window_s
        self.variant = variant
        self.beats = 0
        self.rows: list[dict] = []     # 1 秒ごと
        self._acc: list[dict] = []
        self._sec = -1
        self.history: list[dict] = []  # Claude が宣言した区間の履歴 [{"t":秒,"section":...}]
        self.max_db = -80.0            # これまでの最大音量（相対レベルの基準）
        self.max_onset = 1e-6
        self.cand = None               # ② 候補選択式（--candidates）: main.py が毎フレーム入れる {"anchor_bars": 境目から今までの小節数 or None, "chorus_bars": 前のサビの頭から or None}

    def push(self, t: float, feat: dict, onset: float):
        sec = int(t)
        if sec != self._sec and self._acc:
            n = len(self._acc)
            rms = sum(a["rms_db"] for a in self._acc) / n
            onset = sum(a["onset"] for a in self._acc) / n
            self.max_db = max(self.max_db, rms); self.max_onset = max(self.max_onset, onset)
            if self.variant == "c":
                lv = max(0.0, min(1.0, (rms + 60.0) / 60.0))                               # -60 dBFS を 0、0 dBFS を 1（固定）
                on = min(1.0, onset / ONSET_FIXED_SCALE)
            else:
                lv = max(0.0, min(1.0, 1 + (rms - self.max_db) / 30.0))                    # 最大音量を 1、30 dB 下を 0
                on = onset / self.max_onset                                                # 最大オンセット密度を 1
            row = {"t": self._sec, "level": round(lv, 2), "bright": int(sum(a["centroid"] for a in self._acc) / n), "onset": round(on, 2)}
            if self.variant in ("b", "c", "d", "e", "f"):
                row["beat"] = self.beats; row["bar"] = self.beats // 4 + 1
            self.rows.append(row)
            self.rows = self.rows[-self.window_s:]
            self._acc = []
        self._sec = sec
        self._acc.append({"rms_db": feat["rms_db"], "centroid": feat["centroid"], "onset": onset})

    def on_beat(self):
        self.beats += 1

    def summary(self, t: float, tempo_bpm: float, last: Optional[Foresight]) -> dict:
        if self.variant == "a":
            return {
                "now_s": round(t, 1),
                "tempo_bpm": round(tempo_bpm, 1),
                "legend": "level=音量（曲中の最大を1・30dB下を0）, bright=スペクトル重心Hz, onset=オンセット密度（最大を1）。1秒ごと・古い→新しい",
                "last_30s": self.rows,
                "sections_so_far": self.history[-12:],
                "previous_answer": json.loads(last.model_dump_json()) if last else None,
            }
        lv = ("level=音量（-60dBFSを0・0dBFSを1の固定尺度）, onset=オンセット密度（固定尺度）" if self.variant == "c"
              else "level=音量（曲中の最大を1・30dB下を0）, onset=オンセット密度（最大を1）")
        bars: dict[int, list[float]] = {}
        for r in self.rows:
            bars.setdefault(r["bar"], []).append(r["level"])
        last8 = [{"bar": b, "level": round(sum(v) / len(v), 2)} for b, v in sorted(bars.items())][-8:]
        extra = {}
        if self.cand is not None:      # ② 候補選択式: これから来る小節頭 8 つの構造の手がかり（Python が数える・CAND_RULE）
            bar_now = self.beats // 4 + 1
            lvs = [r["level"] for r in last8]
            trend = "flat"
            if len(lvs) >= 4:
                d = sum(lvs[-2:]) / 2 - sum(lvs[-4:-2]) / 2
                trend = "rising" if d >= 0.04 else ("falling" if d <= -0.04 else "flat")
            ab, cb = self.cand.get("anchor_bars"), self.cand.get("chorus_bars")
            extra["candidates"] = [{"k": k, "bar": bar_now + k,
                                    "from_boundary": (None if ab is None else int(round(ab + k))),
                                    "on_grid": (ab is not None and int(round(ab + k)) % 8 == 0),
                                    "from_last_chorus": (None if cb is None else int(round(cb + k))),
                                    "level_trend": trend} for k in range(1, 9)]
        return {
            **extra,
            "now_s": round(t, 1),
            "tempo_bpm": round(tempo_bpm, 1),
            "beat_now": self.beats, "bar_now": self.beats // 4 + 1,
            "legend": lv + ", bright=スペクトル重心Hz, beat/bar=曲頭からの拍番号・小節番号（4拍=1小節・ポップスの区間は多くが4か8小節単位）。1秒ごと・古い→新しい",
            "last_30s": self.rows,
            "last_8_bars_level": last8,
            "sections_so_far": self.history[-12:],
            "previous_answer": json.loads(last.model_dump_json()) if last else None,
        }
