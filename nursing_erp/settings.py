"""
Django settings for nursing_erp project — 养老院业务管理系统
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "unfold",                           # Must be before django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "import_export",
    # Project apps (added progressively)
    "residents.apps.ResidentsConfig",
    "staff.apps.StaffConfig",
    "operations.apps.OperationsConfig",
    "incidents.apps.IncidentsConfig",
    "meals.apps.MealsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "nursing_erp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "nursing_erp.wsgi.application"

# Use SQLite for local dev, PostgreSQL for Docker deployment
_db_password = os.environ.get("DB_PASSWORD", "")
if _db_password:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "nursing_erp"),
            "USER": os.environ.get("DB_USER", "nursing"),
            "PASSWORD": _db_password,
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# django-unfold settings
UNFOLD = {
    "SITE_TITLE": "养老院管理系统",
    "SITE_HEADER": "养老院综合管理平台",
    "SITE_URL": "/",
    "SITE_SYMBOL": "home",
    "TABS": [
        {"items": [{"title": "AI 院长助手", "link": "https://hz-sanfu.eldcare.cn:9443/chat/"}]},
    ],
    "COLORS": {
        "primary": {
            "50": "239 246 255",
            "100": "219 234 254",
            "200": "191 219 254",
            "300": "147 197 253",
            "400": "96 165 250",
            "500": "59 130 246",
            "600": "37 99 235",
            "700": "29 78 216",
            "800": "30 64 175",
            "900": "30 58 138",
            "950": "23 37 84",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {"title": "👴 老人照护", "collapsible": True, "items": [
                {"title": "老人档案", "icon": "person", "link": "/admin/residents/resident/"},
                {"title": "护理日志", "icon": "edit_note", "link": "/admin/residents/nursinglog/"},
                {"title": "健康记录", "icon": "monitor_heart", "link": "/admin/residents/healthrecord/"},
                {"title": "用药记录", "icon": "medication", "link": "/admin/residents/medicationrecord/"},
                {"title": "作息记录", "icon": "bedtime", "link": "/admin/residents/residentroutine/"},
            ]},
            {"title": "👥 人员管理", "collapsible": True, "items": [
                {"title": "员工档案", "icon": "badge", "link": "/admin/staff/employee/"},
                {"title": "排班表", "icon": "calendar_month", "link": "/admin/staff/schedule/"},
                {"title": "考勤记录", "icon": "fingerprint", "link": "/admin/staff/attendance/"},
                {"title": "任务派发", "icon": "assignment", "link": "/admin/staff/task/"},
                {"title": "绩效考核", "icon": "trending_up", "link": "/admin/staff/performance/"},
            ]},
            {"title": "🏠 院内事务", "collapsible": True, "items": [
                {"title": "库存管理", "icon": "inventory", "link": "/admin/operations/inventoryitem/"},
                {"title": "入库记录", "icon": "add_shopping_cart", "link": "/admin/operations/stockin/"},
                {"title": "领用记录", "icon": "remove_shopping_cart", "link": "/admin/operations/stockout/"},
                {"title": "报修工单", "icon": "build", "link": "/admin/operations/maintenanceorder/"},
                {"title": "卫生巡检", "icon": "cleaning_services", "link": "/admin/operations/inspection/"},
                {"title": "审批流程", "icon": "approval", "link": "/admin/operations/approval/"},
            ]},
            {"title": "🚨 异常上报", "collapsible": True, "items": [
                {"title": "异常记录", "icon": "warning", "link": "/admin/incidents/incidentreport/"},
            ]},
            {"title": "🍽️ 点餐送餐", "collapsible": True, "items": [
                {"title": "每日菜单", "icon": "menu_book", "link": "/admin/meals/mealplan/"},
                {"title": "点餐订单", "icon": "restaurant", "link": "/admin/meals/mealorder/"},
                {"title": "改退餐记录", "icon": "change_circle", "link": "/admin/meals/mealmodificationlog/"},
                {"title": "餐费月结", "icon": "payments", "link": "/admin/meals/mealfinance/"},
                {"title": "食堂看板", "icon": "soup_kitchen", "link": "/kitchen/"},
                {"title": "财务月结", "icon": "account_balance", "link": "/finance/"},
            ]},
            {"title": "⚙️ 系统管理", "collapsible": True, "items": [
                {"title": "用户账号", "icon": "manage_accounts", "link": "/admin/auth/user/"},
                {"title": "用户组", "icon": "group", "link": "/admin/auth/group/"},
            ]},
        ],
    },
}
