"""kiku-hikari — 音を聴いてムービングライトが光る（40 Hz の速い輪）。

  音声入力（25 ms）→ 特徴量 ＋ 自前の拍追従 → モーションエンジン → Stinger Spot の DMX → Art-Net → EtherMX
  すべてを 1 本の JSONL ログに時刻つきで残す（拍・テンポ・位相・DMX・遅れ）。

モード:
  direct … 音量→明るさ・重心→色の直結（v0・11/2）
  beat   … 拍連動（計画の比較 3 段の ①）。--bpm N で固定テンポ（拍追従の退避策）。拍頭は Space キーで合わせ直せる（Windows）
  rules  … ② ルール表: 拍連動の上に「特徴量→色・明るさの床」の直結表を載せる（Claude なし・先読みなし）
  claude … ① の上に Claude の先読み（色・語彙・溜め・境界で開く）を載せる（③）。--every 秒ごとに要約を送る
使い方:
  py -3.12 -m kiku_hikari.main --mode beat --seconds 60
  py -3.12 -m kiku_hikari.main --mode beat --bpm 120 --seconds 60      # 固定テンポ
  py -3.12 -m kiku_hikari.main --mode direct --no-audio --seconds 10   # 音なしで結線だけ
  py -3.12 -m kiku_hikari.main --mode beat --play path.wav             # 手元の WAV をヘッドホンから鳴らしてマイクで聴く（自己試験）
"""
from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np

from . import artnet
from .change import ChangeDetector
from .engine import BeatEngine, ForesightEngine
from .fixtures import StingerSpot11
from .runlog import RunLog

FRAME = 1 / 40.0


def pick_color(centroid_hz: float) -> str:
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


class FixedTempo:
    """退避策: 固定 BPM。Space で拍頭を合わせ直す（位相だけ・周期は固定）"""

    def __init__(self, bpm: float):
        self.period_s = 60.0 / bpm
        self.tempo_bpm = bpm
        self.t_last = time.perf_counter()
        self.phase = 0.0
        self.confidence = 1.0

    def tap(self, t: float):
        self.t_last = t

    def tick(self, t: float) -> bool:
        beat = False
        while t - self.t_last >= self.period_s:
            self.t_last += self.period_s
            beat = True
        self.phase = (t - self.t_last) / self.period_s
        return beat


