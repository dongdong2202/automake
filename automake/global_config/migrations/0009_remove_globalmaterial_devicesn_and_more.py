from django.db import migrations, models
import django.db.models.deletion

def clear_global_materials(apps, schema_editor):
    GlobalMaterial = apps.get_model('global_config', 'GlobalMaterial')
    GlobalMaterial.objects.all().delete()

class Migration(migrations.Migration):

    dependencies = [
        ('global_config', '0008_remove_globalmaterial_id_alter_globalmaterial_name'),
    ]

    operations = [
        migrations.RunPython(clear_global_materials),
        migrations.RemoveField(
            model_name='globalmaterial',
            name='deviceSN',
        ),
        migrations.AlterField(
            model_name='globalmaterial',
            name='deviceVersion',
            field=models.ForeignKey(default='1', on_delete=django.db.models.deletion.CASCADE, to='global_config.devicemodel', to_field='code', verbose_name='设备版本'),
        ),
        migrations.AlterField(
            model_name='globalmaterial',
            name='initHight',
            field=models.IntegerField(default=100, verbose_name='满料高度'),
        ),
    ]
