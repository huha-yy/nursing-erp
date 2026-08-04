from typing import List, Optional
from datetime import date

from ninja import Router, Query
from ninja.pagination import paginate, PageNumberPagination

from .models import Employee, Schedule, Attendance

router = Router(tags=["人员管理"])


@router.get("/employees/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_employees(
    request,
    dept: Optional[str] = Query(None, description="部门筛选"),
    is_caregiver: Optional[bool] = Query(None, description="是否护理员"),
):
    qs = Employee.objects.all()
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
    return [
        {
            "id": s.id, "employee_name": s.employee.name, "date": str(s.date),
            "shift": s.shift, "building": s.building, "floor": s.floor,
            "task_note": s.task_note,
        }
        for s in qs
    ]
