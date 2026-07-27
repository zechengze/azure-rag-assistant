"""
API Serializers — 輸入驗證層。
所有使用者輸入均在此進行驗證與清理，防範惡意輸入。
"""

from __future__ import annotations

import re

from django.conf import settings
from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    """聊天請求序列化器，嚴格驗證查詢輸入。"""

    query = serializers.CharField(
        min_length=1,
        max_length=settings.RAG_MAX_QUERY_LENGTH,
        trim_whitespace=True,
        error_messages={
            "min_length": "查詢不得為空白",
            "max_length": f"查詢長度不得超過 {settings.RAG_MAX_QUERY_LENGTH} 字元",
        },
    )
    history = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        max_length=20,  # 最多保留 20 輪對話記錄
    )
    stream = serializers.BooleanField(required=False, default=False)

    def validate_query(self, value: str) -> str:
        """過濾潛在的 Prompt Injection 嘗試。"""
        # 移除控制字元
        cleaned = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value)

        # 偵測常見的 Prompt Injection 模式（記錄但不阻擋，由 System Prompt 分離處理）
        injection_patterns = [
            r"ignore\s+previous\s+instructions",
            r"forget\s+everything",
            r"system\s*:\s*you\s+are",
            r"<\s*system\s*>",
        ]
        for pattern in injection_patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                import logging

                logging.getLogger(__name__).warning(
                    "潛在 Prompt Injection 偵測: %s", cleaned[:100]
                )
                break

        return cleaned

    def validate_history(self, value: list[dict]) -> list[dict]:
        """驗證對話歷史格式，僅允許 user/assistant 角色。"""
        validated = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role", "")
            content = entry.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                validated.append(
                    {
                        "role": role,
                        "content": content[:2000],  # 截斷過長歷史
                    }
                )
        return validated


class DocumentUploadSerializer(serializers.Serializer):
    """文件上傳序列化器。"""

    ALLOWED_CONTENT_TYPES = {
        "text/plain",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    MAX_FILE_SIZE_MB = 10

    title = serializers.CharField(min_length=1, max_length=200, trim_whitespace=True)
    file = serializers.FileField()

    def validate_file(self, value):
        """驗證檔案類型與大小。"""
        # 驗證 MIME 類型
        content_type = getattr(value, "content_type", "")
        if content_type not in self.ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError(
                f"不支援的檔案類型：{content_type}。" f"允許類型：PDF、TXT、DOCX"
            )

        # 驗證檔案大小
        max_size = self.MAX_FILE_SIZE_MB * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError(
                f"檔案大小超過限制（最大 {self.MAX_FILE_SIZE_MB} MB）"
            )

        return value


class DocumentListSerializer(serializers.Serializer):
    """文件清單回應序列化器（唯讀，供 GET /api/documents/ 使用）。"""

    document_id = serializers.CharField()
    title = serializers.CharField()
    created_at = serializers.DateTimeField()
    chunk_count = serializers.IntegerField()
    file_size = serializers.IntegerField()
