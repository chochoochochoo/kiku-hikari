"""kiku-hikari v0 — 音を聴いて灯体が光る最小の通し（11/2 の到達点）。

  音声入力（25 ms）→ 特徴量（RMS・重心・低域フラックス）→ 40 Hz で DMX を作る → Art-Net → EtherMX → Stinger Spot
  すべてを 1 本の JSONL ログに時刻つきで残す。

この段階の対応づけは「音量→明るさ・明るさ(重心)→色」の直結（計画の比較 3 段のうち ①/② の土台）。拍追従と Claude は 11/3〜。
使い方:
  py -3.12 -m kiku_hikari.main --seconds 20                 # ノードを探して送る
  py -3.12 -m kiku_hikari.main --node 10.106.195.239 --universe 0 --address 1
  py -3.12 -m kiku_hikari.main --no-audio --seconds 10      # 音なし（合成信号）で結線だけ確認
"""
from __future__ import annotations

import argparse
import math
import time

from . import artnet
from .fixtures import StingerSpot11
from .runlog import RunLog

FRAME = 1 / 40.0  # 25 ms


def pick_color(centroid_hz: float) -> str:
    """スペクトル重心→色（暫定の直結表。暗い音＝赤系、明るい音＝青系）"""
    if centroid_hz < 300:
        return "red"
    if centroid_hz < 700:
        return "orange"
    if centroid_hz < 1500:
        return "yellow"
    if centroid_hz < 3000:
        return "green"
    if centroid_hz < 5000:
        return "light_blue"
    return "blue"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", help="Art-Net ノードの IP（省略時は ArtPoll で探す）")
    ap.add_argument("--universe", type=int, default=None, help="Port-Address（省略時はノードの出力ポートの値）")
    ap.add_argument("--address", type=int, default=1, help="灯体の DMX 開始アドレス")
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--no-audio", action="store_true", help="音声入力なし（合成信号）")
    ap.add_argument("--floor-db", type=float, default=-55.0, help="この音量以下は暗い")
    ap.add_argument("--ceil-db", type=float, default=-15.0, help="この音量以上で最大")
    ap.add_argument("--logdir", default="logs")
    a = ap.parse_args(argv)

    log = RunLog(a.logdir, tag="v0")
    node_ip, universe = a.node, a.universe
    if node_ip is None or universe is None:
        nodes = artnet.discover()
        log.event("artnet_discover", nodes=[{"ip": n.ip, "mac": n.mac, "outputs": n.outputs} for n in nodes])
        outs = [n for n in nodes if n.outputs]
        if not outs:
            print("Art-Net の出力ノードが見つからない（ArtPollReply なし）。--node で指定してください")
            log.close(); return 2
        node_ip = node_ip or outs[0].ip
        universe = universe if universe is not None else outs[0].outputs[0]
    print(f"送り先 {node_ip} universe {universe} address {a.address} ログ {log.path}")
    log.event("config", node=node_ip, universe=universe, address=a.address, audio=not a.no_audio)

    sender = artnet.ArtNetSender(node_ip, universe)
    fx = StingerSpot11(address=a.address)
    dmx = bytearray(512)

    audio = None
    if not a.no_audio:
        from .audio_in import AudioIn
        audio = AudioIn().start()
        log.event("audio_start", device=audio.device, fs=audio.fs, block=audio.block)

    t_start = time.perf_counter()
    next_t = t_start
    frames = 0
    feat = {"rms_db": -80.0, "centroid": 0.0, "flux_low": 0.0, "peak": 0.0}
    level = 0.0
    try:
        while time.perf_counter() - t_start < a.seconds:
            now = time.perf_counter()
            # 音声: たまったブロックを全部消費して最新の特徴量にする（遅れを溜めない）
            if audio is not None:
                n = 0
                while not audio.q.empty():
                    x = audio.q.get_nowait(); feat = audio.features(x); n += 1
                if n:
                    log.event("audio", **{k: float(v) for k, v in feat.items()}, blocks=n)
            else:
                tt = now - t_start
                feat = {"rms_db": -35 + 20 * math.sin(tt * 2 * math.pi / 4), "centroid": 400 + 2600 * (0.5 + 0.5 * math.sin(tt * 0.7)), "flux_low": 0.0, "peak": 0.0}
            # 直結の対応づけ: 音量→明るさ（立ち上がり速く・減衰ゆっくり）、重心→色、音量で Pan をゆっくり振る
            target = (feat["rms_db"] - a.floor_db) / (a.ceil_db - a.floor_db)
            target = max(0.0, min(1.0, target))
            level = max(target, level * 0.93)
            pan = 0.5 + 0.25 * math.sin((now - t_start) * 2 * math.pi / 8)
            written = fx.render(dmx, pan=pan, tilt=0.55, color=pick_color(feat["centroid"]), dimmer=level, shutter="open", speed=0.0)
            sender.send(dmx)
            frames += 1
            if frames % 8 == 0:  # 5 Hz でログ（毎フレームは多すぎる）
                log.event("dmx", frame=frames, **written, level=round(level, 3))
            next_t += FRAME
            sleep = next_t - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.perf_counter()  # 遅れたら追いつかずに刻み直す
                log.event("late", by_ms=round(-sleep * 1000, 1))
    finally:
        sender.blackout()
        log.event("blackout")
        if audio is not None:
            audio.stop(); log.event("audio_stop", dropped=audio.dropped)
        sender.close()
        log.event("summary", frames=frames, seconds=round(time.perf_counter() - t_start, 2), fps=round(frames / max(1e-6, time.perf_counter() - t_start), 1))
        log.close()
    print(f"frames {frames} / {a.seconds}s  log {log.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
