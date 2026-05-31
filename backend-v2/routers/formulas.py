"""公式路由"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from auth.dependencies import get_user_id
from hub import get_hub
from hub.service import ServiceHub

router = APIRouter(prefix="/api/v1/formulas", tags=["formulas"])


class FormulaCreate(BaseModel):
    name: str
    expression: str
    description: Optional[str] = None


class FormulaUpdate(BaseModel):
    name: Optional[str] = None
    expression: Optional[str] = None
    description: Optional[str] = None


class FormulaGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


@router.get("")
async def list_formulas(user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.list_formulas(user_id)


@router.post("")
async def create_formula(body: FormulaCreate, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.create_formula(user_id, body.model_dump())


@router.get("/groups")
async def list_groups(user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.list_formula_groups(user_id)


@router.post("/groups")
async def create_group(body: FormulaGroupCreate, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.create_formula_group(user_id, body.model_dump())


@router.put("/groups/{group_id}")
async def update_group(group_id: int, body: FormulaGroupCreate, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.update_formula_group(user_id, group_id, body.model_dump())


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    await hub.delete_formula_group(user_id, group_id)
    return {"deleted": True}


@router.get("/{formula_id}")
async def get_formula(formula_id: int, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.get_formula(user_id, formula_id)


@router.put("/{formula_id}")
async def update_formula(formula_id: int, body: FormulaUpdate, version: int = Query(...), user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.update_formula(user_id, formula_id, body.model_dump(), version)


@router.delete("/{formula_id}")
async def delete_formula(formula_id: int, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    await hub.delete_formula(user_id, formula_id)
    return {"deleted": True}
