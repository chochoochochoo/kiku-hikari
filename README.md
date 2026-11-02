# kiku-hikari — 曲を聴いて、ムービングライトが光る

Built with Claude: Japan 2026（Cerebral Valley × Anthropic・2026-11-02 12:30 〜 11-08 20:00）の提出作品。
このリポジトリの内容はすべてハッカソン期間中に Claude Code で新規に制作する。

- 制作: I LLC
- 状態: 2026-11-02 13:10 作成（初回コミット）。README は提出までに書き直す。

## 秘密値の扱い（公開リポジトリなので最初に決めた）
- 鍵は `.env`（.gitignore 済み）か環境変数 `ANTHROPIC_API_KEY` からだけ読む。雛形は `.env.example`。説明用のメールは example.com、鍵の例は `sk-ant-...` のように短く書く
- `tools/secret_scan.py` が「git に実際に入る中身」（ステージ済みの blob・コミットの blob・名義・本文）を検査する。鍵・トークン・JWT・秘密鍵・個人メール・電話番号・郵便番号・入れてはいけない種類のファイル（.env・*.pem・__pycache__・logs/ の生データ等）・不明なバイナリ。壊れた時は止める側に倒す
  - 1層目 Claude Code の PreToolUse フック（`.claude/settings.json`・Write/Edit/Bash の内容を実行前に検査。`--no-verify` と force push は permissions.deny で禁止）
  - 2層目 git の pre-commit / pre-push（クローン直後に `python tools/install_hooks.py`。コミット名義も noreply アドレスに設定し、全履歴を1回検査する）
  - 3層目 GitHub Actions（`.github/workflows/secret-scan.yml`・push ごとに全履歴）と GitHub の secret scanning / push protection
- 作者の本名・住所・社名などの拒否語はリポジトリ外 `~/.kiku-hikari-denylist.txt` に置く（無い機械では警告が出る）
- 実行ログは `logs/` に出し、公開するものだけ `logs/public/` に置く（そこだけ追跡され、検査を通る）
