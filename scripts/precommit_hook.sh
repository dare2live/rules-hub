#!/bin/sh
# Rules Hub pre-commit 隐私闸门（本地钩子，位于 .git/hooks/，不入库）
# 安装：cp scripts/precommit_hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# 回滚：mv .git/hooks/pre-commit .git/hooks/pre-commit.disabled
set -u
ROOT="$(git rev-parse --show-toplevel)"
echo "== 本次将入库的文件清单 =="
git diff --cached --name-only | /usr/bin/sed 's/^/  /'
echo "== 隐私守卫（config/privacy_patterns.txt）=="
/bin/sh "$ROOT/scripts/precommit_guard.sh" || {
  echo "提交被拒绝：上面的命中项不得入库（命中值已打码）。"
  echo "正确做法：改掉内容，或把确认安全的路径加进 config/privacy_patterns.txt 的允许段；不要绕过钩子。"
  exit 1
}
