# Sprachchroniken V1.6 — Railway Free 手機按需使用指南

此版本只需要 Python、Discord Bot Token 和 Railway；不需要 AI API，也不需要在雲端安裝 Windows 德語語音。

> **目標：** 外出時啟動 Bot，使用手機在 Discord 練習 2–4 小時，自動或手動結束後，學習進度不遺失。

## 重要限制（先閱讀）

1. **GitHub 只保存程式碼**，程式實際在 Railway 執行。請把本資料夾的內容放在 GitHub Repository 根目錄（`bot.py` 和 `requirements.txt` 應位於根目錄）。
2. **不會自動按 Discord 指令喚醒**。Bot 離線後，需在 Railway 的 Deployments 頁面重新部署才能使用；它可能需要短暫啟動時間。
3. **不是 24 小時免費承諾。** Railway Free 目前有每月 US$1 的使用額度。這個 Bot 預計每次 4 小時後正常結束，但是否在額度內，取決於實際 CPU、RAM、Volume 和網路用量。請在 Railway 的 Usage 頁面確認。
4. **每週提醒僅在 Bot 正在線上時運作。** 如果平時都關機，請勿依賴它準時私訊提醒。
5. **進度來源只能有一個正在使用。** V1.6 已提供手動 `/de sync export/import/confirm` 交換完整 SQLite 備份。切換環境請先匯出、停止原本 Bot，再啟動另一端匯入；這不是即時同步，也不會自動合併衝突。
6. **音訊暫停。** Linux 雲端版會隱藏首頁聽力按鈕；`/de hoeren` 顯示停用訊息。Windows 本機版原有語音功能仍保留。

## 第一步：安全地上傳 GitHub

1. 在 GitHub 建立 **Private** Repository，名稱例如 `EJ-Sprachchroniken`。
2. 只上傳**這份部署資料夾**的程式碼：`bot.py`、`engine.py`、`local_tts.py`、`runtime_config.py`、`requirements.txt`、`questions_v1_4.json`、測試、文件及 `.gitignore` 等。
3. 絕對不要上傳 `.env`、`data/`、`*.sqlite3`。`.gitignore` 已替你排除；若使用 GitHub 網站手動上傳，仍需自行確認清單。
4. 原始 ZIP 含有已填入 Discord Token 的 `.env`。**不可把原始 ZIP 原封不動傳到公開 Repository。** 如果 Token 曾公開，先在 Discord Developer Portal → Bot → Reset Token，換發後用新 Token 部署。

## 第二步：建立 Railway Free 專案

1. 打開 https://railway.com/ 並登入，連結 GitHub。
2. 建立新 Project，選擇 **Deploy from GitHub Repo**，挑選 `EJ-Sprachchroniken`。
3. 建立服務後，確認 Root Directory 是 `/`（前提是 `bot.py` 在 Repo 根目錄）。
4. 選取這個 Service → **Settings → Deploy → Start Command**，設定：

   ```text
   python bot.py
   ```

5. 將 **Restart Policy** 設為 **On Failure**，不要設 Always。正常結束後應保持停止狀態。
6. 如果有開啟 **Serverless/App Sleeping**，請關閉。Discord Bot 需要長期 WebSocket 心跳，這個功能不能可靠地讓它閒置後自動休眠。
7. Service 不必設定對外網域，因為 Bot 主動連線到 Discord，不是一個網站。

Railway 目前正在轉換設定檔機制，因此本專案刻意不提供舊式 `railway.toml`；以上設定請直接在 Dashboard 操作。

## 第三步：設定 Variables

在 Railway Service → **Variables** 新增以下環境變數：

| Key | Value | 用途 |
| --- | --- | --- |
| `DISCORD_TOKEN` | 你自己 Discord Developer Portal 取得的 Token | 連線 Discord，絕對不可公開 |
| `DISCORD_GUILD_ID` | 你的測試伺服器 ID（可留空） | 讓 Slash Commands 快速同步 |
| `BOT_OWNER_ID` | 你的 Discord 使用者數字 ID | 只有你可以執行 `/de shutdown` |
| `AUTO_SHUTDOWN_HOURS` | `4` | 連線成功後 4 小時正常關閉 |
| `DATABASE_PATH` | `/data/sprachchroniken.sqlite3` | 雲端 SQLite 存放位置 |
| `ENABLE_LISTENING` | `false` | 雲端不提供 Windows TTS |
| `SYNC_DEVICE_LABEL` | `Railway` | 在同步備份中標註資料來源 |

Discord ID 取得方式：開啟 Discord 設定中的開發者模式，再對自己的使用者名稱右鍵或長按，複製使用者 ID。`BOT_OWNER_ID` 不能填 Bot ID，也不能填你的暱稱。

> 注意：沒有設定 `BOT_OWNER_ID` 時，任何人都不能用 `/de shutdown`。4 小時自動結束仍然有效。

## 第四步：掛載資料磁碟（最重要）

1. 在 Railway 專案建立一個 **Volume**，連結到 Sprachchroniken Service。
2. 設定 Volume **Mount Path** 為 `/data`。
3. `DATABASE_PATH` 必須與掛載位置相符：`/data/sprachchroniken.sqlite3`。
4. 新使用者可先啟動一次，由 Bot 建立空資料庫；**有既有學習紀錄的使用者請看下一段**。
5. 定期備份 Volume 裡的資料庫；不要把私人日記放在公開 GitHub。

