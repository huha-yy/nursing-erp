"""种子用户组（2026-08-25 演示口径）：

此前非超管账号对后台一律 403（无组无权限）——按部门建 6 组挂全员，
后台台账按角色可见，演示可换账号走查。权限以只读为主，日常记录类
（护理日志/健康记录/异常上报）给写；财务可核销账单、总务可管库存
工单。页面 API（erp_auth）不校验模型权限，不受影响；后台管理员仍
可在此之上随意调整（迁移只跑一次，后续 admin 改组不会被覆盖）。

权限行在全新库上要 post_migrate 才有，故先显式 create_permissions
再查（标准种子迁移范式）。
"""

from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations

# (app_label, model) —— 全业务模型清单（院办管理组全量只读）
_VIEW_ALL = [
    ("residents", "resident"), ("residents", "nursinglog"),
    ("residents", "healthrecord"), ("residents", "medicationrecord"),
    ("residents", "residentroutine"), ("residents", "carelevelchange"),
    ("residents", "transferrecord"), ("residents", "dischargerecord"),
    ("staff", "employee"), ("staff", "schedule"), ("staff", "attendance"),
    ("staff", "task"), ("staff", "performance"),
    ("operations", "inventoryitem"), ("operations", "stockin"),
    ("operations", "stockout"), ("operations", "maintenanceorder"),
    ("operations", "inspection"), ("operations", "approval"),
    ("incidents", "incidentreport"),
    ("meals", "dish"), ("meals", "weekmenu"), ("meals", "mealorder"),
    ("meals", "mealmodificationlog"), ("meals", "mealfinance"),
    ("beds", "building"), ("beds", "floor"), ("beds", "room"), ("beds", "bed"),
    ("billing", "monthlybill"), ("billing", "feerule"),
    ("assessments", "assessment"), ("assessments", "assessmentitem"),
    ("assessments", "assessmentscore"), ("assessments", "gradelevelmap"),
    ("family", "familymember"), ("family", "familybinding"),
]

_BEDS_VIEW = [("beds", m) for m in ("building", "floor", "room", "bed")]


def _v(pairs):
    return {("view", app, model) for app, model in pairs}


def _rw(pairs):
    return _v(pairs) | {(a, app, model) for a in ("add", "change")
                         for app, model in pairs}


# (action, app_label, model)
GROUP_PERMS = {
    "院办管理组": _v(_VIEW_ALL) | {
        ("view", "auditlog", "operationlog"),
        ("view", "admin", "logentry"),
        ("view", "auth", "user"), ("view", "auth", "group"),
    },
    "护理组": _v([
        ("residents", "resident"), ("residents", "nursinglog"),
        ("residents", "healthrecord"), ("residents", "medicationrecord"),
        ("residents", "residentroutine"), ("residents", "carelevelchange"),
        ("residents", "transferrecord"), ("residents", "dischargerecord"),
        ("assessments", "assessment"), ("assessments", "gradelevelmap"),
        ("incidents", "incidentreport"),
        ("meals", "dish"), ("meals", "weekmenu"), ("meals", "mealorder"),
        ("staff", "schedule"), ("staff", "attendance"), ("staff", "task"),
    ] + _BEDS_VIEW) | {
        ("add", "residents", "nursinglog"), ("change", "residents", "nursinglog"),
        ("add", "residents", "healthrecord"), ("change", "residents", "healthrecord"),
        ("add", "incidents", "incidentreport"),
    },
    "医务组": _v([
        ("residents", "resident"), ("residents", "nursinglog"),
        ("residents", "healthrecord"), ("residents", "medicationrecord"),
        ("residents", "residentroutine"),
        ("assessments", "assessment"), ("assessments", "gradelevelmap"),
        ("incidents", "incidentreport"),
    ] + _BEDS_VIEW) | _rw([
        ("residents", "healthrecord"), ("residents", "medicationrecord"),
    ]) | {("add", "incidents", "incidentreport")},
    "财务组": _v([
        ("billing", "monthlybill"), ("billing", "feerule"),
        ("meals", "mealfinance"), ("meals", "mealorder"),
        ("meals", "mealmodificationlog"),
        ("residents", "resident"), ("beds", "building"),
    ]) | {("change", "billing", "monthlybill")},
    "总务组": _rw([
        ("operations", "inventoryitem"), ("operations", "stockin"),
        ("operations", "stockout"), ("operations", "maintenanceorder"),
        ("operations", "inspection"), ("operations", "approval"),
    ]) | _v(_BEDS_VIEW),
    "安保组": _v([("residents", "resident")] + _BEDS_VIEW) | {
        ("view", "incidents", "incidentreport"),
        ("add", "incidents", "incidentreport"),
    },
}

# 部门 → 组（员工档案为准；无档案的账号不挂组）
DEPT_TO_GROUP = {
    "院长": "院办管理组",
    "综合办": "院办管理组",
    "护理科": "护理组",
    "医务科": "医务组",
    "财务科": "财务组",
    "总务科": "总务组",
    "安全保卫科": "安保组",
}


def seed(apps, schema_editor):
    involved = {app for specs in GROUP_PERMS.values()
                for _, app, _ in specs}
    for app_label in sorted(involved):
        create_permissions(global_apps.get_app_config(app_label))

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Employee = apps.get_model("staff", "Employee")

    perm_map = {}
    for action, app, model in {s for specs in GROUP_PERMS.values() for s in specs}:
        ct = ContentType.objects.get(app_label=app, model=model)
        perm_map[(action, app, model)] = Permission.objects.get(
            content_type=ct, codename=f"{action}_{model}"
        )

    for name, specs in GROUP_PERMS.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set([perm_map[s] for s in specs])  # 对齐到种子集（一次性）

    group_map = {name: Group.objects.get(name=name) for name in GROUP_PERMS}
    for emp in Employee.objects.select_related("user"):
        group = group_map.get(DEPT_TO_GROUP.get(emp.dept, ""))
        if group is not None:
            emp.user.groups.add(group)


def unseed(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=list(GROUP_PERMS)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0005_task_assigner_emp"),
        ("auditlog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
