"""
Azure Document Intelligence 服務封裝層。
使用 prebuilt-layout 模型抽取 PDF 文字 + 表格 (轉為 Markdown 保留結構)。
"""

from __future__ import annotations

import logging

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError
from django.conf import settings
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class DocumentIntelligenceServiceError(Exception):
    """Azure Document Intelligence 服務例外。"""


class AzureDocumentIntelligenceService:
    """
    封裝 Azure Document Intelligence,提供 PDF 文字 + 表格抽取功能。

    使用情境:
        service = AzureDocumentIntelligenceService()
        markdown_content = service.extract_text(pdf_bytes)
    """

    MODEL_ID = "prebuilt-layout"

    def __init__(self) -> None:
        endpoint = settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        key = settings.AZURE_DOCUMENT_INTELLIGENCE_KEY
        if not endpoint or not key:
            raise DocumentIntelligenceServiceError(
                "Document Intelligence 端點或金鑰未設定 "
                "(AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT / _KEY)"
            )
        self._client = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key),
        )

    @retry(
        retry=retry_if_exception_type(AzureError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def extract_text(self, file_bytes: bytes) -> str:
        """
        使用 prebuilt-layout 模型分析 PDF,回傳 Markdown 格式的全文 (含表格)。

        Args:
            file_bytes: PDF 檔案的原始 bytes

        Returns:
            Markdown 格式的文件內容

        Raises:
            DocumentIntelligenceServiceError: Azure 服務呼叫失敗
        """
        try:
            poller = self._client.begin_analyze_document(
                model_id=self.MODEL_ID,
                body=AnalyzeDocumentRequest(bytes_source=file_bytes),
                output_content_format="markdown",
            )
            result = poller.result()
            content = result.content or ""
            pages = len(getattr(result, "pages", []) or [])
            logger.info(
                "Document Intelligence 抽取完成 | pages=%d | content_len=%d",
                pages,
                len(content),
            )
            return content
        except AzureError as exc:
            logger.error("Document Intelligence 抽取失敗: %s", exc, exc_info=True)
            raise DocumentIntelligenceServiceError(f"PDF 抽取失敗: {exc}") from exc
