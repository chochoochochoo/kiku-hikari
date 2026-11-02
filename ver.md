# ver.md — kiku-hikari（このリポジトリ専用の作業記録。版番号 Vyyyymm.nnn はこのファイル内で採番）

---
### V202611.001 – 20261102-13:03:07
**指示:** はじまった！ gitログインしたい（→ chochoochochoo で gh 認証後、リポジトリ名 kiku-hikari・最初から公開 を本人決定）
**変更:** リポジトリ作成。README.md 雛形・.gitignore・ver.md。コミット名義は GitHub の noreply アドレス
---
### V202611.002 – 20261102-13:20
**指示:** リポジトリ公開、機微情報もらさないように仕組みつくっておいて（各実行ファイルのキャッシュとかに API が漏れると聞いた）
**変更:** .gitignore を全面書き換え（秘密値・キャッシュ・エディタ設定・音源・ログ）、.env.example、tools/secret_scan.py（鍵/トークン/秘密鍵/個人メール/禁止ファイル種・リポジトリ外の拒否語リスト対応）、tools/install_hooks.py（pre-commit/pre-push）、.claude/settings.json（Write/Edit の PreToolUse フック）。偽の鍵でコミットが止まること・フックが4種で止まることを確認。README に「秘密値の扱い」
---
