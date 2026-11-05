# Die Sprachchroniken — Discord 德文 RPG（V1）

獨立的 Python + Discord Slash Commands + SQLite 學習遊戲。**無須任何 AI API、無 Token 計費**；每週使用 ChatGPT Plus 手動匯出／匯入 JSON。

## 目前可使用

- `/de diary`、`/de collect`、`/de vocab add`：隨手保存學習素材。
- `/de daily`、`/de quick`、`/de practice`、`/de answer`：客觀題即時評分、XP／金幣、技能紀錄。
- `/de profile`、`/de skills`：階級與練習結果。
- `/de quest`、`/de finish`：主線起點及條件式支線；週任務可透過 ChatGPT JSON 加入。
- `/de culture map`、`/de culture list`、`/de culture discover`：五大文化領土及探索／理解／掌握狀態。
- `/de review export`、`/de review import`、`/de review confirm`、`/de review status`、`/de review due`：每週批改交換。
- `/de help`：Discord 內建說明。

## 安裝（Windows PowerShell）

1. 安裝 Python 3.11+。建立 Discord Application → Bot，取得 Token，邀請 Bot 至伺服器並授予 `bot`、`applications.commands` scopes；不需開啟 Message Content Intent。
2. 解壓縮本專案，進入 `sprachchroniken` 資料夾。
3. 建立虛擬環境並安裝套件：

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. 複製 `.env.example` 為 `.env`，填入 `DISCORD_TOKEN`。測試階段可填入 `DISCORD_GUILD_ID`，指令同步會較快。**勿上傳 .env 或公開 Token。**
5. 執行 `python bot.py`，Discord 中輸入 `/de help`。

## 每週 ChatGPT Plus 工作流程

1. Discord：`/de review export` 下載 `de_review_*.json`。
2. ChatGPT：將匯出 JSON 和本專案 `CHATGPT_PROMPT.md` 一起上傳，請它生成 `de_weekly_package.json`。
3. Discord：`/de review import` 上傳結果 JSON，檢查預覽。
4. Discord：`/de review confirm` 正式寫入。重複匯入同一批次會被拒絕。未提供批改的紀錄會保留待處理狀態。

## 資料保存

所有內容預設存於 `data/sprachchroniken.sqlite3`，重啟程式不會消失。升級前請關閉 Bot 並備份整個 `data` 資料夾。每位 Discord 使用者各自有紀錄及任務。

## V1 限制／未完成項目

- 自由寫作不會即時 AI 批改；必須使用每週 JSON 交換。
- 目前內建少量示範選擇題；大規模題庫透過每週匯入增加。
- `/de quick` 提供按時間選擇的短任務入口，**尚無計時器**。
- `/de finish` 是簡易完成機制，已解鎖任務可以手動結束；尚未具備 NPC 對話狀態機、分支劇情驗證或完整 Boss 戰。
- 文化圖以文字完成率呈現，預設每領土 4 個種子節點，非先前示意的 20 節點。文化知識內容需在後續版本擴充和校驗。
- 複習清單可顯示到期項目，但尚未具有完整間隔複習評分與下次日期更新介面。
- 批改匯入提供資料結構檢查，但 AI 回答的語言正確性仍需人工判斷；正式長期使用前，應增加匯入前的資料備份功能。
- 歷史詳細檢視、語音與德檢模擬考尚未實作。此版本是可執行基礎架構，不是完整遊戲成品。

## 本機測試

```powershell
python -m unittest discover -s tests -v
```
