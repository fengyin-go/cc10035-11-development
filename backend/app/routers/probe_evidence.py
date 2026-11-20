"""探针证据专用接口：试跑、许可、分站点证据数据集、证据清单、发布闸口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.probe_evidence.catalog import CatalogError
from app.probe_evidence.permissions import PermissionError as DomainPermissionError
from app.probe_evidence.service import get_service

router = APIRouter(prefix="/api/probe-evidence", tags=["探针证据"])


class TrialPayload(BaseModel):
    fields: list[str] | None = None
    sample_version: str | None = None


class AdhocTrialPayload(BaseModel):
    site: str
    page_id: str
    # 字段名 -> 选择器
    fields: dict[str, str]
    template_ids: list[int] = Field(default_factory=list)
    sample_version: str | None = None


class GrantPayload(BaseModel):
    allowed_fields: list[str] = Field(default_factory=list)
    note: str = ""


class UpdatePermissionPayload(BaseModel):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    note: str = ""


def _service():
    return get_service()


@router.get("/pages")
def list_pages() -> dict[str, Any]:
    """采样页目录：页面、版本与可用字段。"""
    return {"items": _service().list_pages()}


@router.get("/pages/{page_id}/validation")
def validate_page(page_id: str, sample_version: str | None = None) -> dict[str, Any]:
    """校验采样页的数据归属与可用字段。"""
    try:
        return _service().validate_sampling(page_id, sample_version)
    except CatalogError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/templates")
def list_templates() -> dict[str, Any]:
    return {"items": _service().list_templates()}


@router.get("/templates/{template_id}")
def get_template(template_id: int) -> dict[str, Any]:
    template = _service().get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"模板 {template_id} 未登记")
    return template


@router.get("/permissions/{site}")
def permission_history(site: str) -> dict[str, Any]:
    service = _service()
    try:
        return {"site": site, "current": service.current_permission(site),
                "history": service.permission_history(site)}
    except DomainPermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/permissions/{site}/grant")
def grant_permission(site: str, payload: GrantPayload) -> dict[str, Any]:
    """以完整字段集登记新许可版本。"""
    return {"ok": True, "permission": _service().grant_permission(
        site, payload.allowed_fields, payload.note)}


@router.post("/permissions/{site}/update")
def update_permission(site: str, payload: UpdatePermissionPayload) -> dict[str, Any]:
    """补许可/收回许可，生成下一许可版本（旧版本保留）。"""
    try:
        return {"ok": True, "permission": _service().update_permission(
            site, payload.added, payload.removed, note=payload.note)}
    except DomainPermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/templates/{template_id}/trial")
def run_template_trial(template_id: int, payload: TrialPayload) -> dict[str, Any]:
    """按模板发起探针试跑，结果回写模板证据清单。"""
    try:
        result = _service().run_template_trial(
            template_id, fields=payload.fields, sample_version=payload.sample_version)
    except CatalogError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DomainPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    return {"ok": True, **result.to_dict()}


@router.post("/trials")
def run_adhoc_trial(payload: AdhocTrialPayload) -> dict[str, Any]:
    """不依赖模板登记的试跑入口（仍受站点许可与样本归属约束）。"""
    try:
        result = _service().run_trial(
            site=payload.site,
            page_id=payload.page_id,
            fields=payload.fields,
            template_ids=payload.template_ids,
            sample_version=payload.sample_version,
        )
    except CatalogError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DomainPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"ok": True, **result.to_dict()}


@router.get("/datasets")
def list_datasets() -> dict[str, Any]:
    """分站点探针证据数据集总览。"""
    return {"items": _service().list_datasets()}


@router.get("/datasets/{site}")
def site_dataset(site: str) -> dict[str, Any]:
    service = _service()
    return {"summary": service.dataset_summary(site),
            "batches": service.list_site_batches(site)}


@router.get("/datasets/{site}/batches/{batch_id}")
def get_batch(site: str, batch_id: str) -> dict[str, Any]:
    try:
        return _service().get_batch(site, batch_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc


@router.get("/manifest")
def list_manifest(template_id: int | None = None) -> dict[str, Any]:
    """模板证据清单：实际交付字段及样本出处。"""
    return {"items": _service().list_manifest(template_id)}


@router.get("/templates/{template_id}/publish-check")
def publish_check(template_id: int) -> dict[str, Any]:
    """发布闸口：用实际采到的证据核对每个字段选择器能否发布。"""
    try:
        return _service().check_template_publish(template_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
