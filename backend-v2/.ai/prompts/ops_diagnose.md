# 运维诊断标准流程

## 步骤

### 1. 了解当前状态
读 `.ai/context.md` 了解项目当前状态和已知问题。

### 2. 查知识库
读 `.ai/knowledge_base.md` 查看已知问题和解决方案。

### 3. 获取系统状态
调用诊断 API（需要 admin 权限）：

```bash
# 整体健康
curl -s https://jinkuaicha.com/api/v1/health | jq .

# 详细监控（CPU/内存/磁盘/DB连接/Redis）
curl -s -H "Authorization: Bearer $TOKEN" https://jinkuaicha.com/api/v1/admin/monitor | jq .

# Redis 状态
curl -s -H "Authorization: Bearer $TOKEN" https://jinkuaicha.com/api/v1/admin/diagnose/redis | jq .

# 数据库状态
curl -s -H "Authorization: Bearer $TOKEN" https://jinkuaicha.com/api/v1/admin/diagnose/db | jq .

# 采集状态
curl -s -H "Authorization: Bearer $TOKEN" https://jinkuaicha.com/api/v1/admin/diagnose/fetcher | jq .

# 队列状态
curl -s -H "Authorization: Bearer $TOKEN" https://jinkuaicha.com/api/v1/admin/diagnose/queue | jq .

# 单基金诊断
curl -s -H "Authorization: Bearer $TOKEN" "https://jinkuaicha.com/api/v1/admin/diagnose/fund?code=160644" | jq .
```

### 4. 服务器端检查
```bash
# SSH 登录
ssh root@101.200.129.61

# 服务状态
systemctl status jinkuaicha

# 最近日志
journalctl -u jinkuaicha -n 100 --no-pager

# 系统资源
free -h && df -h / && uptime

# PostgreSQL
sudo -u deploy psql -d jinkuaicha -c "SELECT count(*) FROM fund_daily;"
sudo -u deploy psql -d jinkuaicha -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"

# Redis
redis-cli info memory
redis-cli info stats
redis-cli llen stream:events
```

### 5. 分析
- 对比 `.ai/benchmarks.json` 判断 API 响应是否异常
- 对比 `.ai/knowledge_base.md` 判断是否已知问题
- 检查 `job_log` 表查看定时任务执行历史
- 检查 `admin_audit_log` 表查看近期操作

### 6. 输出诊断报告
```markdown
## 诊断报告

### 问题描述
[现象描述]

### 系统状态
- CPU: xx% | 内存: xx% | 磁盘: xx%
- DB 连接: x/10 | Redis 内存: xxMB/128MB
- 最近采集: 2026-05-30 15:00 | 队列长度: x

### 根因分析
[根因]

### 建议操作
[操作建议]

### 风险评估
[风险]
```

### 7. 执行修复（如需）
读 `.ai/prompts/fix_bug.md` 执行修复流程。

所有 admin_write 操作记录到 `admin_audit_log` 表。
