"""
Redis Streams 消息队列
生产者（fetcher/scheduler）发布事件，消费者（pipeline）处理。
"""
import json
import logging
from datetime import datetime, timezone

from constants import (
    STREAM_BLOCK_MS,
    STREAM_CONSUMER,
    STREAM_GROUP,
    STREAM_KEY,
    STREAM_MAX_LEN,
    STREAM_READ_COUNT,
)

logger = logging.getLogger("app")


def _get_pool():
    """运行时获取 Redis 连接池（避免 import 时 _pool 为 None）"""
    from cache import _pool
    return _pool


async def init_consumer_group() -> None:
    """创建消费者组（已存在则跳过），失败时重试"""
    for attempt in range(3):
        try:
            pool = _get_pool()
            if pool is None:
                logger.warning("Redis 连接池未就绪，跳过消费者组初始化")
                return
            await pool.xgroup_create(STREAM_KEY, STREAM_GROUP, id="0", mkstream=True)
            logger.info("Stream 消费者组初始化: %s/%s", STREAM_KEY, STREAM_GROUP)
            return
        except Exception as e:
            if "BUSYGROUP" in str(e):
                logger.info("Stream 消费者组已存在: %s/%s", STREAM_KEY, STREAM_GROUP)
                return
            logger.warning("Stream 消费者组创建失败 (attempt %d/3): %s", attempt + 1, e)
            if attempt < 2:
                await asyncio.sleep(1)
    logger.error("Stream 消费者组创建失败，已重试 3 次")


async def publish_event(event_type: str, payload: dict) -> str:
    """
    生产者：发布事件到 Stream。
    返回消息 ID，失败返回空字符串（降级，不抛异常）。
    """
    try:
        msg_id = await _get_pool().xadd(
            STREAM_KEY,
            {
                "type": event_type,
                "data": json.dumps(payload, ensure_ascii=False, default=str),
                "ts": datetime.now(timezone.utc).isoformat(),
            },
            maxlen=STREAM_MAX_LEN,
        )
        return msg_id
    except Exception:
        logger.error("MQ publish failed: type=%s", event_type)
        return ""


async def consume_events(
    count: int = STREAM_READ_COUNT,
    block_ms: int = STREAM_BLOCK_MS,
) -> list[dict]:
    """
    消费者：读取事件列表。
    无事件时阻塞 block_ms 毫秒后返回空列表。
    """
    try:
        results = await _get_pool().xreadgroup(
            STREAM_GROUP,
            STREAM_CONSUMER,
            streams={STREAM_KEY: ">"},
            count=count,
            block=block_ms,
        )
        events = []
        for _stream_name, messages in results:
            for msg_id, fields in messages:
                events.append({
                    "id": msg_id,
                    "type": fields["type"],
                    "data": json.loads(fields["data"]),
                    "ts": fields.get("ts"),
                })
        return events
    except Exception:
        return []


async def ack_event(msg_id: str) -> None:
    """确认消费（处理成功后调用）"""
    try:
        await _get_pool().xack(STREAM_KEY, STREAM_GROUP, msg_id)
    except Exception:
        pass


async def get_stream_length() -> int:
    """监控：Stream 未消费事件数，失败返回 -1"""
    try:
        info = await _get_pool().xinfo_stream(STREAM_KEY)
        return info["length"]
    except Exception:
        return -1
