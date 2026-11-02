#!/bin/sh
# python3 が無い環境（Windows は python、Mac は python3）でも同じ検査を呼ぶ薄い包み。引数はそのまま渡す。
# Windows の python3 は Microsoft Store 誘導の空スタブのことがあるので、実際に動くかを確かめてから使う
top=$(cd "$(dirname "$0")/.." && pwd)
for py in python3 python py; do
  if "$py" -c "pass" >/dev/null 2>&1; then exec "$py" "$top/tools/secret_scan.py" "$@"; fi
done
echo "secret_scan: 動く python が見つからないので止めます" >&2
exit 2
