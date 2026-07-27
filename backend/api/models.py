"""Domain models."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Document(models.Model):
    """使用者上傳的知識庫文件中繼資料 (Blob + Search 內容存於 Azure)。"""

    document_id = models.CharField(max_length=64, unique=True, db_index=True)
    title = models.CharField(max_length=200)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    file_size = models.PositiveIntegerField()
    chunk_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.document_id})"
