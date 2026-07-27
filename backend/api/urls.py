"""API route definitions."""

from django.urls import path

from api.views import (
    ChatCompletionView,
    DocumentDeleteView,
    DocumentListView,
    DocumentUploadView,
    HealthView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("chat/", ChatCompletionView.as_view(), name="chat"),
    path("documents/", DocumentListView.as_view(), name="document-list"),
    path(
        "documents/upload/",
        DocumentUploadView.as_view(),
        name="document-upload",
    ),
    path(
        "documents/<str:document_id>/",
        DocumentDeleteView.as_view(),
        name="document-delete",
    ),
]
