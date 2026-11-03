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

## EtherMX Set の設定（本人の画面・2026-11-02 14:3x）
- 2007 = 10.106.195.239: ポート 1・2 = 出力 Universe 0（Net 0/Sub 0）、ポート 3・4 = 出力 Universe 2・3 → **灯体はポート 1 か 2 に挿す**（Universe 0 に送っている）
- 2008 = 10.106.195.240: ポート 1・2 = 入力（Net 1 / Univ 1）、ポート 3・4 = 出力 Universe 2・3（本件では未使用）
- サブネット 255.0.0.0・DHCP なし・Unicast 使用なし・ArtSync なし・設定後消灯・DMX 出力繰返し **29 Hz → 40 Hz に上げる依頼**（こちらは 40 Hz 送信）・Art-Net 送信繰返し 0.1 秒

## PrefLight（kuwatec の照明ビジュアライザ・母艦に導入済み・登録済み）— 実機が無い間の「画面の灯体」
- `C:\Program Files\PrefLight\PrefLight.exe`。灯体ライブラリに American DJ「Stinger Spot」あり（`SupportFiles/Instruments/AmericanDJ/Stinger Spot`・制御 cMod/cPan/cTlt/cCol/cGob/cSht/cDim/cSpd/cFnc/cDmC ＝ 9/11ch）
- 入力: DoctorMX / Art-Net / sACN / OSC（ヘルプ「DMX 接続...」）。Art-Net は UDP 6454 を PrefLight が占有するので、こちらの ArtPoll 探索は PrefLight 起動中は使わず `--node 127.0.0.1`（または母艦の LAN IP）で直接送る。ArtPollReply には応える
- 記録: ファイルメニュー「静止画として記録」「動画に記録」→ `Documents\PrefLight Capture\`（登録済みなので 10 秒制限なし）
- シーン: `preflight/stage.plt`（本人が GUI で作成: Stinger Spot ×1・アドレス 1・11ch・Universe 0）
- **2026-11-02 15:48 受信成功**: 3 台目の Stinger を「系統 3 = Art-Net Net 3 / Sub 0 / Univ 0」（Port-Address 0x0300 = 768）に置き、`--node 127.0.0.1 --universe 768` で送って動いた（拍連動モード・白ビーム・Pan 204）。
  - 失敗していた間の状況: 同じ PC で DoctorMX が Art-Net 0/0/0 を送信中＋EtherMX 2007/2008 の入力ポートも 0/0/0 で Art-Net を出していた。ヘルプ「同一コンピューター内の複数の送信元は 1 つとみなされ正常にマージされない」「マージ対象以外の送信元は無視」に該当した可能性が高い（事実: EtherMX を Net 1 に変え、系統 3 を新設した後に受信した。DoctorMX 送信の停止が効いたかは未切り分け）
  - 送り先は 127.0.0.1 で足りる（ローカル UDP の到達は 5 アドレスで確認済み）。ファイアウォールは無関係
  - 教訓: PrefLight を使う時は **専用の Net（例: Net 3）を切り、同じ PC の他の Art-Net 送信元（DoctorMX の Art-Net 出力）を止める**
- **16:10 3 灯で動作**: PrefLight の 3 台を系統 1（Art-Net 0.0.0）・11ch・アドレス 1/12/23 に揃え、`--fixtures 3 --node <母艦の LAN アドレス> --universe 0` で 3 本のビームが拍で動いた。
  - 実測で分かった PrefLight の癖: ArtDmx の Net 番号は照合されず、Sub/Univ が一致する全系統に同じデータが配られる（Net 2・Net 3 宛は届かなかった）。送り先は母艦の LAN アドレス（127.0.0.1 宛は届かない時があった）。DoctorMX が起動中は同一 PC 送信元として扱われ、こちらが捨てられる。9ch モード（Fine 無し）の灯体は 5ch 目の色値をシャッターに読んで暗くなる

## 台湾側（本人が持参・2026-11-02 時点）
- EtherMX 1 台・DoctorMX 1 台・Mac mini・Win10 機。家の PrefLight が使えない時の代替案: Win10 に PrefLight 試用（保存不可・動画 10 秒）＋このコード。いまは未使用

## 灯体 ADJ Dotz Par（9ch モード・8 台・2026-11-03 本人指示で追加）
- チャンネル表は説明書 p.8（9ch）・p.9（カラーマクロ）。1 赤 / 2 緑 / 3 青 / 4 マスターディマー / 5 カラーマクロ / 6 プログラム / 7 速度・感度 / 8 ストロボ / 9 ディマーカーブ（`kiku_hikari/fixtures.py` の `DotzPar9`）
- 固定する値: 5〜7ch は 0（RGB を使う時はマクロ不可・6ch=000 で灯体側の自動／サウンド演出を切る）、9ch は 0（STANDARD）。ストロボ（8ch）は Stinger と同じ上限（`Safety.max_strobe_hz_equiv` 0.45）で 1〜255 の遅→速に割り当てる（実機の Hz は未計測）
- 色名→RGB: Stinger の色ホイール 8 色と同じ名前で `PAR_RGB` に持つ（orange=255/90/0・light_blue=0/150/255・pink=255/40/140 は目安。実機で見て直す）
- アドレス: Stinger 3 台 = 1/12/23（11ch・〜33）、Par 8 台 = 34/43/52/61/70/79/88/97（9ch・〜105）。ユニバースは同じ 0.0.0。起動時に重なりと 512 超えを検査し、あれば exit 2
- 使い方: `--fixtures 3 --pars 8`（`--par-address 34` が既定）。既定は `--pars 0` で従来どおり Stinger だけ。ログの `rig` に全台のアドレス、`dmx` に 1 台目の Par の `[R,G,B,ディマー]`
- 各モードでの役割（Stinger＝動きとビーム、Par＝面の色。ブラインド判定の条件を揃えるため、3 モードとも Par は Stinger と同じ色・明るさ・シャッターを受ける）
  - ① 拍連動: 白で、Stinger と同じ拍の明滅
  - ② ルール表: 表の色（スペクトル重心→色）と、音量の床つきの明るさ
  - ③ Claude: Claude の色を Stinger と揃える（別役は付けない。溜めの暗さ・境界の開き・次の色も Stinger と同時）
- 画面の仮想灯体（`--viz`）は Stinger だけを描く（Par は PrefLight で見る）
- PrefLight: 機種 `AmericanDJ/Dotz Par 100`（Dotz Par を元にした定義）・pMod=3 が 9ch で、並びは説明書と同じ。14:39 保存の stage.plt は Par 4 台（34・43 は設定済み、残り 2 台は未設定）。8 台の配置が保存されたらコミットする

## Par の配置パターンとスポット 6 台（2026-11-03 本人指示・`fixtures.par_pattern` / `spot_levels`）
Par 8 台（左→右）は 3 モードで次のように光る。① は全台白で拍の明滅。② は表の色と対の色（`PAR_PAIR`）を奇数/偶数に置く。③ は Claude の区間で選ぶ。verse などは全台同じ主色、pre_chorus は左→右に「主色→次の色」のグラデーション（次の色替えの予告）、chorus は奇数/偶数の 2 色を小節ごとに入れ替える。どの区間でも、開いた直後の 0.5 秒は中央から外へ広げる。スポット 6 台（汎用 1ch ディマー・`--spots 6 --spot-address 501`・左→右）は次のとおり。① は一定 50%、② は音量に追従（30〜100%）。③ は区間で点ける台数を変え（intro・verse は中央 2 台＝1 人抜き、pre_chorus は 4 台、chorus は 6 台、break は 0 台）、明るさは溜めと開きに合わせる。①② を単純な固定にしたのは、ブラインド判定で「Claude の判断があるかないか」だけを比べるため。点滅の安全上限は今のまま（Par のストロボは Stinger と同じ上限、スポットは点滅させない）。注意: Claude がサビと言う割合は 2〜5% なので、③ でも多くの時間は「全台同色・中央 2 台」になる（05_mixture_funk の 80 秒で全台同色が 98%、中央 2 台が 92%）。
- **サビ判定の手当て**（`--chorus-bars 8`・既定 8・③ のみ・2026-11-03 本人の決定）: Claude がサビと言う割合が 2〜5% と少ないため、③ では Par とスポット向けに区間を読み替える。Claude が小節数で答えた境界（救済は含めない）を過ぎた所から 8 小節を chorus 扱い、その手前の 2 小節を pre_chorus 扱いにする。Stinger と Claude 本体の区間名は変えない。外れても隠さない（ログの `light_chorus` と dmx の `lsec`）。80 秒の疑似走行の結果は次のとおり。05_mixture_funk は全台同色が 98%→49%、中央 2 台が 92%→41% に下がり、サビ扱いは 23.5 秒と 43.5 秒に始まった（一番近い耳の切れ目との差 +0.4・+1.5 秒）。03_idol_dance は全台同色 37%・中央 2 台 29% で、サビ扱いは 5 回始まった（差は −1.4〜+1.5 秒）。サビ扱いは時間の約半分を占める。耳の切れ目は 4 秒おきほどと密なので、±1.5 秒に入ったこと自体は偶然でも起こりうる（サビかどうかの正解は無い）。
