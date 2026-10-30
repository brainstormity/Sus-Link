from tortoise import fields, models


class MachineState(models.Model):
    name = fields.CharField(max_length=63, pk=True)
    machine_id = fields.CharField(max_length=80)
    setup_version = fields.CharField(max_length=80, default="")


class ModelState(models.Model):
    name = fields.CharField(max_length=100, pk=True)
    quota_day = fields.CharField(max_length=10, default="")
    requests = fields.IntField(default=0)
    limited_at = fields.DatetimeField(null=True)
    retry_at = fields.DatetimeField(null=True)
    reason = fields.CharField(max_length=80, default="")


class Scan(models.Model):
    id = fields.UUIDField(pk=True)
    status = fields.CharField(max_length=30, default="running")
    url = fields.TextField()
    evidence = fields.JSONField(default=dict)
    report = fields.JSONField(default=dict)
    model = fields.CharField(max_length=100, default="")
    created_at = fields.DatetimeField(auto_now_add=True)
    completed_at = fields.DatetimeField(null=True)
