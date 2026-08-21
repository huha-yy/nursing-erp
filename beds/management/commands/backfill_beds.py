"""存量老人 → 床位台账回填（幂等，可重复执行）。

用法：
    python manage.py backfill_beds             # 正式回填
    python manage.py backfill_beds --dry-run   # 只看将要做什么

规则：
- 只处理 bed 为空且楼栋字符串非空的老人（幂等的保证：链接过的不再处理）
- 逐级 get_or_create 建链：楼栋 → 楼层 → 房间 → 床位
- 现有数据是"一人一间"，每间房建 1 张"1"床
- 目标床位已被其他老人占用时跳过并告警（人工处理）
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from beds.models import Bed, Building, Floor, Room
from residents.models import Resident


class Command(BaseCommand):
    help = "按老人的楼栋/楼层/房间字符串回填四级床位台账（幂等）"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只统计不落库")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        residents = list(
            Resident.objects.filter(bed__isnull=True)
            .exclude(Q(building="") | Q(building__isnull=True))
            .order_by("building", "floor", "room")
        )

        if dry_run:
            seen, need_create = set(), 0
            for r in residents:
                key = (r.building.strip(), r.floor.strip(), r.room.strip())
                if key in seen:
                    continue
                seen.add(key)
                if not self._chain_exists(*key):
                    need_create += 1
                    self.stdout.write(f"  [计划] {key[0]} {key[1]} {key[2]}室 → 建 1 床")
            self.stdout.write(self.style.SUCCESS(
                f"[dry-run] 待处理老人 {len(residents)} 位，涉及房间 {len(seen)} 间，"
                f"其中需新建链 {need_create} 组"
            ))
            return

        created = {"building": 0, "floor": 0, "room": 0, "bed": 0}
        linked, skipped = 0, 0

        for r in residents:
            building, c = Building.objects.get_or_create(name=r.building.strip())
            created["building"] += c
            floor, c = Floor.objects.get_or_create(building=building, name=r.floor.strip())
            created["floor"] += c
            room, c = Room.objects.get_or_create(floor=floor, number=r.room.strip())
            created["room"] += c
            bed, c = Bed.objects.get_or_create(
                room=room, number="1", defaults={"status": Bed.Status.AVAILABLE}
            )
            created["bed"] += c

            occupant = bed.occupant.first()
            if occupant and occupant.pk != r.pk:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"  [跳过] {r}（{r.building} {r.floor} {r.room}室）→ "
                    f"{bed} 已被 {occupant} 占用，需人工处理"
                ))
                continue

            r.bed = bed
            r.save(update_fields=["bed", "building", "floor", "room"])  # 字符串重同步为同值
            linked += 1

        self.stdout.write(self.style.SUCCESS(
            f"回填完成：新建 楼栋{created['building']}/楼层{created['floor']}/"
            f"房间{created['room']}/床位{created['bed']}，"
            f"链接老人 {linked} 位，跳过 {skipped} 位，剩余未链接 "
            f"{Resident.objects.filter(bed__isnull=True).count()} 位"
        ))

    def _chain_exists(self, building_name, floor_name, room_number) -> bool:
        return Room.objects.filter(
            floor__building__name=building_name,
            floor__name=floor_name,
            number=room_number,
        ).exists()
