from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('menus', '0011_remove_menusku_category'),
        ('global_config', '0006_rename_device_type'),
    ]

    operations = [
        migrations.RenameField(
            model_name='menuitem',
            old_name='device_type',
            new_name='device_model',
        ),
        migrations.AlterField(
            model_name='menuitem',
            name='device_model',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='local_items', to='global_config.devicemodel', verbose_name='设备型号'),
        ),
    ]
