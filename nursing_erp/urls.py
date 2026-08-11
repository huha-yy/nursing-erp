from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from nursing_erp.views import kitchen_today, finance_monthly, quick_log, weekly_order, menu_ocr_page

api = NinjaAPI(title="养老院管理系统 API", version="1.0.0")

# Phase 1-A API routers
from residents.api import router as residents_router
from staff.api import router as staff_router
from incidents.api import router as incidents_router
from operations.api import router as operations_router
from meals.api import router as meals_router

api.add_router("/", residents_router)
api.add_router("/", staff_router)
api.add_router("/", incidents_router)
api.add_router("/", operations_router)
api.add_router("/", meals_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("kitchen/", kitchen_today, name="kitchen_today"),
    path("finance/", finance_monthly, name="finance_monthly"),
    path("quick-log/", quick_log, name="quick_log"),
    path("weekly-order/", weekly_order, name="weekly_order"),
    path("menu-ocr/", menu_ocr_page, name="menu_ocr"),
]

from django.conf import settings
from django.conf.urls.static import static

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
