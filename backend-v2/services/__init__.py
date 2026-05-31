"""
业务服务模块 — M6 服务层

依赖: database, models, cache, formula_engine
被依赖: hub
对外接口:
  - FundService: 基金查询+缓存
  - AssetService: 资产查询
  - DataService: 日线查询
  - FormulaService: 公式 CRUD
  - AlertService: 预警 CRUD
  - SystemService: 健康+监控+诊断
  - SSEService: SSE 增量推送
"""