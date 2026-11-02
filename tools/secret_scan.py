# 秘密値・私的情報の漏えい検査（kiku-hikari）
# 使い方:
#   python tools/secret_scan.py --staged          # git のステージ済みファイル（pre-commit）
#   python tools/secret_scan.py --range A..B      # push 対象コミットの変更ファイル（pre-push）
#   python tools/secret_scan.py --all             # 追跡中の全ファイル
#   python tools/secret_scan.py --hook            # Claude Code PreToolUse（stdin の JSON から Write/Edit の内容を検査）
#   python tools/secret_scan.py <path>...         # 任意のファイル
# 見つかったら理由を stderr に出して exit 2（git hook・Claude Code hook ともに「止める」の意味）。
# 行末に「secret-scan: allow」と書いた行は見逃す（例示用）。
# リポジトリ外の拒否語リスト ~/.kiku-hikari-denylist.txt（1行1語・個人のメール等）があれば、それも検査する。
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = [
    ("Anthropic API キー", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI 風キー", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}")),
    ("GitHub トークン", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("AWS アクセスキー", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API キー", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}")),
    ("Slack トークン", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("Discord Webhook", re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[\w\-]+")),
    ("秘密鍵ブロック", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |)PRIVATE KEY")),
    ("URL 埋め込み認証", re.compile(r"https?://[^\s/:@]+:[^\s@/]+@[^\s/]+")),
    ("Authorization ヘッダの実値", re.compile(r"(?i)(?:x-api-key|authorization)\s*[:=]\s*['\"]?(?:bearer\s+)?[A-Za-z0-9_\-\.]{16,}")),
    ("鍵らしき代入", re.compile(r"(?i)\b(?:api[_\-]?key|secret[_\-]?key|access[_\-]?token|auth[_\-]?token|password|passwd)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
    ("メールアドレス（公開名義は noreply のみ）", re.compile(r"[A-Za-z0-9._%+\-]+@(?!users\.noreply\.github\.com)(?:gmail|yahoo|outlook|icloud|hotmail)\.[a-z]{2,}", re.I)),
]
FORBIDDEN_PATHS = [
    re.compile(r"(^|/)\.env(\..*)?$"),
    re.compile(r"\.(pem|key|p12|pfx|crt|token)$"),
    re.compile(r"(^|/)id_(rsa|ed25519)"),
    re.compile(r"(^|/)\.(netrc|npmrc|pypirc)$"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"\.py[cod]$"),
    re.compile(r"(^|/)\.(pytest|mypy|ruff)_cache/"),
    re.compile(r"(^|/)\.ipynb_checkpoints/"),
    re.compile(r"(^|/)\.claude/settings\.local\.json$"),
    re.compile(r"(^|/)\.claude/\.credentials"),
    re.compile(r"(^|/)(secrets|credentials)/"),
    re.compile(r"\.(sqlite|db)$"),
]
ALLOW_PATH = re.compile(r"(^|/)\.env\.example$")


def denylist():
    p = os.path.join(os.path.expanduser("~"), ".kiku-hikari-denylist.txt")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8", errors="replace") as f:
        return [w.strip() for w in f if w.strip() and not w.startswith("#")]


def scan_text(text, label):
    hits = []
    words = denylist()
    for ln, line in enumerate(text.splitlines(), 1):
        if "secret-scan: allow" in line:
            continue
        for name, rx in PATTERNS:
            if rx.search(line):
                hits.append(f"{label}:{ln}: {name}")
        low = line.lower()
        for w in words:
            if w.lower() in low:
                hits.append(f"{label}:{ln}: 拒否語（~/.kiku-hikari-denylist.txt）")
    return hits


def scan_path(rel):
    rel = rel.replace("\\", "/")
    hits = []
    if not ALLOW_PATH.search(rel) and any(rx.search(rel) for rx in FORBIDDEN_PATHS):
        hits.append(f"{rel}: 入れてはいけない種類のファイル（.gitignore の対象）")
    p = os.path.join(ROOT, rel)
    if os.path.isfile(p):
        with open(p, "rb") as f:
            raw = f.read()
        if b"\0" in raw[:8000]:
            return hits  # バイナリは中身を見ない
        hits += scan_text(raw.decode("utf-8", errors="replace"), rel)
    return hits


def git_files(args):
    out = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return [l for l in out.stdout.splitlines() if l.strip()]


def hook_mode():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    ti = data.get("tool_input", {}) or {}
    path = (ti.get("file_path") or "").replace("\\", "/")
    hits = []
    if path:
        rel = os.path.relpath(path, ROOT).replace("\\", "/") if os.path.isabs(path) else path
        if not rel.startswith("..") and not ALLOW_PATH.search(rel) and any(rx.search(rel) for rx in FORBIDDEN_PATHS):
            hits.append(f"{rel}: 入れてはいけない種類のファイルへの書き込み")
    for key in ("content", "new_string"):
        if ti.get(key):
            hits += scan_text(ti[key], path or key)
    for e in ti.get("edits", []) or []:
        if e.get("new_string"):
            hits += scan_text(e["new_string"], path or "edit")
    if hits:
        print("secret_scan: 書き込みを止めました（秘密値・私的情報の疑い）\n" + "\n".join(hits[:20]), file=sys.stderr)
        return 2
    return 0


def main(argv):
    if argv[:1] == ["--hook"]:
        return hook_mode()
    if argv[:1] == ["--staged"]:
        files = git_files(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    elif argv[:1] == ["--range"] and len(argv) > 1:
        files = git_files(["diff", "--name-only", "--diff-filter=ACMR", argv[1]])
    elif argv[:1] == ["--all"]:
        files = git_files(["ls-files"])
    else:
        files = argv
    hits = []
    for f in files:
        hits += scan_path(f)
    if hits:
        print("secret_scan: 止めました（秘密値・私的情報の疑い）。直すか、例示なら行末に secret-scan: allow を付ける", file=sys.stderr)
        print("\n".join(hits[:50]), file=sys.stderr)
        return 2
    print(f"secret_scan: OK（{len(files)} ファイル）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
