from django.apps import apps
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, User
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from ninja import NinjaAPI

from nursing_erp.api_auth import erp_auth
from nursing_erp.views import (
    assessment_detail_page,
    assessment_form_page,
    assessments_board,
    bed_board,
    billing_board,
    finance_monthly,
    kitchen_today,
    meal_order_ocr_page,
    menu_ocr_page,
    quick_log,
    resident_lifecycle,
    weekly_order,
)

from family.api import family_api
from family.views import (
    family_billing,
    family_care,
    family_home,
    family_login,
    family_logout,
    family_order,
    family_password,
)

api = NinjaAPI(title="养老院管理系统 API", version="1.0.0", auth=erp_auth)

# Django 内置组/模型显示名对齐侧栏口径（认证和授权/管理/用户/组/日志记录 → 系统管理等）。
# 运行时只改显示层：autodetector 读 original_attrs 类创建时快照，不会误生成 auth/admin 迁移；
# admin index 组名行名（行名读 verbose_name_plural，故双属性同赋）、模型页标题/面包屑都取这里的值。
# i18n：gettext_lazy 包裹（中文即 msgid）——zh 走 msgid 回退渲染中文，
# en 从 locale/en/LC_MESSAGES/ 查中文→英文。
apps.get_app_config("auth").verbose_name = _("系统管理")
apps.get_app_config("admin").verbose_name = _("后台变更日志")
User._meta.verbose_name = User._meta.verbose_name_plural = _("用户账号")
Group._meta.verbose_name = Group._meta.verbose_name_plural = _("用户组")
LogEntry._meta.verbose_name = LogEntry._meta.verbose_name_plural = _("后台变更日志")

# Phase 1-A API routers
from assessments.api import router as assessments_router
from beds.api import router as beds_router
from billing.api import router as billing_router
from incidents.api import router as incidents_router
from meals.api import router as meals_router
from operations.api import router as operations_router
from residents.api import router as residents_router
from staff.api import router as staff_router

api.add_router("/", residents_router)
api.add_router("/", staff_router)
api.add_router("/", incidents_router)
api.add_router("/", operations_router)
api.add_router("/", meals_router)
api.add_router("/", beds_router)
api.add_router("/", billing_router)
api.add_router("/", assessments_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    # 语言切换 POST 端点（set_language 视图，写 django_language cookie）
    path("i18n/", include("django.conf.urls.i18n")),
    # 家属 API 独立实例（auth=family_auth），必须排在员工 /api/ 之前，
    # 否则 /api/family/… 会被员工的 router 抢先匹配
    path("api/family/", family_api.urls),
    path("api/", api.urls),
    path("kitchen/", kitchen_today, name="kitchen_today"),
    path("beds/", bed_board, name="bed_board"),
    path("billing/", billing_board, name="billing_board"),
    path("assessments/", assessments_board, name="assessments_board"),
    path("assessments/new/", assessment_form_page, name="assessment_form_page"),
    path(
        "assessments/<int:assessment_id>/",
        assessment_detail_page,
        name="assessment_detail_page",
    ),
    path("finance/", finance_monthly, name="finance_monthly"),
    path("quick-log/", quick_log, name="quick_log"),
    path("weekly-order/", weekly_order, name="weekly_order"),
    path("menu-ocr/", menu_ocr_page, name="menu_ocr"),
    path("meal-order-ocr/", meal_order_ocr_page, name="meal_order_ocr"),
    path("resident/<int:resident_id>/lifecycle/", resident_lifecycle, name="resident_lifecycle"),
    # 家属端（fat-JS 页面，数据走 /api/family/*）
    path("family/login/", family_login, name="family_login"),
    path("family/logout/", family_logout, name="family_logout"),
    path("family/", family_home, name="family_home"),
    path("family/care/", family_care, name="family_care"),
    path("family/care/<int:resident_id>/", family_care, name="family_care_resident"),
    path("family/order/", family_order, name="family_order"),
    path("family/billing/", family_billing, name="family_billing"),
    path("family/password/", family_password, name="family_password"),
]

from django.conf import settings
from django.conf.urls.static import static

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
