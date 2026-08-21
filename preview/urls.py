"""One URL: GET shows the upload form, POST shows the analysis."""

from django.urls import path

from preview import views

urlpatterns = [
    path("", views.import_preview, name="import-preview"),
]
