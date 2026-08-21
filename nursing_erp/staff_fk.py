"""StaffFkMixin — 员工姓名字符串列与 Employee FK 双向同步（Q2 定稿）。

字符串列（staff_name/operator/taken_by/...）是既有 admin 筛选与
AI 侧 /api/ 契约的兼容缓存，Employee FK 才是责任人追溯链的权威。

save() 三分支（apps.get_model 惰性引用，避免 app 加载环）：
1. FK 已设 → 字符串同步为员工姓名（FK 为准）
2. FK 空、字符串非空 → 按 strip 后姓名精确匹配；恰好 1 条才自动挂接，
   0 条（错字/离职）或 >1 条（重名歧义）保持 null，交回填清单人工处理
3. 两者皆空 → 跳过

注意：queryset.update()/bulk_update 绕过本方法，FK 漂移由
backfill_staff_fk 命令幂等补齐。
"""

from django.apps import apps


class StaffFkMixin:
    """挂接员工 FK 的模型混入。staff_fk_fields: ((字符串列, FK列), ...)"""

    staff_fk_fields: tuple[tuple[str, str], ...] = ()

    def save(self, *args, **kwargs):
        touched = []
        if self.staff_fk_fields:
            employee = apps.get_model("staff", "Employee")
            for str_col, fk_col in self.staff_fk_fields:
                fk_id = getattr(self, f"{fk_col}_id")
                name = (getattr(self, str_col) or "").strip()
                if fk_id:
                    emp_name = getattr(self, fk_col).name
                    if getattr(self, str_col) != emp_name:
                        setattr(self, str_col, emp_name)
                        touched.append(str_col)
                elif name:
                    # [:2] 一次查询同时判定唯一性，省掉 count+first 两查
                    matched = list(
                        employee.objects.filter(name=name).values_list("pk", flat=True)[:2]
                    )
                    if len(matched) == 1:
                        setattr(self, f"{fk_col}_id", matched[0])
                        touched.append(fk_col)
        if touched and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = list({*kwargs["update_fields"], *touched})
        super().save(*args, **kwargs)
