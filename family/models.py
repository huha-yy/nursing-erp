"""家属账号与绑定 — 家属端（页 + AI 问答）的身份真源（路线图 Q6 预留角色概念落地）。

设计口径：
- 家属 = Django User(is_staff=False, username=手机号) + FamilyMember 档案，
  与员工（Employee 挂 user）同构但互斥——api_auth.erp_auth 见到 FamilyMember
  档案的 session 一律拒入员工 /api/（2026-08-24 家属端安全闭合）
- 一位家属可绑定多位老人（老两口），一位老人可被多位家属绑定；
  relation 只做展示，不参与权限判断——权限只认绑定存在与否
- token 供 dl-control 机器调用（/api/family/auth/ 登录换取，之后带
  X-Family-Token 访问家属 API），泄漏可经 admin「重新生成令牌」作废
"""

import secrets

from django.conf import settings
from django.db import models


def _new_token() -> str:
    return secrets.token_hex(16)


class FamilyMember(models.Model):
    """家属账号 — 手机号即登录名（User.username），初始密码由开通入口生成。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_profile",
        verbose_name="登录账号",
    )
    name = models.CharField(max_length=30, verbose_name="姓名")
    phone = models.CharField(max_length=15, unique=True, verbose_name="手机号")
    token = models.CharField(
        max_length=64, default=_new_token, unique=True, editable=False,
        verbose_name="AI 接入令牌",
    )
    is_active = models.BooleanField(default=True, verbose_name="启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "家属账号"
        verbose_name_plural = verbose_name
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}({self.phone})"

    def regen_token(self):
        """作废旧令牌（家属端怀疑泄漏时由 admin action 触发）。"""
        self.token = _new_token()
        self.save(update_fields=["token", "updated_at"])


class FamilyBinding(models.Model):
    """家属↔老人绑定台账 — 行由家属开通/解除流程维护，不开放手工增删。"""

    class Relation(models.TextChoices):
        CHILD = "子女", "子女"
        SPOUSE = "配偶", "配偶"
        PARENT = "父母", "父母"
        SIBLING = "兄弟姐妹", "兄弟姐妹"
        OTHER = "其他", "其他"

    family = models.ForeignKey(
        FamilyMember, on_delete=models.CASCADE,
        related_name="bindings", verbose_name="家属",
    )
    resident = models.ForeignKey(
        "residents.Resident", on_delete=models.CASCADE,
        related_name="family_bindings", verbose_name="老人",
    )
    relation = models.CharField(
        max_length=10, choices=Relation.choices,
        default=Relation.CHILD, verbose_name="与老人关系",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="绑定时间")

    class Meta:
        verbose_name = "家属绑定"
        verbose_name_plural = verbose_name
        ordering = ["family__name", "resident__name"]
        constraints = [
            models.UniqueConstraint(fields=["family", "resident"], name="family_resident_unique"),
        ]


def is_family_user(user) -> bool:
    """user 是否家属身份（挂 FamilyMember 档案）— erp_auth / staff_required 共用。

    匿名/员工/裸账号返回 False；调用方需先确认 user 已认证。
    """
    return FamilyMember.objects.filter(user=user).exists()
