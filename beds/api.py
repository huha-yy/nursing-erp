from ninja import Query, Router
from ninja.pagination import PageNumberPagination, paginate

from nursing_erp.api_scope import resolve_building_scope

from .models import Bed
from .services import occupancy_stats

router = Router(tags=["床位台账"])


@router.get("/beds/", response=list[dict])
@paginate(PageNumberPagination, page_size=50)
def list_beds(
    request,
    building: str | None = Query(None, description="楼栋名称筛选，如 1号楼"),
    floor: str | None = Query(None, description="楼层名称筛选，如 1层"),
    status: str | None = Query(None, description="床位状态筛选：可用/维修/停用"),
    occupied: bool | None = Query(None, description="占用筛选：true 已住 / false 空床"),
    search: str | None = Query(None, description="房间号/床位号模糊搜索"),
):
    """查询床位列表，占用关系由老人档案派生。

    统计/台账类端点的 scope 语义是"覆盖"而非叠加：楼栋受限请求里
    ?building= 被 scope 覆盖（scope 即答案，叠加只会得到冲突空集）。
    """
    scope = resolve_building_scope(request)
    if scope:
        building = scope  # 覆盖显式参数
    qs = Bed.objects.select_related("room__floor__building").prefetch_related("occupant")
    if building:
        qs = qs.filter(room__floor__building__name=building)
    if floor:
        qs = qs.filter(room__floor__name=floor)
    if status:
        qs = qs.filter(status=status)
    if occupied is not None:
        qs = qs.filter(occupant__isnull=not occupied)
    if search:
        qs = qs.filter(room__number__icontains=search) | qs.filter(number__icontains=search)
    qs = qs.order_by("room__floor__building__name", "room__floor__name", "room__number", "number")
    return [format_bed(b) for b in qs]


@router.get("/beds/occupancy/", response=dict)
def bed_occupancy(
    request,
    building: str | None = Query(None, description="只看单栋（缺省全院）"),
):
    """入住率统计：按楼栋 total/occupied/free/maintenance/rate + 全院合计。

    scope 覆盖语义同 /beds/：楼栋受限请求只返回本楼（显式参数被覆盖）。
    """
    scope = resolve_building_scope(request)
    return occupancy_stats(scope or building)


def format_bed(b: Bed) -> dict:
    occupant = b.occupant.first()  # prefetch 缓存，一人一床约束保证至多 1 条
    return {
        "id": b.id,
        "building": b.room.floor.building.name,
        "floor": b.room.floor.name,
        "room": b.room.number,
        "bed": b.number,
        "full_location": b.full_location,
        "status": b.status,
        "occupant": None
        if occupant is None
        else {
            "id": occupant.id,
            "name": occupant.name,
            "care_level": occupant.care_level,
        },
    }
