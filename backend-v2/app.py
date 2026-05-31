"""
金快查 v2 — FastAPI 入口
启动: uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""
import asyncio
import contextvars
import logging
import sys
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from cache import close_redis, init_redis
from config import Settings

settings = Settings()

from database import dispose_engine, init_engine
from exceptions import register_exception_handlers
from metrics import metrics
from mq import init_consumer_group
from trade_calendar import load_calendar

# ── 请求ID上下文 ─────────────────────────────────────────────

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


# ── 日志配置 ────────────────────────────────────────────────

class RequestContextFilter(logging.Filter):
    """日志自动携带 request_id"""
    def filter(self, record):
        record.request_id = request_id_ctx.get("-")
        return True


class SafeFormatter(logging.Formatter):
    """格式化时为缺失的自定义字段提供默认值，避免 KeyError"""
    _DEFAULTS = {"request_id": "-"}

    def format(self, record):
        for key, default in self._DEFAULTS.items():
            if not hasattr(record, key):
                setattr(record, key, default)
        return super().format(record)


_fmt = "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(SafeFormatter(_fmt))
_handler.addFilter(RequestContextFilter())

logging.basicConfig(level=logging.INFO, handlers=[_handler])
# uvicorn 子 logger 也挂上同一个 handler
for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "watchfiles"):
    logging.getLogger(name).addHandler(_handler)

logger = logging.getLogger("app")


# ── 请求 ID 中间件 ──────────────────────────────────────────

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-Id", str(uuid.uuid4())[:8])
        request.state.request_id = rid
        request_id_ctx.set(rid)
        metrics.record_api_request()

        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response


# ── httpx 全局客户端 ────────────────────────────────────────

_http_client: httpx.AsyncClient | None = None


async def init_http_client() -> None:
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30,
        ),
    )


async def close_http_client() -> None:
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None


def get_http_client() -> httpx.AsyncClient:
    return _http_client


# ── Stream Consumer ──────────────────────────────────────────

async def _run_consumer(session_factory):
    """Stream 消费者循环"""
    from processors.pipeline import stream_consumer
    await stream_consumer(session_factory)


# ── lifespan ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("服务启动中...")

    # 1. 配置
    import config as config_module
    settings = Settings()
    app.state.settings = settings
    config_module.settings = settings  # 注入到 config 模块，供 scheduler/fetchers 使用

    # 2. 数据库
    init_engine(settings)

    # 3. Redis
    await init_redis(settings.REDIS_URL, settings.REDIS_MAX_CONNECTIONS)
    await init_consumer_group()

    # 4. 交易日历
    from database import async_session_factory
    async with async_session_factory() as session:
        await load_calendar(session)
        await session.commit()

    # 5. httpx 客户端
    await init_http_client()

    # 6. Hub 编排器（注入到 app.state，路由层通过 request.app.state.hub 访问）
    from hub.service import ServiceHub
    app.state.hub = ServiceHub(async_session_factory)

    # 7. scheduler
    from scheduler import create_scheduler, init_scheduler_http, close_scheduler_http, check_and_catchup
    await init_scheduler_http()
    sched = create_scheduler()
    sched.start()
    await check_and_catchup()

    # 8. stream_consumer
    consumer_task = asyncio.create_task(_run_consumer(async_session_factory))

    logger.info("服务启动完成")
    yield

    # ===== 关闭 =====
    logger.info("服务关闭中...")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    sched.shutdown(wait=True)
    await close_scheduler_http()
    await close_http_client()
    await close_redis()
    await dispose_engine()
    logger.info("服务已关闭")


# ── FastAPI app ─────────────────────────────────────────────

from fastapi.responses import JSONResponse
from database import json_serializer


class CustomJSONResponse(JSONResponse):
    """自定义 JSON 响应，处理 Decimal/datetime 等类型"""
    def render(self, content) -> bytes:
        import json
        return json.dumps(content, ensure_ascii=False, default=json_serializer).encode("utf-8")


app = FastAPI(
    title="金快查 数据中台",
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=CustomJSONResponse,
)

# 中间件挂载顺序: 先加的后执行 (LIFO)
# 实际执行顺序: RequestId → CORS → Auth → 路由
try:
    from auth.middleware import AuthMiddleware
    app.add_middleware(AuthMiddleware)
except Exception as e:
    logger.warning("AuthMiddleware 未就绪，跳过: %s", e)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_methods=settings.CORS_ALLOW_METHODS.split(","),
    allow_headers=settings.CORS_ALLOW_HEADERS.split(","),
)
app.add_middleware(RequestIdMiddleware)

# 全局异常处理器
register_exception_handlers(app)


# ── 路由注册 ────────────────────────────────────────────────

from routers import main_router
app.include_router(main_router)


@app.get("/")
async def root():
    return {"message": "金快查 v2 API", "docs": "/docs"}