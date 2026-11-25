# secret_scan の抜け道テスト（一時クローンで実施・本物のリポジトリは触らない）。使い方: python tools/test_secret_scan.py
# 偽の鍵はこのファイルに文字列として書かず、実行時に組み立てる（このファイル自体が検査で止まらないように）
import json
import os
import shutil
import subprocess
import sys
import tempfile

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="kh-test-")
R = os.path.join(T, "repo")
FAKE_ANT = "sk-" + "ant-" + "api03-" + "X" * 32
FAKE_GH = "gh" + "p_" + "A" * 40
MAIL = "owner" + "@" + "gmail" + ".com"
PHONE = "09" + "0-12" + "34-5678"
PW = "password=" + "MyPrivate" + "Password123"


def sh(args, cwd=R, inp=None):
    r = subprocess.run(args, cwd=cwd, input=inp, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout + r.stderr).strip()


res = []


def case(name, want, got, note=""):
    res.append((got == want, name, want, got, note[-160:]))


def w(rel, text, enc="utf-8"):
    p = os.path.join(R, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding=enc) as f:
        f.write(text)
    return p


subprocess.run(["git", "clone", "-q", SRC, R], check=True)
for f in ("tools/secret_scan.py", "tools/secret_scan.sh", "tools/install_hooks.py", ".gitignore", ".claude/settings.json", "README.md"):
    os.makedirs(os.path.dirname(os.path.join(R, f)), exist_ok=True)
    shutil.copy(os.path.join(SRC, f), os.path.join(R, f))
code, out = sh([sys.executable, "tools/install_hooks.py"])
case("install_hooks（履歴がきれいなら 0）", 0, code, out)
sh(["git", "add", "-A"])
code, out = sh(["git", "commit", "-q", "--allow-empty", "-m", "test base"])
case("きれいなコミットは通る", 0, code, out)