### 把原本 Windows 的進度搬進去（推薦 V1.6 Discord 指令）

現在**不需要特地使用 CLI** 才能匯入原本的學習進度。推薦第一次切換時：

1. 在 Windows 上使用這份 **V1.6**，並設定 `.env` 內的 `BOT_OWNER_ID` 為你自己的 Discord 使用者 ID。
2. 使用 Windows Bot 的 `/de sync export`，下載完整 `.sqlite3` 備份。
3. 正常關閉 Windows Bot，再啟動 Railway Bot；它也必須是 V1.6 並設定相同的 `BOT_OWNER_ID`。
4. 在 Railway Bot 上用 `/de sync import` 上傳檔案，檢查預覽差異，再使用 `/de sync confirm confirmation:REPLACE` 正式替換。
5. 之後外出結束時反向操作即可；完整流程見 [SYNC_WINDOWS_RAILWAY.md](SYNC_WINDOWS_RAILWAY.md)。

以下 CLI 方式保留作為手動搬移與救援備案。

### 手動搬移備案：Railway CLI

你原本 ZIP 內的 `data/sprachchroniken.sqlite3` 含有既有紀錄。本交付包**特意沒有放入這份個人資料**，避免誤傳 GitHub。

1. 先在 Windows 停止舊的 Python Bot，備份 `data/sprachchroniken.sqlite3`。
2. 在 Railway 確認 Volume `/data` 已掛載；若 Bot 正在運作，先到 Deployments 將它停掉，避免覆寫開啟中的 SQLite。
3. 安裝並登入 [Railway CLI](https://docs.railway.com/cli)，在 CLI 連結到正確的 Railway 專案和環境。
4. 用 volume file upload（CLI 會讓你挑選正確 Volume）：

   ```text
   railway volume files upload ./data/sprachchroniken.sqlite3 /sprachchroniken.sqlite3
   ```

   這裡的 `/sprachchroniken.sqlite3` 是 Volume 的內部相對根目錄；掛載到 Service 的 `/data` 後，Bot 讀取 `/data/sprachchroniken.sqlite3`。

5. 可以用 `railway volume files list /` 確認檔案存在，然後重新部署 Bot。
6. 在 Discord 使用 `/de profile`、`/de journal`、`/de progress` 驗證原有紀錄是否出現。確認前不要刪除 Windows 原始備份。

如果不方便使用 CLI，也能使用 `railway volume browse /` 的互動式檔案管理功能。若檔案上傳或權限出錯，先停下來，不要改成把資料庫 Commit 到 GitHub。

## 第五步：手機啟動、操作、關閉

### 出門前 / 出門時：啟動

1. 手機瀏覽器登入 Railway Dashboard。
2. 開啟你的 Project → Sprachchroniken Service → **Deployments**。
3. 從既有部署的選單選 **Redeploy**，或使用 **Deploy Latest Commit**。這是重新啟動一個執行個體，並不是啟動 Discord 指令本身。
4. 等待部署顯示正常運行、日誌出現 `Die Sprachchroniken connected`。
5. 手機開 Discord → `/de help`，即可開始。

### 用完：關閉

- 在 Discord 執行 **`/de shutdown`**（僅 `BOT_OWNER_ID` 有權限）。Bot 回覆後會正常關閉與 Discord 的連線。或者等待 4 小時自動關閉。
- Railway 設為 **On Failure** 時，正常退出不會自動重啟。
- 如需立即從網頁停止，也可以在 Railway **Deployments** 選執行中的部署 → **Remove**。Remove 是停止並移除該部署，不是刪掉整個專案或 Volume。

不要在有未完成寫入或匯入時強制 Remove，優先使用 `/de shutdown`。

## 重要檢查清單

- [ ] GitHub Repository **沒有 `.env`、`data`、SQLite 資料庫**。
- [ ] Railway Variables 有正確的 Discord Bot Token。
- [ ] `BOT_OWNER_ID` 是你自己的 Discord 使用者數字 ID。
- [ ] Volume 掛載 `/data`，資料庫也設定成 `/data/sprachchroniken.sqlite3`。
- [ ] Restart Policy = On Failure；Serverless = Off。
- [ ] `/de daily`、`/de practice`、`/de diary`、`/de vocab add` 都可用。
- [ ] `/de shutdown` 後在 Railway 看見服務停止，稍後 Redeploy 可再次使用。
- [ ] 重新部署後 `/de progress` 和 `/de journal` 仍保有前次紀錄。
- [ ] Railway Usage 符合 Free 額度，必要時設定消費限制。
- [ ] Windows 與 Railway 都設了同一個 `BOT_OWNER_ID`，但各自使用不同的 `SYNC_DEVICE_LABEL`。
- [ ] 完成一次 Windows → Railway → Windows 的 `/de sync` 往返測試。

官方文件：

- https://docs.railway.com/pricing
- https://docs.railway.com/deployments/deployment-actions
- https://docs.railway.com/deployments/restart-policy
- https://docs.railway.com/volumes
- https://docs.railway.com/deployments/serverless
