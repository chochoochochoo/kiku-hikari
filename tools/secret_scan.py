# 秘密値・私的情報の漏えい検査（kiku-hikari）
# 検査するのは「git に実際に入る中身」（ステージ済み blob・コミット内の blob・コミットの名義と本文）。作業フォルダの今の中身ではない。
# 使い方:
#   python tools/secret_scan.py --staged          # ステージ済みの中身（pre-commit）
#   python tools/secret_scan.py --range A..B      # push 対象コミットの全 blob と名義・本文（pre-push）
#   python tools/secret_scan.py --history         # 全履歴とタグ（CI・クローン直後の確認）
#   python tools/secret_scan.py --object SHA      # タグや単体オブジェクト（pre-push でタグを送る時）
#   python tools/secret_scan.py --all             # 追跡中の全ファイル（HEAD の中身）
#   python tools/secret_scan.py --hook            # Claude Code PreToolUse（stdin の JSON。Write/Edit/MultiEdit/Bash）
#   python tools/secret_scan.py <path>...         # 任意のファイル（作業フォルダ）
# 見つかったら理由を stderr に出して exit 2（git hook・Claude Code hook ともに「止める」の意味）。
# 壊れた時も止める側に倒す（git の失敗・JSON の失敗・例外 → exit 2）。
# 例示の見逃し: .md と .env.example の行末に「secret-scan: allow」がある行だけ。コードやログでは効かない。
# リポジトリ外の拒否語リスト ~/.kiku-hikari-denylist.txt（1行1語・個人のメール・本名など）があれば、それも検査する。
import json
import os
import re
import subprocess
import sys

for s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = [
    ("Anthropic API キー", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI 風キー", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}")),
    ("GitHub トークン", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("AWS アクセスキー", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API キー", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}")),
    ("Slack トークン", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}")),
    ("Discord Webhook", re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[\w\-]+")),
    ("秘密鍵ブロック", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |)PRIVATE KEY")),
    ("URL 埋め込み認証", re.compile(r"https?://[^\s/:@]+:[^\s@/]+@[^\s/]+")),
    ("Authorization ヘッダの実値", re.compile(r"(?i)(?:x-api-key|authorization)\s*[:=]\s*['\"]?(?:bearer\s+)?[A-Za-z0-9_\-\.]{16,}")),
    ("鍵らしき代入（引用符つき）", re.compile(r"(?i)\b[\w\-]*(?:api[_\-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"](?=\S*\d)[^'\"\s]{8,}['\"]")),
    ("鍵らしき代入（引用符なし・数字を含む）", re.compile(r"(?i)\b[\w\-]*(?:api[_\-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*(?![\"'$({\[])(?=\S*\d)[A-Za-z0-9!#%&*+./:=?@^_~\-]{8,}")),
    ("電話番号", re.compile(r"(?<![\d\-])(?:0\d{1,4}-\d{1,4}-\d{4}|0[789]0\d{8}|\+81[\-\s]?\d{1,4}[\-\s]?\d{1,4}[\-\s]?\d{4})(?![\d\-])")),
    ("郵便番号", re.compile(r"〒\s?\d{3}-?\d{4}|(?<![\d\-])\d{3}-\d{4}(?![\d\-])(?=.*[都道府県市区町村郡])")),
    ("メールアドレス（公開名義は noreply のみ）", re.compile(r"(?i)[A-Za-z0-9._%+\-]+@(?!users\.noreply\.github\.com|github\.com|anthropic\.com|example\.)[A-Za-z0-9.\-]+\.[a-z]{2,}")),
]
FORBIDDEN_PATHS = [
    re.compile(r"(^|/)\.env(\..*)?$"),
    re.compile(r"\.(pem|key|p12|pfx|crt|token|raw|coverage|sqlite|db)$"),
    re.compile(r"(^|/)\.coverage"),
    re.compile(r"(^|/)id_(rsa|ed25519)"),
    re.compile(r"(^|/)\.(netrc|npmrc|pypirc)$"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"\.py[cod]$"),
    re.compile(r"(^|/)\.(pytest|mypy|ruff)_cache/"),
    re.compile(r"(^|/)\.(hypothesis|ipynb_checkpoints)/"),
    re.compile(r"(^|/)\.claude/settings\.local\.json$"),
    re.compile(r"(^|/)\.claude/\.credentials"),
    re.compile(r"(^|/)(secrets|credentials)/"),
    re.compile(r"(^|/)(credentials|token)[^/]*\.json$"),
    re.compile(r"^logs/(?!public/)"),
]
HARD = {"Anthropic API キー", "OpenAI 風キー", "GitHub トークン", "AWS アクセスキー", "Google API キー", "Slack トークン", "JWT", "Discord Webhook", "秘密鍵ブロック", "URL 埋め込み認証"}
ALLOW_PATH = re.compile(r"(^|/)\.env\.example$")
ALLOW_MARK_EXT = (".md", ".env.example")
BINARY_OK_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".wav", ".mp3", ".flac", ".ogg", ".mp4", ".woff", ".woff2", ".ttf", ".otf")
DENY_PATH = os.path.join(os.path.expanduser("~"), ".kiku-hikari-denylist.txt")


