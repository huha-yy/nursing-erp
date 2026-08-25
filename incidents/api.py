from typing import List, Optional

from django.utils import timezone
from ninja import Router, Query, Schema
from ninja.errors import HttpError
from ninja.pagination import paginate, PageNumberPagination

from nursing_erp.api_scope import resident_for_write, scope_filter

from .models import IncidentReport

router = Router(tags=["异常上报"])


class IncidentIn(Schema):
    resident_id: int
    category: str  # fall/illness/mood/refuse_eat/wander/skin/other
    severity: str = "info"  # info/warning/danger
    description: str = ""


class HandleIn(Schema):
    operator: str = ""  # 处理人署名（AI 侧传 nursing 会话姓名）


@router.get("/incidents/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_incidents(
    request,
    severity: Optional[str] = Query(None, description="严重程度(info/warning/danger)"),
    handled: Optional[bool] = Query(None, description="是否已处理"),
    category: Optional[str] = Query(None, description="异常类型"),
):
    qs = IncidentReport.objects.select_related("resident").all()
    if severity:
        qs = qs.filter(severity=severity)
    if handled is not None:
        qs = qs.filter(handled=handled)
    if category:
        qs = qs.filter(category=category)
    qs = scope_filter(qs, request, "resident__building")
    return [
        {
            "id": i.id,
            "resident_name": i.resident.name,
            "building": i.resident.building,
            "category": i.category,
            "category_display": i.get_category_display(),
            "severity": i.severity,
            "severity_display": i.get_severity_display(),
            "description": i.description,
            "handled": i.handled,
            "handled_by": i.handled_by,
            "handled_at": i.handled_at.isoformat() if i.handled_at else None,
            "created_at": i.created_at.isoformat(),
        }
        for i in qs
    ]


@router.post("/incidents/{incident_id}/handle/", response=dict)
def handle_incident(request, incident_id: int, payload: HandleIn = None):
    """标记已处理（2026-08-25）— AI 侧告警页的写路径。

    幂等：重复调用不报错也不改写首次的处理人/时间。写前过
    resident_for_write 楼栋守卫（不存在 404 / 越栋 403）。
    """
    incident = IncidentReport.objects.filter(pk=incident_id).first()
    if incident is None:
        raise HttpError(404, "异常上报不存在")
    resident_for_write(request, incident.resident_id)

    if incident.handled:
        return {"id": incident.id, "status": "already_handled"}

    incident.handled = True
    incident.handled_by = ((payload.operator if payload else "") or "")[:30]
    incident.handled_at = timezone.now()
    incident.save(update_fields=["handled", "handled_by", "handled_at"])
    return {
        "id": incident.id,
        "status": "handled",
        "handled_by": incident.handled_by,
        "handled_at": incident.handled_at.isoformat(),
    }


@router.post("/incidents/", response=dict)
def create_incident(request, payload: IncidentIn):
    """创建异常上报 — Agent 通过对话写入"""
    resident_for_write(request, payload.resident_id)  # 404/403 楼栋守卫
    incident = IncidentReport.objects.create(
        resident_id=payload.resident_id,
        category=payload.category,
        severity=payload.severity,
        description=payload.description,
    )
    return {"id": incident.id, "status": "created", "severity": payload.severity}
