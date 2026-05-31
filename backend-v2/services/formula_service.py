"""
公式 CRUD 服务 — 乐观锁 + 每用户最多10个 + 名称唯一性
"""
import asyncio
import logging
from typing import Optional

from sqlalchemy import text

from constants import FORMULA_MAX_COUNT, FORMULA_MAX_FUNDS
from exceptions import (
    BadRequestException,
    ConflictException,
    FormulaParseException,
    NotFoundException,
)

logger = logging.getLogger("app")

# P1 并发限制
_compute_semaphore = asyncio.Semaphore(1)


# ── 公式 CRUD ───────────────────────────────────────────────


async def list_formulas(session_factory, user_id: str) -> list[dict]:
    """列出用户的所有公式"""
    async with session_factory() as session:
        result = await session.execute(text(
            "SELECT * FROM user_formula WHERE user_id = :uid ORDER BY sort_order, id"
        ), {"uid": user_id})
        return [dict(r._mapping) for r in result.fetchall()]


async def get_formula(session_factory, user_id: str, formula_id: int) -> dict:
    """获取单个公式"""
    async with session_factory() as session:
        row = await session.execute(text(
            "SELECT * FROM user_formula WHERE id = :id AND user_id = :uid"
        ), {"id": formula_id, "uid": user_id})
        result = row.first()

    if not result:
        raise NotFoundException(f"公式 {formula_id} 不存在")
    return dict(result._mapping)


async def create_formula(session_factory, user_id: str, data: dict) -> dict:
    """创建公式（先校验表达式，检查名称唯一，检查数量上限）"""
    expression = data.get("expression", "")
    name = data.get("name", "")

    # 校验表达式
    _validate_expression_syntax(expression)

    async with session_factory() as session:
        # 检查数量上限
        count = await session.execute(text(
            "SELECT COUNT(*) FROM user_formula WHERE user_id = :uid"
        ), {"uid": user_id})
        if (count.scalar() or 0) >= FORMULA_MAX_COUNT:
            raise BadRequestException(f"每用户最多 {FORMULA_MAX_COUNT} 个公式")

        # 检查名称唯一
        dup = await session.execute(text(
            "SELECT COUNT(*) FROM user_formula WHERE user_id = :uid AND name = :name"
        ), {"uid": user_id, "name": name})
        if (dup.scalar() or 0) > 0:
            raise BadRequestException("公式名称已存在")

        # 插入
        result = await session.execute(text("""
            INSERT INTO user_formula (user_id, group_id, name, expression, description, sort_order)
            VALUES (:uid, :gid, :name, :expr, :desc, :sort)
            RETURNING *
        """), {
            "uid": user_id,
            "gid": data.get("group_id"),
            "name": name,
            "expr": expression,
            "desc": data.get("description"),
            "sort": data.get("sort_order", 0),
        })
        await session.commit()
        return dict(result.first()._mapping)


async def update_formula(
    session_factory,
    user_id: str,
    formula_id: int,
    data: dict,
    version: int,
) -> dict:
    """
    修改公式（乐观锁）。
    version 不匹配 → 返回 409。
    """
    if "expression" in data:
        _validate_expression_syntax(data["expression"])

    async with session_factory() as session:
        # 乐观锁检查
        current = await session.execute(text(
            "SELECT version FROM user_formula WHERE id = :id AND user_id = :uid"
        ), {"id": formula_id, "uid": user_id})
        cur = current.first()
        if not cur:
            raise NotFoundException(f"公式 {formula_id} 不存在")
        if cur._mapping["version"] != version:
            raise ConflictException(
                f"版本冲突: 期望 {version}，当前 {cur._mapping['version']}",
                detail={"current_version": cur._mapping["version"]},
            )

        # 名称唯一性（如果改了名称）
        if "name" in data:
            dup = await session.execute(text(
                "SELECT COUNT(*) FROM user_formula "
                "WHERE user_id = :uid AND name = :name AND id != :id"
            ), {"uid": user_id, "name": data["name"], "id": formula_id})
            if (dup.scalar() or 0) > 0:
                raise BadRequestException("公式名称已存在")

        # 更新
        sets = []
        params = {"id": formula_id, "uid": user_id, "ver": version}
        for field in ("name", "expression", "description", "group_id", "sort_order"):
            if field in data:
                sets.append(f"{field} = :{field}")
                params[field] = data[field]
        sets.append("version = version + 1")
        sets.append("updated_at = NOW()")

        result = await session.execute(text(
            f"UPDATE user_formula SET {', '.join(sets)} "
            f"WHERE id = :id AND user_id = :uid AND version = :ver RETURNING *"
        ), params)
        await session.commit()
        row = result.first()
        if not row:
            raise ConflictException("更新失败，请重试")
        return dict(row._mapping)


