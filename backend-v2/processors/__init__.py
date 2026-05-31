"""
数据处理模块 — M4 处理层

依赖: mq, cache, database, models, constants
被依赖: 消费者协程（在 app.py lifespan 中启动）
对外接口:
  - stream_consumer(): Stream 消费者主循环
  - daily_save_processor(): 每日入库处理
"""