"""The shop's URLs."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.ProductList.as_view(), name="product-list"),
    path("<int:product_id>/", views.product_detail, name="product-detail"),
]
