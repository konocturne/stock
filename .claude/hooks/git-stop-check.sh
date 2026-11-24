#!/usr/bin/env bash
# 返答を終える前：未コミットの変更や push していないコミットが残っていたら止めて、commit/push を促す。
input=$(cat)
active=$(printf '%s' "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
. "$(dirname "$0")/git-rules-lib.sh"
problems=(); cur=$(git branch --show-current 2>/dev/null)
if [ "$MODE" = "main" ]; then
  [ "$cur" != "$BASE" ] && ! allowed_branch "$cur" && problems+=("今のブランチが $BASE ではない（${cur:-detached}）")
  target="$BASE"
else
  [ "$cur" = "$BASE" ] && [ -n "$(git status --porcelain)" ] && problems+=("$BASE の上で変更している（作業ブランチに移すこと）")
  target="$cur"
fi
[ -n "$(git status --porcelain)" ] && problems+=("コミットしていない変更がある")
if [ -n "$target" ]; then
  git fetch -q origin "$target" >/dev/null 2>&1
  if git rev-parse -q --verify "origin/$target" >/dev/null; then
    ahead=$(git rev-list --count "origin/$target..HEAD" 2>/dev/null || echo 0)
    [ "${ahead:-0}" -gt 0 ] && problems+=("origin/$target に push していないコミットが ${ahead} 件ある")
  elif [ "$MODE" = "pr" ] && [ "$cur" != "$BASE" ]; then
    problems+=("ブランチ $cur をまだ push していない")
  fi
fi
[ ${#problems[@]} -eq 0 ] && exit 0
joined=$(printf '%s、' "${problems[@]}"); joined=${joined%、}
if [ "$MODE" = "main" ]; then how="$BASE でコミットして git push origin $BASE"; else how="作業ブランチでコミットして push"; fi
msg="git ルール（CLAUDE.md）：${joined}。作業がひと段落したなら、${how} してください。途中ならその旨をユーザーに伝えてください。"
if [ "$active" = "true" ]; then jq -n --arg m "$msg" '{systemMessage:$m}'; else jq -n --arg m "$msg" '{decision:"block",reason:$m}'; fi
exit 0
