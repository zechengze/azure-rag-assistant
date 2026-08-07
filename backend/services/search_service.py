"""
Azure AI Search 服務封裝層。
負責向量索引管理、混合搜尋（關鍵字 + 語意向量）與文件 Chunking。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery
from django.conf import settings

from services.openai_service import AzureOpenAIService
from services.tenancy import odata_literal, require_tenant

logger = logging.getLogger(__name__)

CHUNK_SIZE = settings.RAG_CHUNK_SIZE  # 512 tokens
CHUNK_OVERLAP = settings.RAG_CHUNK_OVERLAP  # 128 tokens
TOP_K = settings.RAG_TOP_K  # 5


class AzureSearchService:
    """
    封裝 Azure AI Search，提供文件索引與 RAG 混合搜尋功能。

    索引結構：
        - id: 文件 chunk 唯一識別碼
        - document_id: 原始文件 ID（對應 Blob Storage）
        - title: 文件標題
        - content: Chunk 文字內容
        - content_vector: 向量嵌入（1536 維）
        - chunk_index: Chunk 在原文件中的順序
        - user_id: 文件擁有者（用於存取控制過濾）
    """

    def __init__(self) -> None:
        credential = AzureKeyCredential(settings.AZURE_SEARCH_KEY)
        self._search_client = SearchClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=settings.AZURE_SEARCH_INDEX_NAME,
            credential=credential,
        )
        self._index_client = SearchIndexClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            credential=credential,
        )
        self._openai_service = AzureOpenAIService()

    def ensure_index_exists(self) -> None:
        """確保搜尋索引已建立（應用程式啟動時呼叫）。"""
        try:
            self._index_client.get_index(settings.AZURE_SEARCH_INDEX_NAME)
            logger.info("索引 %s 已存在", settings.AZURE_SEARCH_INDEX_NAME)
        except Exception:
            logger.info("建立索引 %s", settings.AZURE_SEARCH_INDEX_NAME)
            self._create_index()

    def _create_index(self) -> None:
        """建立支援向量搜尋的 Azure AI Search 索引。"""
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(
                name="document_id", type=SearchFieldDataType.String, filterable=True
            ),
            SimpleField(
                name="user_id", type=SearchFieldDataType.String, filterable=True
            ),
            SearchableField(
                name="title",
                type=SearchFieldDataType.String,
                analyzer_name="zh-Hant.lucene",
            ),
            SearchableField(
                name="content",
                type=SearchFieldDataType.String,
                analyzer_name="zh-Hant.lucene",
            ),
            SimpleField(
                name="chunk_index", type=SearchFieldDataType.Int32, sortable=True
            ),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=1536,
                vector_search_profile_name="hnswProfile",
            ),
        ]
        vector_search = VectorSearch(
            profiles=[
                VectorSearchProfile(
                    name="hnswProfile", algorithm_configuration_name="hnswConfig"
                )
            ],
            algorithms=[HnswAlgorithmConfiguration(name="hnswConfig")],
        )
        index = SearchIndex(
            name=settings.AZURE_SEARCH_INDEX_NAME,
            fields=fields,
            vector_search=vector_search,
        )
        self._index_client.create_or_update_index(index)
        logger.info("索引建立完成")

    def index_document(
        self,
        document_id: str,
        title: str,
        content: str,
        user_id: str,
    ) -> int:
        """
        將文件分割為 Chunks 並建立向量索引。

        Args:
            document_id: 對應 Blob Storage 的文件 ID
            title: 文件標題
            content: 文件全文
            user_id: 文件擁有者 ID（用於多租戶存取控制）

        Returns:
            成功索引的 chunk 數量
        """
        chunks = self._split_into_chunks(content)
        documents = []

        for i, chunk_text in enumerate(chunks):
            try:
                vector = self._openai_service.get_embedding(chunk_text)
                documents.append(
                    {
                        "id": f"{document_id}-chunk-{i}",
                        "document_id": document_id,
                        "user_id": user_id,
                        "title": title,
                        "content": chunk_text,
                        "chunk_index": i,
                        "content_vector": vector,
                    }
                )
            except Exception as exc:
                logger.warning("Chunk %d 向量化失敗，跳過: %s", i, exc)

        if documents:
            result = self._search_client.upload_documents(documents=documents)
            success_count = sum(1 for r in result if r.succeeded)
            logger.info(
                "文件 %s 索引完成：%d/%d chunks",
                document_id,
                success_count,
                len(chunks),
            )
            return success_count

        return 0

    @staticmethod
    def _tenant_filter(user_id: str) -> str:
        """
        建立租戶隔離條件。

        所有使用者的 chunk 存於同一個索引，這條 filter 是唯一的邊界，因此
        一律經由此方法產生：值走 odata_literal 跳脫，空租戶當場拒絕。
        """
        return f"user_id eq {odata_literal(require_tenant(user_id))}"

    def hybrid_search(
        self,
        query: str,
        user_id: str,
        top_k: int = TOP_K,
    ) -> list[dict[str, Any]]:
        """
        執行混合搜尋（關鍵字 BM25 + 向量語意搜尋）。
        使用 user_id 過濾確保多租戶資料隔離。

        Args:
            query: 使用者查詢文字
            user_id: 當前使用者 ID（用於存取控制）
            top_k: 最多召回幾個文件段落

        Returns:
            召回的文件段落清單，包含 title、content、score
        """
        try:
            query_vector = self._openai_service.get_embedding(query)
            vector_query = VectorizedQuery(
                vector=query_vector,
                k_nearest_neighbors=top_k * 2,  # 過召回後再重排
                fields="content_vector",
            )

            results = self._search_client.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=self._tenant_filter(user_id),  # 存取控制過濾
                select=["id", "document_id", "title", "content", "chunk_index"],
                top=top_k,
            )

            documents = []
            for result in results:
                documents.append(
                    {
                        "id": result["id"],
                        "document_id": result["document_id"],
                        "title": result["title"],
                        "content": result["content"],
                        "chunk_index": result["chunk_index"],
                        "score": result.get("@search.score", 0.0),
                    }
                )

            logger.info("混合搜尋召回 %d 個段落，查詢：%s", len(documents), query[:50])
            return documents

        except AzureError as exc:
            logger.error("Azure AI Search 搜尋失敗: %s", exc, exc_info=True)
            raise SearchServiceError(f"搜尋服務失敗: {exc}") from exc

    def delete_document(self, document_id: str, user_id: str) -> None:
        """
        刪除指定文件在本租戶底下的所有索引 Chunks。

        user_id 為必填並併入 filter：索引全租戶共用，僅以 document_id 撈取
        等同於信任呼叫端已驗過擁有者——那層檢查目前只存在於 view，任何新的
        呼叫點漏做就會跨租戶刪除。租戶條件屬於資料存取層自身的責任。
        """
        try:
            # 查詢該文件的所有 chunk（限定本租戶）
            results = self._search_client.search(
                search_text="*",
                filter=(
                    f"document_id eq {odata_literal(document_id)}"
                    f" and {self._tenant_filter(user_id)}"
                ),
                select=["id"],
            )
            chunk_ids = [{"id": r["id"]} for r in results]

            if chunk_ids:
                self._search_client.delete_documents(documents=chunk_ids)
                logger.info(
                    "已刪除文件 %s 的 %d 個索引 chunks", document_id, len(chunk_ids)
                )
        except AzureError as exc:
            logger.error("刪除索引失敗: %s", exc, exc_info=True)
            raise SearchServiceError(f"刪除索引失敗: {exc}") from exc

    @staticmethod
    def _split_into_chunks(
        text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
    ) -> list[str]:
        """
        將長文本分割為有重疊的 Chunks。
        使用句子邊界切分，避免在句子中間截斷。

        Args:
            text: 待分割文字
            chunk_size: 每個 chunk 的最大字元數
            overlap: 相鄰 chunk 的重疊字元數

        Returns:
            分割後的文字段落清單
        """
        # 以句號、問號、驚嘆號等句子邊界分割
        sentences = re.split(r"(?<=[。！？.!?])\s*", text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks: list[str] = []
        current_chunk: list[str] = []
        current_length = 0

        for sentence in sentences:
            sentence_length = len(sentence)

            if current_length + sentence_length > chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                # 保留最後幾個句子作為 overlap
                overlap_sentences = []
                overlap_length = 0
                for s in reversed(current_chunk):
                    if overlap_length + len(s) <= overlap:
                        overlap_sentences.insert(0, s)
                        overlap_length += len(s)
                    else:
                        break
                current_chunk = overlap_sentences
                current_length = overlap_length

            current_chunk.append(sentence)
            current_length += sentence_length

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks


class SearchServiceError(Exception):
    """Azure AI Search 服務例外。"""

    pass
