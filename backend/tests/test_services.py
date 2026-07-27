"""
RAG 服務測試套件。
使用 pytest-mock 模擬 Azure 服務，禁止在測試中呼叫付費 API。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.openai_service import AzureOpenAIService, OpenAIServiceError
from services.search_service import AzureSearchService

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_openai_client():
    """模擬 AzureOpenAI 客戶端，避免呼叫真實 API。"""
    with patch("services.openai_service.AzureOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_search_client():
    """模擬 Azure AI Search 客戶端。"""
    with patch("services.search_service.SearchClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def sample_context_documents():
    """測試用文件段落。"""
    return [
        {
            "id": "doc-001-chunk-0",
            "document_id": "doc-001",
            "title": "Azure OpenAI 使用指南",
            "content": "Azure OpenAI Service 提供 GPT-4 等大型語言模型的 REST API 存取。",
            "chunk_index": 0,
            "score": 0.95,
        },
        {
            "id": "doc-001-chunk-1",
            "document_id": "doc-001",
            "title": "Azure OpenAI 使用指南",
            "content": "使用 Azure OpenAI 時，需要設定端點 URL 與 API 金鑰。",
            "chunk_index": 1,
            "score": 0.87,
        },
    ]


# ─── AzureOpenAIService 測試 ─────────────────────────────────────────────────


class TestAzureOpenAIService:

    def test_get_embedding_returns_vector(self, mock_openai_client):
        """get_embedding 應回傳浮點數向量。"""
        expected_vector = [0.1, 0.2, 0.3] * 512  # 模擬 1536 維向量
        mock_openai_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=expected_vector)]
        )

        with patch("services.openai_service.settings") as mock_settings:
            mock_settings.AZURE_OPENAI_ENDPOINT = "https://test.openai.azure.com/"
            mock_settings.AZURE_OPENAI_KEY = "test-key"
            mock_settings.AZURE_OPENAI_API_VERSION = "2024-02-01"
            mock_settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-large"
            mock_settings.AZURE_OPENAI_CHAT_DEPLOYMENT = "gpt-4.1-mini"

            service = AzureOpenAIService()
            service._client = mock_openai_client

            result = service.get_embedding("測試文字")

        assert result == expected_vector
        mock_openai_client.embeddings.create.assert_called_once()

    def test_get_embedding_truncates_long_text(self, mock_openai_client):
        """超過 8000 字元的文字應被截斷。"""
        long_text = "A" * 10000
        mock_openai_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536)]
        )

        with patch("services.openai_service.settings") as mock_settings:
            mock_settings.AZURE_OPENAI_ENDPOINT = "https://test.openai.azure.com/"
            mock_settings.AZURE_OPENAI_KEY = "test-key"
            mock_settings.AZURE_OPENAI_API_VERSION = "2024-02-01"
            mock_settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-large"
            mock_settings.AZURE_OPENAI_CHAT_DEPLOYMENT = "gpt-4.1-mini"

            service = AzureOpenAIService()
            service._client = mock_openai_client
            service.get_embedding(long_text)

        call_args = mock_openai_client.embeddings.create.call_args
        assert len(call_args.kwargs["input"]) <= 8000

    def test_chat_completion_builds_correct_messages(
        self, mock_openai_client, sample_context_documents
    ):
        """chat_completion 應將 system prompt 與使用者輸入分離。"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="測試回答"))]
        mock_response.usage = MagicMock(total_tokens=150)
        mock_openai_client.chat.completions.create.return_value = mock_response

        with patch("services.openai_service.settings") as mock_settings:
            mock_settings.AZURE_OPENAI_ENDPOINT = "https://test.openai.azure.com/"
            mock_settings.AZURE_OPENAI_KEY = "test-key"
            mock_settings.AZURE_OPENAI_API_VERSION = "2024-02-01"
            mock_settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-large"
            mock_settings.AZURE_OPENAI_CHAT_DEPLOYMENT = "gpt-4.1-mini"

            service = AzureOpenAIService()
            service._client = mock_openai_client
            result = service.chat_completion(
                user_query="什麼是 Azure OpenAI？",
                context_documents=sample_context_documents,
            )

        assert result == "測試回答"
        call_args = mock_openai_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]

        # 驗證 System Prompt 與使用者輸入分離
        assert messages[0]["role"] == "system"
        assert "Azure OpenAI 使用指南" in messages[0]["content"]  # 文件注入至 system
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "什麼是 Azure OpenAI？"

    def test_chat_completion_raises_service_error_on_failure(self, mock_openai_client):
        """Azure API 失敗時應拋出 OpenAIServiceError。"""
        mock_openai_client.chat.completions.create.side_effect = Exception("API Error")

        with patch("services.openai_service.settings") as mock_settings:
            mock_settings.AZURE_OPENAI_ENDPOINT = "https://test.openai.azure.com/"
            mock_settings.AZURE_OPENAI_KEY = "test-key"
            mock_settings.AZURE_OPENAI_API_VERSION = "2024-02-01"
            mock_settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-large"
            mock_settings.AZURE_OPENAI_CHAT_DEPLOYMENT = "gpt-4.1-mini"

            service = AzureOpenAIService()
            service._client = mock_openai_client

            with pytest.raises(OpenAIServiceError):
                service.chat_completion(
                    user_query="測試",
                    context_documents=[],
                )


