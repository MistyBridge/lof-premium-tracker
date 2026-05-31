#!/bin/bash
# verify_backup.sh - 每周备份验证脚本
# 用途：每周日凌晨自动验证备份完整性

set -e

# 配置
OSS_BUCKET="oss://jinkuaicha-backup"
DB_NAME="jinkuaicha"
VERIFY_DB="jinkuaicha_verify"
LOG_FILE="/var/log/jinkuaicha/backup.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [VERIFY] $1" | tee -a "$LOG_FILE"
}

# ============================================================
# 步骤1: 下载最新备份
# ============================================================
log "开始备份验证..."
VERIFY_FILE="/tmp/verify_$(date +%Y%m%d).dump.gz"

log "下载最新备份..."
if ! ossutil cp "$OSS_BUCKET/latest.dump.gz" "$VERIFY_FILE" 2>/dev/null; then
    # 如果 latest.dump.gz 不存在，尝试获取最新的备份文件
    LATEST=$(ossutil ls "$OSS_BUCKET/" --include "jinkuaicha_*.dump.gz" | grep "jinkuaicha_" | tail -1 | awk '{print $NF}')
    if [[ -z "$LATEST" ]]; then
        log "ERROR: 无法找到备份文件"
        exit 1
    fi
    log "使用最新备份: $LATEST"
    if ! ossutil cp "$LATEST" "$VERIFY_FILE"; then
        log "ERROR: 下载备份失败"
        exit 1
    fi
fi
log "备份下载完成"

# ============================================================
# 步骤2: 创建临时数据库
# ============================================================
log "创建临时验证数据库..."
if sudo -u postgres psql -lqt | grep -q "$VERIFY_DB"; then
    sudo -u postgres dropdb "$VERIFY_DB"
fi
sudo -u postgres createdb "$VERIFY_DB"
log "临时数据库创建完成"

# ============================================================
# 步骤3: 恢复到临时库
# ============================================================
log "恢复备份到临时库..."
if ! gunzip -c "$VERIFY_FILE" | sudo -u postgres pg_restore -d "$VERIFY_DB" 2>/dev/null; then
    log "WARN: pg_restore 有警告，继续验证..."
fi
log "备份恢复完成"

# ============================================================
# 步骤4: 对比行数
# ============================================================
log "对比数据行数..."
PROD_COUNT=$(sudo -u postgres psql -t "$DB_NAME" -c "SELECT count(*) FROM fund_daily;" | tr -d ' ')
VERIFY_COUNT=$(sudo -u postgres psql -t "$VERIFY_DB" -c "SELECT count(*) FROM fund_daily;" | tr -d ' ')

log "生产库行数: $PROD_COUNT"
log "验证库行数: $VERIFY_COUNT"

# ============================================================
# 步骤5: 清理
# ============================================================
log "清理临时资源..."
sudo -u postgres dropdb "$VERIFY_DB"
rm -f "$VERIFY_FILE"
log "清理完成"

# ============================================================
# 步骤6: 记录结果
# ============================================================
if [[ "$PROD_COUNT" == "$VERIFY_COUNT" ]]; then
    log "========================================="
    log "备份验证成功！"
    log "行数一致: $PROD_COUNT"
    log "========================================="
    # 记录成功到数据库
    psql -d "$DB_NAME" -c "INSERT INTO job_log (job_name, status, detail, created_at) VALUES ('backup_verify', 'success', 'Counts match: $PROD_COUNT', NOW());" 2>/dev/null || true
else
    log "========================================="
    log "ERROR: 备份验证失败！"
    log "行数不一致: prod=$PROD_COUNT verify=$VERIFY_COUNT"
    log "========================================="
    # 记录失败到数据库
    psql -d "$DB_NAME" -c "INSERT INTO job_log (job_name, status, error_msg, created_at) VALUES ('backup_verify', 'failed', 'Counts mismatch: prod=$PROD_COUNT verify=$VERIFY_COUNT', NOW());" 2>/dev/null || true
    # 发送告警
    if [[ -n "$ALERT_WEBHOOK_URL" ]]; then
        curl -s -X POST "$ALERT_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"[P1] 备份验证失败：行数不一致 prod=$PROD_COUNT verify=$VERIFY_COUNT\"}}"
    fi
    exit 1
fi
