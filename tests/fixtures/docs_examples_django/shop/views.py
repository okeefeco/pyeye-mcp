"""The shop's pages."""

from django.shortcuts import render
from django.views.generic import ListView

from .models import Product


class ProductList(ListView):
    """List every product."""

    model = Product


def product_detail(request, product_id: int):
    """Show one product."""
    return render(request, "shop/detail.html", {"product_id": product_id})
