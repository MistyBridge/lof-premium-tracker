# 共享约束 — 所有柯必须遵守

## 红线
1. **仅操作 backend-v2/ 目录**，不得修改根目录下任何文件
2. **禁止修改前端**: index.html / js/ / css/ / pages/ / assets/ / functions/
3. **禁止修改 v1 后端**: backend/ 目录保持 Railway 现有运行状态
4. **所有新代码写入 backend-v2/**

## API 兼容性
- v2 API 路径: /api/v1/funds, /api/v1/funds/:code/chart 等
- 字段名保持和 v1 一致（code/name/close/nav/premium_rate/amount 等）
- 将来前端通过 ?api=https://api.jinkuaicha.com 切换到 v2

## 并行运行
- v1 (Railway) 继续服务现有用户
- v2 (阿里云) 独立开发测试
- v2 验证通过后才切换 DNS