from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0005_devicematerialstock'),
        ('global_config', '0006_rename_device_type'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='device',
            name='device_model',
        ),
        migrations.RenameField(
            model_name='device',
            old_name='device_type',
            new_name='device_model',
        ),
        migrations.AlterField(
            model_name='device',
            name='device_model',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='devices', to='global_config.devicemodel', verbose_name='设备型号'),
        ),
    ]
