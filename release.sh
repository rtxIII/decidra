#!/usr/bin/env bash
# Decidra 发布脚本：校验 → 推送 → 打 tag → GitHub Release
#
# 用法:
#   ./release.sh                  # 以 pyproject.toml 的 version 发布 v<version>
#   ./release.sh --notes FILE     # 使用手写 release notes 文件（默认由提交记录生成）
#   ./release.sh --force          # tag/release 已存在时删除重打（仅限刚发布无人消费的场景）
#   ./release.sh --dry-run        # 只做校验与 notes 预览，不推送、不打 tag、不建 release
set -euo pipefail

cd "$(dirname "$0")"

RELEASE_BRANCH="main"
PYTHON_BIN="${PYTHON:-python3}"

FORCE=0
DRY_RUN=0
NOTES_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)   FORCE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --notes)   NOTES_FILE="${2:?--notes 需要文件参数}"; shift 2 ;;
        *) echo "未知参数: $1" >&2; exit 1 ;;
    esac
done

die() { echo "错误: $*" >&2; exit 1; }
info() { echo "==> $*"; }

# ---------- 前置校验 ----------
command -v git >/dev/null || die "缺少 git"
command -v gh  >/dev/null || die "缺少 gh CLI"
gh auth status >/dev/null 2>&1 || die "gh 未登录，先执行 gh auth login"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" == "$RELEASE_BRANCH" ]] || die "当前分支 $BRANCH，发布须在 $RELEASE_BRANCH"

# 工作区须干净（未跟踪文件不阻塞）
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "工作区有未提交改动，先提交或暂存"

VERSION="$(grep -m1 -E '^version *= *"' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')"
[[ -n "$VERSION" ]] || die "无法从 pyproject.toml 读取 version"
TAG="v$VERSION"
info "发布版本: $TAG"

# ---------- 依赖 pin 校验 ----------
# 两个来源：pyproject.toml 与 requirements.txt 中所有 pkg==ver。
# 1) 版本号须为合法 PEP 440（拦截 0.1.9codex 这类 pip 无法解析的 pin）；
# 2) 同一包在两文件中的 pin 须一致。
info "校验依赖 pin ..."
grep -hoE "[A-Za-z0-9_.-]+==[^\"', ]+" pyproject.toml requirements.txt \
    | "$PYTHON_BIN" -c '
import sys
try:
    from packaging.version import Version, InvalidVersion
except ModuleNotFoundError:  # 环境未装 packaging 时用 pip 内置副本
    from pip._vendor.packaging.version import Version, InvalidVersion

pins = {}
bad = False
for line in sys.stdin.read().split():
    package_name, _, pinned_version = line.partition("==")
    try:
        Version(pinned_version)
    except InvalidVersion:
        print(f"  非法版本号: {line}", file=sys.stderr)
        bad = True
        continue
    if package_name in pins and pins[package_name] != pinned_version:
        print(f"  pin 不一致: {package_name}=={pins[package_name]} 与 =={pinned_version}", file=sys.stderr)
        bad = True
    pins[package_name] = pinned_version
sys.exit(1 if bad else 0)
' || die "依赖 pin 校验未通过，修正后重试"

# ---------- tag 冲突处理 ----------
TAG_EXISTS=0
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && TAG_EXISTS=1
git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1 && TAG_EXISTS=1

if [[ $TAG_EXISTS -eq 1 && $FORCE -eq 0 ]]; then
    die "tag $TAG 已存在。确认无人消费后用 --force 重打，或先升级 pyproject.toml 的 version"
fi

# ---------- 与远端同步 ----------
git fetch -q origin "$RELEASE_BRANCH"
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse "origin/$RELEASE_BRANCH")"
if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]]; then
    git merge-base --is-ancestor "origin/$RELEASE_BRANCH" HEAD \
        || die "本地与 origin/$RELEASE_BRANCH 分叉（或落后），先手动同步"
fi

# ---------- 生成 release notes ----------
NOTES_TMP=""
if [[ -z "$NOTES_FILE" ]]; then
    NOTES_TMP="$(mktemp)"
    trap 'rm -f "$NOTES_TMP"' EXIT
    # 排除当前 TAG 自身（重打场景 HEAD 可能已带该 tag），找真正的前一个 tag
    PREV_TAG="$(git describe --tags --abbrev=0 --exclude "$TAG" 2>/dev/null || true)"
    if [[ -n "$PREV_TAG" ]]; then
        RANGE="$PREV_TAG..HEAD"
        echo "## 变更（$PREV_TAG 以来）" > "$NOTES_TMP"
    else
        RANGE="HEAD"
        echo "## 变更" > "$NOTES_TMP"
    fi
    git log --no-merges --pretty='- %s' "$RANGE" >> "$NOTES_TMP"
    NOTES_FILE="$NOTES_TMP"
fi
[[ -s "$NOTES_FILE" ]] || die "release notes 文件为空: $NOTES_FILE"

info "release notes 预览:"
sed 's/^/    /' "$NOTES_FILE"

if [[ $DRY_RUN -eq 1 ]]; then
    info "dry-run 结束：校验通过，未推送、未打 tag、未建 release"
    exit 0
fi

# ---------- 执行发布 ----------
if [[ $TAG_EXISTS -eq 1 ]]; then
    info "重打 $TAG：删除已有 release 与 tag ..."
    gh release delete "$TAG" --yes --cleanup-tag 2>/dev/null || true
    git tag -d "$TAG" 2>/dev/null || true
    git push --delete origin "$TAG" 2>/dev/null || true
fi

if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]]; then
    info "推送 $RELEASE_BRANCH ..."
    git push origin "$RELEASE_BRANCH"
fi

info "打 tag 并推送 ..."
git tag -a "$TAG" -m "Decidra $TAG"
git push origin "$TAG"

info "创建 GitHub Release ..."
gh release create "$TAG" --title "$TAG" --notes-file "$NOTES_FILE"

info "完成: $(gh release view "$TAG" --json url -q .url)"
