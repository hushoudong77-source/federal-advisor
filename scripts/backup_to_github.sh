#!/bin/bash
# ============================================================
# 联邦投顾法典备份脚本 — GitHub 仓库
# 使用方式: /备份  → 调用本脚本
# 仓库: github.com/hushoudong77-source/federal-advisor
# ============================================================

set -euo pipefail

REPO_DIR="/home/agent/cow"
BACKUP_BRANCH="master"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
COMMIT_MSG="备份: $(date '+%Y-%m-%d %H:%M:%S') — 联邦法典全量快照"

echo "============================================"
echo " 联邦投顾法典备份 — GitHub 仓库"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"
echo ""

cd "$REPO_DIR"

# Step 1: 检查仓库状态
echo "[1/3] 检查仓库状态..."
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "       ❌ 不是有效的 Git 仓库"
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
REMOTE=$(git remote get-url origin 2>/dev/null | sed 's/https:\/\/[^@]*@/https:\/\/***@/' || echo "无远程")
echo "       分支: ${BRANCH}"
echo "       远程: ${REMOTE}"

# Step 2: 暂存变更并提交
echo "[2/3] 暂存变更并提交..."
git add AGENT.md USER.md RULE.md MEMORY.md knowledge/ scripts/ 2>/dev/null || true

# 检查是否有变更
if git diff --cached --quiet 2>/dev/null; then
    echo "       ⚠️ 无变更，跳过提交"
else
    git commit -m "$COMMIT_MSG" 2>/dev/null || true
    echo "       已提交: ${COMMIT_MSG}"
fi

# Step 3: 推送（通过 ghproxy.net 代理 — 腾讯云到 GitHub TCP 阻断的解决方案）
echo "[3/3] 推送至 GitHub（via ghproxy.net）..."
# 确保 remote 使用代理
git remote set-url origin https://ghproxy.net/https://github.com/hushoudong77-source/federal-advisor.git 2>/dev/null || true
if timeout 30 git push origin "$BRANCH" 2>&1; then
    echo "       ✅ 推送成功"
else
    echo "       ❌ 推送失败（代理超时，稍后重试）"
    exit 1
fi

echo ""
echo "✅ 备份完成"
echo "   仓库: github.com/hushoudong77-source/federal-advisor"
echo "   分支: ${BRANCH}"
echo "   提交: ${COMMIT_MSG}"
echo ""
echo "   覆盖内容: AGENT.md / USER.md / RULE.md / MEMORY.md / knowledge/ / scripts/"
