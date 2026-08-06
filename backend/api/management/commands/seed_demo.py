"""
建立公開 demo 帳號並索引展示語料。

線上 demo 若讓訪客登入後看到空的知識庫，就無法示範 RAG——但要求訪客自備
文件又提高了門檻。此指令預先索引一組說明本專案架構的語料，訪客登入即可
直接提問。

指令為 idempotent：重複執行不會產生重複文件。加上 --reset 則先移除既有
demo 文件（Blob + Search index + DB）再重新索引。

用法:
    DEMO_PASSWORD=<password> python manage.py seed_demo
    DEMO_PASSWORD=<password> python manage.py seed_demo --reset
"""

from __future__ import annotations

import os
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from api.models import Document
from services.blob_service import AzureBlobService, BlobServiceError
from services.search_service import AzureSearchService, SearchServiceError

DEMO_DATA_DIR = Path(__file__).resolve().parent / "demo_data"
DEFAULT_USERNAME = "demo"
TXT_MIME = "text/plain"


class Command(BaseCommand):
    """建立 demo 使用者並索引 demo_data/ 底下的展示語料。"""

    help = "建立 demo 帳號並索引展示語料 (idempotent)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--username",
            default=DEFAULT_USERNAME,
            help=f"demo 帳號名稱 (預設: {DEFAULT_USERNAME})",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="先刪除該帳號既有文件再重新索引",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # 公開可登入的帳號密碼一律由環境變數注入，不接受預設值——
        # 硬編碼的 demo 密碼會隨程式碼一起進版控，等同公開憑證。
        password = os.environ.get("DEMO_PASSWORD", "").strip()
        if not password:
            raise CommandError(
                "DEMO_PASSWORD 環境變數未設定。拒絕以預設密碼建立公開帳號。"
            )

        username: str = options["username"]
        user = self._ensure_user(username, password)

        if options["reset"]:
            self._reset_documents(user)

        try:
            search_service = AzureSearchService()
            search_service.ensure_index_exists()
        except (SearchServiceError, ValueError) as exc:
            raise CommandError(f"無法初始化搜尋索引: {exc}") from exc

        corpus = sorted(DEMO_DATA_DIR.glob("*.md"))
        if not corpus:
            raise CommandError(f"找不到展示語料: {DEMO_DATA_DIR}")

        indexed = 0
        skipped = 0
        for path in corpus:
            title = self._extract_title(path)
            if Document.objects.filter(user=user, title=title, is_active=True).exists():
                self.stdout.write(f"  略過 (已存在): {title}")
                skipped += 1
                continue

            chunk_count = self._index_file(path, title, user, search_service)
            self.stdout.write(
                self.style.SUCCESS(f"  已索引: {title} ({chunk_count} chunks)")
            )
            indexed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\n完成 — 帳號 {username}：新增 {indexed} 份、略過 {skipped} 份"
            )
        )

    # ── helpers ────────────────────────────────────────────────────────────

    def _ensure_user(self, username: str, password: str) -> Any:
        """建立或更新 demo 使用者，回傳 user 實例。"""
        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(username=username)
        # 密碼每次都重設，讓輪替 demo 憑證只需重跑此指令。
        user.set_password(password)
        user.save()

        action = "已建立" if created else "已更新密碼"
        self.stdout.write(f"{action} demo 帳號: {username}")
        return user

    def _reset_documents(self, user: Any) -> None:
        """移除該使用者所有文件的 Blob、索引與 DB 記錄。"""
        documents = Document.objects.filter(user=user)
        if not documents.exists():
            return

        blob_service = AzureBlobService()
        search_service = AzureSearchService()
        user_id = str(user.id)

        for document in documents:
            try:
                blob_service.delete_document(
                    document_id=document.document_id, user_id=user_id
                )
                search_service.delete_document(
                    document_id=document.document_id, user_id=user_id
                )
            except (BlobServiceError, SearchServiceError) as exc:
                # reset 是清理動作，個別文件清不掉不該中斷整批重建。
                self.stderr.write(
                    self.style.WARNING(f"  清理 {document.title} 失敗，繼續: {exc}")
                )

        count = documents.count()
        documents.delete()
        self.stdout.write(f"已移除 {count} 份既有文件")

    def _index_file(
        self,
        path: Path,
        title: str,
        user: Any,
        search_service: AzureSearchService,
    ) -> int:
        """上傳單一語料檔至 Blob 並建立索引，回傳 chunk 數量。"""
        content_bytes = path.read_bytes()
        user_id = str(user.id)

        # 走與正式上傳端點相同的路徑（Blob → extract_text → index），
        # 確保 demo 資料與使用者自行上傳的文件在系統中完全同構。
        upload = SimpleUploadedFile(path.name, content_bytes, content_type=TXT_MIME)

        try:
            blob_service = AzureBlobService()
            document_id, _url = blob_service.upload_document(
                file=upload, user_id=user_id, filename=path.name
            )
            upload.seek(0)
            content = blob_service.extract_text(upload)
            chunk_count = search_service.index_document(
                document_id=document_id,
                title=title,
                content=content,
                user_id=user_id,
            )
        except (BlobServiceError, SearchServiceError) as exc:
            raise CommandError(f"索引 {path.name} 失敗: {exc}") from exc

        Document.objects.create(
            document_id=document_id,
            title=title,
            user=user,
            file_size=len(content_bytes),
            chunk_count=chunk_count,
        )
        return chunk_count

    @staticmethod
    def _extract_title(path: Path) -> str:
        """取檔案第一個 Markdown H1 作為標題，沒有則退回檔名。"""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem
