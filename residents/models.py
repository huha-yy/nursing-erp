from django.db import models


class Resident(models.Model):
    """老人电子档案"""

    class CareLevel(models.TextChoices):
        SELF_CARE = "自理", "自理"
        HALF_CARE = "半护", "半护"
        FULL_CARE = "全护", "全护"
        DEMENTIA = "失智", "失智"

    name = models.CharField(max_length=50, verbose_name="姓名")
    gender = models.CharField(max_length=4, default="男", verbose_name="性别")
    age = models.IntegerField(null=True, blank=True, verbose_name="年龄")
    id_card = models.CharField(max_length=18, unique=True, verbose_name="身份证号")
    building = models.CharField(max_length=20, verbose_name="楼栋")
    floor = models.CharField(max_length=10, verbose_name="楼层")
    room = models.CharField(max_length=10, verbose_name="房间号")
    admission_date = models.DateField(null=True, blank=True, verbose_name="入住日期")
    diagnosis = models.TextField(blank=True, verbose_name="既往病史")
    allergies = models.TextField(blank=True, verbose_name="过敏史")
    care_level = models.CharField(
        max_length=10,
        choices=CareLevel.choices,
        default=CareLevel.SELF_CARE,
        verbose_name="护理等级",
    )
    contact_name = models.CharField(max_length=30, blank=True, verbose_name="紧急联系人")
    contact_phone = models.CharField(max_length=15, blank=True, verbose_name="联系电话")
    notes = models.TextField(blank=True, verbose_name="备注")
    photo = models.ImageField(upload_to="residents/", blank=True, verbose_name="老人照片")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建档时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "老人档案"
        verbose_name_plural = verbose_name
        ordering = ["building", "floor", "room"]
        indexes = [
            models.Index(fields=["building"]),
            models.Index(fields=["care_level"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name


class NursingLog(models.Model):
    """护理日志 — 替代纸质笔记"""

    class Category(models.TextChoices):
        FEEDING = "feeding", "喂饭/协助进食"
        HYGIENE = "hygiene", "洗漱/助浴"
        TOILET = "toilet", "如厕协助"
        TURNING = "turning", "翻身护理"
        MEDICINE = "medicine", "服药"
        VITAL_SIGNS = "vital_signs", "生命体征测量"
        REHAB = "rehab", "康复训练"
        OTHER = "other", "其他"

    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="logs", verbose_name="老人"
    )
    log_date = models.DateField(verbose_name="日期")
    log_time = models.TimeField(auto_now_add=True, verbose_name="记录时间")
    category = models.CharField(
        max_length=20, choices=Category.choices, verbose_name="护理类型"
    )
    detail = models.TextField(blank=True, verbose_name="详细记录")
    staff_name = models.CharField(max_length=30, blank=True, verbose_name="护理员")

    class Meta:
        verbose_name = "护理日志"
        verbose_name_plural = verbose_name
        ordering = ["-log_date", "-log_time"]
        indexes = [
            models.Index(fields=["log_date"]),
            models.Index(fields=["resident", "log_date"]),
        ]

    def __str__(self):
        return f"{self.resident.name} — {self.get_category_display()} — {self.log_date}"


class HealthRecord(models.Model):
    """健康数据记录"""
    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="health_records", verbose_name="老人"
    )
    record_date = models.DateField(verbose_name="日期")
    blood_pressure = models.CharField(max_length=20, blank=True, verbose_name="血压")
    blood_sugar = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True, verbose_name="血糖(mmol/L)"
    )
    heart_rate = models.IntegerField(null=True, blank=True, verbose_name="心率(次/分)")
    weight = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True, verbose_name="体重(kg)"
    )
    temperature = models.DecimalField(
        max_digits=3, decimal_places=1, null=True, blank=True, verbose_name="体温(℃)"
    )
    note = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "健康记录"
        verbose_name_plural = verbose_name
        ordering = ["-record_date"]
        indexes = [models.Index(fields=["resident", "record_date"])]

    def __str__(self):
        return f"{self.resident.name} — {self.record_date}"


