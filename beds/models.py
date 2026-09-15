from django.db import models
from django.utils.translation import gettext_lazy as _


class Building(models.Model):
    """楼栋 — 床位台账第一级"""

    name = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("楼栋名称"),
        help_text=_("须与员工档案的楼栋名一致（如 1号楼），改名会导致楼栋权限失配"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("创建时间"))

    class Meta:
        verbose_name = _("楼栋台账")
        verbose_name_plural = verbose_name
        ordering = ["name"]

    def __str__(self):
        return self.name


class Floor(models.Model):
    """楼层 — 床位台账第二级"""

    building = models.ForeignKey(
        Building, on_delete=models.CASCADE, related_name="floors", verbose_name=_("楼栋")
    )
    name = models.CharField(max_length=10, verbose_name=_("楼层名称"))  # 如 "1层"

    class Meta:
        verbose_name = _("楼层台账")
        verbose_name_plural = verbose_name
        ordering = ["building__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["building", "name"], name="uniq_floor_per_building"),
        ]

    def __str__(self):
        return f"{self.building.name} {self.name}"


class Room(models.Model):
    """房间 — 床位台账第三级"""

    floor = models.ForeignKey(
        Floor, on_delete=models.CASCADE, related_name="rooms", verbose_name=_("楼层")
    )
    number = models.CharField(max_length=10, verbose_name=_("房间号"))  # 如 "101"

    class Meta:
        verbose_name = _("房间台账")
        verbose_name_plural = verbose_name
        ordering = ["floor__building__name", "floor__name", "number"]
        constraints = [
            models.UniqueConstraint(fields=["floor", "number"], name="uniq_room_per_floor"),
        ]

    def __str__(self):
        return f"{self.floor} {self.number}室"


class Bed(models.Model):
    """床位 — 床位台账第四级，占用关系由 Resident.bed 反向派生"""

    class Status(models.TextChoices):
        AVAILABLE = "可用", _("可用")
        MAINTENANCE = "维修", _("维修")
        DISABLED = "停用", _("停用")

    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="beds", verbose_name=_("房间")
    )
    number = models.CharField(max_length=10, verbose_name=_("床位号"))  # 如 "1"
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.AVAILABLE,
        verbose_name=_("床位状态"),
    )

    class Meta:
        verbose_name = _("床位台账")
        verbose_name_plural = verbose_name
        ordering = [
            "room__floor__building__name", "room__floor__name", "room__number", "number",
        ]
        indexes = [models.Index(fields=["status"])]
        constraints = [
            models.UniqueConstraint(fields=["room", "number"], name="uniq_bed_per_room"),
        ]

    def __str__(self):
        return f"{self.room}-{self.number}床"

    @property
    def full_location(self) -> str:
        room = self.room
        return f"{room.floor.building.name} {room.floor.name} {room.number}室 {self.number}床"
