"""
外部服務呼叫的重試行為測試。

CLAUDE.md §3.2 要求所有外部 API 呼叫加入重試機制。重試很容易寫成「看起來
有、實際不會觸發」——裝飾器套在對外方法上,方法內的 except 先把可重試例外
換成自訂例外,tenacity 收到的型別就不在重試清單內。這裡直接數 SDK 被呼叫
幾次,而不是斷言裝飾器存在。
"""

from __future__ import annotations

from typing import Iterator
from unittest.mock import MagicMock, patch

import httpx
import pytest
from azure.core.exceptions import ResourceExistsError, ServiceRequestError
from openai import APITimeoutError, RateLimitError
from tenacity import wait_none

from services.blob_service import AzureBlobService, BlobServiceError
from services.openai_service import AzureOpenAIService, OpenAIServiceError

RETRY_ATTEMPTS = 3


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch):
    """把重試間隔改為 0,否則每個測試要真的等 2 + 4 秒。"""
    for func in (
        AzureOpenAIService._create_embedding,
        AzureOpenAIService._create_chat_completion,
        AzureOpenAIService._open_chat_stream,
        AzureBlobService._upload_blob,
    ):
        monkeypatch.setattr(func.retry, "wait", wait_none())


@pytest.fixture
def openai_service() -> Iterator[tuple[AzureOpenAIService, MagicMock]]:
    with patch("services.openai_service.AzureOpenAI") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client
        yield AzureOpenAIService(), client


def rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://test.openai.azure.com/")
    return RateLimitError(
        "429 Too Many Requests",
        response=httpx.Response(429, request=request),
        body=None,
    )


def timeout_error() -> APITimeoutError:
    return APITimeoutError(
        request=httpx.Request("POST", "https://test.openai.azure.com/")
    )


# ── Azure OpenAI ─────────────────────────────────────────────────────────────


class TestOpenAIRetry:

    def test_embedding_retries_and_succeeds(self, openai_service):
        """第一次 429、第二次成功 —— 呼叫端不該看到任何錯誤。"""
        service, client = openai_service
        client.embeddings.create.side_effect = [
            rate_limit_error(),
            MagicMock(data=[MagicMock(embedding=[0.1] * 1536)]),
        ]

        result = service.get_embedding("測試文字")

        assert len(result) == 1536
        assert client.embeddings.create.call_count == 2

    def test_embedding_retries_three_times_before_giving_up(self, openai_service):
        service, client = openai_service
        client.embeddings.create.side_effect = timeout_error()

        with pytest.raises(OpenAIServiceError):
            service.get_embedding("測試文字")

        assert client.embeddings.create.call_count == RETRY_ATTEMPTS

    def test_chat_completion_retries_on_rate_limit(self, openai_service):
        service, client = openai_service
        answer = MagicMock()
        answer.choices = [MagicMock(message=MagicMock(content="回答"))]
        answer.usage = MagicMock(total_tokens=10)
        client.chat.completions.create.side_effect = [rate_limit_error(), answer]

        result = service.chat_completion(user_query="問題", context_documents=[])

        assert result == "回答"
        assert client.chat.completions.create.call_count == 2

    def test_chat_stream_retries_while_opening_stream(self, openai_service):
        """
        建立串流失敗可以安全重試(尚未吐出任何 token);
        已經開始串流後才斷線則不重試,否則回答會重複。
        """
        service, client = openai_service
        client.chat.completions.create.side_effect = [
            rate_limit_error(),
            iter([_chunk("答"), _chunk("案")]),
        ]

        tokens = list(
            service.chat_completion_stream(user_query="問題", context_documents=[])
        )

        assert tokens == ["答", "案"]
        assert client.chat.completions.create.call_count == 2

    def test_non_retryable_error_is_not_retried(self, openai_service):
        """非暫時性錯誤(如設定錯誤)重試沒有意義,應該立刻失敗。"""
        service, client = openai_service
        client.embeddings.create.side_effect = ValueError("deployment not found")

        with pytest.raises(OpenAIServiceError):
            service.get_embedding("測試文字")

        assert client.embeddings.create.call_count == 1


def _chunk(content: str) -> MagicMock:
    return MagicMock(choices=[MagicMock(delta=MagicMock(content=content))])


# ── Azure Blob Storage ───────────────────────────────────────────────────────


class TestBlobUploadRetry:

    @pytest.fixture
    def blob_service(self) -> Iterator[tuple[AzureBlobService, MagicMock]]:
        with patch("services.blob_service.BlobServiceClient") as mock_cls:
            client = MagicMock()
            mock_cls.from_connection_string.return_value = client
            yield AzureBlobService(), client

    @staticmethod
    def _file() -> MagicMock:
        file = MagicMock()
        file.read.return_value = b"content"
        file.content_type = "text/plain"
        file.size = 7
        return file

    def test_upload_retries_on_transient_azure_error(self, blob_service):
        service, client = blob_service
        blob_client = (
            client.get_container_client.return_value.get_blob_client.return_value
        )
        blob_client.upload_blob.side_effect = [ServiceRequestError("連線中斷"), None]

        document_id, _url = service.upload_document(
            file=self._file(), user_id="1", filename="a.txt"
        )

        assert document_id
        assert blob_client.upload_blob.call_count == 2

    def test_upload_gives_up_after_three_attempts(self, blob_service):
        service, client = blob_service
        blob_client = (
            client.get_container_client.return_value.get_blob_client.return_value
        )
        blob_client.upload_blob.side_effect = ServiceRequestError("連線中斷")

        with pytest.raises(BlobServiceError):
            service.upload_document(file=self._file(), user_id="1", filename="a.txt")

        assert blob_client.upload_blob.call_count == RETRY_ATTEMPTS

    def test_upload_treats_already_existing_blob_as_success(self, blob_service):
        """
        前一次嘗試其實寫入成功、只是回應沒送達。路徑含本次呼叫才產生的 UUID,
        不可能撞到別人的檔案,重試時的 ResourceExistsError 應視為完成。
        """
        service, client = blob_service
        blob_client = (
            client.get_container_client.return_value.get_blob_client.return_value
        )
        blob_client.upload_blob.side_effect = [
            ServiceRequestError("回應逾時"),
            ResourceExistsError("blob already exists"),
        ]

        document_id, _url = service.upload_document(
            file=self._file(), user_id="1", filename="a.txt"
        )

        assert document_id
        assert blob_client.upload_blob.call_count == 2
