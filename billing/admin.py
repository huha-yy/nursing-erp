from django.contrib import admin
from django.utils.translation import gettext, gettext_lazy as _
from import_export.admin import ImportExportModelAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import FeeRule, MonthlyBill


@admin.register(FeeRule)
class FeeRuleAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ["fee_type_display", "key_display", "monthly_amount"]
    list_filter = ["fee_type"]

    @admin.display(description=_("费用类型"), ordering="fee_type")
    def fee_type_display(self, obj):
        return obj.get_fee_type_display()

    @admin.display(description=_("档位"), ordering="key")
    def key_display(self, obj):
        """档位 key 存中文护理等级原值（出账逻辑键，不可译存储）——
        显示层过 gettext（2026-10-10 评审反馈：Fee Rules 页 Tier 列混杂中文）"""
        return gettext(obj.key) if obj.key else "-"


@admin.register(MonthlyBill)
class MonthlyBillAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = [
        "resident", "month", "bed_fee", "nursing_fee", "meal_fee", "total",
        "status_display", "settled_by", "settled_at",
    ]
    list_filter = ["month", "status"]
    search_fields = ["resident__name"]
    autocomplete_fields = ["resident", "settled_by_emp"]
    actions = ["action_settle", "action_unsettle", "action_regenerate"]
    readonly_fields = ["total", "settled_at"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("resident", "settled_by_emp")

    @admin.display(description=_("状态"), ordering="status")
    def status_display(self, obj):
        return obj.get_status_display()

    def get_readonly_fields(self, request, obj=None):
        """已缴费账单金额冻结：老人/账期/三费不可改（减免走撤销核销→改→重新核销）。"""
        if obj and obj.status == MonthlyBill.Status.PAID:
            return [
                *self.readonly_fields,
                "resident", "month", "bed_fee", "nursing_fee", "meal_fee",
            ]
        return self.readonly_fields

    def _operator(self, request) -> str:
        try:
            return request.user.employee.name
        except Exception:
            return request.user.username

    @action(description=_("核销（全额缴费）"))
    def action_settle(self, request, queryset):
        """逐条 settle()——queryset.update() 会绕过 StaffFkMixin 挂档与 total 重算。"""
        count = 0
        for bill in queryset:
            before = bill.status
            bill.settle(operator=self._operator(request))
            count += before != bill.status
        self.message_user(
            request, _("核销 {} 张账单（已缴费的自动跳过）").format(count)
        )

    @action(description=_("撤销核销"))
    def action_unsettle(self, request, queryset):
        count = 0
        for bill in queryset:
            before = bill.status
            bill.unsettle()
            count += before != bill.status
        self.message_user(request, _("撤销核销 {} 张账单").format(count))

    @action(description=_("重新生成（已缴费冻结跳过）"))
    def action_regenerate(self, request, queryset):
        refreshed = skipped = 0
        for bill in queryset.select_related("resident"):
            was_paid = bill.status == MonthlyBill.Status.PAID
            MonthlyBill.generate_month(bill.resident, bill.month)
            skipped += was_paid
            refreshed += not was_paid
        self.message_user(
            request, _("刷新 {} 张，已缴费冻结跳过 {} 张").format(refreshed, skipped)
        )
