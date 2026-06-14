#!/bin/bash
# ============================================================
# 联邦投顾法典备份脚本 — 坚果云 WebDAV
# 使用方式: /备份  → 调用本脚本
# 环境变量: JIAN_GO_YUN_WEBDAV_URL / JIAN_GO_YUN_USER / JIAN_GO_YUN_PASS
# ============================================================

set -euo pipefail

WEBDAV_URL="${JIAN_GO_YUN_WEBDAV_URL}"
WEBDAV_USER="${JIAN_GO_YUN_USER}"
WEBDAV_PASS="${JIAN_GO_YUN_PASS}"

TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
TAR_NAME="federal-codex-backup_${TIMESTAMP}.tar.gz"
TAR_PATH="/tmp/${TAR_NAME}"
SKILLS_INVENTORY="/tmp/skills_inventory_${TIMESTAMP}.md"

# 生成技能清单
echo "[0/3] 生成技能清单..."
cat > "$SKILLS_INVENTORY" << 'SKILLEOF'
# 联邦投顾技能清单

> 说明: 此清单用于换环境后重新安装技能，不包含技能代码本身
SKILLEOF

echo "> 生成时间: $(date '+%Y-%m-%d %H:%M:%S')" >> "$SKILLS_INVENTORY"
echo "" >> "$SKILLS_INVENTORY"
echo "## 已安装技能" >> "$SKILLS_INVENTORY"
echo "" >> "$SKILLS_INVENTORY"

for skill_dir in /home/agent/cow/skills/*/; do
    name=$(basename "$skill_dir")
    if [ -f "${skill_dir}SKILL.md" ]; then
        desc=$(head -10 "${skill_dir}SKILL.md" | grep -i '<description>' | head -1 | sed 's/<[^>]*>//g' | xargs || true)
        echo "- **${name}**: ${desc:-（无描述）}" >> "$SKILLS_INVENTORY"
    fi
done

echo "" >> "$SKILLS_INVENTORY"
echo "## 换环境安装方式" >> "$SKILLS_INVENTORY"
echo "" >> "$SKILLS_INVENTORY"
echo "登录新环境后，在对话中对助手说：" >> "$SKILLS_INVENTORY"
echo '```' >> "$SKILLS_INVENTORY"
echo "安装技能: [从上述清单逐一安装]" >> "$SKILLS_INVENTORY"
echo '```' >> "$SKILLS_INVENTORY"

echo "       技能清单已生成: $(wc -l < "$SKILLS_INVENTORY") 行"

# 打包
echo "[1/3] 打包法典文件..."
tar -czf "$TAR_PATH" \
    -C /home/agent/cow \
    AGENT.md USER.md RULE.md MEMORY.md \
    knowledge/ \
    scripts/ \
    2>/dev/null

# 追加技能清单
tar -rf "$TAR_PATH" -C /tmp "$(basename "$SKILLS_INVENTORY")" 2>/dev/null || true
rm -f "$SKILLS_INVENTORY"

SIZE=$(du -h "$TAR_PATH" | cut -f1)
echo "       打包完成: ${TAR_NAME} (${SIZE})"

# 上传
echo "[2/3] 上传至坚果云..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -T "$TAR_PATH" \
    "${WEBDAV_URL}${TAR_NAME}" \
    --user "${WEBDAV_USER}:${WEBDAV_PASS}" \
    --connect-timeout 30 \
    --max-time 120 \
    2>&1)

if [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "204" ]; then
    echo "       上传成功 (HTTP ${HTTP_CODE})"
else
    echo "       上传失败 (HTTP ${HTTP_CODE})"
    rm -f "$TAR_PATH"
    exit 1
fi

# 清理本地临时文件
echo "[3/3] 清理本地临时文件..."
rm -f "$TAR_PATH"

# 清理云端旧备份（保留最近10个）
echo "       清理云端旧备份（保留最近10个）..."
FILE_LIST=$(curl -s -X PROPFIND "${WEBDAV_URL}" \
    --user "${WEBDAV_USER}:${WEBDAV_PASS}" \
    -H "Depth: 1" 2>/dev/null \
    | grep -oP 'federal-codex-backup_[^<]+\.tar\.gz' \
    | sort -r)

COUNT=0
while IFS= read -r fname; do
    [ -z "$fname" ] && continue
    COUNT=$((COUNT + 1))
    if [ $COUNT -gt 10 ]; then
        curl -s -o /dev/null -X DELETE "${WEBDAV_URL}${fname}" \
            --user "${WEBDAV_USER}:${WEBDAV_PASS}" 2>/dev/null
        echo "       已删除旧备份: ${fname}"
    fi
done <<< "$FILE_LIST"

echo ""
echo "✅ 备份完成"
echo "   文件名: ${TAR_NAME}"
echo "   位置: 坚果云/cow-backup/"
echo "   大小: ${SIZE}"
