"""
AzureSearchService 補充測試 — hybrid_search / index_document / delete_document。
test_services.py 已涵蓋 chunking,此檔聚焦在搜尋與索引主流程。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import AzureError

from services.search_service import AzureSearchService, SearchServiceError


@pytest.fixture
def search_service_mocked():
    """完整 mock 整條 search_service 依賴鏈。"""
    with (
        patch("services.search_service.SearchClient") as mock_sc,
        patch("services.search_service.SearchIndexClient") as mock_ic,
        patch("services.search_service.AzureOpenAIService") as mock_openai_cls,
    ):
        mock_search_client = MagicMock()
        mock_index_client = MagicMock()
        mock_openai = MagicMock()
        mock_openai.get_embedding.return_value = [0.1] * 1536
        mock_sc.return_value = mock_search_client
        mock_ic.return_value = mock_index_client
        mock_openai_cls.return_value = mock_openai

        service = AzureSearchService()
        yield service, mock_search_client, mock_index_client, mock_openai


class TestHybridSearch:
    def test_hybrid_search_returns_filtered_docs(self, search_service_mocked):
        service, mock_search_client, _, mock_openai = search_service_mocked

        mock_search_client.search.return_value = iter(
            [
                {
                    "id": "doc1-chunk-0",
                    "document_id": "doc1",
                    "title": "Azure OpenAI 簡介",
                    "content": "...",
                    "chunk_index": 0,
                    "@search.score": 0.95,
                },
            ]
        )
        results = service.hybrid_search(query="What is Azure?", user_id="u1")
        assert len(results) == 1
        assert results[0]["title"] == "Azure OpenAI 簡介"
        assert results[0]["score"] == 0.95
        mock_openai.get_embedding.assert_called_once_with("What is Azure?")

    def test_hybrid_search_wraps_azure_error(self, search_service_mocked):
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.side_effect = AzureError("search down")
        with pytest.raises(SearchServiceError):
            service.hybrid_search(query="x", user_id="u1")

    def test_hybrid_search_filter_includes_user_id(self, search_service_mocked):
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.return_value = iter([])
        service.hybrid_search(query="x", user_id="u42")
        call_kwargs = mock_search_client.search.call_args.kwargs
        assert "u42" in call_kwargs["filter"]


class TestIndexDocument:
    def test_index_document_chunks_and_uploads(self, search_service_mocked):
        service, mock_search_client, _, mock_openai = search_service_mocked
        mock_result = [MagicMock(succeeded=True), MagicMock(succeeded=True)]
        mock_search_client.upload_documents.return_value = mock_result

        content = "第一句。第二句。" * 50  # 足夠長
        count = service.index_document(
            document_id="doc1",
            title="Test",
            content=content,
            user_id="u1",
        )
        assert count == 2
        assert mock_openai.get_embedding.call_count >= 1

    def test_index_document_skips_failed_chunks(self, search_service_mocked):
        service, mock_search_client, _, mock_openai = search_service_mocked
        mock_openai.get_embedding.side_effect = Exception("embed failed")
        # 所有 chunk 都失敗 -> 0 documents -> 不會呼叫 upload
        count = service.index_document(
            document_id="doc1",
            title="Test",
            content="一句。" * 100,
            user_id="u1",
        )
        assert count == 0
        mock_search_client.upload_documents.assert_not_called()


class TestDeleteDocument:
    def test_delete_document_removes_all_chunks(self, search_service_mocked):
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.return_value = iter(
            [{"id": "doc1-chunk-0"}, {"id": "doc1-chunk-1"}]
        )
        service.delete_document("doc1")
        mock_search_client.delete_documents.assert_called_once()
        deleted = mock_search_client.delete_documents.call_args.kwargs["documents"]
        assert len(deleted) == 2

    def test_delete_document_wraps_azure_error(self, search_service_mocked):
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.side_effect = AzureError("search down")
        with pytest.raises(SearchServiceError):
            service.delete_document("doc1")


class TestEnsureIndexExists:
    def test_ensure_index_skips_when_already_exists(self, search_service_mocked):
        service, _, mock_index_client, _ = search_service_mocked
        mock_index_client.get_index.return_value = MagicMock()
        service.ensure_index_exists()
        mock_index_client.create_or_update_index.assert_not_called()

    def test_ensure_index_creates_when_missing(self, search_service_mocked):
        service, _, mock_index_client, _ = search_service_mocked
        mock_index_client.get_index.side_effect = Exception("not found")
        service.ensure_index_exists()
        mock_index_client.create_or_update_index.assert_called_once()
