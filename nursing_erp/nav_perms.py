"""UNFOLD 侧栏 permission 回调 — 按用户组实际持有的 view 权限过滤导航。

settings.py 的 UNFOLD SIDEBAR navigation 每项 "permission" 直接引用本模块
具名函数（callable，**不是** dotted string——unfold sites.py 对 str 走
import_string，失败后回退 str 调用会 500；直接引用写错名=启动 NameError，
fail-fast）。

- 返回必须严格 == True（sites.py 是 ``lazy(callback)(request) == True``），
  故一律包 bool()
- superuser 的 User.has_perm 恒真（obj=None 分支）→ 全量可见
- 闭包挂 nav_perms 属性（codename 元组）供测试做「父项=子项并集」校验
- 轻量页（看板/OCR/快速记录等）后端仅 @staff_required 不分组，本模块给的
  是导航层业务归属（用户拍板 2026-08-27），直链仍开放
- 本模块禁止 import django.conf.settings（settings 反向 import 本模块，防环）
"""


def _perm(codename):
    def check(request):
        user = request.user
        return bool(user.is_authenticated and user.has_perm(codename))

    check.__name__ = codename.replace(".", "_")
    check.nav_perms = (codename,)
    return check


def any_perm(*codenames):
    def check(request):
        user = request.user
        return bool(user.is_authenticated and any(user.has_perm(c) for c in codenames))

    check.__name__ = "any_" + "_".join(c.split(".", 1)[1] for c in codenames)
    check.nav_perms = tuple(codenames)
    return check


# ── AI 院长助手（chat 外链不配 permission，全员可见，防组空壳） ──
quick_log = _perm("residents.view_nursinglog")  # 页面 POST /api/nursing-logs/

# ── 老人照护 ──
resident = _perm("residents.view_resident")
nursinglog = _perm("residents.view_nursinglog")
healthrecord = _perm("residents.view_healthrecord")
medicationrecord = _perm("residents.view_medicationrecord")
residentroutine = _perm("residents.view_residentroutine")
admissionrecord = _perm("residents.view_admissionrecord")
dischargerecord = _perm("residents.view_dischargerecord")
transferrecord = _perm("residents.view_transferrecord")
incidentreport = _perm("incidents.view_incidentreport")
assessment = _perm("assessments.view_assessment")
gradelevelmap = _perm("assessments.view_gradelevelmap")

# 父项 = 全部子项 perm 并集（任一子项持有组可见，保最大可见面）
care_records = any_perm(
    "residents.view_nursinglog",
    "residents.view_healthrecord",
    "residents.view_medicationrecord",
    "residents.view_residentroutine",
)
lifecycle_records = any_perm(
    "residents.view_admissionrecord",
    "residents.view_dischargerecord",
    "residents.view_transferrecord",
)
assessment_center = any_perm(
    "assessments.view_assessment", "assessments.view_gradelevelmap"
)

# ── 床位管理 ──
bed_board = _perm("beds.view_bed")  # 轻量页：看板=按床入住率
building = _perm("beds.view_building")
floor = _perm("beds.view_floor")
room = _perm("beds.view_room")
bed = _perm("beds.view_bed")

# ── 膳食点餐 ──
kitchen_board = _perm("meals.view_mealorder")  # 轻量页：今日订单分餐统计
dish = _perm("meals.view_dish")
weekmenu = _perm("meals.view_weekmenu")
weekly_order = _perm("meals.view_mealorder")  # 轻量页：下单产物=订单
menu_ocr = _perm("meals.view_weekmenu")  # 轻量页：拍照产物=周菜单
meal_order_ocr = _perm("meals.view_mealorder")  # 轻量页：识别点餐单
mealorder = _perm("meals.view_mealorder")
mealmodificationlog = _perm("meals.view_mealmodificationlog")
mealfinance = _perm("meals.view_mealfinance")  # 父+两子（含 /finance/ 轻量页）

order_tools = any_perm("meals.view_mealorder", "meals.view_weekmenu")
order_ledger = any_perm("meals.view_mealorder", "meals.view_mealmodificationlog")

# ── 财务账单 ──
monthlybill = _perm("billing.view_monthlybill")
feerule = _perm("billing.view_feerule")
billing_board = _perm("billing.view_monthlybill")  # 轻量页：出账/核销

# ── 人员管理 ──
employee = _perm("staff.view_employee")
schedule = _perm("staff.view_schedule")
attendance = _perm("staff.view_attendance")
task = _perm("staff.view_task")
performance = _perm("staff.view_performance")

# ── 院内事务 ──
inventoryitem = _perm("operations.view_inventoryitem")
stockin = _perm("operations.view_stockin")
stockout = _perm("operations.view_stockout")
maintenanceorder = _perm("operations.view_maintenanceorder")
inspection = _perm("operations.view_inspection")
approval = _perm("operations.view_approval")
material_center = any_perm(
    "operations.view_inventoryitem",
    "operations.view_stockin",
    "operations.view_stockout",
)

# ── 家属服务 / 审计留痕 / 系统管理 ──
familymember = _perm("family.view_familymember")
familybinding = _perm("family.view_familybinding")
operationlog = _perm("auditlog.view_operationlog")
logentry = _perm("admin.view_logentry")
user_admin = _perm("auth.view_user")
group_admin = _perm("auth.view_group")