def space_pressed() -> bool:
    if sys.platform != "win32":
        return False
    import msvcrt
    hit = False
    while msvcrt.kbhit():
        if msvcrt.getwch() == " ":
            hit = True
    return hit


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["direct", "beat", "rules", "claude"], default="beat")
    ap.add_argument("--every", type=float, default=4.0, help="claude モード: 要約を送る間隔（秒）")
    ap.add_argument("--model", default=None, help="claude モード: モデル ID（既定 claude-opus-5-5）")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--summary", choices=["a", "b", "c", "d", "e", "f"], default="a", help="claude モード: 要約の形（A/B 比較用・claude_worker.FeatureSummarizer）")
    ap.add_argument("--adopt", choices=["strict", "lowok"], default="strict", help="claude モード: 確信度 low の予測を採るか（A/B 比較用）")
    ap.add_argument("--bpm", type=float, default=None, help="固定テンポ（拍追従を使わない退避策）")
    ap.add_argument("--node"); ap.add_argument("--universe", type=int, default=None); ap.add_argument("--address", type=int, default=1)
    ap.add_argument("--fixtures", type=int, default=1, help="灯体の台数（アドレスは --address から 11ch ずつ。左右は Pan を対称に）")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--play", help="自己試験: この WAV を出力デバイスから鳴らす（マイクで聴く）")
    ap.add_argument("--file", help="疑似モード: マイクの代わりにこの WAV を直接入力にする（48 kHz）")
    ap.add_argument("--viz", action="store_true", help="画面に仮想灯体を出す（灯体が無くても見える）")
    ap.add_argument("--out-device", default="Realtek", help="--play の出力デバイス名の一部（WASAPI）")
    ap.add_argument("--floor-db", type=float, default=-55.0); ap.add_argument("--ceil-db", type=float, default=-15.0)
    ap.add_argument("--logdir", default="logs"); ap.add_argument("--no-artnet", action="store_true", help="DMX を送らない（解析だけ）")
    a = ap.parse_args(argv)

    log = RunLog(a.logdir, tag=a.mode)
    sender = None
    if not a.no_artnet:
        node_ip, universe = a.node, a.universe
        if node_ip is not None and universe is None:
            universe = 0  # 送り先を直接指定した時は探索しない（PrefLight が 6454 を占有している時のため）
        if node_ip is None or universe is None:
            nodes = artnet.discover()
            log.event("artnet_discover", nodes=[{"ip": n.ip, "mac": n.mac, "outputs": n.outputs} for n in nodes])
            outs = [n for n in nodes if n.outputs]
            if not outs:
                print("Art-Net の出力ノードが見つからない。--node で指定するか --no-artnet"); log.close(); return 2
            node_ip = node_ip or outs[0].ip
            universe = universe if universe is not None else outs[0].outputs[0]
        sender = artnet.ArtNetSender(node_ip, universe)
        print(f"送り先 {node_ip} universe {universe} address {a.address}")
        node_masked = node_ip if node_ip.startswith(("127.", "10.")) else "<lan-ip>"  # 家の LAN アドレスはログに残さない
        log.event("config", node=node_masked, universe=universe, address=a.address, mode=a.mode, bpm=a.bpm, audio=not a.no_audio)
    else:
        log.event("config", mode=a.mode, bpm=a.bpm, audio=not a.no_audio, artnet=False)
    print(f"ログ {log.path}")

    fxs = [StingerSpot11(address=a.address + 11 * i) for i in range(a.fixtures)]
    fx = fxs[0]
    dmx = bytearray(512)
    viz = None
    if a.viz:
        from .viz import Viz
        viz = Viz()
    engine = ForesightEngine(adopt=a.adopt) if a.mode == "claude" else BeatEngine()
    worker = summarizer = None
    if a.mode == "claude":
        from .claude_worker import ClaudeWorker, FeatureSummarizer
        worker = ClaudeWorker(model=a.model or "claude-opus-5-5", effort=a.effort, log=log, variant=a.summary)
        summarizer = FeatureSummarizer(variant=a.summary)
        log.event("claude_config", model=worker.model, effort=a.effort, every=a.every, summary=a.summary, adopt=a.adopt)
    next_claude = 0.0; seen_gen = -1; f_due = False
    detector = ChangeDetector() if a.mode in ("claude", "beat", "rules") and not a.no_audio else None

    audio = tracker = None
    if not a.no_audio:
        from .audio_in import AudioIn, FileIn
        from .beat import BeatTracker
        audio = (FileIn(a.file) if a.file else AudioIn()).start()
        tracker = BeatTracker() if a.bpm is None else None
        log.event("audio_start", device=audio.device, fs=audio.fs, block=audio.block)
    fixed = FixedTempo(a.bpm) if a.bpm else None

    player = None
    if a.play:
        import sounddevice as sd
        import soundfile as sf
        y, fs = sf.read(a.play, dtype="float32", always_2d=True)
        dev = next(i for i, d in enumerate(sd.query_devices()) if d["max_output_channels"] >= 2 and a.out_device in d["name"] and "WASAPI" in sd.query_hostapis()[d["hostapi"]]["name"])
        sd.play(y, fs, device=dev)
        player = sd
        log.event("play", path=a.play, device=dev)

    t_start = time.perf_counter(); next_t = t_start; t_prev = t_start
    log.event("loop_start")  # これ以降の at= は loop_start からの秒（曲の頭）
    frames = beats = 0
    feat = {"rms_db": -80.0, "centroid": 0.0, "flux_low": 0.0, "peak": 0.0}
    level = 0.0; st = {"tempo_bpm": 0.0, "phase": 0.0, "beat": False, "confidence": 0.0, "onset": 0.0}; extra = {}
    try:
        while time.perf_counter() - t_start < a.seconds:
            now = time.perf_counter(); dt = now - t_prev; t_prev = now
            beat = False
            if audio is not None:
                n = 0
                while not audio.q.empty():
                    x = audio.q.get_nowait(); feat = audio.features(x); n += 1
                    if tracker is not None:
                        st = tracker.process(x)
                        beat = beat or st["beat"]
                    if summarizer is not None:
                        summarizer.push(now - t_start, feat, st.get("onset", 0.0))
                    if detector is not None:
                        ch = detector.push(feat["rms_db"], feat["centroid"], st.get("onset", 0.0))
                        if ch:
                            log.event("change_detected", at=round(now - t_start, 2), z=ch["z"])
                            if worker is not None:
                                engine.on_change(now)
                if n:
                    log.event("audio", **{k: float(v) for k, v in feat.items()}, blocks=n)
            else:
                tt = now - t_start
                feat = {"rms_db": -35 + 20 * math.sin(tt * 2 * math.pi / 4), "centroid": 400 + 2600 * (0.5 + 0.5 * math.sin(tt * 0.7)), "flux_low": 0.0, "peak": 0.0}
            if fixed is not None:
                if space_pressed():
                    fixed.tap(now); log.event("tap")
                beat = fixed.tick(now)
                st = {"tempo_bpm": fixed.tempo_bpm, "phase": fixed.phase, "beat": beat, "confidence": 1.0}
            target = max(0.0, min(1.0, (feat["rms_db"] - a.floor_db) / (a.ceil_db - a.floor_db)))
            level = max(target, level * 0.93)

            if worker is not None:
                tnow = now - t_start
                if a.summary == "f":   # 仮説 3: 句の 2・6 小節目の頭（境界の候補の 3 小節前）で聞く。拍が取れない間と 10 秒空いた時は従来どおり
                    due = (f_due or tnow >= next_claude + 6.0) and tnow >= 3.0
                else:
                    due = tnow >= next_claude and tnow >= 3.0
                if due:
                    f_due = False          # f: 前の依頼がまだ返っていなければ、この回は見送る（遅れて聞いても意味がない）
                    summ = summarizer.summary(tnow, st["tempo_bpm"], worker.latest)
                    if worker.request(summ):
                        log.event("claude_req", gen=worker.generation, rows=len(summ["last_30s"]))
                    next_claude = tnow + a.every
                if worker.latest_gen > seen_gen:
                    seen_gen = worker.latest_gen
                    engine.on_foresight(worker.latest, now, asked_at=worker.latest_asked, bar_at_ask=worker.latest_bar)
                    summarizer.history.append({"t": round(tnow, 1), "section": worker.latest.section_now.value})
                    log.event("foresight_applied", gen=seen_gen, boundary_in=round(engine.boundary_at - now, 1) if engine.boundary_at else None, late=engine.last_late)
            if a.mode == "direct":
                pan = 0.5 + 0.25 * math.sin((now - t_start) * 2 * math.pi / 8)
                params = {"pan": pan, "tilt": 0.55, "color": pick_color(feat["centroid"]), "dimmer": level, "shutter": "open", "speed": 0.0}
            else:
                if beat:
                    engine.on_beat(); beats += 1
                    if summarizer is not None:
                        summarizer.on_beat()
                        if summarizer.beats % 16 in (4, 12):   # f: 小節 2・6・10・14… の頭
                            f_due = True
                    log.event("beat", n=beats, tempo_bpm=st["tempo_bpm"], confidence=st["confidence"])
                period_s = 60.0 / st["tempo_bpm"] if st["tempo_bpm"] else 0.5
                if worker is not None:
                    params = engine.step(dt, st["phase"], period_s, level, now=now)
                    extra = {"tame": params.pop("tame"), "opened": params.pop("opened")}
                    for ev in engine.events:
                        log.event("engine_event", what=ev[0], at=(round(ev[1] - t_start, 2) if ev[0] in ("open", "rescue") else ev[1]))
                    engine.events.clear()
                else:
                    params = engine.step(dt, st["phase"], period_s, level); extra = {}
                    if a.mode == "rules":  # ② 特徴量→色の直結表（重心→色・音量→床）
                        params["color"] = pick_color(feat["centroid"])
                        params["dimmer"] = min(1.0, params["dimmer"] * (0.6 + 0.4 * level))
            written = fx.render(dmx, **params)
            for i, f in enumerate(fxs[1:], 1):  # 2 台目以降: 偶数番は Pan を左右対称に、中央は正面寄り
                p2 = dict(params)
                if i % 2 == 1:
                    p2["pan"] = 1.0 - params["pan"]
                elif a.fixtures >= 3 and i == a.fixtures - 1 and a.fixtures % 2 == 1:
                    p2["pan"] = 0.5 + 0.3 * (params["pan"] - 0.5)
                f.render(dmx, **p2)
            if sender is not None:
                sender.send(dmx)
            frames += 1
            if viz is not None and frames % 2 == 0:
                fsx = getattr(engine, "fs", None)
                viz.update(dmx, a.address, {"beat": beats, "tempo": st["tempo_bpm"], "phase": st["phase"], "mode": a.mode,
                                            "section": fsx.section_now.value if fsx else "-", "next": fsx.section_next.value if fsx else "-",
                                            "boundary": round(engine.boundary_at - now, 1) if getattr(engine, "boundary_at", None) else "-",
                                            "tame": extra.get("tame", "-"), "scene": fsx.scene_word if fsx else "", "reason": fsx.reason if fsx else ""})
            if frames % 8 == 0:
                log.event("dmx", frame=frames, **written, level=round(level, 3), phase=round(st["phase"], 3), tempo_bpm=st["tempo_bpm"], **(extra if a.mode != "direct" else {}))
            next_t += FRAME
            sleep = next_t - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.perf_counter(); log.event("late", by_ms=round(-sleep * 1000, 1))
    finally:
        if sender is not None:
            sender.blackout(); sender.close(); log.event("blackout")
        if player is not None:
            player.stop()
        if audio is not None:
            audio.stop(); log.event("audio_stop", dropped=audio.dropped)
        el = time.perf_counter() - t_start
        log.event("summary", frames=frames, beats=beats, seconds=round(el, 2), fps=round(frames / max(1e-6, el), 1), tempo_bpm=st["tempo_bpm"])
        log.close()
    print(f"frames {frames} beats {beats} tempo {st['tempo_bpm']} / {a.seconds}s  log {log.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
