# クローン直後に1回: python tools/install_hooks.py
# ① git hook（pre-commit / pre-push）を .git/hooks に入れる
# ② このリポジトリのコミット名義を GitHub の noreply アドレスにする（個人メールを履歴に出さない）
# ③ 全履歴の検査を1回回す
import os
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRE_COMMIT = """#!/bin/sh
# ステージ済みの中身を検査（止める時は exit 2）
exec sh "$(git rev-parse --show-toplevel)/tools/secret_scan.sh" --staged
"""
PRE_PUSH = """#!/bin/sh
# push 対象コミットの全 blob と名義・本文を検査
top=$(git rev-parse --show-toplevel)
while read local_ref local_sha remote_ref remote_sha; do
  if [ "$local_sha" = "0000000000000000000000000000000000000000" ]; then continue; fi   # リモートの ref 削除
  case "$remote_ref" in refs/tags/*) sh "$top/tools/secret_scan.sh" --history || exit 2; continue;; esac   # タグ: 指す先だけでなく、未 push の手前のコミットも含めて全履歴を見る
  if [ "$remote_sha" = "0000000000000000000000000000000000000000" ]; then
    sh "$top/tools/secret_scan.sh" --history || exit 2
  else
    sh "$top/tools/secret_scan.sh" --range "$remote_sha..$local_sha" || exit 2
  fi
done
exit 0
"""


def run(args, check=False):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        print(r.stderr.strip())
    return r.stdout.strip()


d = os.path.join(ROOT, ".git", "hooks")
os.makedirs(d, exist_ok=True)
for name, body in (("pre-commit", PRE_COMMIT), ("pre-push", PRE_PUSH)):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("installed", p)

login = run(["gh", "api", "user", "--jq", ".login"])
uid = run(["gh", "api", "user", "--jq", ".id"])
if login and uid:
    run(["git", "config", "user.name", login])
    run(["git", "config", "user.email", f"{uid}+{login}@users.noreply.github.com"])
    print("commit identity:", run(["git", "config", "user.email"]))
else:
    print("gh でログインしていないので名義を設定できない。先に gh auth login するか、git config user.email を noreply アドレスにすること")
    sys.exit(2)

r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "secret_scan.py"), "--history"], cwd=ROOT)
sys.exit(r.returncode)
