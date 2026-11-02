# 機材と結線のメモ（11/2 時点・実測したものだけ）

## Art-Net ノード（2026-11-02 14:05 ArtPoll で発見・`py -3.12 -m kiku_hikari.artnet`）
| IP | MAC | ポート | 役割（ArtPollReply の PortTypes） |
|---|---|---|---|
| 10.106.195.239 | 00:1b:c5:0b:c3:ef | 1 | Art-Net → DMX 出力（Port-Address 0 ＝ Net 0 / Sub 0 / Universe 0）。GoodOutput=0x80（送出中） |
| 10.106.195.240 | 00:1b:c5:0b:c3:f0 | 1 | DMX → Art-Net 入力（本件では使わない） |

- 母艦の 10.10.10.10 側のインターフェースから 10.255.255.255 へのブロードキャストで両方が返事。名前欄は空（EtherMX の初期値と思われる・未確認）。
- 送信は `.239` へユニキャスト・Universe 0・40 Hz（ArtDmx・512 ch）。

## 灯体 ADJ Stinger Spot（STI680）
- チャンネル表は取扱説明書 p.17–20（9ch / 11ch）。本コードは **11ch モード・開始アドレス 1** を前提にしている（`kiku_hikari/fixtures.py`）。灯体側のメニューで `11Ch` と `A001` に合わせること（未確認: 本人が実機で確認）。
- Pan 540° / Tilt 210°（製品ページ）。Pan/Tilt の最大速度・角加速度は未計測（11/3 に実測して `Safety` の値を更新）。
- 安全弁の暫定値: 1 フレームあたり Pan/Tilt 8bit で ±6、ストロボは速さの上限 0.45、Dimmer 上限 255。

## 音声入力
- `マイク (USB Audio CODEC)`・Windows WASAPI・1ch・48 kHz（番号は挿し直しで変わるので名前で選ぶ）。25 ms ブロック（40 Hz）で 20 秒間 0 ドロップ。

## 11/2 の到達点（PLAN §7 の受け入れ条件「入力の RMS と時刻がログに出る・灯体の色が Python から変わる」）
- RMS と時刻: `logs/public/20261102-140740-v0-silence-20s.jsonl`（無音〜環境音・800 フレーム・40.0 fps・late 0）
- 灯体の色: ArtDmx を Universe 0 の .239 へ送り、ノードは GoodOutput=送出中。**灯体が実際に光ったかは本人の目視待ち**（綴は見られない）
