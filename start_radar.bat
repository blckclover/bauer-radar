@echo off
echo [Camillo Radar] Initiating daily scan...

:: 1. 設定你的系統環境變數（已替換為真實金鑰與網址）
set GEMINI_API_KEY=AQ.Ab8RN6IGGlH4QCewXcLpd-nJqieSQUh207nz_3uF5gmJLTdsHw
set DISCORD_WEBHOOK_ALERTS=https://discord.com/api/webhooks/1511106019772727357/D4MUpEKzCirblpVbbPRJyTZY922o5Uk3kJj9wN1z-cAqddObSI_CretGY4Pu58j7_gVd
set DISCORD_WEBHOOK_DEEPDIVE=https://discord.com/api/webhooks/1511111862639394847/gNWRbfc00H2pmbHExXLj2jbRFSYCzRXLzTjvKwgLVfwjSEJv51jfkGfWGZIHu7tGGMfJ

:: 2. 切換到你的專案目錄
cd /d C:\Users\bauer\Projects\dividend-analyzer

:: 3. 執行 Python 腳本
python auto_hunter_cron.py

echo [Camillo Radar] Scan complete.
pause
