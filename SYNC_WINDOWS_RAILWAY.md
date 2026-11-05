# Sprachchroniken V1.6 — Windows ↔ Railway 學習進度同步

這是**手動快照交換**，不是即時雙向同步。每次把一份完整 `.sqlite3` 備份下載，再上傳到另一個環境，確認後整份覆蓋。

## 同步指令

| Discord 指令 | 功能 |
| --- | --- |
| `/de sync status` | 查看裝置、最近快照版本、目前是否有新紀錄 |
| `/de sync export` | 匯出完整 SQLite 備份檔供手機下載 |
| `/de sync import` | 上傳另一端的 `.sqlite3`，只檢查並預覽，不會修改資料 |
| `/de sync confirm confirmation:REPLACE` | 15 分鐘內確認取代，目前資料先自動備份 |

**安全限制：** 只有 `.env` 或 Railway Variables 中 `BOT_OWNER_ID` 指定的 Discord 使用者可以操作。所有回覆都是 ephemeral（只有操作人可見）。備份本身有私人日記、紀錄和使用者 ID，不要轉傳或公開上傳 GitHub。

## 第一次從 Windows 搬到 Railway

1. 先在 Windows 解壓 **V1.6** 程式，保留原有 `.env` 中的 Token 設定，但**不要覆蓋或丟掉原本 `data/sprachchroniken.sqlite3`**。如使用新資料夾，必須先把原本 `data` 資料夾複製過去，或將 `DATABASE_PATH` 指向原檔位置。請在關閉舊 Bot 後進行。
2. Windows `.env` 設 `BOT_OWNER_ID=你的 Discord 數字使用者 ID`、`SYNC_DEVICE_LABEL=Windows`、`AUTO_SHUTDOWN_HOURS=0`。
3. 只開啟 Windows 端的 Bot，輸入 `/de sync status`，再輸入 `/de sync export`；**下載該回覆附上的 `.sqlite3` 檔案**到手機或電腦。
4. 關閉 Windows Bot，確認同一個 Token 沒有另外一個 Bot 程序還在執行。
5. 在 Railway 將同一份 **V1.6** 程式部署好，Variables 設 `BOT_OWNER_ID`、`SYNC_DEVICE_LABEL=Railway`、`DATABASE_PATH=/data/sprachchroniken.sqlite3`，並掛載 `/data` Volume。
6. 啟動 Railway Bot，在手機 Discord 使用 `/de sync import`，選擇第 3 步的 `.sqlite3` 檔案。
7. 檢查來源、XP、單字、日記和可能的警告。確認是最新進度後，輸入 `/de sync confirm confirmation:REPLACE`。
8. 使用 `/de profile`、`/de journal`、`/de progress` 確認資料和原本一致。

## 外出結束，將雲端新進度帶回家

1. Railway 還在線上時，先使用 `/de sync export`，**務必下載最新快照到手機**。
2. 執行 `/de shutdown`，或等待四小時自動關閉。
3. 回家打開 Windows Bot，使用 `/de sync import` 上傳剛剛下載的雲端檔案。
4. 檢查預覽差異，輸入 `/de sync confirm confirmation:REPLACE`。
5. 使用 `/de progress` 確認 XP 和日記等記錄。之後在家繼續使用 Windows 版的聽力功能即可。

> 如果忘記在 Railway 4 小時關機前匯出，不用急：Volume 內的進度仍在。下次重新部署 Railway Bot 後，先匯出，再切回 Windows。這時先不要在 Windows 新增紀錄，避免分支衝突。

## 發生衝突怎麼辦？

當預覽出現：

- **此裝置在上次同步後又有新紀錄**：兩端可能各自寫入；請先在目的地 `/de sync export` 備份當前資料，並決定要保留哪一端。
- **來源不是目前版本的直接下一版本**：可能用了舊檔或跳過一次匯入。確認下載時間與來源，必要時重新從來源匯出。
- **兩邊資料相同**：不必再匯入。
- **預覽後本機已有資料變動**：系統會拒絕確認覆蓋，必須重新 `/de sync import`。

V1.6 的 Confirm 是**整份替換**，沒有自動合併多個分支。檔案內含 SHA-256 的邏輯資料摘要，用來驗證版本與內容是否一致，但它並不提供密碼保護或數位簽章；請只匯入自己從另一端下載的檔案。

## 資料保護與救援

- 來源資料庫匯出時使用 SQLite Backup API，以取得一致的備份，不會直接複製可能正在寫入的原始 SQLite 主檔。
- 每次 Confirm 前會將目的地完整備份到資料庫同層的 `sync_backups/` 資料夾，例如 Windows 的 `data/sync_backups/`、Railway 的 `/data/sync_backups/`。
- Confirm 如果失敗，程式會嘗試用這份備份復原。如果復原也失敗，先停止 Bot，保留備份，避免重複匯入。
- 只接受本專案 V1.6 匯出的 SQLite，檔案上限 15 MB，完整性與必要的資料表結構都會檢查。
- 上傳後的確認有效期是 **15 分鐘**，過期請重新上傳。
- Discord 的 ephemeral 附件不是長期備份系統。下載成功後，建議另外安全保存一份最新備份，並清理手機中不需要的舊檔。

## 不要做的事

1. 不要同時啟動 Windows 與 Railway 上使用同一個 Token 的 Bot。
2. 不要把 `.env` 或 `.sqlite3` 放進 GitHub Repository。
3. 不要在還沒成功匯出雲端新進度前，就繼續修改 Windows 的舊資料庫。
4. 不要手動在 Bot 執行時直接覆蓋 `data/sprachchroniken.sqlite3`；請用 `/de sync import/confirm`。

## 本機驗證

```powershell
python -m unittest discover -s tests -v
```

此測試包括 Windows → Railway → Windows 往返、舊資料衝突、預覽後新增紀錄阻止覆蓋，以及篡改備份的驗證。