# ─── AzureSearchService 測試 ─────────────────────────────────────────────────


class TestChunkSplitting:
    """測試文件分割邏輯（不依賴 Azure 服務）。"""

    def test_split_short_text_returns_single_chunk(self):
        """短文本應回傳單一 chunk。"""
        text = "這是一段短文字。"
        chunks = AzureSearchService._split_into_chunks(text, chunk_size=1000)
        assert len(chunks) == 1
        assert text.strip() in chunks[0]

    def test_split_long_text_creates_multiple_chunks(self):
        """長文本應被分割為多個 chunk。"""
        sentences = ["這是第一句話。" * 10] * 50
        text = "".join(sentences)
        chunks = AzureSearchService._split_into_chunks(text, chunk_size=200, overlap=50)
        assert len(chunks) > 1

    def test_empty_text_returns_empty_list(self):
        """空文字應回傳空清單。"""
        chunks = AzureSearchService._split_into_chunks("")
        assert chunks == []

    def test_chunks_respect_size_limit(self):
        """每個 chunk 的長度不應超過 chunk_size 的合理範圍。"""
        text = "短句。" * 200
        chunk_size = 100
        chunks = AzureSearchService._split_into_chunks(
            text, chunk_size=chunk_size, overlap=20
        )
        for chunk in chunks:
            # 允許單一長句超過限制，但一般情況下應符合
            assert len(chunk) <= chunk_size * 3  # 容錯範圍


# ─── 輸入驗證測試 ─────────────────────────────────────────────────────────────


class TestChatRequestSerializer:
    """測試查詢輸入的驗證邏輯。"""

    def test_valid_query_passes_validation(self):
        from api.serializers import ChatRequestSerializer

        with patch("api.serializers.settings") as mock_settings:
            mock_settings.RAG_MAX_QUERY_LENGTH = 2000
            serializer = ChatRequestSerializer(data={"query": "什麼是 RAG？"})
            assert serializer.is_valid()

    def test_empty_query_fails_validation(self):
        from api.serializers import ChatRequestSerializer

        with patch("api.serializers.settings") as mock_settings:
            mock_settings.RAG_MAX_QUERY_LENGTH = 2000
            serializer = ChatRequestSerializer(data={"query": ""})
            assert not serializer.is_valid()
            assert "query" in serializer.errors

    def test_query_exceeding_max_length_fails(self):
        # max_length 在 Serializer class 定義時讀取 settings.RAG_MAX_QUERY_LENGTH (=2000),
        # 後續 patch settings 已無法改變 CharField 設定,故直接以 2001 字測試實際限制。
        from api.serializers import ChatRequestSerializer

        serializer = ChatRequestSerializer(data={"query": "A" * 2001})
        assert not serializer.is_valid()
        assert "query" in serializer.errors
