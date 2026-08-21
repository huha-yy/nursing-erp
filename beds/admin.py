from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from unfold.admin import ModelAdmin

from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import Bed, Building, Floor, Room


@admin.register(Building)
class BuildingAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]


@admin.register(Floor)
class FloorAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "building__name"
    list_display = ["building", "name"]
    list_filter = ["building"]
    search_fields = ["building__name", "name"]


@admin.register(Room)
class RoomAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "floor__building__name"
    list_display = ["building_name", "floor", "number"]
    list_filter = ["floor__building", "floor"]
    search_fields = ["number", "floor__name", "floor__building__name"]

    @admin.display(description="楼栋", ordering="floor__building__name")
    def building_name(self, obj):
        return obj.floor.building.name


@admin.register(Bed)
class BedAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "room__floor__building__name"
    list_display = ["full_location", "status", "occupant_name"]
    list_filter = ["status", "room__floor__building__name", "room__floor__name"]
    # search_fields 是 ResidentAdmin autocomplete_fields=["bed"] 的硬依赖
    search_fields = ["number", "room__number", "room__floor__name", "room__floor__building__name"]
    list_per_page = 50

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("room__floor__building")
            .prefetch_related("occupant")
        )

    @admin.display(description="在住老人")
    def occupant_name(self, obj):
        occupant = obj.occupant.first()  # prefetch 缓存
        return occupant.name if occupant else "—"
