"""
View 整合測試 — 使用 DRF APIClient 覆蓋三個主要端點。
所有 Azure 服務呼叫均透過 mock 隔離,符合 CLAUDE.md「禁止呼叫付費 API」規範。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from api.models import Document
from services.blob_service import BlobServiceError
from services.openai_service import OpenAIServiceError
from services.search_service import SearchServiceError

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """每個測試前清空 throttle 計數,避免 30/hour 限流影響測試。"""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(username="alice", password="VerySecret123!")


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(username="bob", password="VerySecret123!")


@pytest.fixture
def client(user):
    api_client = APIClient()
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def anon_client():
    return APIClient()


def parse_sse(body: str) -> list[dict[str, Any]]:
    """
    以 SSE 規範解析回應主體,回傳各事件的 JSON payload。

    刻意不用 `"data: xxx" in body` 之類的子字串比對 —— 那種斷言在事件被
    換行截斷時照樣通過,正是原本的 bug 沒被測到的原因。這裡照規範走:
    空行分事件、`data:` 行去掉前綴後以換行接回,與瀏覽器端行為一致。
    """
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        data_lines = [
            line[5:].lstrip(" ")
            for line in block.split("\n")
            if line.startswith("data:")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


# ── ChatCompletionView ────────────────────────────────────────────────────────


class TestChatCompletionView:
    URL = "/api/chat/"

    @patch("api.views.AzureOpenAIService")
    @patch("api.views.AzureSearchService")
    def test_chat_success_non_stream(self, mock_search_cls, mock_openai_cls, client):
        mock_search_cls.return_value.hybrid_search.return_value = [
            {"title": "doc1", "chunk_index": 0, "content": "Azure OpenAI 簡介"},
            {"title": "doc1", "chunk_index": 1, "content": "Embedding 教學"},
        ]
        mock_openai_cls.return_value.chat_completion.return_value = "這是 AI 回答"

        resp = client.post(self.URL, {"query": "什麼是 Azure OpenAI?"}, format="json")

        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "這是 AI 回答"
        assert body["sources"] == [
            {"title": "doc1", "chunk_index": 0},
            {"title": "doc1", "chunk_index": 1},
        ]
        mock_search_cls.return_value.hybrid_search.assert_called_once()
        mock_openai_cls.return_value.chat_completion.assert_called_once()

    def test_chat_empty_query_returns_400(self, client):
        resp = client.post(self.URL, {"query": ""}, format="json")
        assert resp.status_code == 400
        assert "errors" in resp.json()

    def test_chat_oversized_query_returns_400(self, client):
        resp = client.post(self.URL, {"query": "A" * 3000}, format="json")
        assert resp.status_code == 400

    def test_chat_unauthenticated_returns_401(self, anon_client):
        resp = anon_client.post(self.URL, {"query": "hi"}, format="json")
        assert resp.status_code == 401

    @patch("api.views.AzureSearchService")
    def test_chat_search_failure_returns_503(self, mock_search_cls, client):
        mock_search_cls.return_value.hybrid_search.side_effect = SearchServiceError(
            "search down"
        )
        resp = client.post(self.URL, {"query": "hi"}, format="json")
        assert resp.status_code == 503

    @patch("api.views.AzureOpenAIService")
    @patch("api.views.AzureSearchService")
    def test_chat_openai_failure_returns_503(
        self, mock_search_cls, mock_openai_cls, client
    ):
        mock_search_cls.return_value.hybrid_search.return_value = []
        mock_openai_cls.return_value.chat_completion.side_effect = OpenAIServiceError(
            "openai down"
        )
        resp = client.post(self.URL, {"query": "hi"}, format="json")
        assert resp.status_code == 503

    @patch("api.views.AzureOpenAIService")
    @patch("api.views.AzureSearchService")
    def test_chat_streaming_yields_sse(self, mock_search_cls, mock_openai_cls, client):
        mock_search_cls.return_value.hybrid_search.return_value = []
        mock_openai_cls.return_value.chat_completion_stream.return_value = iter(
            ["Hello", " ", "world"]
        )

        resp = client.post(self.URL, {"query": "hi", "stream": True}, format="json")
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/event-stream")

        events = parse_sse(b"".join(resp.streaming_content).decode("utf-8"))
        assert [e["token"] for e in events if "token" in e] == ["Hello", " ", "world"]
        assert events[-1] == {"done": True}

    @patch("api.views.AzureOpenAIService")
    @patch("api.views.AzureSearchService")
    def test_chat_streaming_preserves_newlines_in_tokens(
        self, mock_search_cls, mock_openai_cls, client
    ):
        """
        token 內含換行時,接收端必須能還原出一模一樣的字串。

        換行若直接寫進 `data:` 會被 SSE 當成事件邊界,該行之後的內容遭丟棄 ——
        模型回答的段落與條列會全部黏成一行,是 demo 中肉眼可見的缺陷。
        """
        tokens = ["這是第一行", "\n\n", "1. 項目一", "\n2. 項目二", "結尾"]
        mock_search_cls.return_value.hybrid_search.return_value = []
        mock_openai_cls.return_value.chat_completion_stream.return_value = iter(tokens)

        resp = client.post(self.URL, {"query": "hi", "stream": True}, format="json")

        events = parse_sse(b"".join(resp.streaming_content).decode("utf-8"))
        received = "".join(e["token"] for e in events if "token" in e)
        assert received == "".join(tokens)

    @patch("api.views.AzureOpenAIService")
    @patch("api.views.AzureSearchService")
    def test_chat_streaming_token_may_look_like_sentinel(
        self, mock_search_cls, mock_openai_cls, client
    ):
        """模型輸出剛好等於結束哨符時,不得被誤判為串流結束。"""
        mock_search_cls.return_value.hybrid_search.return_value = []
        mock_openai_cls.return_value.chat_completion_stream.return_value = iter(
            ["[DONE]", "後續內容"]
        )

        resp = client.post(self.URL, {"query": "hi", "stream": True}, format="json")

        events = parse_sse(b"".join(resp.streaming_content).decode("utf-8"))
        assert [e["token"] for e in events if "token" in e] == ["[DONE]", "後續內容"]
        assert events[-1] == {"done": True}

    @patch("api.views.AzureOpenAIService")
    @patch("api.views.AzureSearchService")
    def test_chat_streaming_error_yields_generic_error_event(
        self, mock_search_cls, mock_openai_cls, client
    ):
        """
        串流錯誤事件只能帶通用訊息 — 服務層例外包著 SDK 原始錯誤
        (端點、部署名稱、request id),那些細節屬於伺服器日誌,
        不得隨 SSE 送到瀏覽器。
        """
        mock_search_cls.return_value.hybrid_search.return_value = []

        def boom(*args, **kwargs):
            raise OpenAIServiceError(
                "串流失敗: https://internal.openai.azure.com deployment=gpt-4.1"
            )
            yield  # pragma: no cover

        mock_openai_cls.return_value.chat_completion_stream.side_effect = boom

        resp = client.post(self.URL, {"query": "hi", "stream": True}, format="json")
        body = b"".join(resp.streaming_content).decode("utf-8")
        events = parse_sse(body)
        assert "error" in events[-1]
        assert "internal.openai.azure.com" not in body
        assert "gpt-4.1" not in body


# ── DocumentUploadView ────────────────────────────────────────────────────────


class TestDocumentUploadView:
    URL = "/api/documents/upload/"

    @patch("api.views.AzureSearchService")
    @patch("api.views.AzureBlobService")
    def test_upload_txt_success(self, mock_blob_cls, mock_search_cls, client, user, db):
        mock_blob = mock_blob_cls.return_value
        mock_blob.upload_document.return_value = ("docid123", "https://blob/x")
        mock_blob.extract_text.return_value = "hello world"
        mock_search_cls.return_value.index_document.return_value = 3

        file = SimpleUploadedFile("test.txt", b"hello world", content_type="text/plain")
        resp = client.post(
            self.URL,
            {"title": "Test Doc", "file": file},
            format="multipart",
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["document_id"] == "docid123"
        assert body["chunk_count"] == 3

        # 確認 Document 模型已建立
        doc = Document.objects.get(document_id="docid123")
        assert doc.title == "Test Doc"
        assert doc.user == user
        assert doc.chunk_count == 3
        assert doc.is_active is True
        # __str__ 覆蓋
        assert "docid123" in str(doc)

    def test_upload_bad_mime_returns_400(self, client):
        file = SimpleUploadedFile(
            "test.bin", b"binary", content_type="application/octet-stream"
        )
        resp = client.post(
            self.URL,
            {"title": "Bad", "file": file},
            format="multipart",
        )
        assert resp.status_code == 400

    def test_upload_oversize_returns_400(self, client):
        big_data = b"A" * (11 * 1024 * 1024)
        file = SimpleUploadedFile("big.txt", big_data, content_type="text/plain")
        resp = client.post(
            self.URL,
            {"title": "Big", "file": file},
            format="multipart",
        )
        assert resp.status_code == 400

    def test_upload_missing_title_returns_400(self, client):
        file = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
        resp = client.post(self.URL, {"file": file}, format="multipart")
        assert resp.status_code == 400

    @patch("api.views.AzureBlobService")
    def test_upload_blob_failure_returns_500(self, mock_blob_cls, client):
        mock_blob_cls.return_value.upload_document.side_effect = BlobServiceError(
            "blob down"
        )
        file = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
        resp = client.post(
            self.URL,
            {"title": "Test", "file": file},
            format="multipart",
        )
        assert resp.status_code == 500

    def test_upload_unauthenticated_returns_401(self, anon_client):
        file = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
        resp = anon_client.post(
            self.URL,
            {"title": "Test", "file": file},
            format="multipart",
        )
        assert resp.status_code == 401


# ── DocumentListView ──────────────────────────────────────────────────────────


class TestDocumentListView:
    URL = "/api/documents/"

    def test_list_returns_only_own_active_documents(self, client, user, other_user, db):
        Document.objects.create(
            document_id="mine-001",
            title="My Doc",
            user=user,
            file_size=100,
            chunk_count=2,
        )
        Document.objects.create(
            document_id="mine-deleted",
            title="Soft deleted",
            user=user,
            file_size=100,
            chunk_count=1,
            is_active=False,
        )
        Document.objects.create(
            document_id="bob-001",
            title="Bob Doc",
            user=other_user,
            file_size=100,
            chunk_count=1,
        )

        resp = client.get(self.URL)

        assert resp.status_code == 200
        docs = resp.json()["documents"]
        assert [d["document_id"] for d in docs] == ["mine-001"]
        assert docs[0]["title"] == "My Doc"
        assert docs[0]["chunk_count"] == 2
        assert docs[0]["file_size"] == 100
        assert "created_at" in docs[0]

    def test_list_empty_returns_empty_array(self, client, db):
        resp = client.get(self.URL)
        assert resp.status_code == 200
        assert resp.json()["documents"] == []

    def test_list_ordered_newest_first(self, client, user, db):
        for i in range(3):
            Document.objects.create(
                document_id=f"doc-{i}",
                title=f"Doc {i}",
                user=user,
                file_size=10,
                chunk_count=1,
            )
        resp = client.get(self.URL)
        ids = [d["document_id"] for d in resp.json()["documents"]]
        assert ids == ["doc-2", "doc-1", "doc-0"]

    def test_list_unauthenticated_returns_401(self, anon_client):
        resp = anon_client.get(self.URL)
        assert resp.status_code == 401


# ── DocumentDeleteView ────────────────────────────────────────────────────────


class TestDocumentDeleteView:
    @staticmethod
    def url(document_id: str) -> str:
        return f"/api/documents/{document_id}/"

    @patch("api.views.AzureSearchService")
    @patch("api.views.AzureBlobService")
    def test_delete_success(self, mock_blob_cls, mock_search_cls, client, user, db):
        doc = Document.objects.create(
            document_id="del-001",
            title="To Delete",
            user=user,
            file_size=100,
            chunk_count=2,
        )
        resp = client.delete(self.url("del-001"))
        assert resp.status_code == 204

        mock_blob_cls.return_value.delete_document.assert_called_once_with(
            document_id="del-001", user_id=str(user.id)
        )
        mock_search_cls.return_value.delete_document.assert_called_once_with(
            document_id="del-001", user_id=str(user.id)
        )

        doc.refresh_from_db()
        assert doc.is_active is False

    def test_delete_not_found_returns_404(self, client):
        resp = client.delete(self.url("nonexistent"))
        assert resp.status_code == 404

    @patch("api.views.AzureSearchService")
    @patch("api.views.AzureBlobService")
    def test_delete_other_users_doc_returns_404(
        self, mock_blob_cls, mock_search_cls, client, other_user, db
    ):
        doc = Document.objects.create(
            document_id="other-001",
            title="Other user doc",
            user=other_user,
            file_size=100,
            chunk_count=1,
        )
        # alice tries to delete bob's document
        resp = client.delete(self.url("other-001"))
        assert resp.status_code == 404

        # 404 只是回應；真正要釘住的是 Azure 上什麼都沒被動到，
        # 且 bob 的中繼資料仍為有效。
        mock_blob_cls.return_value.delete_document.assert_not_called()
        mock_search_cls.return_value.delete_document.assert_not_called()
        doc.refresh_from_db()
        assert doc.is_active is True

    @patch("api.views.AzureSearchService")
    @patch("api.views.AzureBlobService")
    def test_delete_blob_failure_returns_500(
        self, mock_blob_cls, mock_search_cls, client, user, db
    ):
        Document.objects.create(
            document_id="fail-001",
            title="Will fail",
            user=user,
            file_size=100,
            chunk_count=1,
        )
        mock_blob_cls.return_value.delete_document.side_effect = BlobServiceError(
            "blob down"
        )
        resp = client.delete(self.url("fail-001"))
        assert resp.status_code == 500

    def test_delete_unauthenticated_returns_401(self, anon_client):
        resp = anon_client.delete(self.url("any"))
        assert resp.status_code == 401


# ── Health endpoint ───────────────────────────────────────────────────────────


class TestHealthView:
    def test_health_returns_200_without_auth(self, anon_client):
        resp = anon_client.get("/api/health/")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ── JWT Token endpoints ───────────────────────────────────────────────────────


class TestJWTEndpoints:
    def test_obtain_token_pair(self, user, db):
        api_client = APIClient()
        resp = api_client.post(
            "/api/token/",
            {"username": "alice", "password": "VerySecret123!"},
            format="json",
        )
        assert resp.status_code == 200
        assert "access" in resp.json()
        assert "refresh" in resp.json()

    def test_obtain_token_with_bad_credentials(self, db):
        api_client = APIClient()
        resp = api_client.post(
            "/api/token/",
            {"username": "nobody", "password": "wrong"},
            format="json",
        )
        assert resp.status_code == 401
