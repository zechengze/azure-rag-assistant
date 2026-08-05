"""
Azure OpenAI 服務封裝層。
所有 Azure OpenAI API 呼叫集中於此模組，View 層透過此服務存取 AI 功能。
"""

from __future__ import annotations

import logging
from typing import Iterator, cast

from django.conf import settings
from openai import (
    APIConnectionError,
    APITimeoutError,
    AzureOpenAI,
    RateLimitError,
    Stream,
)
from openai.types import CreateEmbeddingResponse
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# 可重試的例外類型
RETRYABLE_EXCEPTIONS = (APIConnectionError, APITimeoutError, RateLimitError)

# 重試策略集中於此,三個 SDK 呼叫共用。
#
# reraise=True: 次數用盡後拋出最後一次的原始例外 (而非 tenacity 的
# RetryError),外層才能照常轉換為 OpenAIServiceError。
_retry_azure_openai = retry(
    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)


class AzureOpenAIService:
    """
    封裝 Azure OpenAI 服務，提供 Chat Completion 與 Embedding 功能。

    使用情境：
        service = AzureOpenAIService()
        response = service.chat_completion(messages=[...], context_documents=[...])
    """

    def __init__(self) -> None:
        self._client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
        self._chat_deployment = settings.AZURE_OPENAI_CHAT_DEPLOYMENT
        self._embedding_deployment = settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT

    # ── 帶重試的 SDK 呼叫 ────────────────────────────────────────────────
    #
    # 重試裝飾器必須套在「只做 SDK 呼叫」的方法上,由它原樣拋出
    # RateLimitError 等可重試例外。若把裝飾器套在對外方法,方法內的
    # except 會先把例外換成 OpenAIServiceError,tenacity 收到的型別
    # 不在重試清單內,重試就完全不會發生。

    @_retry_azure_openai
    def _create_embedding(self, text: str) -> CreateEmbeddingResponse:
        return self._client.embeddings.create(
            input=text,
            model=self._embedding_deployment,
        )

    @_retry_azure_openai
    def _create_chat_completion(self, messages: list[dict]) -> ChatCompletion:
        return self._client.chat.completions.create(
            model=self._chat_deployment,
            messages=messages,
            temperature=0.7,
            max_tokens=1500,
        )

    @_retry_azure_openai
    def _open_chat_stream(self, messages: list[dict]) -> Stream[ChatCompletionChunk]:
        """只重試「建立串流」這一步 —— 已經吐出 token 後重試會重複輸出。"""
        stream = self._client.chat.completions.create(
            model=self._chat_deployment,
            messages=messages,
            temperature=0.7,
            max_tokens=1500,
            stream=True,
        )
        # create() 的回傳型別隨 stream 參數而異,mypy 無法從這裡窄化,
        # 但 stream=True 時 SDK 必定回傳 Stream。
        return cast(Stream[ChatCompletionChunk], stream)

    # ── 對外 API ────────────────────────────────────────────────────────

    def get_embedding(self, text: str) -> list[float]:
        """
        產生文字的向量嵌入，用於 Azure AI Search 索引與查詢。

        Args:
            text: 要向量化的文字內容

        Returns:
            1536 維度的浮點數向量

        Raises:
            OpenAIServiceError: Azure OpenAI 服務呼叫失敗（含重試耗盡）
        """
        try:
            # 截斷過長輸入（embedding 模型限制）
            response = self._create_embedding(text[:8000])
            return response.data[0].embedding
        except Exception as exc:
            logger.error("Embedding 生成失敗: %s", exc, exc_info=True)
            raise OpenAIServiceError(f"Embedding 生成失敗: {exc}") from exc

    def chat_completion(
        self,
        user_query: str,
        context_documents: list[dict],
        conversation_history: list[dict] | None = None,
    ) -> str:
        """
        根據 RAG 召回的文件與使用者查詢產生回應。
        System Prompt 與使用者輸入明確分離，防範 Prompt Injection。

        Args:
            user_query: 使用者問題（已通過輸入驗證）
            context_documents: RAG 召回的文件段落清單
            conversation_history: 前次對話記錄（可選）

        Returns:
            AI 生成的回答文字

        Raises:
            OpenAIServiceError: Azure OpenAI 服務呼叫失敗（含重試耗盡）
        """
        try:
            messages = self._build_messages(
                user_query, context_documents, conversation_history or []
            )
            response = self._create_chat_completion(messages)
            answer = response.choices[0].message.content or ""
            logger.info(
                "Chat completion 成功 | tokens: %d",
                response.usage.total_tokens if response.usage else 0,
            )
            return answer
        except Exception as exc:
            logger.error("Chat completion 失敗: %s", exc, exc_info=True)
            raise OpenAIServiceError(f"Chat completion 失敗: {exc}") from exc

    def chat_completion_stream(
        self,
        user_query: str,
        context_documents: list[dict],
        conversation_history: list[dict] | None = None,
    ) -> Iterator[str]:
        """
        串流版本的 chat completion，用於 Server-Sent Events 即時回應。

        Yields:
            逐 token 的文字片段

        Raises:
            OpenAIServiceError: Azure OpenAI 服務呼叫失敗（含重試耗盡）
        """
        try:
            messages = self._build_messages(
                user_query, context_documents, conversation_history or []
            )
            stream = self._open_chat_stream(messages)
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            logger.error("串流 chat completion 失敗: %s", exc, exc_info=True)
            raise OpenAIServiceError(f"串流失敗: {exc}") from exc

    def _build_messages(
        self,
        user_query: str,
        context_documents: list[dict],
        conversation_history: list[dict],
    ) -> list[dict]:
        """
        組裝對話訊息，System Prompt 與使用者輸入嚴格分離。

        注意：context_documents 注入至 System Prompt，非 User Message，
        避免 Prompt Injection 攻擊向量。
        """
        context_text = "\n\n---\n\n".join(
            f"[文件 {i+1}] {doc.get('title', '未知')}\n{doc.get('content', '')}"
            for i, doc in enumerate(context_documents)
        )

        system_prompt = (
            "你是一個專業的知識問答助理。請根據以下提供的文件內容回答使用者問題。\n\n"
            "規則：\n"
            "1. 僅根據提供的文件內容回答，不得憑空捏造資訊\n"
            "2. 若文件中找不到答案，請明確告知使用者\n"
            "3. 回答時可引用文件來源\n"
            "4. 使用繁體中文回答\n\n"
            f"參考文件：\n{context_text}"
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # 加入歷史對話（最近 6 輪）
        for entry in conversation_history[-6:]:
            if entry.get("role") in ("user", "assistant"):
                messages.append({"role": entry["role"], "content": entry["content"]})

        # 使用者輸入獨立於 System Prompt 之外
        messages.append({"role": "user", "content": user_query})
        return messages


class OpenAIServiceError(Exception):
    """Azure OpenAI 服務例外，用於統一錯誤處理。"""

    pass
