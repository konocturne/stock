# 共通：.claude/git-rules.conf を読む
#   MODE=main  … main で直接作業し、ブランチを作らない（既定）
#   MODE=pr    … main へ直接 push しない。作業ブランチ → プルリクエストで main へ（argyle の作業系など）
#   ALLOW_BRANCH=…  … MODE=main でも作ってよいブランチ名（シェルのパターン。空白区切りで複数）
MODE=main; ALLOW_BRANCH=""; BASE=main
conf="${CLAUDE_PROJECT_DIR:-.}/.claude/git-rules.conf"
[ -f "$conf" ] && . "$conf"
allowed_branch() { local b="$1" p; for p in $ALLOW_BRANCH; do case "$b" in $p) return 0;; esac; done; return 1; }
