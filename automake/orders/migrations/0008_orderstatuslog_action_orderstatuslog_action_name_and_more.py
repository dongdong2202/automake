from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0007_orderinvoice_usercoupon_userpointlog'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderstatuslog',
            name='action',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32, verbose_name='事件动作'),
        ),
        migrations.AddField(
            model_name='orderstatuslog',
            name='action_name',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='动作名称'),
        ),
        migrations.AddField(
            model_name='orderstatuslog',
            name='operator_type',
            field=models.CharField(default='system', max_length=20, verbose_name='操作主体类型'),
        ),
        migrations.AddField(
            model_name='orderstatuslog',
            name='payload',
            field=models.JSONField(blank=True, default=dict, verbose_name='流转上下文快照'),
        ),
        migrations.AlterField(
            model_name='orderstatuslog',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发生时间'),
        ),
    ]
