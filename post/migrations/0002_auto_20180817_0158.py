# -*- coding: utf-8 -*-
# Generated by Django 1.10 on 2018-08-16 22:58
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('post', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='post',
            name='comment',
            field=models.IntegerField(default=1, editable=False, verbose_name='like'),
        ),
        migrations.AlterField(
            model_name='post',
            name='like',
            field=models.IntegerField(default=1, editable=False, verbose_name='like'),
        ),
        migrations.AlterField(
            model_name='post',
            name='look',
            field=models.IntegerField(default=1, editable=False, verbose_name='like'),
        ),
    ]
