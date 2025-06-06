# Generated by Django 5.2.1 on 2025-05-17 07:57

import shortuuid.main
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('a_rtchat', '0007_remove_chatgroup_delivered_at_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='groupmessage',
            name='delivered_at',
        ),
        migrations.RemoveField(
            model_name='groupmessage',
            name='read_by',
        ),
        migrations.AlterField(
            model_name='chatgroup',
            name='group_name',
            field=models.CharField(default=shortuuid.main.ShortUUID.uuid, max_length=128, unique=True),
        ),
    ]
