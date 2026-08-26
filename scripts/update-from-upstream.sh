#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/usestrix/strix.git}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"
ORIGIN_REMOTE="${ORIGIN_REMOTE:-origin}"

MODE="merge"
DRY_RUN=false
DO_PUSH=false
DO_STASH=false
ALL_BRANCHES=false
LOCAL_BRANCH=""

usage() {
    cat <<EOF
🦉 Strix Upstream Sync

Usage: scripts/update-from-upstream.sh [options]

Fetches ${UPSTREAM_REMOTE} (${UPSTREAM_URL}) and brings branch
'${UPSTREAM_BRANCH}' into your local branch. Adds the upstream remote if missing.

Options:
  -b, --branch <name>   Local branch to update (default: current branch)
  -n, --dry-run         Show what would be pulled in, then stop
  -r, --rebase          Rebase local commits onto upstream instead of merging
  -s, --stash           Stash uncommitted changes first, restore afterwards
  -p, --push            Push the updated branch to '${ORIGIN_REMOTE}' when done
  -a, --all-branches    Fetch every upstream branch, not just '${UPSTREAM_BRANCH}'
  -h, --help            Show this help

Environment overrides:
  UPSTREAM_REMOTE (${UPSTREAM_REMOTE})   UPSTREAM_URL (${UPSTREAM_URL})
  UPSTREAM_BRANCH (${UPSTREAM_BRANCH})   ORIGIN_REMOTE (${ORIGIN_REMOTE})

Note: --rebase rewrites local commits. If you have already pushed them to
'${ORIGIN_REMOTE}', the follow-up push needs --force-with-lease.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -b|--branch)  LOCAL_BRANCH="$2"; shift 2;;
        -n|--dry-run) DRY_RUN=true; shift;;
        -r|--rebase)  MODE="rebase"; shift;;
        -s|--stash)   DO_STASH=true; shift;;
        -p|--push)    DO_PUSH=true; shift;;
        -a|--all-branches) ALL_BRANCHES=true; shift;;
        -h|--help)    usage; exit 0;;
        *)            echo -e "${RED}Unknown option: $1${NC}"; echo; usage; exit 1;;
    esac
done

echo -e "${BLUE}🦉 Strix Upstream Sync${NC}"
echo "================================"

cd "$PROJECT_ROOT"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}Error: $PROJECT_ROOT is not a git repository${NC}"
    exit 1
fi

if ! git remote get-url "$UPSTREAM_REMOTE" > /dev/null 2>&1; then
    echo -e "${YELLOW}Adding remote '${UPSTREAM_REMOTE}':${NC} $UPSTREAM_URL"
    git remote add "$UPSTREAM_REMOTE" "$UPSTREAM_URL"
else
    CURRENT_URL="$(git remote get-url "$UPSTREAM_REMOTE")"
    if [ "$CURRENT_URL" != "$UPSTREAM_URL" ]; then
        echo -e "${YELLOW}Note:${NC} remote '${UPSTREAM_REMOTE}' points at $CURRENT_URL"
    fi
fi

if [ -z "$LOCAL_BRANCH" ]; then
    LOCAL_BRANCH="$(git symbolic-ref --quiet --short HEAD || true)"
    if [ -z "$LOCAL_BRANCH" ]; then
        echo -e "${RED}Error: HEAD is detached. Check out a branch or pass --branch${NC}"
        exit 1
    fi
fi

STARTING_BRANCH="$(git symbolic-ref --quiet --short HEAD || git rev-parse HEAD)"
echo -e "${YELLOW}Branch:${NC} $LOCAL_BRANCH  ${YELLOW}Upstream:${NC} ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}  ${YELLOW}Mode:${NC} $MODE"

STASHED=false
restore_stash() {
    if [ "$STASHED" = true ]; then
        echo -e "\n${BLUE}Restoring stashed changes...${NC}"
        if git stash pop; then
            STASHED=false
        else
            echo -e "${RED}Could not restore the stash cleanly - it is kept in 'git stash list'${NC}"
        fi
    fi
}
trap restore_stash EXIT

