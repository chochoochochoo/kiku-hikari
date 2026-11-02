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
code, out = sh(["git", "commit", "-q", "-m", "test base"])
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
    ("H7 .md の allow 印は通る", 0, {"tool_name": "Write", "tool_input": {"file_path": R + "/README.md", "content": f"例: {FAKE_ANT}  secret-scan: allow\n"}}),
    ("H8 .py の allow 印は効かない", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/x.py", "content": f"k='{FAKE_ANT}'  # secret-scan: allow\n"}}),
    ("H9 電話番号を止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/x.md", "content": f"連絡 {PHONE}\n"}}),
    ("H10 引用符なし password を止める", 2, {"tool_name": "Write", "tool_input": {"file_path": R + "/c.ini", "content": PW + "\n"}}),
    ("H11 os.environ の代入は通る", 0, {"tool_name": "Write", "tool_input": {"file_path": R + "/c.py", "content": 'api_key = os.environ["ANTHROPIC_API_KEY"]\n'}}),
    ("H12 壊れた JSON は止める", 2, None),
]
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
