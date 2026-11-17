"""Create the product table."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """The shop's first migration."""

    initial = True
    dependencies: list[tuple[str, str]] = []
    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[("name", models.CharField(max_length=100))],
        ),
    ]