# A dry run only reads, so it leaves the working tree and HEAD alone.
BASE_REF="$LOCAL_BRANCH"
if [ "$DRY_RUN" = false ]; then
    if ! git diff --quiet || ! git diff --cached --quiet; then
        if [ "$DO_STASH" = true ]; then
            echo -e "\n${BLUE}Stashing uncommitted changes...${NC}"
            git stash push --include-untracked --message "update-from-upstream $(date +%Y-%m-%dT%H:%M:%S)"
            STASHED=true
        else
            echo -e "${RED}Error: working tree has uncommitted changes${NC}"
            echo "Commit them, or re-run with --stash to set them aside during the update."
            exit 1
        fi
    fi

    if [ "$STARTING_BRANCH" != "$LOCAL_BRANCH" ]; then
        echo -e "\n${BLUE}Switching to $LOCAL_BRANCH...${NC}"
        git checkout "$LOCAL_BRANCH"
    fi
    BASE_REF="HEAD"
fi

UPSTREAM_REF="${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"

echo -e "\n${BLUE}Fetching ${UPSTREAM_REMOTE}...${NC}"
if [ "$ALL_BRANCHES" = true ]; then
    git fetch --prune --tags "$UPSTREAM_REMOTE"
else
    # Only the branch we sync from - upstream carries 100+ working branches.
    git fetch --tags "$UPSTREAM_REMOTE" \
        "+refs/heads/${UPSTREAM_BRANCH}:refs/remotes/${UPSTREAM_REF}"
fi

if ! git rev-parse --verify --quiet "$UPSTREAM_REF" > /dev/null; then
    echo -e "${RED}Error: $UPSTREAM_REF does not exist${NC}"
    echo "Run with --all-branches to see what upstream offers."
    exit 1
fi

read -r BEHIND AHEAD <<< "$(git rev-list --left-right --count "${UPSTREAM_REF}...${BASE_REF}")"
echo -e "${YELLOW}New upstream commits:${NC} $BEHIND   ${YELLOW}Local-only commits:${NC} $AHEAD"

if [ "$BEHIND" -eq 0 ]; then
    echo -e "\n${GREEN}Already up to date with ${UPSTREAM_REF}${NC}"
    exit 0
fi

echo -e "\n${BLUE}Incoming commits:${NC}"
git --no-pager log --oneline --no-decorate --max-count=40 "${BASE_REF}..${UPSTREAM_REF}"
if [ "$BEHIND" -gt 40 ]; then
    echo "... and $((BEHIND - 40)) more"
fi

DEP_CHANGES="$(git diff --name-only "${BASE_REF}..${UPSTREAM_REF}" -- pyproject.toml uv.lock poetry.lock)"

if [ "$DRY_RUN" = true ]; then
    echo -e "\n${YELLOW}Dry run - nothing changed.${NC}"
    exit 0
fi

echo -e "\n${BLUE}Updating $LOCAL_BRANCH...${NC}"
if [ "$AHEAD" -eq 0 ]; then
    git merge --ff-only "$UPSTREAM_REF"
elif [ "$MODE" = "rebase" ]; then
    if ! git rebase "$UPSTREAM_REF"; then
        echo -e "\n${RED}Rebase hit conflicts.${NC}"
        echo "Resolve them, then: git add <files> && git rebase --continue"
        echo "Or back out with: git rebase --abort"
        exit 1
    fi
else
    if ! git merge --no-edit "$UPSTREAM_REF"; then
        echo -e "\n${RED}Merge hit conflicts.${NC}"
        echo "Resolve them, then: git add <files> && git commit"
        echo "Or back out with: git merge --abort"
        exit 1
    fi
fi
echo -e "${GREEN}Branch updated.${NC}"

restore_stash

if [ -n "$DEP_CHANGES" ]; then
    echo -e "\n${YELLOW}Dependency files changed upstream:${NC}"
    echo "$DEP_CHANGES" | sed 's/^/  /'
    echo "Run 'make dev-install' to sync your environment."
fi

if [ "$DO_PUSH" = true ]; then
    echo -e "\n${BLUE}Pushing to ${ORIGIN_REMOTE}/${LOCAL_BRANCH}...${NC}"
    if [ "$MODE" = "rebase" ] && [ "$AHEAD" -gt 0 ]; then
        git push --force-with-lease "$ORIGIN_REMOTE" "$LOCAL_BRANCH"
    else
        git push "$ORIGIN_REMOTE" "$LOCAL_BRANCH"
    fi
else
    echo -e "\n${YELLOW}Not pushed.${NC} To publish: git push ${ORIGIN_REMOTE} ${LOCAL_BRANCH}"
fi

echo -e "\n${GREEN}Done!${NC}"
