# kiku-hikari（聴く・光）— 曲を聴いて、ムービングライトが光る

**Built with Claude: Japan 2026**（Cerebral Valley × Anthropic・2026-11-02 12:30 〜 11-08 20:00）の提出作品。制作: I LLC。
このリポジトリの内容はすべてハッカソン期間中に Claude Code で新規に制作した（下の「11/2 前に行った準備」参照）。

> 「聴く」と「光」は、ふだん一緒に使われない言葉です。小さな会場では、照明は拍で点滅するだけになりがちです。
> このソフトは、演奏中の曲を聴いて **曲の構造を先読みし**、サビの頭でちょうど開く・静かな場面は青く沈める、といった照明オペレーターの判断を Claude に肩代わりさせます。

## 誰のためか
公民館・学校・小さなライブハウスなど、**照明オペレーターがいない小規模の現場**。作者は公共ホールの舞台設備（音響・映像・照明）を設計する側の人間で、「拍で点滅するだけ」の現状を何年も見てきました。

## Claude の役割（製品の中）
Claude API（`claude-opus-5-5`・`kiku_hikari/claude_worker.py`）が約 4 秒ごとに、直近 30 秒の音の要約（音量・明るさ・オンセット密度・テンポ・これまでの区間）を受け取り、**Enum 固定の JSON** で返します:
次の境界まで何小節（既定。小節頭で開く）／いまの区間と次の区間／開き方（hard_cut・ramp・bloom・blackout_then_burst）／色と次の色／動きの語彙（hold・sweep・chase・bounce）／溜め（dim_hold・slow_close・freeze）／感情 2 軸（快不快・覚醒度）／浮かぶ情景を一語／確信度／理由。
拍・位相・数値・安全は Python が担当し、Claude は秒単位の判断だけをします（「Claude が流れを止めない」設計）。

## 他モデルは壁打ちと監査にのみ使用
製品コードを書いたのは Claude Code だけです。OpenAI Codex と Gemini は「漏えい防止の仕組みの監査」に、Gemini は知識ファイル v2 の材料集め（公式ライブ映像を時刻つきで書き出す。URL を渡すだけで、動画はダウンロードしない）にも使いました。ローカル LLM は期間前の話題出しに使いました。照明の判断をするのは製品の中の Claude だけです。何にどう使ったかは `docs/ai-usage-log.md` に時刻つきで残しています。

## 11/2 前に行った準備（リポジトリの外・成果物ではない）
計画書・勝ち筋の整理・分野の調査（演出照明・拍追従・楽曲構造・Art-Net・共感覚）・自作の試験曲 10 曲（生成音源・非公開・入力素材としてのみ使用）。運営 FAQ「事前の計画・構想は認めるが、リポジトリの外で行う」に従い、ここには入れていません。持ち込みデータは試験曲（非公開）だけです。

## Claude Code で何を作ったか（この節が最長）
- **2 つの輪**: 速い輪（Python・40 Hz・`main.py`）と遅い輪（Claude・約 4 秒・`claude_worker.py`）。遅い輪は別スレッド・同時 1 件・世代番号つきで、古い返答は捨てる。失敗やレート制限は「返答なし」として速い輪を止めない
- **自前の拍追従**（`beat.py`）: Windows の Python 3.12 に aubio・madmom が入らないため、対数スペクトルのフラックス→自己相関＋倍音加算→櫛で位相合わせ、を numpy だけで書いた。評価は `tools/beat_eval.py`（結果 `docs/eval-beat.md`。生成時に指定した BPM は当てにならないと判明）
- **先読みエンジン**（`engine.py`）: Claude の予測境界を「直後の小節頭」にクオンタイズして開く。溜めは境界の 1 小節前から。予測が外れても **音響変化検出**（`change.py`・CUSUM）が後から境界を見つけて開く（救済）。位相リセットはしない
- **灯体と安全**（`fixtures.py`）: ADJ Stinger Spot 11ch の表（取説の画像ページを Claude Code が読んで転記）、Pan/Tilt のスルーレート制限、ストロボ上限、明るさ上限
- **Art-Net**（`artnet.py`）: ArtPoll で EtherMX を探し、ArtDmx をユニキャスト。標準ライブラリのみ
- **ログ**（`runlog.py`）: 拍・テンポ・位相・Claude の要求/応答・DMX・遅れを 1 本の JSONL に時刻つきで。動画の字幕とブラインド判定の照合はここから作る
- **知識ファイル**（`knowledge/lighting_knowledge_v2.json`・既定）: 照明家の判断を「区間×感情×色・動き・溜め」の規則 30 本に。v1（`lighting_knowledge.json`・25 本）は研究の原文（Palmer 2013 の音楽→色、先読みフェードの特許、点滅の安全基準）から Claude Code のサブエージェントが下書きした。v2 では、公式ライブ映像 100 本を Gemini に時刻つきで書き出させ、それを Claude が集計して規則を差し替えた。例: サビは白が主役、1 曲に 4 色、pre_chorus はサビの約 16 秒前に色を変える、ブレイクで暗転するのは 3 割だけ、演歌はサビで白を足さず 2 色で幕と背景で山を作る。各規則の出典は動画の URL（時刻つき）。差し替えは `tools/import_knowledge.py` で上書きするだけ。system の固定部に置いてプロンプトキャッシュに乗せる（実測: 毎回約 17,800 トークンがキャッシュ読み）
- **疑似モード**（`--file` と `--viz`）: 灯体もマイクも無い人が WAV を入れて画面の仮想灯体で見られる
- **公開リポジトリの守り**（`tools/secret_scan.py`・`.claude/settings.json`・GitHub Actions）: Claude Code の PreToolUse フック／git の pre-commit・pre-push／CI の 3 層で鍵・個人情報を止める。敵対レビュア 2 体・Codex・Gemini の監査で見つかった抜け道 30 件超を反映し、`tools/test_secret_scan.py`（一時クローンで 39 ケース）で機械確認
- **評価を先に**（`docs/eval-blind.md`）: 第三者 3 人のブラインド判定（同じ曲で ① 拍連動／② ルール表／③ Claude を A/B/C に匿名化）

