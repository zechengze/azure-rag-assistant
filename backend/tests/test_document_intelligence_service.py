"""
AzureDocumentIntelligenceService 測試 — 全程 mock,不呼叫真實 Azure。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import AzureError

from services.document_intelligence_service import (
    AzureDocumentIntelligenceService,
    DocumentIntelligenceServiceError,
)


class TestDocumentIntelligenceService:
    def test_init_raises_when_endpoint_missing(self, settings):
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = ""
        settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "k"
        with pytest.raises(DocumentIntelligenceServiceError):
            AzureDocumentIntelligenceService()

    def test_init_raises_when_key_missing(self, settings):
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = (
            "https://test.cognitiveservices.azure.com/"
        )
        settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = ""
        with pytest.raises(DocumentIntelligenceServiceError):
            AzureDocumentIntelligenceService()

    @patch("services.document_intelligence_service.DocumentIntelligenceClient")
    def test_extract_text_returns_markdown_content(self, mock_client_cls, settings):
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = (
            "https://test.cognitiveservices.azure.com/"
        )
        settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "test-key"

        mock_result = MagicMock()
        mock_result.content = "# 標題\n\n表格內容..."
        mock_result.pages = [MagicMock(), MagicMock()]
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_client_cls.return_value.begin_analyze_document.return_value = mock_poller

        service = AzureDocumentIntelligenceService()
        result = service.extract_text(b"%PDF-1.4 fake content")

        assert result == "# 標題\n\n表格內容..."
        mock_client_cls.return_value.begin_analyze_document.assert_called_once()

    @patch("services.document_intelligence_service.DocumentIntelligenceClient")
    def test_extract_text_wraps_azure_error(self, mock_client_cls, settings):
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = (
            "https://test.cognitiveservices.azure.com/"
        )
        settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "test-key"

        mock_client_cls.return_value.begin_analyze_document.side_effect = AzureError(
            "DI service unavailable"
        )

        service = AzureDocumentIntelligenceService()
        with pytest.raises(DocumentIntelligenceServiceError, match="PDF 抽取失敗"):
            service.extract_text(b"%PDF-1.4")

    @patch("services.document_intelligence_service.DocumentIntelligenceClient")
    def test_extract_text_handles_empty_content(self, mock_client_cls, settings):
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = (
            "https://test.cognitiveservices.azure.com/"
        )
        settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "test-key"

        mock_result = MagicMock()
        mock_result.content = None
        mock_result.pages = []
        mock_poller = MagicMock()
        mock_poller.result.return_value = mock_result
        mock_client_cls.return_value.begin_analyze_document.return_value = mock_poller

        service = AzureDocumentIntelligenceService()
        result = service.extract_text(b"%PDF-1.4")
        assert result == ""
