"""
多租戶邊界工具測試。

隔離為共用資源加過濾條件的模型，條件寫錯不會拋錯、只會安靜地讀到或刪到別人
的資料，因此構造條件的這兩個函式以測試逐項釘住。
"""

from __future__ import annotations

import pytest

from services.tenancy import odata_literal, require_tenant


class TestRequireTenant:
    def test_returns_value_unchanged(self) -> None:
        assert require_tenant("42") == "42"

    def test_strips_surrounding_whitespace(self) -> None:
        assert require_tenant("  42  ") == "42"

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_rejects_blank(self, blank: str) -> None:
        """空租戶在 OData 與 Blob 前綴下都會安靜失效，須當場中止。"""
        with pytest.raises(ValueError):
            require_tenant(blank)


class TestOdataLiteral:
    def test_wraps_in_single_quotes(self) -> None:
        assert odata_literal("42") == "'42'"

    def test_doubles_embedded_quote(self) -> None:
        """OData 以連續兩個單引號表示字面上的單引號。"""
        assert odata_literal("o'brien") == "'o''brien'"

    def test_injection_attempt_stays_inside_the_literal(self) -> None:
        """
        跳出引號的嘗試須整段留在字串常值內，不得成為新的布林條件。

        未跳脫時 `user_id eq '' or user_id ne ''` 恆真，索引即對全部租戶
        開放；跳脫後這串輸入只會是一個比對不到任何文件的 user_id。
        """
        payload = "' or user_id ne '"
        condition = f"user_id eq {odata_literal(payload)}"
        assert condition == "user_id eq ''' or user_id ne '''"
