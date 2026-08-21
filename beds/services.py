"""床位聚合统计 — /api/beds/occupancy/ 与 /beds/ 看板共用同一份数学。"""

from django.db.models import Count, Q

from .models import Bed, Building


def occupancy_stats(building: str | None = None) -> dict:
    """按楼栋聚合床位状态。

    口径：
    - occupied：已链接老人的床（一人一床约束保证至多 1 人）
    - free：状态"可用"且未占用
    - maintenance / disabled：按床位状态计（与 occupied 独立统计，
      维修床若仍挂着老人会同时计入 occupied）
    - rate = occupied / total，四舍五入两位小数；total=0 时为 0
    """
    buildings = Building.objects.order_by("name")
    if building:
        buildings = buildings.filter(name=building)

    rows = []
    for b in buildings:
        agg = Bed.objects.filter(room__floor__building=b).aggregate(
            total=Count("id"),
            occupied=Count("occupant", filter=Q(occupant__isnull=False)),
            free=Count("id", filter=Q(status=Bed.Status.AVAILABLE, occupant__isnull=True)),
            maintenance=Count("id", filter=Q(status=Bed.Status.MAINTENANCE)),
            disabled=Count("id", filter=Q(status=Bed.Status.DISABLED)),
        )
        rows.append({"building": b.name, **agg, "rate": _rate(agg["occupied"], agg["total"])})

    total = {
        k: sum(r[k] for r in rows)
        for k in ("total", "occupied", "free", "maintenance", "disabled")
    }
    return {"buildings": rows, "total": {**total, "rate": _rate(total["occupied"], total["total"])}}


def _rate(occupied: int, total: int) -> float:
    return round(occupied / total, 2) if total else 0
