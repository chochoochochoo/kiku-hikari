# kiku-hikari — 曲を聴いて、ムービングライトが光る

Built with Claude: Japan 2026（Cerebral Valley × Anthropic・2026-11-02 12:30 〜 11-08 20:00）の提出作品。
このリポジトリの内容はすべてハッカソン期間中に Claude Code で新規に制作する。

- 制作: I LLC
- 状態: 2026-11-02 13:10 作成（初回コミット）。README は提出までに書き直す。

## 秘密値の扱い（公開リポジトリなので最初に決めた）
- 鍵は `.env`（.gitignore 済み）か環境変数 `ANTHROPIC_API_KEY` からだけ読む。雛形は `.env.example`
- `tools/secret_scan.py` が鍵・トークン・秘密鍵・個人メール・入れてはいけない種類のファイル（.env・*.pem・__pycache__ 等）を検査する
  - git の pre-commit / pre-push（`python tools/install_hooks.py` で導入）
  - Claude Code の PreToolUse フック（`.claude/settings.json`・Write/Edit の内容を書き込む前に検査）
  - GitHub 側の secret scanning と push protection も有効
- 実行ログは `logs/` に出し、公開するものだけ検査してから `logs/public/` に置く