async def delete_formula(session_factory, user_id: str, formula_id: int) -> None:
    """删除公式"""
    async with session_factory() as session:
        result = await session.execute(text(
            "DELETE FROM user_formula WHERE id = :id AND user_id = :uid RETURNING id"
        ), {"id": formula_id, "uid": user_id})
        await session.commit()
        if not result.first():
            raise NotFoundException(f"公式 {formula_id} 不存在")


# ── 公式组 CRUD ─────────────────────────────────────────────


async def list_formula_groups(session_factory, user_id: str) -> list[dict]:
    """列出用户的公式组"""
    async with session_factory() as session:
        result = await session.execute(text(
            "SELECT * FROM user_formula_group WHERE user_id = :uid ORDER BY sort_order, id"
        ), {"uid": user_id})
        return [dict(r._mapping) for r in result.fetchall()]


async def create_formula_group(session_factory, user_id: str, data: dict) -> dict:
    """创建公式组"""
    async with session_factory() as session:
        result = await session.execute(text("""
            INSERT INTO user_formula_group (user_id, name, description, sort_order)
            VALUES (:uid, :name, :desc, :sort) RETURNING *
        """), {
            "uid": user_id,
            "name": data.get("name", ""),
            "desc": data.get("description"),
            "sort": data.get("sort_order", 0),
        })
        await session.commit()
        return dict(result.first()._mapping)


async def update_formula_group(
    session_factory,
    user_id: str,
    group_id: int,
    data: dict,
) -> dict:
    """修改公式组"""
    async with session_factory() as session:
        sets = []
        params = {"id": group_id, "uid": user_id}
        for field in ("name", "description", "sort_order"):
            if field in data:
                sets.append(f"{field} = :{field}")
                params[field] = data[field]
        sets.append("updated_at = NOW()")

        result = await session.execute(text(
            f"UPDATE user_formula_group SET {', '.join(sets)} "
            f"WHERE id = :id AND user_id = :uid RETURNING *"
        ), params)
        await session.commit()
        row = result.first()
        if not row:
            raise NotFoundException(f"公式组 {group_id} 不存在")
        return dict(row._mapping)


async def delete_formula_group(session_factory, user_id: str, group_id: int) -> None:
    """删除公式组"""
    async with session_factory() as session:
        result = await session.execute(text(
            "DELETE FROM user_formula_group WHERE id = :id AND user_id = :uid RETURNING id"
        ), {"id": group_id, "uid": user_id})
        await session.commit()
        if not result.first():
            raise NotFoundException(f"公式组 {group_id} 不存在")


# ── 校验 ────────────────────────────────────────────────────


def _validate_expression_syntax(expression: str) -> None:
    """基础表达式校验（详细 AST 校验由 formula_engine/parser 完成）"""
    if not expression or not expression.strip():
        raise FormulaParseException("表达式不能为空")
    if len(expression) > 1000:
        raise FormulaParseException("表达式过长（最大 1000 字符）")


async def validate_expression(expression: str) -> dict:
    """公开接口：校验表达式"""
    _validate_expression_syntax(expression)
    return {"valid": True, "expression": expression}
