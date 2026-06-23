from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('global_config', '0007_alter_globalskuingredient_material'),
        ('inventory', '0003_alter_material_name'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='globalskuingredient',
            name='material',
        ),
        migrations.RemoveField(
            model_name='globalmaterial',
            name='id',
        ),
        migrations.AlterField(
            model_name='globalmaterial',
            name='name',
            field=models.ForeignKey(
                db_column='name', on_delete=django.db.models.deletion.CASCADE,
                primary_key=True, serialize=False, to='inventory.material',
                to_field='name', verbose_name='物料名称'
            ),
        ),
        migrations.AddField(
            model_name='globalskuingredient',
            name='material',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='ingredients', to='global_config.globalmaterial',
                verbose_name='物料', default='咖啡豆'
            ),
            preserve_default=False,
        ),
    ]
