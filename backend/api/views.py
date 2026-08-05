"""
API Views — 知識問答與文件管理端點。
所有端點均需 JWT 驗證,透過 Service 層呼叫 Azure 服務。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from api.models import Document
from api.serializers import (
    ChatRequestSerializer,
    DocumentListSerializer,
    DocumentUploadSerializer,
)
from services.blob_service import AzureBlobService, BlobServiceError
from services.openai_service import AzureOpenAIService, OpenAIServiceError
from services.search_service import AzureSearchService, SearchServiceError

logger = logging.getLogger(__name__)


def sse_event(payload: dict[str, Any]) -> str:
    """
    將單一事件序列化為 SSE 幀,payload 一律走 JSON。

    不能直接寫 `data: {token}` — SSE 以換行界定欄位,token 內含的換行會把
    該行之後的內容變成沒有欄位名的行而被接收端丟棄。模型輸出的段落與條列
    因此整段消失(實測 "第一行\\n\\n1. 項目一" 只會還原成 "第一行1. 項目一")。
    JSON 序列化把換行轉義為 \\n,每個事件保證是單行。

    結束與錯誤改用結構化欄位而非 [DONE] / [ERROR] 字串哨符,模型輸出剛好
    等於哨符時也不會被誤判為串流結束。
    """
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class HealthView(APIView):
    """
    GET /api/health/
    輕量健康檢查端點 — 不需驗證、不查 DB、不呼叫 Azure。
    用於 Dockerfile HEALTHCHECK 與 Azure App Service liveness probe。
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []  # 不執行任何 auth
    throttle_classes: list = []

    def get(self, _request: Request) -> Response:
        return Response({"status": "ok"})


class ChatThrottle(UserRateThrottle):
    """聊天端點獨立限流: 每小時 30 次。"""

    scope = "chat"


class ChatCompletionView(APIView):
    """
    POST /api/chat/
    接收使用者問題,執行 RAG 搜尋後返回 AI 回答。
    支援串流模式 (stream=true)。
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ChatThrottle]

    def post(self, request: Request) -> Response | StreamingHttpResponse:
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        user_query: str = data["query"]
        conversation_history: list[dict] = data.get("history", [])
        stream_mode: bool = data.get("stream", False)

        user_id = str(request.user.id)

        try:
            search_service = AzureSearchService()
            context_documents = search_service.hybrid_search(
                query=user_query,
                user_id=user_id,
            )

            openai_service = AzureOpenAIService()

            if stream_mode:
                return self._stream_response(
                    openai_service,
                    user_query,
                    context_documents,
                    conversation_history,
                )

            answer = openai_service.chat_completion(
                user_query=user_query,
                context_documents=context_documents,
                conversation_history=conversation_history,
            )

            return Response(
                {
                    "answer": answer,
                    "sources": [
                        {
                            "title": doc["title"],
                            "chunk_index": doc["chunk_index"],
                        }
                        for doc in context_documents
                    ],
                }
            )

        except SearchServiceError as exc:
            logger.error("RAG 搜尋失敗 | user=%s | error=%s", user_id, exc)
            return Response(
                {"error": "搜尋服務暫時無法使用,請稍後再試"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except OpenAIServiceError as exc:
            logger.error("AI 生成失敗 | user=%s | error=%s", user_id, exc)
            return Response(
                {"error": "AI 服務暫時無法使用,請稍後再試"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    def _stream_response(
        self,
        openai_service: AzureOpenAIService,
        user_query: str,
        context_documents: list[dict],
        conversation_history: list[dict],
    ) -> StreamingHttpResponse:
        """產生 Server-Sent Events 串流回應。"""

        def event_stream():
            try:
                for token in openai_service.chat_completion_stream(
                    user_query=user_query,
                    context_documents=context_documents,
                    conversation_history=conversation_history,
                ):
                    yield sse_event({"token": token})
                yield sse_event({"done": True})
            except OpenAIServiceError as exc:
                yield sse_event({"error": str(exc)})

        response = StreamingHttpResponse(
            event_stream(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class DocumentListView(APIView):
    """
    GET /api/documents/
    列出目前使用者尚未刪除的文件,依上傳時間由新至舊排序。
    僅回傳 Document 中繼資料,不觸發任何 Azure 服務呼叫。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        documents = Document.objects.filter(
            user=request.user,
            is_active=True,
        )
        serializer = DocumentListSerializer(documents, many=True)
        return Response({"documents": serializer.data})


class DocumentUploadView(APIView):
    """
    POST /api/documents/upload/
    上傳文件至 Azure Blob Storage 並建立搜尋索引。
    成功後寫入 Document 模型作為中繼資料。
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request: Request) -> Response:
        serializer = DocumentUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_file = serializer.validated_data["file"]
        title = serializer.validated_data["title"]
        user_id = str(request.user.id)

        try:
            blob_service = AzureBlobService()
            document_id, _blob_url = blob_service.upload_document(
                file=uploaded_file,
                user_id=user_id,
                filename=uploaded_file.name,
            )

            uploaded_file.seek(0)
            content = blob_service.extract_text(uploaded_file)

            search_service = AzureSearchService()
            chunk_count = search_service.index_document(
                document_id=document_id,
                title=title,
                content=content,
                user_id=user_id,
            )

            Document.objects.create(
                document_id=document_id,
                title=title,
                user=request.user,
                file_size=uploaded_file.size,
                chunk_count=chunk_count,
            )

            logger.info(
                "文件上傳成功 | user=%s | document_id=%s | chunks=%d",
                user_id,
                document_id,
                chunk_count,
            )

            return Response(
                {
                    "document_id": document_id,
                    "title": title,
                    "chunk_count": chunk_count,
                    "message": f"文件已成功索引,共分割為 {chunk_count} 個段落",
                },
                status=status.HTTP_201_CREATED,
            )

        except (BlobServiceError, SearchServiceError) as exc:
            logger.error("文件處理失敗 | user=%s | error=%s", user_id, exc)
            return Response(
                {"error": "文件處理失敗,請稍後再試"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DocumentDeleteView(APIView):
    """
    DELETE /api/documents/<document_id>/
    刪除指定文件 (Blob + Search index + 軟刪除 Document 記錄)。
    擁有者驗證透過 Document 模型查詢,效能優於掃描 Blob 容器。
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, document_id: str) -> Response:
        user_id = str(request.user.id)

        document = Document.objects.filter(
            document_id=document_id,
            user=request.user,
            is_active=True,
        ).first()

        if document is None:
            return Response(
                {"error": "文件不存在或無權限存取"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            blob_service = AzureBlobService()
            search_service = AzureSearchService()

            blob_service.delete_document(document_id=document_id, user_id=user_id)
            search_service.delete_document(document_id)

            document.is_active = False
            document.save(update_fields=["is_active"])

            logger.info(
                "文件刪除成功 | user=%s | document_id=%s",
                user_id,
                document_id,
            )
            return Response(status=status.HTTP_204_NO_CONTENT)

        except (BlobServiceError, SearchServiceError) as exc:
            logger.error("文件刪除失敗 | user=%s | error=%s", user_id, exc)
            return Response(
                {"error": "文件刪除失敗"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
