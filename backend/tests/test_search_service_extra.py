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

    def test_hybrid_search_filter_is_exactly_the_tenant_condition(
        self, search_service_mocked
    ):
        """
        比對完整 filter 字串，而非 `"u42" in filter`。

        子字串斷言證明不了隔離：被注入的
        `user_id eq 'u42' or user_id ne 'x'` 同樣含有 u42，照樣會通過，
        但那條 filter 會讓整個索引全開。
        """
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.return_value = iter([])
        service.hybrid_search(query="x", user_id="u42")
        call_kwargs = mock_search_client.search.call_args.kwargs
        assert call_kwargs["filter"] == "user_id eq 'u42'"

    def test_hybrid_search_escapes_quote_in_user_id(self, search_service_mocked):
        """
        user_id 內的單引號須跳脫，否則可拼出恆真條件而讀到全部租戶。

        目前 user_id 是整數主鍵所以拼不出來，但這個前提沒有任何地方強制
        （見 CLAUDE.md 1.3 的 Azure AD / MSAL 整合）。
        """
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.return_value = iter([])
        service.hybrid_search(query="x", user_id="u1' or user_id ne 'zzz")
        call_kwargs = mock_search_client.search.call_args.kwargs
        assert call_kwargs["filter"] == "user_id eq 'u1'' or user_id ne ''zzz'"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_hybrid_search_rejects_blank_tenant(self, search_service_mocked, blank):
        """空租戶會比對不到任何文件而看起來像「沒有資料」，須當場拒絕。"""
        service, mock_search_client, _, _ = search_service_mocked
        with pytest.raises(ValueError):
            service.hybrid_search(query="x", user_id=blank)
        mock_search_client.search.assert_not_called()


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
        service.delete_document(document_id="doc1", user_id="u42")
        mock_search_client.delete_documents.assert_called_once()
        deleted = mock_search_client.delete_documents.call_args.kwargs["documents"]
        assert len(deleted) == 2

    def test_delete_document_scopes_lookup_to_owner(self, search_service_mocked):
        """
        撈取待刪 chunk 的條件須同時綁定 document_id 與租戶。

        只用 document_id 撈取，等於把隔離責任丟給呼叫端；view 目前有先查
        擁有者，但那層檢查漏掉時此處不會有任何抵抗。
        """
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.return_value = iter([])
        service.delete_document(document_id="doc1", user_id="u42")
        call_kwargs = mock_search_client.search.call_args.kwargs
        expected = "document_id eq 'doc1' and user_id eq 'u42'"
        assert call_kwargs["filter"] == expected

    def test_delete_document_deletes_nothing_across_tenants(
        self, search_service_mocked
    ):
        """租戶條件過濾掉全部 chunk 時不得發出任何 delete。"""
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.return_value = iter([])
        service.delete_document(document_id="doc1", user_id="not-the-owner")
        mock_search_client.delete_documents.assert_not_called()

    def test_delete_document_rejects_blank_tenant(self, search_service_mocked):
        service, mock_search_client, _, _ = search_service_mocked
        with pytest.raises(ValueError):
            service.delete_document(document_id="doc1", user_id="")
        mock_search_client.search.assert_not_called()

    def test_delete_document_wraps_azure_error(self, search_service_mocked):
        service, mock_search_client, _, _ = search_service_mocked
        mock_search_client.search.side_effect = AzureError("search down")
        with pytest.raises(SearchServiceError):
            service.delete_document(document_id="doc1", user_id="u42")


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