# A: ステージしてから作業ツリーを消す
p = w("a.py", f'KEY = "{FAKE_ANT}"\n')
sh(["git", "add", "a.py"])
w("a.py", "x = 1\n")
code, out = sh(["git", "commit", "-q", "-m", "A"])
case("A ステージ後に作業ツリーを消しても止まる", 1, code, out)
sh(["git", "reset", "-q", "a.py"]); os.remove(p)
# B: 日本語ファイル名
p = w("設定メモ.txt", f"token = {FAKE_GH}\n")
sh(["git", "add", "-A"]); code, out = sh(["git", "commit", "-q", "-m", "B"])
case("B 日本語ファイル名でも止まる", 1, code, out)
sh(["git", "reset", "-q"]); os.remove(p)
# C: UTF-16
p = w("log16.txt", f"contact {MAIL}\n", enc="utf-16")
sh(["git", "add", "-A"]); code, out = sh(["git", "commit", "-q", "-m", "C"])
case("C UTF-16 でも止まる", 1, code, out)
sh(["git", "reset", "-q"]); os.remove(p)
# D: 不明なバイナリ
p = os.path.join(R, "notes.dat"); open(p, "wb").write(b"\0\0" + MAIL.encode())
sh(["git", "add", "-A"]); code, out = sh(["git", "commit", "-q", "-m", "D"])
case("D 不明なバイナリは止まる", 1, code, out)
sh(["git", "reset", "-q"]); os.remove(p)
# D2: 画像は通る
open(os.path.join(R, "pic.png"), "wb").write(b"\x89PNG\r\n\x1a\n\0\0")
sh(["git", "add", "-A"]); code, out = sh(["git", "commit", "-q", "-m", "D2"])
case("D2 画像バイナリは通る", 0, code, out)
# E: logs/public は追跡される・logs/ 直下は無視
w("logs/public/run1.txt", "t=0.0 rms=-20\n"); w("logs/raw.txt", "x\n")
sh(["git", "add", "-A"]); code, out = sh(["git", "status", "--short"])
case("E logs/public だけ追跡される", True, ("logs/public/run1.txt" in out) and ("logs/raw.txt" not in out), out)
code, out = sh(["git", "commit", "-q", "-m", "E"])
case("E logs/public のきれいなログは通る", 0, code, out)
# F: --range の壊れた sha は止まる
code, out = sh([sys.executable, "tools/secret_scan.py", "--range", "0" * 39 + "1..HEAD"])
case("F git 失敗は exit 2", 2, code, out)
# G: 名義に gmail → --history が止まる（--no-verify で無理やり作る）
w("g.txt", "ok\n"); sh(["git", "add", "-A"])
sh(["git", "-c", "user.email=" + MAIL, "commit", "-q", "--no-verify", "-m", "G"])
code, out = sh([sys.executable, "tools/secret_scan.py", "--history"])
case("G 名義の gmail を --history が止める", 2, code, out)
# G2: 鍵を入れて消した履歴も --range が止める
sh(["git", "reset", "-q", "--hard", "HEAD~1"])
w("h.py", f'K="{FAKE_ANT}"\n'); sh(["git", "add", "-A"]); sh(["git", "commit", "-q", "--no-verify", "-m", "h1"])
w("h.py", "K=None\n"); sh(["git", "add", "-A"]); sh(["git", "commit", "-q", "--no-verify", "-m", "h2"])
code, out = sh([sys.executable, "tools/secret_scan.py", "--range", "HEAD~2..HEAD"])
case("G2 入れて消した鍵も --range が止める", 2, code, out)
sh(["git", "reset", "-q", "--hard", "HEAD~2"])
# K: マージの時に足した中身（2026-11-25）。diff-tree はマージで何も返さないので、-m を付けないと push 時と CI の検査から漏れる
sh(["git", "checkout", "-q", "-b", "side-k"]); w("k_side.txt", "ok\n"); sh(["git", "add", "-A"]); sh(["git", "commit", "-q", "-m", "k side"])
sh(["git", "checkout", "-q", "-"]); w("k_main.txt", "ok\n"); sh(["git", "add", "-A"]); sh(["git", "commit", "-q", "-m", "k main"])
sh(["git", "merge", "-q", "--no-ff", "--no-commit", "side-k"])
w("k_merge.py", f'KEY = "{FAKE_ANT}"\n'); sh(["git", "add", "-A"])
code, out = sh(["git", "commit", "-q", "-m", "K"])
case("K マージの途中で足した鍵は pre-commit が止める", 1, code, out)
sh(["git", "commit", "-q", "--no-verify", "-m", "K"])
code, out = sh(["git", "rev-list", "--parents", "-n", "1", "HEAD"])
case("K の試験コミットは親が 2 つ", 3, len(out.split()), out)
code, out = sh([sys.executable, "tools/secret_scan.py", "--range", "HEAD~1..HEAD"])
case("K2 マージで足した鍵を --range が止める", 2, code, out)
code, out = sh([sys.executable, "tools/secret_scan.py", "--history"])
case("K3 マージで足した鍵を --history が止める", 2, code, out)
sh(["git", "reset", "-q", "--hard", "HEAD~1"]); sh(["git", "branch", "-q", "-D", "side-k"])
# L: 種類が変わったファイル（シンボリックリンク → 普通のファイル）。git の状態は T で、ACMR だけを見ていると漏れる
code, blob = sh(["git", "hash-object", "-w", "--stdin"], inp="target")
sh(["git", "update-index", "--add", "--cacheinfo", f"120000,{blob},lnk"]); sh(["git", "commit", "-q", "-m", "L0 symlink"])
p = w("lnk", f'KEY = "{FAKE_ANT}"\n')
code, blob = sh(["git", "hash-object", "-w", "lnk"])
sh(["git", "update-index", "--cacheinfo", f"100644,{blob},lnk"])
code, out = sh(["git", "diff", "--cached", "--name-status"])
case("L の試験の状態は T", True, out.startswith("T"), out)
code, out = sh(["git", "commit", "-q", "-m", "L"])
case("L 種類が変わったファイルの鍵は pre-commit が止める", 1, code, out)
sh(["git", "commit", "-q", "--no-verify", "-m", "L"])
code, out = sh([sys.executable, "tools/secret_scan.py", "--range", "HEAD~1..HEAD"])
case("L2 種類が変わったファイルの鍵を --range が止める", 2, code, out)
sh(["git", "reset", "-q", "--hard", "HEAD~2"])
if os.path.exists(p):
    os.remove(p)


