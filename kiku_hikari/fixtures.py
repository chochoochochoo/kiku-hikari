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

    def render(self, dmx: bytearray, *, color: str = "white", dimmer: float = 1.0, shutter: str = "open", strobe: float = 0.0, **_ignored) -> dict:
        """Stinger と同じ意味の値を受け取る（pan/tilt/gobo/speed は無視）。ストロボは Stinger と同じ上限（Safety.max_strobe_hz_equiv）"""
        s = self.safety
        r, g, b = PAR_RGB.get(color, PAR_RGB["white"])
        dim = 0 if shutter == "closed" else int(max(0, min(s.max_dimmer, round(dimmer * 255))))
        stb = 0
        if shutter == "strobe":
            stb = int(1 + max(0.0, min(s.max_strobe_hz_equiv, strobe)) * 254)   # 1..255 遅→速 のうち上限まで（実機の Hz は未計測）
        vals = [r, g, b, dim, 0, 0, 0, stb, PAR_CURVE_STANDARD]
        a = self.address - 1
        dmx[a:a + 9] = bytes(vals)
        return {"r": r, "g": g, "b": b, "dimmer": dim, "strobe": stb}
