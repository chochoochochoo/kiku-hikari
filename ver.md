# ver.md — kiku-hikari（このリポジトリ専用の作業記録。版番号 Vyyyymm.nnn はこのファイル内で採番。時刻は date か git log の実測値を使う＝推測で書かない）

---
### V202611.001 – 20261102-13:03:07
**指示:** はじまった！ gitログインしたい（→ chochoochochoo で gh 認証後、リポジトリ名 kiku-hikari・最初から公開 を本人決定）
**変更:** リポジトリ作成。README.md 雛形・.gitignore・ver.md。コミット名義は GitHub の noreply アドレス
---
### V202611.002 – 20261102-13:09:00
**指示:** リポジトリ公開、機微情報もらさないように仕組みつくっておいて（各実行ファイルのキャッシュとかに API が漏れると聞いた）
**変更:** .gitignore を全面書き換え（秘密値・キャッシュ・エディタ設定・音源・ログ）、.env.example、tools/secret_scan.py（鍵/トークン/秘密鍵/個人メール/禁止ファイル種・リポジトリ外の拒否語リスト対応）、tools/install_hooks.py（pre-commit/pre-push）、.claude/settings.json（Write/Edit の PreToolUse フック）。偽の鍵でコミットが止まること・フックが4種で止まることを確認。README に「秘密値の扱い」
---
### V202611.003 – 20261102-13:19:32
**指示:** 漏えい防止の仕組み 他aiたちにも監査させて
**変更:** 監査4系統（敵対レビュア2体=Opus・Codex・Gemini）の指摘を反映。secret_scan.py を「git に入る中身」（ステージ済み blob・コミットの blob・名義・本文）の検査に書き換え（--staged/--range/--history/--all）。日本語ファイル名（quotepath off・-z）、UTF-16、不明バイナリ、git 失敗時・JSON 失敗時は止める側、allow 印は .md と .env.example のみ、電話番号・郵便番号・引用符なし代入・JWT を追加、.env への書き込みとリポジトリ外は hook で対象外。Claude フックに Bash を追加（--no-verify・force push・コマンド内の鍵）と permissions.deny。secret_scan.sh（python3 の Store スタブを避けて動く解釈系を選ぶ）。install_hooks.py が名義を noreply に設定し全履歴を検査。.gitignore を logs/* 形式に（logs/public が追跡される）。GitHub Actions で push ごとに全履歴検査。tools/test_secret_scan.py（一時クローンで 24 ケース・全 OK）
---
### V202611.004 – 20261102-13:26:38
**指示:** （監査の続き）Gemini の監査結果を反映
**変更:** 代入名の拡大・引用符なし代入の行末条件除去・電話番号のハイフンなし/+81・郵便番号は〒か住所語の近傍のみ・メール許可に github.com・allow 印でも本物の鍵の形と拒否語は止める・禁止パスは大文字小文字無視・.zip は不明バイナリ扱い・許可バイナリも鍵の形だけ検査・NotebookEdit・-n/core.hooksPath・コミット時点の名義検査（--staged）・タグ本文（--object・--history）・pre-push の ref 削除を素通し・install_hooks は gh 未ログインで停止。test_secret_scan.py を 39 ケースに（全 OK）
---
### V202611.005 – 20261102-14:09:10
**指示:** PLAN §7 の 11/2 分（音声入力・ログ基盤・Art-Net 疎通）着手して（本人不在・綴が進める）
**変更:** kiku_hikari/ パッケージ新設: artnet.py（ArtPoll 探索・ArtDmx 送信）、audio_in.py（WASAPI 48 kHz 25 ms・RMS/重心/低域フラックス）、runlog.py（JSONL・単調時計）、fixtures.py（Stinger Spot 11ch 表＋安全弁）、main.py（v0: 40 Hz 直結）。Art-Net ノード 2 台を発見（.239 が Universe 0 出力）。20 秒の通しログを logs/public/ に（検査済み）。docs/hardware-notes.md・docs/ai-usage-log.md・README「いま動くもの」
---
### V202611.006 – 20261102-14:16:30
**指示:** （本人不在・綴が 11/3 分へ前倒し）拍追従・40 Hz エンジン・拍で Pan/Tilt
**変更:** kiku_hikari/beat.py（因果の拍追従: 対数スペクトルのフラックス→自己相関＋倍音加算→櫛で位相合わせ・位相リセットなし）、engine.py（拍で Pan 左右・Tilt 2 拍・明るさパルス）、main.py を --mode direct/beat・--bpm 固定＋Space タップ・--play 自己試験・--no-artnet に拡張。tools/beat_eval.py と docs/eval-beat.md（10 曲の表・指定 BPM は当てにならない）。自己試験ログを logs/public/ に（検査済み）
---
### V202611.007 – 20261102-14:22:55
**指示:** （本人不在・綴が 11/5 分へ前倒し）Claude ワーカー・先読み・JSON→DMX 結線
**変更:** kiku_hikari/claude_worker.py（Foresight の Enum 固定 JSON・messages.parse・system 固定部に知識ファイル＋cache_control・同時 1 件・世代番号・失敗は「返答なし」扱い）、engine.py に ForesightEngine（語彙・溜め・感情の床・境界を小節頭にクオンタイズして開く）、main.py に --mode claude／--every／--model／--effort。自己試験 80 秒（03）: 18 応答・late 0・開き 1 回。README「いま動くもの」を 3 モードに
---
### V202611.008 – 20261102-14:24:05
**指示:** （綴の自己訂正）ver.md と docs/ai-usage-log.md の時刻を git log・スクショの実測に合わせて訂正（.002〜.007 を推測で書いていた）。② ルール表モード
**変更:** 時刻 6 件＋10 件を訂正。main.py に --mode rules（拍連動＋重心→色・音量→床の直結表。Claude なし）
---
### V202611.009 – 20261102-14:27:47
**指示:** （本人不在・綴が 11/4 分へ前倒し）音響変化検出・ブラインド判定の手順・知識ファイル
**変更:** kiku_hikari/change.py（CUSUM の変化検出）と engine.on_change（救済: 次の小節頭で開く）。knowledge/lighting_knowledge.json（サブエージェントが研究の原文から下書き・規則 25）。claude_worker の要約を相対レベル（曲中最大=1）に正規化・legend を添付。docs/eval-blind.md（第三者 3 人・ラテン方格・質問 3 つ）。07 で 80 秒の自己試験: Claude 18 応答（キャッシュ読み 11,813 トークン/回）・救済 3 回
---
### V202611.010 – 20261102-14:33:03
**指示:** （本人不在・綴）疑似モードと README の本文。本人から EtherMX の設定画面（2007=.239 出力 U0/U0/U2/U3、2008=.240 入力/入力/U2/U3・DMX 出力 29 Hz）
**変更:** audio_in.FileIn（WAV を実時間で直接入力）、viz.py（tkinter の仮想灯体）、main.py に --file / --viz。README を提出形に書き直し（誰のためか／Claude の役割／他モデル／11/2 前の準備／Claude Code で何を作ったか／いま動くもの／審査員向けセットアップ／残り）。docs/hardware-notes.md に EtherMX 設定（DMX 出力 29→40 Hz の依頼）
---
### V202611.011 – 20261102-14:34:48
**指示:** （綴）仮想灯体の窓が他の窓の後ろに隠れる→最前面に。判定シートの雛形
**変更:** viz.py topmost＋位置指定（スクショで表示を確認: 青い円・拍/テンポ/位相/色/明るさ・Claude の判断行）。docs/blind-sheet.csv。shots/snap.ps1 を全モニタ撮影に
---
### V202611.012 – 20261102-14:38:53
**指示:** （綴）同一曲 3 段の公開ログと字幕生成
**変更:** tools/subtitles.py（ログ→SRT）。自作曲 05 を ①beat／②rules／③claude で 70 秒ずつ（--file・灯体なし）→ logs/public/ に 3 本（検査済み）
---
### V202611.013 – 20261102-14:40:27
**指示:** （綴）正解づけと的中率の道具
**変更:** tools/annotate_sections.py（作者が耳で境界を打つ→sections/*.json・Claude には渡さない）、tools/foresight_eval.py（開き vs 正解・予測/救済の別・余計な開き）。.gitignore は sections/* を除外し sections/public/ だけ追跡

## 次回再開ポイント（2026-11-02 14:4x・本人が戻ったら）
1. 実機: 灯体を 2007 のポート 1/2 に、11Ch・A001、EtherMX の DMX 出力を 40 Hz に → `py -3.12 -m kiku_hikari.main --mode beat --seconds 60` で拍で Pan/Tilt が打てるか目視（PLAN の 11/3 18:00 の関門）
2. Pan/Tilt の最大速度を見て fixtures.Safety（max_pan_step/max_tilt_step）を詰める
3. 知識ファイル knowledge/lighting_knowledge.json の「根拠なし」「energy の目安」を本人の判断で上書き
4. 正解づけ: `py -3.12 tools/annotate_sections.py <wav>` を 3 曲 → `tools/foresight_eval.py` で的中率
5. ブラインド判定（docs/eval-blind.md）の 3 人の候補・撮影場所
6. 残り: 動画（字幕は tools/subtitles.py）、README 英語付記、Max コードを別アカウントで適用
---
### V202611.014 – 20261102-14:41:16
**指示:** （綴）拍追従の立ち上がり改善を試す
**変更:** 立ち上がり重み 0.6 の実験は 10 曲評価で悪化（docs/eval-beat.md に記録）→ beat.py は元に戻した（コード変更なし）
---
### V202611.015 – 20261102-15:13:36
**指示:** いま台湾なので物理的な接続できない→ PrefLight（kuwatec）で対応しよう（本人）
**変更:** docs/hardware-notes.md に PrefLight の事実（Stinger Spot がライブラリにある・Art-Net 入力・6454 占有・動画記録）。main.py: --node 指定時は探索せず Universe 0 を既定に。preflight/ フォルダ（シーンは本人が GUI で作成）
---