# H: hook モード
def hook(d):
    return sh([sys.executable, "tools/secret_scan.py", "--hook"], inp=json.dumps(d))


cases = [
    ("H1 Bash --no-verify を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify -m x"}}),
    ("H2 Bash heredoc の鍵を止める", 2, {"tool_name": "Bash", "tool_input": {"command": f"cat > x.py <<'EOF'\nK='{FAKE_ANT}'\nEOF"}}),
    ("H3 Bash のふつうのコマンドは通る", 0, {"tool_name": "Bash", "tool_input": {"command": "python main.py --device 15"}}),
    ("H4 .env への書き込みは通る", 0, {"tool_name": "Write", "tool_input": {"file_path": R + "/.env", "content": f"ANTHROPIC_API_KEY={FAKE_ANT}\n"}}),
    ("H5 リポジトリ外は通る", 0, {"tool_name": "Write", "tool_input": {"file_path": os.path.join(T, "outside.md"), "content": f"mail {MAIL}\n"}}),
    ("H6 Edit の鍵は止める", 2, {"tool_name": "Edit", "tool_input": {"file_path": R + "/x.py", "old_string": "a", "new_string": f'key = "{FAKE_ANT}"'}}),
    ("H7 .md の allow 印でメールの例は通る", 0, {"tool_name": "Write", "tool_input": {"file_path": R + "/README.md", "content": f"例: {MAIL}  secret-scan: allow\n"}}),
    ("H8 .py の allow 印は効かない", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/x.py", "content": f"k='{FAKE_ANT}'  # secret-scan: allow\n"}}),
    ("H9 電話番号を止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/x.md", "content": f"連絡 {PHONE}\n"}}),
    ("H10 引用符なし password を止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/c.ini", "content": PW + "\n"}}),
    ("H11 os.environ の代入は通る", 0, {"tool_name": "Write", "tool_input": {"file_path": R + "/c.py", "content": 'api_key = os.environ["ANTHROPIC_API_KEY"]\n'}}),
    ("H12 壊れた JSON は止める", 2, None),
    ("H13 git commit -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -n -m x"}}),
    ("H14 core.hooksPath を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git -c core.hooksPath=/dev/null push"}}),
    ("H15 git@github.com の URL は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git remote set-url origin git@github.com:u/r.git"}}),
    ("H16 大文字の .PEM は止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/cert.PEM", "content": "x\n"}}),
    ("H17 .md の allow 印でも本物の鍵の形は止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/README.md", "content": f"{FAKE_ANT} secret-scan: allow\n"}}),
    ("H18 .md の allow 印で電話番号の例は通る", 0, {"tool_name": "Write", "tool_input": {"file_path": R + "/README.md", "content": f"例 {PHONE} secret-scan: allow\n"}}),
    ("H19 NotebookEdit の鍵を止める", 2, {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": R + "/a.ipynb", "new_source": f"k='{FAKE_ANT}'"}}),
    ("H20 コード中の 123-4567 は通る（郵便番号の誤検知）", 0, {"tool_name": "Write", "tool_input": {"file_path": R + "/x.py", "content": "RANGE = '123-4567'\n"}}),
    ("H21 住所つきの郵便番号は止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/x.md", "content": "123-" + "4567 東京都千代田区\n"}}),
    ("H22 ハイフンなし携帯番号を止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/x.md", "content": "tel " + "0901" + "2345678\n"}}),
    ("H23 行末コメント付きの password= を止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/c.ini", "content": PW + " # memo\n"}}),
    # 2026-11-25: フックを飛ばす書き方の抜け（省略形・束ねた短いオプション・全体オプション・小文字の設定名・行の継続・リダイレクト）と、止めてはいけない形
    ("H24 --no-verify の省略形を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit --no-veri -m x"}}),
    ("H25 push の --no-verify の省略形を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git push --no-verif origin main"}}),
    ("H26 束ねた -nm を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -nm x"}}),
    ("H27 束ねた -nm に数字が続いても止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -nm123"}}),
    ("H28 束ねた -an を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -an -m x"}}),
    ("H29 束ねた -sn を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -sn -m x"}}),
    ("H30 git -C . commit -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git -C . commit -n -m x"}}),
    ("H31 git -c 設定 commit -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git -c user.name=x commit -n -m x"}}),
    ("H32 引用符と空白のある設定値の後ろでも止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git -c user.name=\"a b\" commit -n -m x"}}),
    ("H33 git --no-pager commit -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git --no-pager commit -n -m x"}}),
    ("H34 git --git-dir=.git commit -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git --git-dir=.git commit -n -m x"}}),
    ("H35 小文字の core.hookspath を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git -c core.hookspath=/dev/null commit -m x"}}),
    ("H36 git config での core.HooksPath を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git config core.HooksPath /dev/null"}}),
    ("H37 行の継続の後ろの -n を止める（字下げあり）", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m x \\\n  -n"}}),
    ("H38 行の継続の後ろの -n を止める（字下げなし）", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m x \\\n-n"}}),
    ("H39 git.exe commit -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git.exe commit -n -m x"}}),
    ("H40 大文字の GIT.EXE commit -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "GIT.EXE commit -n -m x"}}),
    ("H41 リダイレクトの後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m x 2>&1 -n"}}),
    ("H42 入力のリダイレクト <&0 の後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m x <&0 -n"}}),
    ("H43 上書きのリダイレクト >| の後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m x >| out -n"}}),
    ("H44 語の途中で継続した --no-verify を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit --no-\\\nverify -m x"}}),
    ("H45 語の途中で継続した -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -\\\nn -m x"}}),
    ("H46 語の途中で継続した commit を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git com\\\nmit -n -m x"}}),
    ("H47 メッセージの後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"fix -nothing\" -n"}}),
    ("H48 メッセージが -- でも後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m -- -n"}}),
    ("H49 heredoc のメッセージを閉じた後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(cat <<'EOF'\nfix: x\n\n- item\nEOF\n)\" -n"}}),
    ("H50 複数行のメッセージを閉じた後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"title\n\nbody\" -n"}}),
    ("H51 逃がした引用符のある設定値の後ろでも止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git -c user.name=\"a\\\" b\" commit -n -m x"}}),
    ("H52 $( ) の中に別の引用符があっても後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(printf %s 'a\"b')\" -n -m \"z\""}}),
    ("H53 $'…' の後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m $'it\\'s' -n -m 'z'"}}),
    ("H54 引用符の中の git commit の後ろにある本物の -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "GIT_EDITOR=\"git commit\" git commit -n -m \"x\""}}),
    ("H55 heredoc の本文に引用符や ) の行があっても、閉じた後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(cat <<'EOF'\nFix \"quote\n) done\nEOF\n)\" -n"}}),
    ("H56 続けて打った 2 つ目の git -C . commit -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m x && git -C . commit -n -m y"}}),
    ("H57 heredoc の後ろに空の行があっても、閉じた後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m $(cat <<EOF\nmsg\nEOF\n\n) -n"}}),
    ("H58 算術の << を heredoc と取り違えず、複数行のメッセージの後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"v$((1<<3))\nbody\" -n"}}),
    ("H59 閉じた $( ) の後ろの << を heredoc と取り違えず、後ろの -n を止める", 2, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(date) <<EOF\nbody\" -n"}}),
    ("H60 続けて打つ git log -n 5 は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git add -A && git commit -m \"msg\" && git log --oneline -n 5"}}),
    ("H61 パイプの先の tail -n は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -m x 2>&1 | tail -n 5"}}),
    ("H62 git log --grep=commit -n 3 は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git log --grep=commit -n 3"}}),
    ("H63 git -C commit log -n 3 は通る（commit という名のフォルダ）", 0, {"tool_name": "Bash", "tool_input": {"command": "git -C commit log -n 3"}}),
    ("H64 git stash push -m n は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git stash push -m n"}}),
    ("H65 git push -u origin main は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git push -u origin main"}}),
    ("H66 git commit --amend --no-edit は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit --amend --no-edit"}}),
    ("H67 git commit -am は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -am \"x\""}}),
    ("H68 git commit -uno は通る（値の中の n）", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -uno -m x"}}),
    ("H69 git commit -mdone は通る（値の中の n）", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -mdone"}}),
    ("H70 git commit -Fnotes.txt は通る（値の中の n）", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -Fnotes.txt"}}),
    ("H71 git -C . status は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git -C . status --short"}}),
    ("H72 メッセージの中のハイフンの語 -only は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"add -only option\""}}),
    ("H73 メッセージの中のハイフンの語 -noprofile は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'Use -noprofile in PowerShell'"}}),
    ("H74 hookspath を探すだけの grep は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "grep -rn hookspath tools/ && git status"}}),
    ("H75 hookspath を探すだけの git grep は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git grep -i hookspath"}}),
    ("H76 heredoc のメッセージで後ろに何も付けない形は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(cat <<'EOF'\nfix: x\n\n- item one\n- item two\nEOF\n)\""}}),
    ("H77 heredoc のメッセージの後ろで続けて打つ git log -n 5 は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(cat <<'EOF'\nfix: x\nEOF\n)\" && git log --oneline -n 5"}}),
    ("H78 heredoc の本文に引用符と -n があっても通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(cat <<'EOF'\nMention \"dry run\" as -n in docs\nEOF\n)\""}}),
    ("H79 heredoc の本文に ) で始まる行があっても通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(cat <<'EOF'\nWrap call (see #12\n) and -name option\nEOF\n)\""}}),
    ("H80 コミット行の注釈に引用符があっても次の行は通る", 0, {"tool_name": "Bash", "tool_input": {"command": "git commit -am wip  # don't push yet\ngrep 'foo -n' file"}}),
]
# I: コミット時点の名義（gmail）を pre-commit が止める
w("i.txt", "ok\n"); sh(["git", "add", "-A"])
code, out = sh(["git", "-c", "user.email=" + MAIL, "commit", "-q", "-m", "I"])
case("I 名義が gmail のコミットは pre-commit で止まる", 1, code, out)
sh(["git", "reset", "-q"])
# J: 注釈つきタグの本文に鍵 → --object が止める
sh(["git", "tag", "-a", "v0-test", "-m", "note " + FAKE_GH])
code, out = sh([sys.executable, "tools/secret_scan.py", "--object", "v0-test"])
case("J タグ本文の鍵を --object が止める", 2, code, out)
code, out = sh([sys.executable, "tools/secret_scan.py", "--history"])
case("J2 タグ本文の鍵を --history が止める", 2, code, out)
sh(["git", "tag", "-d", "v0-test"])
for name, want, d in cases:
    if d is None:
        code, out = sh([sys.executable, "tools/secret_scan.py", "--hook"], inp="{not json")
    else:
        code, out = hook(d)
    case(name, want, code, out)

print(f"tmp={T}")
bad = 0
for ok, name, want, got, note in res:
    print(("OK  " if ok else "NG  ") + name + f"  (want {want} got {got})" + ("" if ok else "\n     " + note.replace("\n", " / ")))
    bad += (not ok)
print("NG =", bad)
shutil.rmtree(T, ignore_errors=True)
sys.exit(1 if bad else 0)