def denylist():
    if not os.path.isfile(DENY_PATH):
        return None
    with open(DENY_PATH, encoding="utf-8-sig", errors="replace") as f:
        return [w.strip() for w in f if w.strip() and not w.startswith("#")]


DENY = denylist()


def decode(raw):
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def scan_text(text, label, hard_only=False):
    hits = []
    allow_ok = label.lower().endswith(ALLOW_MARK_EXT)
    for ln, line in enumerate(text.splitlines(), 1):
        allowed = allow_ok and "secret-scan: allow" in line  # 例示の行: 本物の鍵の形と拒否語だけは見る
        for name, rx in PATTERNS:
            if (allowed or hard_only) and name not in HARD:
                continue
            if rx.search(line):
                hits.append(f"{label}:{ln}: {name}")
        low = line.lower()
        for w in DENY or []:
            if w.lower() in low:
                hits.append(f"{label}:{ln}: 拒否語（~/.kiku-hikari-denylist.txt）")
    return hits


def scan_blob(rel, raw):
    rel = rel.replace("\\", "/")
    hits = []
    low = rel.lower()
    if not ALLOW_PATH.search(low) and any(rx.search(low) for rx in FORBIDDEN_PATHS):
        hits.append(f"{rel}: 入れてはいけない種類のファイル")
    if raw is None:
        return hits
    if b"\0" in raw[:8000] and not (raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff")):
        if not low.endswith(BINARY_OK_EXT):
            hits.append(f"{rel}: 不明なバイナリ（中身を検査できない。画像・音声以外のバイナリは入れない）")
            return hits
        return hits + scan_text(raw.decode("latin-1"), rel, hard_only=True)  # 画像・音声のメタデータに鍵が無いか
    return hits + scan_text(decode(raw), rel)


def git(args, binary=False):
    r = subprocess.run(["git", "-c", "core.quotepath=off"] + args, cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        print("secret_scan: git が失敗したので止めます: git " + " ".join(args) + "\n" + r.stderr.decode("utf-8", "replace"), file=sys.stderr)
        sys.exit(2)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def zlist(args):
    return [p for p in git(args + ["-z"]).split("\0") if p]


def scan_commit_meta(sha):
    meta = git(["log", "-1", "--format=%an%n%ae%n%cn%n%ce%n%s%n%b", sha])
    return scan_text(meta, f"commit {sha[:8]} の名義・本文")


def scan_object(sha):
    """pre-push でタグを送る時などに、そのオブジェクト（tag なら本文と tagger、commit なら通常検査）を見る"""
    typ = git(["cat-file", "-t", sha]).strip()
    if typ == "tag":
        hits = scan_text(git(["cat-file", "-p", sha]), f"tag {sha[:8]}")
        target = git(["rev-list", "-n", "1", sha]).strip()
        h2, _ = scan_commits([target])
        return hits + h2, 1
    if typ == "commit":
        return scan_commits([sha])
    return scan_blob(sha, git(["cat-file", "-p", sha], binary=True)), 1


def scan_identity():
    """コミットしようとしている名義（git config の user.name/email）"""
    ident = git(["var", "GIT_AUTHOR_IDENT"]) + git(["var", "GIT_COMMITTER_IDENT"])
    return scan_text(ident, "コミットの名義（git config user.email）")


def scan_commits(revs):
    hits = []
    n = 0
    for sha in revs:
        hits += scan_commit_meta(sha)
        for rel in zlist(["diff-tree", "-r", "--no-commit-id", "--name-only", "--diff-filter=ACMR", "--root", sha]):
            n += 1
            hits += scan_blob(rel, git(["show", f"{sha}:{rel}"], binary=True))
    return hits, n


def hook_mode():
    data = json.load(sys.stdin)
    ti = data.get("tool_input", {}) or {}
    tool = data.get("tool_name", "")
    hits = []
    if tool == "Bash":
        cmd = ti.get("command") or ""
        if re.search(r"--no-verify|--no-gpg-sign|hooksPath|\bgit\s+(?:commit|push)\b[^|;&\n]*\s-[a-zA-Z]*n\b", cmd):
            hits.append("Bash: --no-verify / -n / core.hooksPath は使わない（秘密値検査を飛ばす）")
        if re.search(r"git\s+push\b.*(\s-f\b|--force)", cmd):
            hits.append("Bash: force push は使わない（push 前の検査範囲が壊れる）")
        hits += scan_text(cmd, "Bash コマンド")
    else:
        path = (ti.get("file_path") or ti.get("notebook_path") or "").replace("\\", "/")
        rel = path
        if path and os.path.isabs(path):
            try:
                rel = os.path.relpath(path, ROOT).replace("\\", "/")
            except ValueError:
                rel = ".."  # 別ドライブ＝リポジトリ外
        if rel.startswith(".."):
            return 0  # リポジトリ外（台帳・メモリ）は対象外
        if re.search(r"(^|/)\.env$", rel):
            return 0  # 鍵の置き場所そのもの（.gitignore 済み）
        if not ALLOW_PATH.search(rel.lower()) and any(rx.search(rel.lower()) for rx in FORBIDDEN_PATHS):
            hits.append(f"{rel}: 入れてはいけない種類のファイルへの書き込み")
        for key in ("content", "new_string", "new_source"):
            if ti.get(key):
                hits += scan_text(ti[key], rel or key)
        for e in ti.get("edits", []) or []:
            if e.get("new_string"):
                hits += scan_text(e["new_string"], rel or "edit")
    if hits:
        print("secret_scan: 止めました（秘密値・私的情報の疑い）。鍵は .env か環境変数へ。例示なら .md の行末に secret-scan: allow\n" + "\n".join(hits[:20]), file=sys.stderr)
        return 2
    return 0


def main(argv):
    if argv[:1] == ["--hook"]:
        try:
            return hook_mode()
        except Exception as e:  # 壊れた時は止める側に倒す
            print(f"secret_scan: フックが壊れたので止めます: {e!r}", file=sys.stderr)
            return 2
    if DENY is None:
        print(f"secret_scan: 注意: 拒否語リストが無い（{DENY_PATH}）。個人情報の語は検査されない", file=sys.stderr)
    hits = []
    n = 0
    if argv[:1] == ["--staged"]:
        hits += scan_identity()
        for rel in zlist(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]):
            n += 1
            hits += scan_blob(rel, git(["show", f":{rel}"], binary=True))
    elif argv[:1] == ["--object"] and len(argv) > 1:
        hits, n = scan_object(argv[1])
    elif argv[:1] == ["--range"] and len(argv) > 1:
        hits, n = scan_commits(git(["rev-list", argv[1]]).split())
    elif argv[:1] == ["--history"]:
        hits, n = scan_commits(git(["rev-list", "--all"]).split())
        for line in git(["for-each-ref", "refs/tags", "--format=%(objectname) %(objecttype)"]).splitlines():
            sha, typ = line.split()
            if typ == "tag":
                hits += scan_text(git(["cat-file", "-p", sha]), f"tag {sha[:8]}")
    elif argv[:1] == ["--all"]:
        for rel in zlist(["ls-files"]):
            n += 1
            hits += scan_blob(rel, git(["show", f"HEAD:{rel}"], binary=True))
    else:
        for rel in argv:
            n += 1
            p = os.path.join(ROOT, rel)
            raw = open(p, "rb").read() if os.path.isfile(p) else None
            hits += scan_blob(rel, raw)
    if hits:
        print("secret_scan: 止めました（秘密値・私的情報の疑い）。直すか、例示なら .md の行末に secret-scan: allow を付ける", file=sys.stderr)
        print("\n".join(hits[:50]), file=sys.stderr)
        return 2
    print(f"secret_scan: OK（{n} 件・拒否語 {len(DENY or [])} 語）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
