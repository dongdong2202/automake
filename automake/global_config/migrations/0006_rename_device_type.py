from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('global_config', '0005_globalmenuitem_detail_page_and_more'),
        ('devices', '0005_devicematerialstock'),
        ('menus', '0011_remove_menusku_category'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='DeviceType',
            new_name='DeviceModel',
        ),
        migrations.AlterModelTable(
            name='DeviceModel',
            table='global_device_model',
        ),
        migrations.AlterModelOptions(
            name='devicemodel',
            options={'verbose_name': '全局设备型号', 'verbose_name_plural': '全局设备型号列表'},
        ),
        migrations.AlterField(
            model_name='devicemodel',
            name='code',
            field=models.CharField(max_length=64, unique=True, verbose_name='型号编码'),
        ),
        migrations.AlterField(
            model_name='devicemodel',
            name='description',
            field=models.TextField(blank=True, verbose_name='型号描述'),
        ),
        migrations.AlterField(
            model_name='devicemodel',
            name='name',
            field=models.CharField(max_length=128, verbose_name='设备型号名称'),
        ),
        migrations.RenameField(
            model_name='globalmenucategory',
            old_name='device_type',
            new_name='device_model',
        ),
        migrations.AlterField(
            model_name='globalmenucategory',
            name='device_model',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='categories', to='global_config.devicemodel', verbose_name='设备型号'),
        ),
    ]
