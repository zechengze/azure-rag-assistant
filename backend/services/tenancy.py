"""
多租戶邊界的共用工具。

本專案的隔離不是「一個租戶一份資源」，而是共用資源加上過濾條件：Blob 共用
一個 container（以 {user_id}/ 前綴切分）、Azure AI Search 共用一個索引（以
user_id 欄位過濾）。這種模型下，租戶條件漏寫或寫錯不會產生任何錯誤——查詢
照樣成功，只是回傳或刪除了別人的資料。因此構造條件的邏輯集中於此，不散落成
各 service 裡的 f-string。
"""

from __future__ import annotations


def require_tenant(user_id: str) -> str:
    """
    確認租戶識別碼存在，回傳去除前後空白的值。

    空值在兩種隔離機制下都會安靜失效：OData 的 `user_id eq ''` 比對不到任何
    文件（看起來像「這個使用者沒有資料」），Blob 前綴則退化成 `/{doc}/` 這種
    跨租戶比對。呼叫端弄丟身分屬於程式錯誤，應當場中止而非帶著空租戶跑完。
    """
    tenant = (user_id or "").strip()
    if not tenant:
        raise ValueError("租戶識別碼不可為空——無法據以建立資料隔離條件")
    return tenant


def odata_literal(value: str) -> str:
    """
    將值包成 OData 字串常值，內含的單引號以連續兩個單引號跳脫。

    索引為全租戶共用，擋在中間的只有 filter 這一條字串：值若能跳出引號，
    `' or user_id ne '` 這類輸入會讓條件恆真而使整個索引全開。目前 user_id
    是 Django 的整數主鍵，跳脫與否結果相同——但這個前提沒有任何地方強制，
    改用 Azure AD 的 oid / preferred_username 之後即不再成立。過濾條件不
    建立在「呼叫端會傳乾淨的值」這種假設上。
    """
    return "'" + value.replace("'", "''") + "'"
