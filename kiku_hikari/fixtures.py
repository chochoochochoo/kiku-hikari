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
