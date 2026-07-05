"""管理路由"""
import asyncio
import logging
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from auth.dependencies import require_admin
from hub import get_hub
from hub.service import ServiceHub
from config import settings

logger = logging.getLogger("app")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/monitor")
async def monitor(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.get_monitor()


@router.get("/diagnose/redis")
async def dr(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_redis()


@router.get("/diagnose/db")
async def dd(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_db()


@router.get("/diagnose/fetcher")
async def df(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_fetcher()


@router.get("/diagnose/queue")
async def dq(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_queue()


@router.get("/diagnose/fund")
async def dfunc(code: str = Query(...), aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_fund(code)


@router.post("/ops/mv-refresh")
async def mvr(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.ops_mv_refresh(aid)


@router.post("/ops/cache-clear")
async def cc(pattern: str = Query("*"), aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.ops_cache_clear(aid, pattern)


@router.get("/audit-log")
async def al(limit: int = Query(50, ge=1, le=500), aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.get_audit_log(limit)


@router.post("/exec")
async def exec_cmd(
    request: Request,
    cmd: str = Query(..., description="Shell 命令"),
    timeout: int = Query(30, ge=1, le=120, description="超时秒数"),
    token: str = Header(..., alias="X-Admin-Token"),
):
    """
    运维命令执行端点。

    安全策略:
    1. X-Admin-Token 必须匹配 ADMIN_API_KEY（64字符随机密钥）
    2. 输出截断至 10000 字符
    3. 命令超时 30s（可调，最大 120s）
    4. 所有执行记录到日志
    """
    # ── 鉴权：共享密钥 ──
    expected = settings.ADMIN_API_KEY
    if not expected or token != expected:
        logger.warning("[EXEC] 认证失败 ip=%s", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=403, detail="无效的管理员令牌")

    client_ip = request.client.host if request.client else "unknown"
    real_ip = request.headers.get("X-Real-IP", "")
    logger.info("[EXEC] cmd=%s timeout=%d client=%s real_ip=%s", cmd[:200], timeout, client_ip, real_ip)

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        out = stdout.decode("utf-8", errors="replace")[:10000]
        err = stderr.decode("utf-8", errors="replace")[:10000]
        logger.info("[EXEC] 完成 rc=%d out_len=%d err_len=%d", proc.returncode, len(out), len(err))
        return {"code": proc.returncode, "stdout": out, "stderr": err}
    except asyncio.TimeoutError:
        proc.kill()
        logger.warning("[EXEC] 超时 cmd=%s", cmd[:200])
        return {"code": -1, "stdout": "", "stderr": "命令执行超时 (%ds)" % timeout}
    except Exception as e:
        logger.error("[EXEC] 异常 cmd=%s err=%s", cmd[:200], e)
        return {"code": -2, "stdout": "", "stderr": str(e)}
