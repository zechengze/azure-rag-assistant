"""
AzureBlobService 測試 — 涵蓋 MIME 路由、SAS、上傳、刪除 (Azure SDK 全 mock)。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import AzureError
from django.core.files.uploadedfile import SimpleUploadedFile

from services.blob_service import PDF_MIME, TXT_MIME, AzureBlobService, BlobServiceError

# ── Static 路由方法 (不需 Azure SDK) ─────────────────────────────────────────


class TestExtractTextRouting:
    def test_extract_txt_decodes_utf8(self):
        assert (
            AzureBlobService._extract_txt("你好 world".encode("utf-8")) == "你好 world"
        )

    def test_extract_txt_raises_on_invalid_utf8(self):
        with pytest.raises(BlobServiceError):
            AzureBlobService._extract_txt(b"\xff\xfe\xfd invalid")

    def test_extract_text_routing_unknown_mime_raises(self):
        with patch("services.blob_service.BlobServiceClient"):
            service = AzureBlobService()
            file = SimpleUploadedFile(
                "x.bin", b"data", content_type="application/octet-stream"
            )
            with pytest.raises(BlobServiceError, match="不支援"):
                service.extract_text(file)

    def test_extract_text_routes_txt(self):
        with patch("services.blob_service.BlobServiceClient"):
            service = AzureBlobService()
            file = SimpleUploadedFile("x.txt", b"hello", content_type=TXT_MIME)
            assert service.extract_text(file) == "hello"

    def test_extract_text_routes_pdf_to_document_intelligence(self):
        with patch("services.blob_service.BlobServiceClient"):
            service = AzureBlobService()
            file = SimpleUploadedFile("x.pdf", b"%PDF-1.4 fake", content_type=PDF_MIME)
            with patch(
                "services.document_intelligence_service."
                "AzureDocumentIntelligenceService"
            ) as mock_di_cls:
                mock_di_cls.return_value.extract_text.return_value = "# 標題\n內容"
                result = service.extract_text(file)
                assert result == "# 標題\n內容"
                mock_di_cls.return_value.extract_text.assert_called_once()

    def test_extract_text_routes_pdf_propagates_di_error(self):
        from services.document_intelligence_service import (
            DocumentIntelligenceServiceError,
        )

        with patch("services.blob_service.BlobServiceClient"):
            service = AzureBlobService()
            file = SimpleUploadedFile("x.pdf", b"%PDF-1.4", content_type=PDF_MIME)
            with patch(
                "services.document_intelligence_service."
                "AzureDocumentIntelligenceService"
            ) as mock_di_cls:
                mock_di_cls.return_value.extract_text.side_effect = (
                    DocumentIntelligenceServiceError("DI down")
                )
                with pytest.raises(BlobServiceError, match="PDF 抽取失敗"):
                    service.extract_text(file)


# ── Upload / Delete / Verify (mocked SDK) ────────────────────────────────────


@pytest.fixture
def mock_blob_sdk():
    """模擬整個 azure.storage.blob 客戶端鏈,回傳容器 mock。"""
    with patch("services.blob_service.BlobServiceClient") as mock_cls:
        mock_service_client = MagicMock()
        mock_container = MagicMock()
        mock_blob_client = MagicMock()
        mock_blob_client.url = "https://test.blob.core.windows.net/x"
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_service_client.get_container_client.return_value = mock_container
        mock_service_client.account_name = "testaccount"
        mock_service_client.credential = MagicMock(account_key="dGVzdGtleQ==")
        mock_cls.from_connection_string.return_value = mock_service_client
        yield mock_service_client, mock_container, mock_blob_client


class TestUploadDocument:
    def test_upload_returns_document_id_and_url(self, mock_blob_sdk):
        _, mock_container, _ = mock_blob_sdk
        service = AzureBlobService()
        file = SimpleUploadedFile("doc.txt", b"hello", content_type="text/plain")
        document_id, url = service.upload_document(
            file=file, user_id="42", filename="doc.txt"
        )
        assert len(document_id) == 32  # uuid4().hex
        assert "blob.core.windows.net" in url

    def test_upload_swallows_existing_container(self, mock_blob_sdk):
        from azure.core.exceptions import ResourceExistsError

        _, mock_container, _ = mock_blob_sdk
        mock_container.create_container.side_effect = ResourceExistsError(
            message="already exists"
        )
        service = AzureBlobService()
        file = SimpleUploadedFile("doc.txt", b"hello", content_type="text/plain")
        document_id, _ = service.upload_document(
            file=file, user_id="42", filename="doc.txt"
        )
        assert document_id  # 沒爆炸

    def test_upload_azure_error_wrapped(self, mock_blob_sdk):
        _, mock_container, mock_blob_client = mock_blob_sdk
        mock_blob_client.upload_blob.side_effect = AzureError("upload failed")
        service = AzureBlobService()
        file = SimpleUploadedFile("doc.txt", b"hello", content_type="text/plain")
        with pytest.raises(BlobServiceError, match="上傳失敗"):
            service.upload_document(file=file, user_id="42", filename="doc.txt")


class TestVerifyOwnerAndDelete:
    def test_verify_owner_returns_true_when_blob_exists(self, mock_blob_sdk):
        _, mock_container, _ = mock_blob_sdk
        mock_container.list_blobs.return_value = iter([MagicMock(name="b1")])
        service = AzureBlobService()
        assert service.verify_owner("docid", "userid") is True

    def test_verify_owner_returns_false_when_empty(self, mock_blob_sdk):
        _, mock_container, _ = mock_blob_sdk
        mock_container.list_blobs.return_value = iter([])
        service = AzureBlobService()
        assert service.verify_owner("docid", "userid") is False

    def test_verify_owner_returns_false_on_azure_error(self, mock_blob_sdk):
        _, mock_container, _ = mock_blob_sdk
        mock_container.list_blobs.side_effect = AzureError("list failed")
        service = AzureBlobService()
        assert service.verify_owner("docid", "userid") is False

    def test_delete_document_with_user_id_uses_prefix(self, mock_blob_sdk):
        _, mock_container, _ = mock_blob_sdk
        fake_blob = MagicMock()
        fake_blob.name = "userid/docid/file.txt"
        mock_container.list_blobs.return_value = [fake_blob]
        service = AzureBlobService()
        service.delete_document(document_id="docid", user_id="userid")
        mock_container.list_blobs.assert_called_once_with(
            name_starts_with="userid/docid/"
        )
        mock_container.delete_blob.assert_called_once_with("userid/docid/file.txt")

    def test_delete_document_requires_user_id(self, mock_blob_sdk):
        """
        不得存在「省略 user_id 就掃全容器」的 fallback。

        舊版以 `/{document_id}/` 子字串比對整個容器，命中的可能是其他租戶
        的 blob；呼叫端漏傳 user_id 時刪除範圍會安靜地跨出本租戶。
        """
        _, mock_container, _ = mock_blob_sdk
        service = AzureBlobService()
        with pytest.raises(TypeError):
            service.delete_document(document_id="docid")
        mock_container.list_blobs.assert_not_called()
        mock_container.delete_blob.assert_not_called()

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_delete_document_rejects_blank_user_id(self, mock_blob_sdk, blank):
        """空 user_id 會讓前綴退化成跨租戶比對，須當場拒絕。"""
        _, mock_container, _ = mock_blob_sdk
        service = AzureBlobService()
        with pytest.raises(ValueError):
            service.delete_document(document_id="docid", user_id=blank)
        mock_container.delete_blob.assert_not_called()

    def test_delete_document_never_touches_other_tenants_blobs(self, mock_blob_sdk):
        """
        刪除只發給前綴查詢回傳的 blob。

        list_blobs 由 Azure 依 name_starts_with 過濾，此處以「回傳空集合」
        模擬非擁有者的情況，確認不會退回任何形式的全容器掃描。
        """
        _, mock_container, _ = mock_blob_sdk
        mock_container.list_blobs.return_value = []
        service = AzureBlobService()
        service.delete_document(document_id="docid", user_id="not-the-owner")
        mock_container.list_blobs.assert_called_once_with(
            name_starts_with="not-the-owner/docid/"
        )
        mock_container.delete_blob.assert_not_called()

    def test_delete_azure_error_wrapped(self, mock_blob_sdk):
        _, mock_container, _ = mock_blob_sdk
        mock_container.list_blobs.side_effect = AzureError("oops")
        service = AzureBlobService()
        with pytest.raises(BlobServiceError):
            service.delete_document(document_id="docid", user_id="userid")


class TestSasUrl:
    def test_generate_sas_url_returns_signed_url(self, mock_blob_sdk):
        service = AzureBlobService()
        with patch("services.blob_service.generate_blob_sas") as mock_gen:
            mock_gen.return_value = "sv=2024-01-01&sig=fake"
            url = service.generate_sas_url(
                user_id="42", document_id="doc1", filename="x.txt"
            )
        assert "blob.core.windows.net" in url
        assert "sv=2024-01-01" in url

    def test_generate_sas_url_requires_account_key(self, mock_blob_sdk):
        mock_service_client, _, _ = mock_blob_sdk
        mock_service_client.credential = MagicMock(spec=[])  # no account_key
        service = AzureBlobService()
        with pytest.raises(BlobServiceError):
            service.generate_sas_url(user_id="42", document_id="doc1", filename="x.txt")


class TestConstruction:
    def test_init_raises_on_bad_connection_string(self):
        with patch("services.blob_service.BlobServiceClient") as mock_cls:
            mock_cls.from_connection_string.side_effect = ValueError("bad")
            with pytest.raises(BlobServiceError):
                AzureBlobService()
