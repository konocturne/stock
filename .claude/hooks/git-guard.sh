#!/usr/bin/env bash
# Bash の前：ルールに反する git 操作を止める。
# ユーザーが明示的に指示した時だけ、コマンドの先頭に CLAUDE_ALLOW_BRANCH=1 を付けて通す。
input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$cmd" ] && exit 0
case "$cmd" in *CLAUDE_ALLOW_BRANCH=1*) exit 0;; esac
printf '%s' "$cmd" | grep -Eq '(^|[^[:alnum:]_])git[[:space:]]' || exit 0
. "$(dirname "$0")/git-rules-lib.sh"
deny() { jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'; exit 0; }
if [ "$MODE" = "main" ]; then
  rule="このリポジトリは $BASE で直接作業し、ユーザーの指示なしにブランチを作らないルールです（CLAUDE.md）。"
else
  rule="このリポジトリは $BASE へ直接 push しないルールです。作業ブランチからプルリクエストで入れます（CLAUDE.md）。"
fi
is_base_ref() { case "$1" in "$BASE"|"$BASE:$BASE"|"HEAD:$BASE"|"refs/heads/$BASE"|"HEAD:refs/heads/$BASE"|*":$BASE"|*":refs/heads/$BASE") return 0;; esac; return 1; }
ref_target() { local r="${1#+}"; r="${r##*:}"; echo "${r#refs/heads/}"; }

while IFS= read -r part; do
  p=$(printf '%s' "$part" | sed -E 's/^[[:space:]]+//; s/^([A-Z_]+=[^[:space:]]*[[:space:]]+)+//')
  echo "$p" | grep -Eq '^(sudo[[:space:]]+)?git[[:space:]]' || continue
  sub=$(echo "$p" | sed -E 's/^(sudo[[:space:]]+)?git([[:space:]]+(-C|-c)[[:space:]]+[^[:space:]]+|[[:space:]]+--[^[:space:]]+)*[[:space:]]+//')
  # リダイレクト（2>&1、> file など）から後ろは引数として見ない
  sub=$(echo "$sub" | sed -E 's/[[:space:]]+[0-9]*[<>].*$//')
  set -- $sub; verb=$1; shift || true
  if [ "$MODE" = "main" ]; then
    newb=""
    case "$verb" in
      checkout) newb=$(echo " $* " | sed -nE 's/.*[[:space:]]-(b|B)[[:space:]]+([^[:space:]]+).*/\2/p'); echo " $* " | grep -q ' --orphan ' && newb="(orphan)";;
      switch) newb=$(echo " $* " | sed -nE 's/.*[[:space:]](-c|-C|--create|--force-create)[[:space:]]+([^[:space:]]+).*/\2/p');;
      branch)
        if ! echo " $* " | grep -Eq '[[:space:]](-d|-D|--delete|-a|-r|-v|-vv|--list|-l|--show-current|--contains|--merged|--no-merged|-u|--set-upstream-to|--unset-upstream)[[:space:]]'; then
          for a in "$@"; do case "$a" in -*) ;; *) newb="$a"; break;; esac; done
        fi;;
      worktree) [ "$1" = "add" ] && deny "$rule git worktree add は使えません。";;
    esac
    if [ -n "$newb" ] && ! allowed_branch "$newb"; then deny "$rule ブランチ「$newb」は作れません。"; fi
  fi
  if [ "$verb" = "push" ]; then
    echo " $* " | grep -Eq '[[:space:]](--delete|-d)[[:space:]]' && continue
    refs=(); seen=0
    for a in "$@"; do case "$a" in -*) continue;; esac; if [ $seen -eq 0 ]; then seen=1; continue; fi; refs+=("$a"); done
    if [ ${#refs[@]} -eq 0 ]; then
      refs=("$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null)")
    fi
    for r in "${refs[@]}"; do
      t=$(ref_target "$r"); [ "$t" = "HEAD" ] && t=$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null)
      if [ "$MODE" = "main" ]; then
        [ "$t" = "$BASE" ] || allowed_branch "$t" || deny "$rule push 先は $BASE だけです（指定: ${t:-detached}）。"
      else
        [ "$t" = "$BASE" ] && deny "$rule $BASE への push は止めました。"
      fi
    done
  fi
  if [ "$MODE" = "pr" ] && [ "$verb" = "merge" ]; then
    cur=$(git -C "${CLAUDE_PROJECT_DIR:-.}" branch --show-current 2>/dev/null)
    [ "$cur" = "$BASE" ] && deny "$rule $BASE の上での merge は止めました。"
  fi
done < <(printf '%s\n' "$cmd" | sed -E 's/(\&\&|\|\||;|\|)/\n/g')
exit 0
