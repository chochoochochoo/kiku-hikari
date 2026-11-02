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
### V202611.003 – 20261102-13:40
**指示:** 漏えい防止の仕組み 他aiたちにも監査させて
**変更:** 監査4系統（敵対レビュア2体=Opus・Codex・Gemini）の指摘を反映。secret_scan.py を「git に入る中身」（ステージ済み blob・コミットの blob・名義・本文）の検査に書き換え（--staged/--range/--history/--all）。日本語ファイル名（quotepath off・-z）、UTF-16、不明バイナリ、git 失敗時・JSON 失敗時は止める側、allow 印は .md と .env.example のみ、電話番号・郵便番号・引用符なし代入・JWT を追加、.env への書き込みとリポジトリ外は hook で対象外。Claude フックに Bash を追加（--no-verify・force push・コマンド内の鍵）と permissions.deny。secret_scan.sh（python3 の Store スタブを避けて動く解釈系を選ぶ）。install_hooks.py が名義を noreply に設定し全履歴を検査。.gitignore を logs/* 形式に（logs/public が追跡される）。GitHub Actions で push ごとに全履歴検査。tools/test_secret_scan.py（一時クローンで 24 ケース・全 OK）
---
