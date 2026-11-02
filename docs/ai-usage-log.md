# AI の使い方の記録（発表用・時系列）

このプロジェクトは Claude Code を開発の中心に置き、Claude が他の AI を呼び分ける形で進めている。
「人がどの AI に何をさせたか」が後から分かるように、ここに日時つきで残す。コードを書いたのは Claude Code（Claude Fable 5.1）のみ。

| 日時 | 誰が／何を | 使った AI | 目的・結果 |
|---|---|---|---|
| 11/2 13:03 | 綴（Claude Code）がリポジトリ作成・README 雛形・.gitignore | Claude Code | キックオフ後の最初のコミット |
| 11/2 13:10〜13:20 | 秘密値の漏えい防止（.gitignore・secret_scan.py・git hook・Claude Code の PreToolUse フック） | Claude Code | 公開リポジトリに鍵・個人情報を入れない仕組み |
| 11/2 13:20〜13:35 | その仕組みの監査を 4 系統に依頼 | 敵対レビュア 2 体（Claude Opus・攻撃者視点／運用視点）、OpenAI Codex（read-only sandbox）、Gemini（agy・MCP 経由） | 抜け道 10+10+8+8 件・誤検知 5 件が見つかり、すべて反映。Gemini は CLI で 2 回空応答→MCP 経由で取得 |
| 11/2 13:40〜14:05 | 監査結果の反映と試験（一時クローンで 39 ケース） | Claude Code | 「ステージ済みの中身」「コミットの名義」「タグ」「Bash 経由」「日本語ファイル名」「UTF-16」まで止まることを機械で確認 |
| 11/2 14:00 | GitHub Actions で全履歴検査 | GitHub（Actions） | push ごとに 3 層目の検査が success |
| 11/2 14:05 | Art-Net ノード探索（ArtPoll） | Claude Code | LAN 上に 2 ノード（EtherMX と思われる・MAC 00:1b:c5）を発見。出力ポートはユニバース 0 |
| 11/2 14:05 | Stinger Spot の DMX チャート（取説 p.17–20 は画像）を Claude が画像として読んで `fixtures.py` に転記 | Claude Code（画像読み） | OCR ソフト無しで表を取り込んだ |
| 11/2 14:07 | v0 を書いて通し実行（音声→特徴量→Art-Net、20 秒・800 フレーム・40.0 fps・late 0・音声ドロップ 0） | Claude Code | 11/2 の受け入れ条件のうち「RMS と時刻がログに出る」を満たす。灯体の点灯は本人の目視待ち |

## キックオフ前（リポジトリの外・成果物ではない）
- 2026-10-14〜11-02 に計画書（PLAN.md）・勝ち筋（STRATEGY.md）・調査（研究 39 話題・原文約 1,600 本・日本照明家協会誌）を作った。運営 FAQ Q4「事前の計画・構想は認めるが、リポジトリの外で行う」に従い、リポジトリには入れない。
- そこでも Claude（Opus・Fable）を中心に、Codex・Gemini・ローカル LLM（LFM・Heretic 27B）を「話題出し」「反証」に使った。製品コードは一切書いていない。
| 11/2 14:20〜14:35 | 自前の拍追従（beat.py）を書き、10 曲でオフライン評価（tools/beat_eval.py・参照に librosa） | Claude Code | 生成時に指定した BPM が当てにならないと判明（docs/eval-beat.md）。評価基準を「librosa との一致＋櫛の照合」に変更 |
| 11/2 14:45〜14:50 | 拍連動モードの自己試験（自作曲 05 をヘッドホン→マイクで 60 秒・2400 フレーム・106 拍・テンポ 132→95.8 に収束・late 0） | Claude Code | 計画 11/3「灯体が拍で Pan/Tilt を打つ」の送信側は完成。実機の目視は本人待ち |
