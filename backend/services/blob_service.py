"""
Azure Blob Storage 服務封裝層。
負責文件上傳、SAS Token 簽發、擁有者驗證,以及依 MIME 類型路由文字抽取。

Blob 路徑慣例: {user_id}/{document_id}/{filename}
路徑前綴用於存取控制驗證,避免越權刪除。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import IO, Any

from azure.core.exceptions import AzureError, ResourceExistsError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)
from django.conf import settings
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


PDF_MIME = "application/pdf"
TXT_MIME = "text/plain"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class BlobServiceError(Exception):
    """Azure Blob Storage 服務例外。"""


class AzureBlobService:
    """
    封裝 Azure Blob Storage 操作。

    使用情境:
        service = AzureBlobService()
        document_id, url = service.upload_document(file, user_id, filename)
        content = service.extract_text(file)  # 依 MIME 路由
    """

    def __init__(self) -> None:
        try:
            self._client = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )
        except ValueError as exc:
            raise BlobServiceError(f"Blob 連線字串設定錯誤: {exc}") from exc
        self._container_name = settings.AZURE_STORAGE_CONTAINER
        self._sas_expiry_hours = settings.AZURE_STORAGE_SAS_EXPIRY_HOURS

    # ── Upload ─────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(AzureError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _upload_blob(self, blob_client: Any, data: bytes, content_type: str) -> None:
        """
        實際的上傳呼叫 —— AzureError 原樣往外拋,tenacity 才看得到並重試。
        裝飾器若套在 upload_document,方法內的 except 會先把例外換成
        BlobServiceError,重試條件永遠不成立。

        重試只涵蓋這一步:document_id 在外層產生,重試不會換路徑,也不會
        重跑容器建立。
        """
        try:
            blob_client.upload_blob(
                data,
                overwrite=False,
                content_settings=ContentSettings(content_type=content_type),
            )
        except ResourceExistsError:
            # 前一次嘗試其實已寫入成功、只是回應沒送達。blob 路徑含本次
            # 呼叫才產生的 UUID,不可能是別人的檔案,視為成功。
            logger.info("Blob 已存在,視為前次重試已完成: %s", blob_client.blob_name)

    def upload_document(
        self,
        file: IO[bytes],
        user_id: str,
        filename: str,
    ) -> tuple[str, str]:
        """
        上傳檔案至 Blob Storage,路徑為 {user_id}/{document_id}/{filename}。

        Returns:
            (document_id, blob_url) — document_id 為新生成的 UUID hex

        Raises:
            BlobServiceError: 上傳失敗（含重試耗盡）
        """
        document_id = uuid.uuid4().hex
        blob_path = f"{user_id}/{document_id}/{filename}"
        content_type = getattr(file, "content_type", "application/octet-stream")

        try:
            container_client = self._client.get_container_client(self._container_name)
            try:
                container_client.create_container()
            except ResourceExistsError:
                pass

            blob_client = container_client.get_blob_client(blob_path)
            file.seek(0)
            self._upload_blob(blob_client, file.read(), content_type)
            logger.info(
                "Blob 上傳完成 | user=%s | document_id=%s | size=%d",
                user_id,
                document_id,
                getattr(file, "size", 0),
            )
            return document_id, blob_client.url
        except AzureError as exc:
            logger.error("Blob 上傳失敗: %s", exc, exc_info=True)
            raise BlobServiceError(f"Blob 上傳失敗: {exc}") from exc

    # ── Text extraction (MIME 路由) ─────────────────────────────────────────

    def extract_text(self, file: IO[bytes]) -> str:
        """
        依 MIME 類型路由文字抽取:
          - application/pdf  → Document Intelligence (保留表格 Markdown)
          - text/plain       → 直接 UTF-8 decode
          - DOCX             → python-docx
        """
        content_type = getattr(file, "content_type", "")
        file.seek(0)

        if content_type == PDF_MIME:
            return self._extract_pdf(file.read())
        if content_type == TXT_MIME:
            return self._extract_txt(file.read())
        if content_type == DOCX_MIME:
            return self._extract_docx(file)
        raise BlobServiceError(f"不支援的檔案類型: {content_type!r}")

    @staticmethod
    def _extract_pdf(data: bytes) -> str:
        # Lazy import to avoid hard dependency when Document Intelligence
        # is not configured (e.g. PDF-less test runs).
        from services.document_intelligence_service import (
            AzureDocumentIntelligenceService,
            DocumentIntelligenceServiceError,
        )

        try:
            return AzureDocumentIntelligenceService().extract_text(data)
        except DocumentIntelligenceServiceError as exc:
            raise BlobServiceError(f"PDF 抽取失敗: {exc}") from exc

    @staticmethod
    def _extract_txt(data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlobServiceError(f"TXT 解碼失敗 (非 UTF-8): {exc}") from exc

    @staticmethod
    def _extract_docx(file: IO[bytes]) -> str:
        try:
            from docx import Document as DocxDocument

            # python-docx 需要可 seek 的檔案物件
            data = file.read() if hasattr(file, "read") else file
            if isinstance(data, bytes):
                data = BytesIO(data)
            doc = DocxDocument(data)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as exc:
            raise BlobServiceError(f"DOCX 解析失敗: {exc}") from exc

    # ── SAS Token ──────────────────────────────────────────────────────────

    def generate_sas_url(self, user_id: str, document_id: str, filename: str) -> str:
        """產生帶 SAS Token 的下載 URL,有效期為設定的 expiry hours (預設 1 小時)。"""
        blob_path = f"{user_id}/{document_id}/{filename}"
        account_name = self._client.account_name
        if account_name is None:
            raise BlobServiceError("無法取得 Storage Account 名稱")

        credential = self._client.credential
        account_key = getattr(credential, "account_key", None)
        if account_key is None:
            raise BlobServiceError(
                "Storage credential 不支援 SAS 簽發 (需 account key)"
            )

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self._container_name,
            blob_name=blob_path,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=self._sas_expiry_hours),
        )
        return (
            f"https://{account_name}.blob.core.windows.net/"
            f"{self._container_name}/{blob_path}?{sas_token}"
        )

    # ── Owner verification & delete ────────────────────────────────────────

    def verify_owner(self, document_id: str, user_id: str) -> bool:
        """透過路徑前綴 {user_id}/{document_id}/ 確認文件擁有者。"""
        try:
            container_client = self._client.get_container_client(self._container_name)
            prefix = f"{user_id}/{document_id}/"
            for _ in container_client.list_blobs(name_starts_with=prefix):
                return True
            return False
        except AzureError as exc:
            logger.error("擁有者驗證失敗: %s", exc, exc_info=True)
            return False

    def delete_document(self, document_id: str, user_id: str | None = None) -> None:
        """
        刪除指定 document_id 底下的所有 blob。
        若提供 user_id 則以前綴精確刪除,否則掃描整個容器 (效能較差,僅作 fallback)。
        """
        try:
            container_client = self._client.get_container_client(self._container_name)
            if user_id:
                prefix = f"{user_id}/{document_id}/"
                blobs = list(container_client.list_blobs(name_starts_with=prefix))
            else:
                blobs = [
                    b
                    for b in container_client.list_blobs()
                    if f"/{document_id}/" in b.name
                ]

            for blob in blobs:
                container_client.delete_blob(blob.name)
                logger.info("Blob 已刪除: %s", blob.name)
        except AzureError as exc:
            raise BlobServiceError(f"Blob 刪除失敗: {exc}") from exc
