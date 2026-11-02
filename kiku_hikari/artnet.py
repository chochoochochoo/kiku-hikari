"""Art-Net 4 の最小実装（送信と探索だけ）。外部ライブラリなし。

- ArtPoll をブロードキャストしてノード（EtherMX 等）を見つける
- ArtDmx を 1 ユニバース分（512 ch）ユニキャストで送る
仕様の根拠: Art-Net 4 Protocol Release（ArtPoll OpCode 0x2000・ArtPollReply 0x2100・ArtDmx 0x5000・UDP 6454）
"""
from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass, field

PORT = 6454
HEADER = b"Art-Net\x00"
OP_POLL = 0x2000
OP_POLL_REPLY = 0x2100
OP_DMX = 0x5000
PROTOCOL_VERSION = 14


@dataclass
class Node:
    ip: str
    port_types: list[int]
    good_output: list[int]
    sw_out: list[int]
    net: int
    sub: int
    mac: str
    short_name: str = ""
    long_name: str = ""

    @property
    def outputs(self) -> list[int]:
        """Art-Net→DMX 出力として設定されているポートの Port-Address（15bit）一覧"""
        res = []
        for i, t in enumerate(self.port_types):
            if t & 0x80:  # bit7 = このポートは DMX 出力
                res.append((self.net << 8) | (self.sub << 4) | (self.sw_out[i] & 0x0F))
        return res


def discover(timeout: float = 2.5, broadcasts: tuple[str, ...] = ("2.255.255.255", "10.255.255.255", "255.255.255.255")) -> list[Node]:
    """ArtPoll を投げて ArtPollReply を集める。見つからなければ空リスト。"""
    pkt = HEADER + struct.pack("<H", OP_POLL) + struct.pack(">H", PROTOCOL_VERSION) + bytes([0x06, 0x00])
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", PORT))
    except OSError:
        pass  # 他のソフトが 6454 を掴んでいても送信はできる（返事は取れない）
    s.settimeout(timeout)
    for dst in broadcasts:
        try:
            s.sendto(pkt, (dst, PORT))
        except OSError:
            pass
    nodes: dict[str, Node] = {}
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            d, addr = s.recvfrom(1024)
        except socket.timeout:
            break
        if len(d) < 207 or d[:8] != HEADER or struct.unpack("<H", d[8:10])[0] != OP_POLL_REPLY:
            continue
        if addr[0] in nodes:
            continue
        nodes[addr[0]] = Node(
            ip=addr[0],
            port_types=list(d[174:178]),
            good_output=list(d[182:186]),
            sw_out=list(d[190:194]),
            net=d[18],
            sub=d[19],
            mac=":".join(f"{b:02x}" for b in d[201:207]),
            short_name=d[26:44].split(b"\0")[0].decode(errors="replace"),
            long_name=d[44:108].split(b"\0")[0].decode(errors="replace"),
        )
    s.close()
    return list(nodes.values())


class ArtNetSender:
    """1 ユニバース分の DMX をユニキャストで送る。send() は毎フレーム呼ぶ（40 Hz 想定）。"""

    def __init__(self, ip: str, universe: int = 0):
        self.ip = ip
        self.universe = universe  # Port-Address（15bit）
        self._seq = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.frames_sent = 0

    def send(self, dmx: bytes | bytearray) -> None:
        data = bytes(dmx[:512]).ljust(2, b"\0")
        if len(data) % 2:
            data += b"\0"
        self._seq = self._seq % 255 + 1  # 1..255（0 は「順序を見ない」の意味なので避ける）
        pkt = (HEADER + struct.pack("<H", OP_DMX) + struct.pack(">H", PROTOCOL_VERSION)
               + bytes([self._seq, 0]) + struct.pack("<H", self.universe & 0x7FFF)
               + struct.pack(">H", len(data)) + data)
        self._sock.sendto(pkt, (self.ip, PORT))
        self.frames_sent += 1

    def blackout(self) -> None:
        self.send(bytes(512))

    def close(self) -> None:
        self._sock.close()


if __name__ == "__main__":
    for n in discover():
        print(n.ip, "mac", n.mac, "out port-addresses", n.outputs, "名前", n.short_name or "(無し)")
