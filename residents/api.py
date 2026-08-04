from typing import List, Optional
from datetime import date

from ninja import Router, Query
from ninja.pagination import paginate, PageNumberPagination

from .models import Resident, NursingLog, HealthRecord, MedicationRecord

router = Router(tags=["老人照护"])


@router.get("/residents/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_residents(
    request,
    building: Optional[str] = Query(None, description="楼栋筛选"),
    care_level: Optional[str] = Query(None, description="护理等级筛选"),
    search: Optional[str] = Query(None, description="姓名模糊搜索"),
):
    """查询老人列表，支持按楼栋/护理等级/姓名筛选"""
    qs = Resident.objects.all()
    if building:
        qs = qs.filter(building=building)
    if care_level:
        qs = qs.filter(care_level=care_level)
    if search:
        qs = qs.filter(name__icontains=search)
    return [format_resident(r) for r in qs]


@router.get("/residents/{resident_id}/", response=dict)
def get_resident(request, resident_id: int):
    """查询老人详情"""
    r = Resident.objects.get(id=resident_id)
    return format_resident(r, detail=True)


@router.get("/residents/{resident_id}/logs/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_resident_logs(
    request,
    resident_id: int,
    log_date: Optional[date] = Query(None, description="日期筛选"),
):
    """查询某老人的护理日志"""
    qs = NursingLog.objects.filter(resident_id=resident_id)
    if log_date:
        qs = qs.filter(log_date=log_date)
    return [
        {
            "id": log.id,
            "log_date": str(log.log_date),
            "category": log.category,
            "category_display": log.get_category_display(),
            "detail": log.detail,
            "staff_name": log.staff_name,
        }
        for log in qs
    ]


@router.get("/residents/{resident_id}/health/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_resident_health(request, resident_id: int):
    """查询某老人的健康数据记录"""
    qs = HealthRecord.objects.filter(resident_id=resident_id)
    return [
        {
            "id": h.id, "record_date": str(h.record_date),
            "blood_pressure": h.blood_pressure, "blood_sugar": float(h.blood_sugar) if h.blood_sugar else None,
            "heart_rate": h.heart_rate, "weight": float(h.weight) if h.weight else None,
            "temperature": float(h.temperature) if h.temperature else None,
            "note": h.note,
        }
        for h in qs
    ]


@router.get("/residents/{resident_id}/medications/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_resident_medications(request, resident_id: int):
    """查询某老人的用药记录"""
    qs = MedicationRecord.objects.filter(resident_id=resident_id)
    return [
        {
            "id": m.id, "medicine_name": m.medicine_name,
            "dosage": m.dosage, "frequency": m.frequency,
            "frequency_display": m.get_frequency_display(),
            "start_date": str(m.start_date),
            "end_date": str(m.end_date) if m.end_date else None,
            "is_active": m.is_active, "note": m.note,
        }
        for m in qs
    ]


def format_resident(r: Resident, detail: bool = False) -> dict:
    data = {
        "id": r.id,
        "name": r.name,
        "gender": r.gender,
        "age": r.age,
        "building": r.building,
        "floor": r.floor,
        "room": r.room,
        "care_level": r.care_level,
    }
    if detail:
        data.update({
            "id_card": r.id_card,
            "admission_date": str(r.admission_date) if r.admission_date else None,
            "diagnosis": r.diagnosis,
            "allergies": r.allergies,
            "contact_name": r.contact_name,
            "contact_phone": r.contact_phone,
            "notes": r.notes,
        })
    return data