## いま動くもの
```
py -3.12 -m kiku_hikari.main --mode claude --file song.wav --viz --no-artnet   # 灯体なし: WAV→画面の仮想灯体
py -3.12 -m kiku_hikari.main --mode claude --seconds 90                         # 灯体あり: マイク→Art-Net
py -3.12 -m kiku_hikari.main --mode beat   --seconds 60                         # ① 拍連動のみ（--bpm 120 で固定テンポ・Space で拍頭合わせ）
py -3.12 -m kiku_hikari.main --mode rules  --seconds 60                         # ② ルール表（Claude なし）
py -3.12 -m kiku_hikari.main --mode claude --play song.wav                      # 自己試験: ヘッドホン→マイクで聴かせる
py -3.12 -m kiku_hikari.artnet                                                  # Art-Net ノードを探す
py -3.12 tools/beat_eval.py <wav のフォルダ>                                     # 拍追従の評価
```
- 実測（11/2・自作曲 03 を 80 秒・Claude Opus 5.5・effort low）: 往復 2.3〜6.4 秒・18 応答・late 0〜2・境界の開き 3 回（予測 1・救済 2）。ログは `logs/public/`
- 評価（11/3・自作曲 4 曲 × 3 回・作者が耳で打った切れ目を正解に・±2 秒・`docs/eval-beat.md`）: 既定（知識 v2・小節数で先読み・色 p2）の F は、区間の境界で 0.30、照明の変わり目で 0.37（Claude を使わない救済だけの場合は 0.06）。間に合った開き 78%。色は 1 曲平均 3.6 種・11.3 回の切り替え（青 36%）。往復は中央値 2.9 秒。区間の境界を先読みできているかは、まだ偶然と区別できない
- 機材の実測は `docs/hardware-notes.md`

## セットアップ（審査員の方へ）
1. Python 3.12（Windows で確認。`py -3.12`）。`pip install numpy sounddevice soundfile pydantic anthropic`
2. `.env.example` をコピーして `.env` を作り、`ANTHROPIC_API_KEY=` に鍵を入れる（`.env` は .gitignore 済み）
3. 48 kHz の WAV を 1 本用意して `py -3.12 -m kiku_hikari.main --mode claude --file song.wav --viz --no-artnet --seconds 90`
   - 画面に仮想灯体が出て、下に拍・テンポ・Claude の判断（区間・次の区間・あと何秒・溜め・情景一語・理由）が流れます
   - 灯体がある場合: EtherMX 等の Art-Net ノードを同じ LAN に置き、Stinger Spot を 11ch・アドレス 1 にして `--no-artnet` を外す
4. 鍵が無い場合は `--mode beat` か `--mode rules`（Claude なし）で動きます

## 秘密値の扱い（公開リポジトリなので最初に決めた）
- 鍵は `.env`（.gitignore 済み）か環境変数 `ANTHROPIC_API_KEY` からだけ読む。雛形は `.env.example`。説明用のメールは example.com、鍵の例は `sk-ant-...` のように短く書く
- `tools/secret_scan.py` が「git に実際に入る中身」（ステージ済みの blob・コミットの blob・名義・本文）を検査する。鍵・トークン・JWT・秘密鍵・個人メール・電話番号・住所つき郵便番号・鍵らしき代入・入れてはいけない種類のファイル（.env・*.pem・__pycache__・logs/ の生データ等・大文字小文字を問わない）・不明なバイナリ・コミットとタグの名義と本文。壊れた時は止める側に倒す。例示の見逃し（.md の行末 `secret-scan: allow`）は本物の鍵の形と拒否語には効かない
  - 1層目 Claude Code の PreToolUse フック（`.claude/settings.json`・Write/Edit/NotebookEdit/Bash の内容を実行前に検査。`--no-verify`・`-n`・force push・core.hooksPath は permissions.deny で禁止）
  - 2層目 git の pre-commit / pre-push（クローン直後に `python tools/install_hooks.py`。コミット名義も noreply アドレスに設定し、全履歴を1回検査する）
  - 3層目 GitHub Actions（`.github/workflows/secret-scan.yml`・push ごとに全履歴）と GitHub の secret scanning / push protection
- 作者の本名・住所・社名などの拒否語はリポジトリ外 `~/.kiku-hikari-denylist.txt` に置く（無い機械では警告が出る）
- 実行ログは `logs/` に出し、公開するものだけ `logs/public/` に置く（そこだけ追跡され、検査を通る）
- 抜け道の試験: `python tools/test_secret_scan.py`（一時クローンで 39 ケース。敵対レビュー 2 体・Codex・Gemini の監査で見つかった抜け道を全部含む）

## 提出に向けて残っていること（11/2 時点）
- 実機の目視（灯体が Python から光るか・Pan/Tilt の最大速度の実測→`Safety` の値）
- 3 曲でのブラインド判定（`docs/eval-blind.md`）と的中率の集計
- 3 分の動画（同じ曲で ①②③ を並べる・ログから字幕）
- README の英語付記
