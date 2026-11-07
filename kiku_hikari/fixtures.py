"""灯体のチャンネル表と、意味のある値（色名・開き・明るさ）→ DMX への変換。安全弁もここ。

ADJ Stinger Spot（STI680）11ch モード。出典: ADJ Stinger Spot User Manual p.19–20（2020）
https://www.adj.com/cdn/shop/files/ADJ_Stinger_Spot_-_User_Manual.pdf
  1 PAN 8bit / 2 PAN fine / 3 TILT 8bit / 4 TILT fine / 5 COLORS / 6 GOBO / 7 SHUTTER-STROBE / 8 DIMMER / 9 MOVEMENT SPEED (fast→slow) / 10 FUNCTION / 11 DIMMER CURVE
可動範囲（製品ページ）: Pan 540°・Tilt 210°。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 色ホイール（ch5）: 各色の範囲の中央値
STINGER_COLORS = {
    "white": 3, "red": 11, "orange": 18, "yellow": 25, "green": 32, "blue": 39, "light_blue": 46, "pink": 53,
}
STINGER_GOBOS = {"open": 3, "g1": 11, "g2": 19, "g3": 27, "g4": 35, "g5": 43, "g6": 51, "g7": 59, "open_shake": 67}
SHUTTER_CLOSED = 0
SHUTTER_OPEN = 255
STROBE_MIN, STROBE_MAX = 16, 131  # strobing slow→fast


@dataclass
class Safety:
    """安全弁（数値は暫定・11/3 に実機で詰める）"""
    max_strobe_hz_equiv: float = 0.45   # ストロボの速さ 0..1 のうち使う上限（光感受性発作の目安 3 Hz 以下に寄せる。実機の Hz は未計測）
    max_dimmer: int = 255
    max_pan_step: int = 6               # 1 フレーム（25 ms）あたりの Pan 8bit の最大変化 ＝ 540°×6/255/0.025s ≈ 508°/s 上限
    max_tilt_step: int = 6


@dataclass
class StingerSpot11:
    address: int = 1                     # DMX 開始アドレス（1 始まり）
    safety: Safety = field(default_factory=Safety)
    # 現在値（スルーレート制限のため保持）
    _pan: float = 128.0
    _tilt: float = 128.0

    @property
    def footprint(self) -> int:
        return 11

    def render(self, dmx: bytearray, *, pan: float = 0.5, tilt: float = 0.5, color: str = "white", gobo: str = "open",
               dimmer: float = 1.0, shutter: str = "open", strobe: float = 0.0, speed: float = 0.0) -> dict:
        """意味のある値を DMX バッファに書く。戻り値は実際に書いた値（ログ用）。
        pan/tilt/dimmer/strobe/speed は 0..1。shutter は open / closed / strobe。"""
        s = self.safety
        tp = max(0.0, min(1.0, pan)) * 255
        tt = max(0.0, min(1.0, tilt)) * 255
        # スルーレート制限（灯体の衝撃を避ける。位相リセットはしない）
        self._pan += max(-s.max_pan_step, min(s.max_pan_step, tp - self._pan))
        self._tilt += max(-s.max_tilt_step, min(s.max_tilt_step, tt - self._tilt))
        pan16 = int(round(self._pan * 257)); tilt16 = int(round(self._tilt * 257))
        if shutter == "closed":
            sh = SHUTTER_CLOSED
        elif shutter == "strobe":
            r = max(0.0, min(s.max_strobe_hz_equiv, strobe))
            sh = int(STROBE_MIN + r * (STROBE_MAX - STROBE_MIN))
        else:
            sh = SHUTTER_OPEN
        dim = int(max(0, min(s.max_dimmer, round(dimmer * 255))))
        vals = [pan16 >> 8, pan16 & 0xFF, tilt16 >> 8, tilt16 & 0xFF,
                STINGER_COLORS.get(color, 3), STINGER_GOBOS.get(gobo, 3), sh, dim,
                int(max(0.0, min(1.0, speed)) * 255), 0, 0]
        a = self.address - 1
        dmx[a:a + 11] = bytes(vals)
        return {"pan8": vals[0], "tilt8": vals[2], "color": vals[4], "gobo": vals[5], "shutter": sh, "dimmer": dim, "speed": vals[8]}


# ADJ Dotz Par 9ch モード。出典: ADJ Dotz Par User Manual p.8（9 チャンネルモード）・p.9（カラーマクロ）
#   1 赤 / 2 緑 / 3 青 / 4 マスターディマー / 5 カラーマクロ / 6 プログラム / 7 プログラム速度・サウンド感度 / 8 ストロボ 遅→速 / 9 ディマーカーブ
#   5〜7ch は 0 固定（説明書: RGB を使う時はマクロ不可・6ch=000 で灯体側の自動演出を切る）。9ch は 0＝STANDARD に固定
# 色名→RGB（Stinger の色ホイール 8 色と同じ名前。Par は面の色として Stinger と揃える）
PAR_RGB = {
    "white": (255, 255, 255), "red": (255, 0, 0), "orange": (255, 90, 0), "yellow": (255, 200, 0), "green": (0, 255, 0),
    "blue": (0, 0, 255), "light_blue": (0, 150, 255), "pink": (255, 40, 140),
}
PAR_CURVE_STANDARD = 0


@dataclass
class DotzPar9:
    address: int = 34
    safety: Safety = field(default_factory=Safety)

    @property
    def footprint(self) -> int:
        return 9

    def render(self, dmx: bytearray, *, color: str = "white", dimmer: float = 1.0, shutter: str = "open", strobe: float = 0.0, rgb=None, **_ignored) -> dict:
        """Stinger と同じ意味の値を受け取る（pan/tilt/gobo/speed は無視）。rgb=(r,g,b) を渡すと色名より優先（グラデーション用）。
        ストロボは Stinger と同じ上限（Safety.max_strobe_hz_equiv）"""
        s = self.safety
        r, g, b = rgb if rgb is not None else PAR_RGB.get(color, PAR_RGB["white"])
        dim = 0 if shutter == "closed" else int(max(0, min(s.max_dimmer, round(dimmer * 255))))
        stb = 0
        if shutter == "strobe":
            stb = int(1 + max(0.0, min(s.max_strobe_hz_equiv, strobe)) * 254)   # 1..255 遅→速 のうち上限まで（実機の Hz は未計測）
        vals = [r, g, b, dim, 0, 0, 0, stb, PAR_CURVE_STANDARD]
        a = self.address - 1
        dmx[a:a + 9] = bytes(vals)
        return {"r": r, "g": g, "b": b, "dimmer": dim, "strobe": stb}


# Par 8 台の配置パターン（2026-11-03 本人指示）。対の色＝奇偶の 2 色目（色相の反対寄り・色ホイール 8 色の中から）
# 9 台目以降はサイドの Par（2026-11-07 本人決定「アドレス全て個別に」・配置 v2e: 袖のスタンドに T バーで 3 台ずつ・アドレス 106〜151）。
#   列の 8 台の規則（中央 2 台・中央から外へ）は最初の PAR_ROW 台にだけ掛け、サイドは claude モードではサビとキメだけ 100%・他は消灯
PAR_ROW = 8
PAR_PAIR = {"white": "blue", "red": "blue", "orange": "light_blue", "yellow": "pink", "green": "pink", "blue": "white", "light_blue": "orange", "pink": "light_blue"}


def blend(c1: str, c2: str, x: float) -> tuple:
    a, b = PAR_RGB.get(c1, PAR_RGB["white"]), PAR_RGB.get(c2, PAR_RGB["white"])
    return tuple(int(round(p + (q - p) * x)) for p, q in zip(a, b))


def par_pattern(n: int, mode: str, color: str, next_color: str = "", section: str = "", bar: int = 0, since_open: float = 9.0) -> list:
    """Par n 台（左→右）の [(rgb, 明るさの係数 0..1)]。① 全台白・② 奇偶 2 色・③ 区間で選ぶ"""
    if n <= 0:
        return []
    if mode == "beat":
        return [(PAR_RGB["white"], 1.0)] * n
    if mode != "claude":                                      # ② / direct: 表の色と対の色を奇偶に（サイドも同じ）
        pair = PAR_PAIR.get(color, "white")
        return [(PAR_RGB.get(color if i % 2 == 0 else pair, PAR_RGB["white"]), 1.0) for i in range(n)]
    nr = min(n, PAR_ROW)                                      # 列の台数。9 台目以降はサイド（下の extra）
    nxt = next_color if next_color and next_color != color else PAR_PAIR.get(color, "white")
    if section == "pre_chorus":                               # 主色→次の色のグラデーション（次の色替えの予告）
        out = [(blend(color, nxt, i / max(1, nr - 1)), 1.0) for i in range(nr)]
    elif section == "chorus":                                 # 奇偶 2 色・小節ごとに入れ替え
        out = [(PAR_RGB.get(color if (i + bar) % 2 == 0 else nxt, PAR_RGB["white"]), 1.0) for i in range(nr)]
    else:
        out = [(PAR_RGB.get(color, PAR_RGB["white"]), 1.0)] * nr
    full = True
    if since_open < 0.5:                                      # 開いた直後: 中央から外へ 0.5 秒で広げる
        c = (nr - 1) / 2; reach = since_open / 0.5 * (c + 0.5)
        out = [(rgb, 1.0 if abs(i - c) <= reach else 0.0) for i, (rgb, _) in enumerate(out)]
        full = reach >= c
    if n > nr:                                                # サイドの Par: サビは列と同じ 2 色・列が端まで広がってから 100%。サビ以外は消灯
        extra = [(PAR_RGB.get(color if (i + bar) % 2 == 0 else nxt, PAR_RGB["white"]), 1.0 if (section == "chorus" and full) else 0.0) for i in range(nr, n)]
        out = out + extra
    return out


# 汎用スポット（PrefLight の Generic/Spot・1ch ディマー）。区間ごとに点ける台数（中央から）
SPOT_COUNT = {"intro": 2, "verse": 2, "pre_chorus": 4, "chorus": 6, "bridge": 2, "interlude": 4, "break": 0, "outro": 2, "unknown": 6}


@dataclass
class Spot1:
    address: int = 501

    @property
    def footprint(self) -> int:
        return 1

    def render(self, dmx: bytearray, level: float) -> int:
        v = int(max(0, min(255, round(level * 255))))
        dmx[self.address - 1] = v
        return v


def spot_levels(n: int, mode: str, dimmer: float, level: float, section: str = "", shutter: str = "open") -> list:
    """スポット n 台（左→右）の明るさ。① 一定 50%・② 音量に追従・③ 区間で台数（中央から）×エンジンの明るさ（溜め・開き）"""
    if n <= 0:
        return []
    if mode == "beat":
        return [0.5] * n
    if mode != "claude":
        return [0.3 + 0.7 * level] * n
    if shutter == "closed":
        return [0.0] * n
    k = min(n, SPOT_COUNT.get(section, n)); lo = (n - k) // 2
    return [dimmer if lo <= i < lo + k else 0.0 for i in range(n)]
