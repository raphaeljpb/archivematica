# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2021-03-08 17:03
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("fpr", "0033_update_idtools"),
    ]

    operations = [
        migrations.DeleteModel(
            name="Agent",
        ),
        migrations.DeleteModel(
            name="Command",
        ),
        migrations.DeleteModel(
            name="CommandClassification",
        ),
        migrations.DeleteModel(
            name="CommandRelationship",
        ),
        migrations.DeleteModel(
            name="CommandsSupportedBy",
        ),
        migrations.DeleteModel(
            name="CommandType",
        ),
        migrations.RemoveField(
            model_name="fileid",
            name="format",
        ),
        migrations.DeleteModel(
            name="FileIDsBySingleID",
        ),
        migrations.DeleteModel(
            name="FileIDType",
        ),
        migrations.DeleteModel(
            name="FileID",
        ),
    ]
