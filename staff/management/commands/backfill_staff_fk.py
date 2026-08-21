"""存量姓名字符串 → Employee FK 回填（幂等，可重复执行）。

用法：
    python manage.py backfill_staff_fk             # 正式回填
    python manage.py backfill_staff_fk --dry-run   # 只看将要做什么

规则（Q2 定稿）：
- 只处理 FK 为空且姓名字符串非空的行（幂等锚点：挂过的不再处理）
- 按姓名精确匹配 Employee：恰好 1 条 → 挂接；0 条（错字/离职）或
  >1 条（重名歧义）→ 保持 null，输出清单标注原因，人工补
- 用 queryset.update() 落库，不走 save()——StockIn/StockOut 的
  save() 会重复增减库存，绝不能在这里触发
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from incidents.models import IncidentReport
from meals.models import MealModificationLog, MealOrder
from operations.models import Approval, Inspection, MaintenanceOrder, StockIn, StockOut
from residents.models import CareLevelChange, NursingLog
from staff.models import Employee, Task

# (模型, 字符串列, FK列, 中文名)
REGISTRY = [
    (NursingLog, "staff_name", "staff_emp", "护理日志"),
    (CareLevelChange, "changed_by", "changed_by_emp", "护理等级变更"),
    (Task, "assigner_name", "assigner_emp", "任务派发"),
    (StockIn, "operator", "operator_emp", "入库记录"),
    (StockOut, "taken_by", "taken_by_emp", "领用记录"),
    (MaintenanceOrder, "reported_by", "reported_by_emp", "报修工单"),
    (Inspection, "inspector_name", "inspector_emp", "卫生巡检"),
    (Approval, "applicant_name", "applicant_emp", "审批单"),
    (IncidentReport, "handled_by", "handled_by_emp", "异常上报"),
    (MealOrder, "ordered_by", "ordered_by_emp", "点餐订单"),
    (MealModificationLog, "changed_by", "changed_by_emp", "改退餐记录"),
]


class Command(BaseCommand):
    help = "按姓名字符串精确匹配 Employee，回填 11 张表的责任人 FK（幂等）"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只统计不落库")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        total = {"linked": 0, "ambiguous": 0, "unmatched": 0}

        for model, str_col, fk_col, label in REGISTRY:
            rows = list(
                model.objects.filter(**{f"{fk_col}__isnull": True})
                .exclude(Q(**{str_col: ""}) | Q(**{f"{str_col}__isnull": True}))
            )
            self.stdout.write(f"{label}: 待回填 {len(rows)} 条")
            linked, ambiguous, unmatched = [], [], []

            for obj in rows:
                name = getattr(obj, str_col).strip()
                if not name:
                    continue
                candidates = list(Employee.objects.filter(name=name))
                if len(candidates) == 1:
                    linked.append(name)
                    if not dry_run:
                        # update() 而非 save()：绕过 StockIn/StockOut 的库存增减副作用
                        model.objects.filter(pk=obj.pk).update(**{fk_col: candidates[0]})
                elif len(candidates) > 1:
                    ambiguous.append((name, candidates))
                    self.stdout.write(self.style.WARNING(
                        f"  [重名] {name} ← {obj}，候选："
                        + "、".join(f"{c.name}[{c.dept}]" for c in candidates)
                    ))
                else:
                    unmatched.append(name)
                    self.stdout.write(self.style.WARNING(f"  [无匹配] {name} ← {obj}"))

            total["linked"] += len(linked)
            total["ambiguous"] += len(ambiguous)
            total["unmatched"] += len(unmatched)
            if linked:
                names = "、".join(sorted(set(linked)))
                tag = "[计划]" if dry_run else "[挂接]"
                self.stdout.write(self.style.SUCCESS(f"  {tag} {len(linked)} 条：{names}"))

        verb = "[dry-run] 计划挂接" if dry_run else "回填完成：挂接"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {total['linked']} 条；重名歧义 {total['ambiguous']} 条、"
            f"无匹配 {total['unmatched']} 条保持空挂，需人工补"
        ))
