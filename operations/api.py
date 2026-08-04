from typing import List, Optional

from ninja import Router, Query
from ninja.pagination import paginate, PageNumberPagination

from .models import InventoryItem, MaintenanceOrder

router = Router(tags=["院内事务"])


@router.get("/inventory/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_inventory(request, category: Optional[str] = Query(None, description="分类筛选")):
    qs = InventoryItem.objects.all()
    if category:
        qs = qs.filter(category=category)
    return [
        {
            "id": i.id, "name": i.name, "category": i.category,
            "quantity": i.quantity, "unit": i.unit,
            "safety_stock": i.safety_stock, "is_low_stock": i.is_low_stock,
        }
        for i in qs
    ]


@router.get("/inventory/low-stock/", response=List[dict])
def list_low_stock(request):
    """库存不足预警列表"""
    qs = InventoryItem.objects.all()
    low = [i for i in qs if i.is_low_stock]
    return [
        {"id": i.id, "name": i.name, "quantity": i.quantity, "unit": i.unit,
         "safety_stock": i.safety_stock, "gap": i.safety_stock - i.quantity}
        for i in low
    ]


@router.get("/maintenance/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_maintenance(request, status: Optional[str] = Query(None, description="状态筛选")):
    qs = MaintenanceOrder.objects.all()
    if status:
        qs = qs.filter(status=status)
    return [
        {
            "id": m.id, "equipment_name": m.equipment_name,
            "location": m.location, "fault_description": m.fault_description,
            "status": m.status, "status_display": m.get_status_display(),
            "reported_by": m.reported_by,
            "reported_at": m.reported_at.isoformat(),
        }
        for m in qs
    ]
