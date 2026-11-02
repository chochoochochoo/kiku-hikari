# git hook（pre-commit / pre-push）を .git/hooks に入れる。クローン直後に1回: python tools/install_hooks.py
import os
import stat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRE_COMMIT = """#!/bin/sh
# 秘密値スキャン（止める時は exit 2）
exec python "$(git rev-parse --show-toplevel)/tools/secret_scan.py" --staged
"""
PRE_PUSH = """#!/bin/sh
# push 対象コミットの変更ファイルを全部スキャン
top=$(git rev-parse --show-toplevel)
while read local_ref local_sha remote_ref remote_sha; do
  if [ "$remote_sha" = "0000000000000000000000000000000000000000" ]; then
    python "$top/tools/secret_scan.py" --all || exit 2
  else
    python "$top/tools/secret_scan.py" --range "$remote_sha..$local_sha" || exit 2
  fi
done
exit 0
"""
d = os.path.join(ROOT, ".git", "hooks")
os.makedirs(d, exist_ok=True)
for name, body in (("pre-commit", PRE_COMMIT), ("pre-push", PRE_PUSH)):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("installed", p)
