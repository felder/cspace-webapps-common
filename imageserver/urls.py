__author__ = 'jblowe'

from django.urls import include, path
from django.views.decorators.cache import cache_page
from imageserver import views

urlpatterns = [
    # ex: /imageserver/blobs/5dbc3c43-b765-4c10-9d5d/derivatives/Medium/content
    # path('<image>', views.get_image, name='get_image'),
    # cache images for 180 days..
    path('<image>.+)', cache_page(60 * 60 * 24 * 180)(views.get_image), name='get_image'),
]
