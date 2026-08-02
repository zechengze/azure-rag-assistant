#!/bin/sh
# Azure App Service 的啟動腳本 — 由 provision.sh 設為 startup-file。
#
# migrate 放在這裡而非映像 CMD:映像保持與環境無關,本機與 CI 直接用
# CMD 的 gunicorn,同一個 image 在不同環境以不同方式啟動。
#
# 為什麼是腳本而不是 inline 指令:App Service 會對 appCommandLine 自行
# 斷詞,巢狀引號 (sh -c '...') 會被拆壞,容器以 sh 語法錯誤 (exit 2)
# 在毫秒內退出。單一路徑沒有引號問題。
set -e

python manage.py migrate --noinput

# exec 讓 gunicorn 取代 shell 成為 PID 1,正確接收平台的停止訊號
exec gunicorn core.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
