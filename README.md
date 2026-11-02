# kiku-hikari — 曲を聴いて、ムービングライトが光る

Built with Claude: Japan 2026（Cerebral Valley × Anthropic・2026-11-02 12:30 〜 11-08 20:00）の提出作品。
このリポジトリの内容はすべてハッカソン期間中に Claude Code で新規に制作する。

- 制作: I LLC
- 状態: 2026-11-02 14:10 v0 ＝ 音声入力→特徴量→Art-Net→灯体 の通しが動く（下の「いま動くもの」）。README は提出までに書き直す。

## いま動くもの（v0・11/2）
```
py -3.12 -m kiku_hikari.artnet                 # Art-Net ノードを探す（ArtPoll）
py -3.12 -m kiku_hikari.audio_in               # 音声入力の特徴量を 3 秒表示
py -3.12 -m kiku_hikari.main --mode direct --seconds 20   # ① 直結（音量→明るさ・重心→色）
py -3.12 -m kiku_hikari.main --mode beat --seconds 60     # ② 拍連動（自前の拍追従で Pan/Tilt を打つ）。--bpm 120 で固定テンポ
py -3.12 -m kiku_hikari.main --mode claude --seconds 90   # ③ Claude の先読み（色・語彙・溜め・境界で開く）を拍の上に載せる
py -3.12 -m kiku_hikari.main --mode claude --play song.wav   # 手元の WAV をヘッドホン→マイクで聴かせる自己試験
py -3.12 -m kiku_hikari.main --no-audio --seconds 10      # 音なしで結線だけ確認
```
- 2 つの輪: 速い輪（Python・40 Hz・拍と数値と安全）と遅い輪（Claude API・約 4 秒ごと・`claude_worker.py`・Enum 固定 JSON＝次の境界まで何秒／次の区間／開き方／色／語彙／溜め／感情 2 軸／情景一語）。知識ファイル `knowledge/lighting_knowledge.json` は system の固定部に置きプロンプトキャッシュに乗る（実測: 毎回 1,994 トークンがキャッシュ読み）
- 実測（11/2・自作曲 03 を 80 秒）: Claude Opus 5.5・effort low で往復 2.3〜4.7 秒・18 回、境界の開きは予測時刻の直後の小節頭にクオンタイズ（46.1 s に 1 回）。ログ `logs/public/`
- 構成: `audio_in.py`（WASAPI 48 kHz・25 ms）→ `beat.py`（自前の拍追従）→ `engine.py`（拍連動／先読みエンジン）→ `fixtures.py`（Stinger Spot 11ch・安全弁）→ `artnet.py`（ArtDmx・ArtPoll・標準ライブラリのみ）。`claude_worker.py` が遅い輪。`runlog.py` が全部を 1 本の時刻つきログにする。評価は `tools/beat_eval.py`・`docs/eval-beat.md`
- 機材の実測は `docs/hardware-notes.md`。依存: numpy・sounddevice（`py -3.12`）

## 秘密値の扱い（公開リポジトリなので最初に決めた）
- 鍵は `.env`（.gitignore 済み）か環境変数 `ANTHROPIC_API_KEY` からだけ読む。雛形は `.env.example`。説明用のメールは example.com、鍵の例は `sk-ant-...` のように短く書く
- `tools/secret_scan.py` が「git に実際に入る中身」（ステージ済みの blob・コミットの blob・名義・本文）を検査する。鍵・トークン・JWT・秘密鍵・個人メール・電話番号・住所つき郵便番号・鍵らしき代入・入れてはいけない種類のファイル（.env・*.pem・__pycache__・logs/ の生データ等・大文字小文字を問わない）・不明なバイナリ・コミットとタグの名義と本文。壊れた時は止める側に倒す。例示の見逃し（.md の行末 `secret-scan: allow`）は本物の鍵の形と拒否語には効かない
  - 1層目 Claude Code の PreToolUse フック（`.claude/settings.json`・Write/Edit/NotebookEdit/Bash の内容を実行前に検査。`--no-verify`・`-n`・force push・core.hooksPath は permissions.deny で禁止）
  - 2層目 git の pre-commit / pre-push（クローン直後に `python tools/install_hooks.py`。コミット名義も noreply アドレスに設定し、全履歴を1回検査する）
  - 3層目 GitHub Actions（`.github/workflows/secret-scan.yml`・push ごとに全履歴）と GitHub の secret scanning / push protection
- 作者の本名・住所・社名などの拒否語はリポジトリ外 `~/.kiku-hikari-denylist.txt` に置く（無い機械では警告が出る）
- 実行ログは `logs/` に出し、公開するものだけ `logs/public/` に置く（そこだけ追跡され、検査を通る）
- 抜け道の試験: `python tools/test_secret_scan.py`（一時クローンで 39 ケース。敵対レビュー 2 体・Codex・Gemini の監査で見つかった抜け道を全部含む）
