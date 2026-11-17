"""The shop's data."""

from django.db import models


class Product(models.Model):
    """Something the shop sells."""

    name = models.CharField(max_length=100)
