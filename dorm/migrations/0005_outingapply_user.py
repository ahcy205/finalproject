import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def link_existing_outings(apps, schema_editor):
    """기존 외박 신청을 학번(= 계정 아이디)이 같은 사용자에게 연결한다."""
    OutingApply = apps.get_model('dorm', 'OutingApply')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    users = {u.username: u.pk for u in User.objects.all()}
    for outing in OutingApply.objects.filter(user__isnull=True):
        user_id = users.get(outing.student_number)
        if user_id:
            outing.user_id = user_id
            outing.save(update_fields=['user'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('dorm', '0004_notice_image_userprofile_phone_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='outingapply',
            name='user',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='outing_applies', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(link_existing_outings, migrations.RunPython.noop),
    ]