class MedicationRecord(models.Model):
    """用药记录"""

    class Frequency(models.TextChoices):
        QD = "qd", "每日1次"
        BID = "bid", "每日2次"
        TID = "tid", "每日3次"
        QID = "qid", "每日4次"
        PRN = "prn", "必要时"

    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="medications", verbose_name="老人"
    )
    medicine_name = models.CharField(max_length=100, verbose_name="药品名称")
    dosage = models.CharField(max_length=50, verbose_name="剂量")
    frequency = models.CharField(
        max_length=10, choices=Frequency.choices, default=Frequency.QD, verbose_name="频次"
    )
    start_date = models.DateField(verbose_name="开始日期")
    end_date = models.DateField(null=True, blank=True, verbose_name="结束日期")
    is_active = models.BooleanField(default=True, verbose_name="服用中")
    note = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "用药记录"
        verbose_name_plural = verbose_name
        ordering = ["-is_active", "medicine_name"]
        indexes = [models.Index(fields=["resident", "is_active"])]

    def __str__(self):
        return f"{self.resident.name} — {self.medicine_name} {self.dosage}"


class ResidentRoutine(models.Model):
    """老人作息记录"""
    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="routines", verbose_name="老人"
    )
    log_date = models.DateField(verbose_name="日期")
    wake_up = models.TimeField(null=True, blank=True, verbose_name="起床时间")
    sleep = models.TimeField(null=True, blank=True, verbose_name="就寝时间")
    breakfast = models.BooleanField(default=True, verbose_name="早餐")
    lunch = models.BooleanField(default=True, verbose_name="午餐")
    dinner = models.BooleanField(default=True, verbose_name="晚餐")
    activities = models.TextField(blank=True, verbose_name="活动情况")
    mood = models.CharField(max_length=20, blank=True, verbose_name="情绪状态")

    class Meta:
        verbose_name = "老人作息"
        verbose_name_plural = verbose_name
        ordering = ["-log_date"]
        indexes = [models.Index(fields=["resident", "log_date"])]

    def __str__(self):
        return f"{self.resident.name} — {self.log_date}"


class CareLevelChange(models.Model):
    """护理等级变更记录 — 生命周期关键节点"""

    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="level_changes", verbose_name="老人"
    )
    from_level = models.CharField(max_length=10, choices=Resident.CareLevel.choices, verbose_name="原等级")
    to_level = models.CharField(max_length=10, choices=Resident.CareLevel.choices, verbose_name="新等级")
    change_date = models.DateField(verbose_name="变更日期")
    reason = models.TextField(blank=True, verbose_name="变更原因")
    changed_by = models.CharField(max_length=30, blank=True, verbose_name="经办人")

    class Meta:
        verbose_name = "护理等级变更"
        verbose_name_plural = verbose_name
        ordering = ["-change_date"]

    def __str__(self):
        return f"{self.resident.name}: {self.get_from_level_display()}→{self.get_to_level_display()}"


class TransferRecord(models.Model):
    """转区记录 — 生命周期关键节点（自理区/介助区/介护区/认知障碍专区）"""

    class Zone(models.TextChoices):
        SELF_CARE = "自理区", "自理区"
        ASSISTED = "介助区", "介助区"
        NURSING = "介护区", "介护区"
        DEMENTIA = "认知障碍专区", "认知障碍专区"

    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="transfers", verbose_name="老人"
    )
    from_zone = models.CharField(max_length=20, choices=Zone.choices, verbose_name="原区域")
    to_zone = models.CharField(max_length=20, choices=Zone.choices, verbose_name="新区域")
    transfer_date = models.DateField(verbose_name="转区日期")
    reason = models.TextField(blank=True, verbose_name="转区原因")

    class Meta:
        verbose_name = "转区记录"
        verbose_name_plural = verbose_name
        ordering = ["-transfer_date"]

    def __str__(self):
        return f"{self.resident.name}: {self.get_from_zone_display()}→{self.get_to_zone_display()}"


class DischargeRecord(models.Model):
    """离院记录 — 生命周期终点"""

    class DischargeType(models.TextChoices):
        DISCHARGED = "出院", "出院"
        TRANSFERRED = "转院", "转院"
        DECEASED = "身故", "身故"

    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="discharges", verbose_name="老人"
    )
    discharge_type = models.CharField(max_length=10, choices=DischargeType.choices, verbose_name="离院类型")
    discharge_date = models.DateField(verbose_name="离院日期")
    reason = models.TextField(blank=True, verbose_name="原因")

    class Meta:
        verbose_name = "离院记录"
        verbose_name_plural = verbose_name
        ordering = ["-discharge_date"]

    def __str__(self):
        return f"{self.resident.name}: {self.get_discharge_type_display()}"
