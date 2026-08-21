from typing import List, Optional
from datetime import date

from django.db.models import Q
from ninja import Router, Query
from ninja.pagination import paginate, PageNumberPagination
from ninja.errors import HttpError

from nursing_erp.api_scope import resolve_building_scope, scope_filter

from .models import Employee, Schedule, Attendance


def _scoped_employee_qs(request):
    """楼栋范围下的员工可见集：本楼 + 未分配楼栋的管理层（building=""）。"""
    scope = resolve_building_scope(request)
    if not scope:
        return Employee.objects.all()
    return Employee.objects.filter(Q(building=scope) | Q(building=""))

router = Router(tags=["人员管理"])


@router.get("/employees/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_employees(
    request,
    dept: Optional[str] = Query(None, description="部门筛选"),
    is_caregiver: Optional[bool] = Query(None, description="是否护理员"),
):
    qs = _scoped_employee_qs(request)
    if dept:
        qs = qs.filter(dept=dept)
    if is_caregiver is not None:
        qs = qs.filter(is_caregiver=is_caregiver)
    return [
        {
            "id": e.id, "name": e.name, "dept": e.dept, "building": e.building,
            "phone": e.phone, "is_caregiver": e.is_caregiver,
        }
        for e in qs
    ]


@router.get("/employees/{employee_id}/attendance/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_employee_attendance(
    request,
    employee_id: int,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
):
    employee = _scoped_employee_qs(request).filter(pk=employee_id).first()
    if employee is None:
        raise HttpError(404, "员工不存在或无权访问")
    qs = Attendance.objects.filter(employee_id=employee_id)
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    return [
        {
            "date": str(a.date),
            "clock_in": a.clock_in.isoformat() if a.clock_in else None,
            "clock_out": a.clock_out.isoformat() if a.clock_out else None,
        }
        for a in qs
    ]


@router.get("/schedules/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_schedules(
    request,
    date_param: Optional[date] = Query(None, alias="date", description="日期"),
    building: Optional[str] = Query(None, description="楼栋"),
):
    qs = Schedule.objects.select_related("employee").all()
    if date_param:
        qs = qs.filter(date=date_param)
    if building:
        qs = qs.filter(building=building)
    qs = scope_filter(qs, request)
    return [
        {
            "id": s.id, "employee_name": s.employee.name, "date": str(s.date),
            "shift": s.shift, "building": s.building, "floor": s.floor,
            "task_note": s.task_note,
        }
        for s in qs
    ]
