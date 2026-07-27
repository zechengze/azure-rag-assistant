"""
seed_demo 管理指令測試。
Blob 與 Search 服務均以 mock 隔離,不呼叫任何付費 Azure API。
"""

from __future__ import annotations

from itertools import count
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from api.management.commands.seed_demo import DEMO_DATA_DIR
from api.models import Document
from services.blob_service import BlobServiceError
from services.search_service import SearchServiceError

CORPUS_SIZE = len(list(DEMO_DATA_DIR.glob("*.md")))

COMMAND_PATH = "api.management.commands.seed_demo"


@pytest.fixture
def mock_azure():
    """Patch 服務層,回傳 (blob_cls, search_cls) 供斷言使用。"""
    with (
        patch(f"{COMMAND_PATH}.AzureBlobService") as blob_cls,
        patch(f"{COMMAND_PATH}.AzureSearchService") as search_cls,
    ):
        ids = count(1)
        blob = blob_cls.return_value
        # document_id 有 unique 約束,每次上傳須回傳不同值
        blob.upload_document.side_effect = lambda **kwargs: (
            f"doc{next(ids)}",
            "https://blob.example/doc",
        )
        blob.extract_text.return_value = "第一句。第二句。第三句。"

        search = search_cls.return_value
        search.index_document.return_value = 3

        yield blob_cls, search_cls


# ── 前置條件 ──────────────────────────────────────────────────────────────────


def test_missing_password_aborts(db, monkeypatch):
    """未提供 DEMO_PASSWORD 時必須拒絕執行,不得使用預設密碼。"""
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="DEMO_PASSWORD"):
        call_command("seed_demo")

    assert not get_user_model().objects.filter(username="demo").exists()


def test_blank_password_aborts(db, monkeypatch):
    """空白字串同樣視為未設定。"""
    monkeypatch.setenv("DEMO_PASSWORD", "   ")

    with pytest.raises(CommandError, match="DEMO_PASSWORD"):
        call_command("seed_demo")


def test_index_failure_surfaces_as_command_error(db, monkeypatch, mock_azure):
    """索引初始化失敗須明確中止,不留下半套資料。"""
    _blob_cls, search_cls = mock_azure
    search_cls.return_value.ensure_index_exists.side_effect = SearchServiceError(
        "索引服務不可用"
    )
    monkeypatch.setenv("DEMO_PASSWORD", "DemoPass123!")

    with pytest.raises(CommandError, match="無法初始化搜尋索引"):
        call_command("seed_demo")

    assert Document.objects.count() == 0


# ── 正常流程 ──────────────────────────────────────────────────────────────────


def test_seeds_user_and_corpus(db, monkeypatch, mock_azure):
    """建立 demo 帳號並索引全部語料。"""
    blob_cls, search_cls = mock_azure
    monkeypatch.setenv("DEMO_PASSWORD", "DemoPass123!")

    call_command("seed_demo")

    user = get_user_model().objects.get(username="demo")
    assert user.check_password("DemoPass123!")

    assert Document.objects.filter(user=user, is_active=True).count() == CORPUS_SIZE
    assert search_cls.return_value.index_document.call_count == CORPUS_SIZE
    assert blob_cls.return_value.upload_document.call_count == CORPUS_SIZE

    # 標題取自 Markdown H1,而非檔名
    titles = set(Document.objects.values_list("title", flat=True))
    assert not any(title.endswith(".md") for title in titles)

    # chunk_count 來自 search service 回報值
    assert all(doc.chunk_count == 3 for doc in Document.objects.all())


def test_indexed_documents_are_user_scoped(db, monkeypatch, mock_azure):
    """索引時必須帶上 user_id,否則多租戶過濾會失效。"""
    _blob_cls, search_cls = mock_azure
    monkeypatch.setenv("DEMO_PASSWORD", "DemoPass123!")

    call_command("seed_demo")

    user = get_user_model().objects.get(username="demo")
    for call in search_cls.return_value.index_document.call_args_list:
        assert call.kwargs["user_id"] == str(user.id)


def test_custom_username(db, monkeypatch, mock_azure):
    monkeypatch.setenv("DEMO_PASSWORD", "DemoPass123!")

    call_command("seed_demo", "--username", "guest")

    assert get_user_model().objects.filter(username="guest").exists()
    assert Document.objects.filter(user__username="guest").count() == CORPUS_SIZE


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_rerun_is_idempotent(db, monkeypatch, mock_azure):
    """重複執行不得產生重複文件。"""
    _blob_cls, search_cls = mock_azure
    monkeypatch.setenv("DEMO_PASSWORD", "DemoPass123!")

    call_command("seed_demo")
    search_cls.return_value.index_document.reset_mock()
    call_command("seed_demo")

    assert Document.objects.count() == CORPUS_SIZE
    search_cls.return_value.index_document.assert_not_called()


def test_reset_rebuilds_corpus(db, monkeypatch, mock_azure):
    """--reset 先清除既有文件 (Blob + index) 再重建。"""
    blob_cls, search_cls = mock_azure
    monkeypatch.setenv("DEMO_PASSWORD", "DemoPass123!")

    call_command("seed_demo")
    original_ids = set(Document.objects.values_list("document_id", flat=True))

    call_command("seed_demo", "--reset")

    assert blob_cls.return_value.delete_document.call_count == CORPUS_SIZE
    assert search_cls.return_value.delete_document.call_count == CORPUS_SIZE
    assert Document.objects.count() == CORPUS_SIZE
    # 全部重新上傳,document_id 應完全換新
    new_ids = set(Document.objects.values_list("document_id", flat=True))
    assert new_ids.isdisjoint(original_ids)


def test_reset_continues_when_cleanup_fails(db, monkeypatch, mock_azure):
    """個別文件清理失敗不應中斷整批重建。"""
    blob_cls, _search_cls = mock_azure
    monkeypatch.setenv("DEMO_PASSWORD", "DemoPass123!")

    call_command("seed_demo")
    blob_cls.return_value.delete_document.side_effect = BlobServiceError(
        "blob 已不存在"
    )

    call_command("seed_demo", "--reset")

    assert Document.objects.count() == CORPUS_SIZE


def test_rerun_rotates_password(db, monkeypatch, mock_azure):
    """重跑指令即可輪替 demo 憑證。"""
    monkeypatch.setenv("DEMO_PASSWORD", "FirstPass123!")
    call_command("seed_demo")

    monkeypatch.setenv("DEMO_PASSWORD", "SecondPass456!")
    call_command("seed_demo")

    user = get_user_model().objects.get(username="demo")
    assert user.check_password("SecondPass456!")
