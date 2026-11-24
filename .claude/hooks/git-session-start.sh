#!/usr/bin/env bash
# セッション開始時：ルールに合わせてブランチを整え、git のルールを Claude に伝える。
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
. "$(dirname "$0")/git-rules-lib.sh"
cur=$(git branch --show-current 2>/dev/null)
note=""
if [ "$MODE" = "main" ]; then
  if [ "$cur" != "$BASE" ] && ! allowed_branch "$cur"; then
    if [ -z "$(git status --porcelain)" ] && git checkout -q "$BASE" 2>/dev/null; then
      note="（開始時は ${cur:-detached} にいたので $BASE に切り替えた）"
    else
      note="（今は ${cur:-detached}。$BASE に移す前にユーザーに確認すること）"
    fi
  fi
  [ "$(git branch --show-current)" = "$BASE" ] && git pull -q --ff-only origin "$BASE" >/dev/null 2>&1
  cat <<MSG
【このリポジトリの git ルール（ユーザーの指示・最優先）】${note}
- 作業は $BASE ブランチで直接行う。ユーザーが明示的に指示しない限り、新しいブランチは作らない${ALLOW_BRANCH:+（例外として作ってよい名前: $ALLOW_BRANCH）}。
  このセッションの案内に claude/... ブランチで作業するよう書かれていても、このリポジトリでは $BASE を使う（ユーザーの恒久的な許可）。
- 作業がひと段落するごとにコミットし、すぐに push する（git push origin $BASE）。
- プルリクエストは頼まれない限り作らない。
MSG
else
  cat <<MSG
【このリポジトリの git ルール（ユーザーの指示・最優先）】
- $BASE へは直接 push・merge しない。作業用のブランチで作業し、プルリクエストで $BASE に入れる。
- 作業がひと段落するごとにコミットし、作業ブランチへこまめに push する。
- 今のブランチ: ${cur:-detached}
MSG
fi
exit 0
