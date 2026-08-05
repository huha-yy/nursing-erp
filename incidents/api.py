from typing import List, Optional

from ninja import Router, Query, Schema
from ninja.pagination import paginate, PageNumberPagination

from .models import IncidentReport

router = Router(tags=["异常上报"])


class IncidentIn(Schema):
    resident_id: int
    category: str  # fall/illness/mood/refuse_eat/wander/skin/other
    severity: str = "info"  # info/warning/danger
    description: str = ""


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
            "created_at": i.created_at.isoformat(),
        }
        for i in qs
    ]


@router.post("/incidents/", response=dict)
def create_incident(request, payload: IncidentIn):
    """创建异常上报 — Agent 通过对话写入"""
    incident = IncidentReport.objects.create(
        resident_id=payload.resident_id,
        category=payload.category,
        severity=payload.severity,
        description=payload.description,
    )
    return {"id": incident.id, "status": "created", "severity": payload.severity}
