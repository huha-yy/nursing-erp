"""家属账号管理 — 开通（一次建 User+档案+绑定）/ 令牌 / 密码重置，绑定台账只读。"""

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action

from residents.models import Resident

from .models import FamilyBinding, FamilyMember

INITIAL_PASSWORD = "123456"


class FamilyMemberAddForm(forms.ModelForm):
    """开通表单 — 手机号即 User.username；一次原子建 User+档案+绑定。"""

    relation = forms.ChoiceField(
        choices=FamilyBinding.Relation.choices,
        initial=FamilyBinding.Relation.CHILD,
        label=_("与老人的关系"),
    )
    residents = forms.ModelMultipleChoiceField(
        queryset=Resident.objects.all(),
        label=_("绑定老人"),
        help_text=_("可多选；同房两老共用一个子女账号即多绑演示"),
    )

    class Meta:
        model = FamilyMember
        fields = ["name", "phone"]

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        # 员工与家属共用 auth_user 命名空间，撞号直接拦下而非静默跳过
        if User.objects.filter(username=phone).exists():
            raise forms.ValidationError(
                _("手机号 {} 已被账号占用（员工或家属），请先处理该账号").format(phone)
            )
        return phone


class FamilyBindingInline(TabularInline):
    """家属 change 页内调整绑定（增删），与独立台账的只读姿态区分。"""

    model = FamilyBinding
    fields = ["resident", "relation"]
    autocomplete_fields = ["resident"]
    extra = 1


@admin.register(FamilyMember)
class FamilyMemberAdmin(ModelAdmin):
    list_display = ["name", "phone", "binding_count", "is_active", "token_short", "created_at"]
    search_fields = ["name", "phone", "user__username"]
    list_filter = ["is_active"]
    readonly_fields = ["token", "created_at", "updated_at"]
    inlines = [FamilyBindingInline]
    actions = ["action_regen_token", "action_reset_password"]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = FamilyMemberAddForm
        return super().get_form(request, obj, **kwargs)

    def get_inline_instances(self, request, obj=None):
        # 开通页只走开通表单（relation+residents）；inline 与多选并存会开出重复绑定
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)

    def get_fields(self, request, obj=None):
        # add 走 FamilyMemberAddForm（name/phone/relation/residents）
        if obj is None:
            return ["name", "phone", "relation", "residents"]
        return ["name", "phone", "is_active", "token", "created_at", "updated_at"]

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        with transaction.atomic():
            user = User.objects.create_user(username=obj.phone, password=INITIAL_PASSWORD)
            obj.user = user
            obj.save()
            residents = list(form.cleaned_data["residents"])
            FamilyBinding.objects.bulk_create(
                FamilyBinding(family=obj, resident=r, relation=form.cleaned_data["relation"])
                for r in residents
            )
        self.message_user(
            request,
            _("已开通家属账号 {}（{}），初始密码 {}，绑定 {} 位老人").format(
                obj.name, obj.phone, INITIAL_PASSWORD, len(residents)
            ),
            messages.SUCCESS,
        )

    @admin.display(description=_("绑定老人数"))
    def binding_count(self, obj):
        return obj.bindings.count()

    @admin.display(description=_("令牌"))
    def token_short(self, obj):
        return obj.token[:8] + "…"

    @action(description=_("重新生成令牌"))
    def action_regen_token(self, request, queryset):
        for fm in queryset:
            fm.regen_token()
        count = queryset.count()
        self.message_user(
            request,
            _("已为 {} 个家属账号重新生成令牌（旧令牌立即作废）").format(count),
            messages.SUCCESS,
        )

    @action(description=_("重置密码为 123456"))
    def action_reset_password(self, request, queryset):
        for fm in queryset:
            fm.user.set_password(INITIAL_PASSWORD)
            fm.user.save(update_fields=["password"])
        count = queryset.count()
        self.message_user(
            request,
            _("已重置 {} 个家属账号密码为 {}").format(count, INITIAL_PASSWORD),
            messages.SUCCESS,
        )


@admin.register(FamilyBinding)
class FamilyBindingAdmin(ModelAdmin):
    """绑定台账 — 只读视图（增删走家属账号页的 inline），供审计"谁能看到谁"。"""

    list_display = ["family", "resident", "relation", "created_at"]
    list_filter = ["relation"]
    search_fields = ["family__name", "family__phone", "resident__name"]
    autocomplete_fields = ["family", "resident"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # 有 view 权限 → 只读模式

    def has_delete_permission(self, request, obj=None):
        return False
