# Clash YAML Manager

適合部署在 Ubuntu VPS 上的輕量級 Clash/Mihomo YAML 節點管理面板。

可上傳現有 YAML，也可直接使用內建預設 YAML。輸入 `vmess://` / `vless://` 節點後，系統會自動替換 `proxies`、清理舊節點引用、補齊策略組，並產生新的 Clash/Mihomo 設定檔。

<!-- RELEASE:START -->
**Latest Stable: [v1.1.1](https://github.com/wwintj/clash-yaml-manager/releases/tag/v1.1.1)**
<!-- RELEASE:END -->

main 是開發分支；以下安裝與升級預設只使用 GitHub Latest Stable Release，API 失敗不會退回 main。只有明確指定 `--channel main` 才使用開發通道，測試命令見下方 Development / Testing。

正式版本以頁首 Latest Stable 為準；功能驗收過程與限制見 [開發報告](docs/V1_1_DEVELOPMENT.md)。

## Fixed Subscriptions — available on main development channel

登入後可從 **Fixed Subscriptions** 建立固定訂閱，保存節點、Policy Options 及 Default / Custom YAML。
一般 Save Changes 更新內容但保持 URL；修改 URL Prefix、Regenerate Link 或 Delete 才會讓舊地址失效。
Disable 暫停匿名讀取，Enable 恢復原地址。固定地址使用 `/s/<prefix>-fs_<secret>`，直到手動刪除，不受 24 小時臨時輸出清理影響。

這是尚未發布的 main 功能，Latest Stable 仍為 **v1.1.1**。測試 VPS 使用下方 `--channel main` 命令。
Custom Base YAML 與生成結果保存在私有 `state/`，編輯時不必重新上傳；瀏覽器的 Generate 草稿仍獨立。
Node Sources 支援 **Manual、Remote URL、Uploaded source**，可以合併多個來源；Base YAML 仍獨立選擇 Default / Custom。
外部來源接受 Clash/Mihomo YAML、Raw VMess/VLESS URI list、Base64 URI list，僅匯入 VMess / VLESS。
Save 或手動 Refresh 更新遠端資料，抓取失敗可使用未變更來源的 last-good cache，固定 URL 保持不變。

### Automatic Refresh — main development

每個 Remote Source 可設定 Auto Refresh：**Off（預設）**、15m、30m、1h、3h、6h、12h、24h。
由獨立 systemd timer 約每五分鐘檢查到期來源；Gunicorn 不承擔排程。
成功會重新計算 Next Refresh；失敗保留 last-good cache，按 5m → 15m → 30m → 1h → 2h → 6h 退避重試。
頁面顯示 UTC 刷新時間、連續失敗次數及最近五筆歷史（最多保存二十筆）。Manual / Uploaded 不自動刷新；自動刷新排程不執行節點健康檢查。

```bash
systemctl status clash-yaml-manager-refresh.timer --no-pager -l
systemctl list-timers clash-yaml-manager-refresh.timer
journalctl -u clash-yaml-manager-refresh.service -n 50 --no-pager
```

儲存及固定 URL 見 [Fixed Subscriptions](docs/FIXED_SUBSCRIPTIONS.md)；來源格式、SSRF 與快取見 [External Sources](docs/EXTERNAL_SOURCES.md)；排程、來源狀態遷移、退避、並發及運維見 [Automatic Refresh](docs/AUTO_REFRESH.md)。

### Node Health / Endpoint Reachability — main development

Fixed Subscription 的健康檢查預設 **Off**；可在 Edit 頁面切換為 **Manual** 或 **Automatic**，再按 **Check Now**。
它只測試 VPS 能否與當前已保存 YAML 中的 VMess/VLESS 節點 `server:port` 建立 TCP 連接，並顯示連線耗時。
連續失敗 1–2 次為 Suspect，3 次起為 Unhealthy；之後成功立即恢復 Healthy。Unhealthy 節點**仍保留**在 YAML 及所有代理群組中。
此檢查**不驗證**代理認證或端到端轉發，也不測試 TLS、WebSocket 或 Reality 協議；Automatic 模式使用下述獨立健康排程。
私網和非全球可路由地址會被封鎖，結果存入獨立私有狀態，不改動 Fixed URL 或 revision。架構、限制及安全細節見 [Node Health](docs/NODE_HEALTH.md)。

### Full Proxy Validation — main development

Fixed Subscription 的 **Full Proxy Validation** 使用可選、受專案管理的 **Mihomo v1.19.31** 對目前已保存的 VMess/VLESS 節點執行端到端 HTTPS URL probe。預設 **Off**；管理員在 Edit 頁面改為 **Manual** 或 **Automatic** 後可按 **Check Proxies Now**。普通安裝或更新不會安裝、更新或啟動 Mihomo；須在 VPS 透過 SSH 執行 `sudo bash /opt/clash-yaml-manager/mihomoctl.sh install`，Web 只顯示引擎狀態。

**Unreleased / main**：amd64 引擎依所有可見 CPU 的 Linux flags 交集，選擇固定的 GOAMD64 v1/v2/v3 資產；完整性校驗通過後若 `-v` 無法執行，才逐級嘗試較低版本。CPU 型號不參與判斷；arm64 資產不變。既有通用 amd64 安裝按 v3 識別，CPU 降級時顯示 INCOMPATIBLE，可透過 SSH `mihomoctl.sh update` 重新選擇。tim VPS 的 amd64-v2 與真實 VMess/VLESS 手動代理驗收已由 operator 明確回報 PASS；未宣稱 Codex 獨立重現。

預設目標是 `https://www.gstatic.com/generate_204`，預期 HTTP 204、逾時 8 秒；可設定全域預設及每個固定訂閱的覆蓋值。結果**只代表該節點在當次檢查能否經 Mihomo 存取所選目標**，不代表所有網站可用。Proxy Health 與 TCP Endpoint Health 獨立；連續失敗 1–2 次為 Suspect，3 次起為 Unhealthy。檢查不移除節點、不更改 YAML/策略或固定 URL，也不觸發自動策略切換；只有明確啟用 Automatic 才會排程健康檢查。安全限制、安裝/回滾、真實 VPS 驗收步驟見 [Full Proxy Validation](docs/PROXY_HEALTH.md)；受控驗收結果見 [報告](docs/PROXY_HEALTH_REPORT.md)。Latest Stable 仍為 **v1.1.1**。

## Policy Engine（Unreleased / main）

Generate YAML 和 Fixed create/edit 可分別設定 Country / Selected Special Groups 的 **Preserve、Select、URL-Test、Fallback、Load-Balance**。預設 Preserve / Preserve 保留 YAML 既有組行為；一般組與手動切換不會自動改型。
自動策略候選僅含本次生成、屬於該組的真實 proxy nodes，排除 DIRECT 和巢狀組；Load-Balance 限 round-robin。客戶端測試 URL 可用 HTTP/HTTPS 與本地位址，伺服器不抓取。
Fixed registry v4 保存策略；v1/v2/v3 仅读取時補 Preserve，不改 URL、revision 或 current YAML。來源刷新重用保存的策略；Health 仍僅觀測，不刪除或排序候選。臨時 Generate 使用原有 /t，沒有額外持久化 Policy 狀態。
範圍、精確 Mihomo v1.19.31 語法、數值限制與 VPS 步驟見 [Policy Engine](docs/POLICY_ENGINE.md)，受控驗證見 [Policy 報告](docs/POLICY_ENGINE_REPORT.md)。**真機 Policy / client 驗收 NOT RUN**。

## Automatic Health（Unreleased / main）

Endpoint 與 Full Proxy Health 可各自選擇 **Off / Manual / Automatic**，預設仍為 Off，既有 Manual 不會自動啟用排程。Automatic 支援 15 分鐘至 24 小時的七檔間隔，仍保留手動 Check Now。獨立 `clash-yaml-manager-health.timer` 掃描到期工作，每輪最多 4 個 Endpoint 訂閱及 1 個 Proxy 訂閱；來源刷新 timer 保持獨立。檢查只讀已保存 YAML，不刷新來源、不移除節點、不修改策略、Fixed URL 或 YAML。調度錯誤使用獨立退避，Mihomo 不可用時保留節點觀察。

架構、狀態遷移及 VPS 指令見 [Automatic Health](docs/AUTOMATIC_HEALTH.md)，受控 Gate 見 [驗收報告](docs/AUTOMATIC_HEALTH_REPORT.md)。**自動 Health 真機驗收 PENDING / NOT FULLY CLOSED**：operator 已回報 timer 安裝、enabled、active(waiting)，實際觸發一次並退出 0，但當次 endpoint=0 / proxy=0；tim 上 systemd-analyze verify PASS、Mihomo COMPATIBLE、healthz 200。仍缺實際到期 Endpoint 與 Proxy 作業的 timer 觸發證據；空掃描或手動 oneshot 不算完整驗收。VERSION / Latest Stable 仍為 **1.1.1 / v1.1.1**。

## 一鍵安裝

在 Ubuntu VPS 上執行：

<!-- INSTALL:START -->
```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-install.sh | sudo bash
```
<!-- INSTALL:END -->

安裝時會提示輸入：

- Web 連接埠，預設 `8899`
- Web 管理密碼：只要求非空；單字元、中文、符號及前後空格均按原值保存為雜湊。

安裝完成後訪問：

```text
http://你的VPS_IP:連接埠
```

例如：

```text
http://1.2.3.4:8899
```

---

## 一鍵升級

適用於已經安裝過的 VPS。升級會保留非認證 `.env` 設定、預設 YAML、上傳檔案、輸出檔案、備份、日誌和 `state/`；舊密碼會安全遷入雜湊認證狀態。

<!-- UPDATE:START -->
```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash
```
<!-- UPDATE:END -->

保留內容：

- `/opt/clash-yaml-manager/.env`
- `/opt/clash-yaml-manager/defaults/default.yaml`
- `/opt/clash-yaml-manager/uploads/`
- `/opt/clash-yaml-manager/outputs/`
- `/opt/clash-yaml-manager/backups/`
- `/opt/clash-yaml-manager/logs/`
- `/opt/clash-yaml-manager/state/`

---

## 一鍵卸載

```bash
sudo bash /opt/clash-yaml-manager/uninstall.sh
```

卸載腳本會停止服務、停用開機自啟、刪除 systemd service，並詢問是否刪除專案目錄。保留目錄時也保留服務帳戶與所有權。選擇刪除目錄時，預設備份 `backups/`、`outputs/`、`state/` 和 `.env` 至 root 私有目錄；只有安裝標記核對成功且沒有殘留進程，才移除本專案的 `clashyaml` 帳戶。

---

## 當前版本與指定版本

```bash
cat /opt/clash-yaml-manager/VERSION
```

安裝/升級可指定已發布的 stable tag（以下 X.Y.Z 替換為目標版本）：

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-install.sh | sudo bash -s -- --version vX.Y.Z
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --version vX.Y.Z
```

相同版本提示 `Already up to date.`；降級預設拒絕，必須另加 `--allow-downgrade`。舊安裝沒有 VERSION 時走保留資料的遷移流程。安裝需要互動終端輸入端口與隱藏密碼；bootstrap 使用 python3、curl，不要求 jq 或 git。詳見 [發布與部署](docs/RELEASE.md)。

## 常用命令

```bash
systemctl status clash-yaml-manager
systemctl restart clash-yaml-manager
systemctl stop clash-yaml-manager
journalctl -u clash-yaml-manager -f
tail -f /opt/clash-yaml-manager/logs/app.log
```

如果使用預設連接埠 `8899` 且啟用了 UFW：

```bash
ufw allow 8899/tcp
ufw reload
```

---

## Releases

正式版本由根目錄 `VERSION` 管理；發布流程自動更新上方 metadata 與 [CHANGELOG](CHANGELOG.md)。維護者執行 `python3 scripts/release.py patch --dry-run`，通過後執行 `python3 scripts/release.py patch` 即完成版本、commit、annotated tag、push 和 GitHub Release。細節見 [自動發布](docs/RELEASE_AUTOMATION.md)。

---

## 手動安裝

如果想先把專案上傳到 VPS，再手動安裝：

```bash
cd /root/clash-yaml-manager
sed -i 's/\r$//' install.sh uninstall.sh update.sh
chmod +x install.sh uninstall.sh update.sh
sudo bash install.sh
```

---

## 節點輸入格式

Web 頁面支援批量輸入節點，每行一個：

```text
COUNTRY|NAME|URI
NAME|URI
URI
```

範例：

```text
US|tim|vmess://xxxx
TW|TW55|vmess://xxxx
JP|JP2|vless://xxxx
HK|GIA|vmess://xxxx
```

main 支援三種格式混用。手工 COUNTRY 優先；否則從 NAME、URI fragment / VMess ps remark 識別。缺名稱時產生確定性的 Node-01 等名稱。仍只支援 VMess / VLESS。

點 **Parse Nodes** 查看 Name、Country、Protocol、Ready / Warning / Error 和來源。修改輸入後顯示 Changes not parsed yet。Preview 可修改 Country / Name，修改立即保存；Apply edit 或 Parse Nodes 更新預覽。手工國家優先，重排未修改的輸入不會丟掉手工修正。直接 Generate 也會解析最新內容，不要求先 Parse。重複名稱或無效 URI 是 Error，阻止生成。

支援完整 249 個 ISO 國家/地區，使用同一份[離線資料](docs/COUNTRY_DATA.md)。Auxiliary 和 Preview 的搜尋欄支援 ISO、English、中文和別名，常用國家置頂；例如 tai 找 Taiwan / Thailand，美 找美國，JP 找日本。判斷只依據旗幟、保守的名稱/代碼和城市別名，沒有 DNS 或 GeoIP。衝突或不明名稱為 **🌐 Unknown**，Warning 仍可 Generate，加入 **🌐 其他节点**。只為本次存在的國家建立策略組，保留來源 YAML 既有組。

## 草稿（main 開發版）

Batch、全部 Auxiliary rows、Policy Options、YAML source 和 Preview 手工修正自動存到同一瀏覽器、同一網站 origin 的 localStorage，保留最後保存後 30 天。提交前同步保存；刷新、退出再登入、session / CSRF 失效後可恢復，顯示 Draft restored。成功生成不清空；**Clear Draft** 需確認。

不儲存上傳 YAML 的內容；恢復 Custom YAML 時必須重新選檔，不會靜默使用預設 YAML。CSRF 保護仍在，token 過期刷新，session 過期登入後恢復。

草稿含分享連結，保存在瀏覽器本機且未加密；共用裝置用完請 Clear Draft。停用儲存、容量不足或瀏覽器清除資料會影響恢復，保存失敗會顯示提示。更換網域或連接埠不會跨 origin 恢復草稿。

---

## 功能說明

- 可以上傳現有 Clash/Mihomo YAML，也可以不上傳，直接使用內建預設 YAML。
- 自動刪除原 `proxies` 中的舊節點。
- 自動清理 `proxy-groups` 裡失效的舊節點引用。
- 支援解析 `vmess://` 和 `vless://`。
- 自動為節點名稱加入國旗。
- 自動把節點加入通用策略組和對應國家 / 地區策略組。
- 可選加入 Netflix、YouTube、AI、Telegram、TikTok、HBO、Disney+、X/Twitter 等特殊策略組。
- main 新 Generate 產生 `/t/<16 位隨機 ID>` 臨時連結，預設 24 小時有效；顯示 Expires（UTC）、Download YAML / Copy Temporary Link / Clear Draft。舊 `/s/` 仍相容。
- 產生 YAML 時顯示處理提示。
- 內建瀏覽器 favicon，訪問面板時瀏覽器標籤頁會顯示圖示。
- 盡量保留原設定裡的 `rules`、`rule-providers`、`dns`、`proxy-groups` 和其他自訂欄位。
- 上傳、輸出、備份、日誌分目錄保存。
- 日誌不會記錄完整節點連結、UUID 或密碼。

---

## 專案結構

```text
clash-yaml-manager/
├── app.py
├── requirements.txt
├── install.sh
├── update.sh
├── remote-update.sh
├── uninstall.sh
├── core/
│   ├── parser.py
│   ├── yaml_utils.py
│   ├── security.py / state.py
│   ├── envfile.py / migrate.py
│   ├── rate_limit.py
│   └── subscriptions.py
├── scripts/
│   └── deploy-common.sh
├── defaults/
│   └── default.yaml
├── static/
│   └── favicon.svg
└── templates/
    └── index.html
```

執行後會自動建立：

```text
uploads/
outputs/
backups/
logs/
state/
```

---

## 安全建議

- 密碼只要求非空，不強制長度或複雜度；請自行選擇合適密碼。
- 不建議長期把管理面板直接暴露在公網。
- 推薦透過 Nginx HTTPS、Tailscale、WireGuard 或 SSH 隧道訪問。
- 如果啟用 HTTPS，可以在 `/opt/clash-yaml-manager/.env` 中設定：

```text
COOKIE_SECURE=true
DOWNLOAD_URL_SCHEME=https
DOWNLOAD_BASE_URL=https://你的網域
TRUST_PROXY_HEADERS=true
UPLOAD_RETENTION_HOURS=1
OUTPUT_RETENTION_HOURS=24
CLEANUP_INTERVAL_HOURS=1
BACKUP_RETENTION_DAYS=7
```

`DOWNLOAD_BASE_URL` 優先於其他 URL 設定。新安裝的 `DOWNLOAD_URL_SCHEME` 預設留空，按請求協議產生連結：直接 IP:PORT 訪問為 HTTP。只透過單層可信 Nginx HTTPS 代理訪問時，才設定 `TRUST_PROXY_HEADERS=true`，由 Nginx 覆寫 `X-Forwarded-For`、`X-Forwarded-Proto`、`X-Forwarded-Host` 和 `X-Forwarded-Port`，並限制外部直接連到 Gunicorn。直接訪問時維持 `false`，不信任用戶傳入的轉發標頭。

升級保留原 `.env`：如果舊安裝是直接 HTTP，卻已有 `DOWNLOAD_URL_SCHEME=https`，請手動改為空值或 `http` 並重啟服務。固定 `SECRET_KEY` 必須在所有 worker 間一致，且不能隨意更換，否則既有簽名訂閱和 session 會失效。

POST 表單與解析 API 使用 Flask-WTF CSRF 保護；表單過期請重新整理以恢復草稿。登出只接受 POST。session 使用 HttpOnly、SameSite=Lax，登入時清除舊狀態；main 登入 session 為 30 天滑動有效，每次活動延長有效期。HTTPS 部署需設定 `COOKIE_SECURE=true`。

新安裝只將 Werkzeug PBKDF2-SHA256（1,000,000 次）密碼雜湊存入 `state/auth.json`，不將明文或 Base64 密碼寫入 `.env`。所有 worker 每次認證都讀取共享檔案，修改密碼後立即生效，無需重啟；其他瀏覽器的舊 session 在下一次請求時失效。runtime 不修改 `.env`。只更新程式而略過升級腳本時，可以從舊環境憑據初始化 state，但仍需管理員完成 `.env` 清理。

登入限速跨 worker 共用 `state/login_attempts.json`，預設 600 秒內失敗 5 次即封鎖該 IP 900 秒，回傳 HTTP 429 與 `Retry-After`；成功登入清除該 IP 紀錄。可用 `LOGIN_MAX_FAILURES`、`LOGIN_WINDOW_SECONDS`、`LOGIN_LOCKOUT_SECONDS` 覆蓋。只採用 `request.remote_addr`（可信代理模式下由 ProxyFix 解析），不自行相信 X-Forwarded-For。共用 IP 的使用者也會共用限額。

systemd 使用專用 `clashyaml:clashyaml`，無登入 shell。程式、預設 YAML、venv 由 root 擁有，服務唯讀；五個 runtime 目錄由服務擁有、mode 700，檔案 mode 600。`.env` 由 root 管理、mode 600，由 systemd 讀取後傳入環境。服務設定 `UMask=0077`、`NoNewPrivileges=true`、`PrivateTmp=true`；若使用低於 1024 的端口，只授予綁定低端口所需 capability。

新輸出檔名為 `tim_YYYYMMDD_N_<128-bit nonce>.yaml`，V2 短鏈使用 128-bit HMAC。刪除後再生成會得到新隨機 identity，原地址不會因序號重設而讀到新輸出。歷史 8/12 hex 簽名只相容舊檔名，新檔不接受弱 token；完整 64 hex 下載 token 仍可使用。訂閱地址屬於持有者憑據，請勿公開；改管理密碼不撤銷訂閱地址，刪除對應輸出可以撤銷。詳細設計與驗收限制見 [Phase 2](docs/PHASE2.md)。

main 預設上傳保留 **1 小時**、輸出 **24 小時**、備份 **7 天**。啟動/請求可觸發 cleanup，跨 worker 鎖與 `state/.last_cleanup` 保證預設每小時最多掃描一次；沒有背景 daemon，無請求時實體檔案留到下次觸發。`/t/` 獨立檢查到期時間，檔案尚未刪除也回傳 404。上傳刪除不影響已生成輸出。Logs 獨立，state/auth.json 等狀態不進入檔案清理。

HOURS 配置優先；未配置時 UPLOAD / OUTPUT 回退舊 `FILE_RETENTION_DAYS`，cleanup 回退 `CLEANUP_INTERVAL_DAYS`。升級保留舊 `.env` 的值；要改成新預設，加入上方三個 HOURS 設定並重啟。無效或非正值回退安全預設，不因歷史配置格式而啟動失敗。備份獨立使用 `BACKUP_RETENTION_DAYS`（或優先 `BACKUP_RETENTION_HOURS`），預設 7 天。

`state/temporary_links.json` 原子保存 ID → filename / created_at / expires_at。到期或刪除清掉映射內容但永久保留 ID tombstone，禁止歷史 ID 重新綁定。請保留這份 state，不要刪除或回滾；ID 使用 secrets 的 96-bit 隨機數。新下載按鈕同樣使用 `/t/`，有效期一致。歷史 `/s/v2...`、legacy `/s/...`、`/sub/`、完整簽名下載仍在檔案存在時按原規則有效，其實體刪除受輸出清理控制。完整 URL 尊重 DOWNLOAD_BASE_URL / request host，保留 HTTP 非標準連接埠。

## 升級保護與回滾

已有安裝請使用 `update.sh` 或 `remote-update.sh`；`install.sh` 會拒絕覆蓋已有應用或 `.env`。本地升級必須從獨立的新版本原始碼目錄執行，不能在 `/opt/clash-yaml-manager` 原地執行。`remote-update.sh` 使用獨立臨時目錄，下載失敗不執行升級。

升級前會檢查原始碼語法、既有 `.env`、端口、固定 SECRET_KEY 及必要工具；備份程式、templates、static、部署腳本與共用 helper、requirements、venv、`.env`、預設 YAML、帳戶標記和原 systemd service。備份放在腳本輸出的 `/root/clash-yaml-manager-update-backup-*` 私有目錄。接著更新依賴並 `pip check`，再確認專用帳戶、停止服務、備份既有 state，先提交認證雜湊再原子刪除舊憑據，然後複製程式、修復所有權與權限、daemon-reload、重啟並檢查本機 HTTP 回應。備份 venv 需要额外磁碟空間。依賴仍在現有 venv 更新，失敗可能部分改動依賴；尚未實作完整 staging 或自動回滾。

新版的安裝與升級會等待應用就緒：在約 30 秒期限內每秒重試公開的 `/healthz`，只有 HTTP 200 且 systemd active 才報告完成。失敗會顯示服務狀態與最近日誌，升級備份保留供手動回滾。v1.0.2 未包含此修復；新版的部署環境需 Python ≥3.10（Gunicorn ≥25.1.0）。

失敗時不要重新執行安裝。依照輸出的備份目錄手動回滾：

1. 停止 `clash-yaml-manager`。
2. 恢復備份中的應用程式檔案和目錄；將目前 `venv` 移到另一個保留目錄，再把備份 `venv` 放回原安裝路徑。
3. 核對備份 `.env` 和 `defaults/default.yaml`；回到舊版 root 服務時必須恢復含舊憑據的備份 `.env`。回到支援 state 的版本時，優先保留最新 state；恢復舊 state 會回復舊密碼版本，可能讓舊 session 再次有效。
4. 將備份的 `clash-yaml-manager.service` 恢復到 `/etc/systemd/system/`；執行 `systemctl daemon-reload` 和 `systemctl restart clash-yaml-manager`。
5. 檢查 `systemctl status`、日誌和原本訪問地址。保留 `uploads/outputs/backups/logs/state`，不用刪除它們。若舊 root 服務寫入過資料，往後再次升級要重新修復 runtime 所有權。升級備份可能包含舊明文/Base64 密碼，僅供 root 復原，確認穩定後按自己的保留政策處理。完整步驟見 [Phase 2 遷移](docs/PHASE2.md#e-migration)。

## Development / Testing

**main is a development channel and is not recommended for normal production use.**
Stable 仍是預設；`--channel stable` 與不帶 channel 參數相同。開發通道必須明確選擇，不會因 main 有更新而自動切換。

全新測試 VPS 安裝當前 main（需要互動終端輸入端口和管理密碼）：

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-install.sh | sudo bash -s -- --channel main
```

已有測試 VPS 升級到當前 main：

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --channel main
```

先解析 `refs/heads/main` 的完整 SHA，再下載該 SHA 的歸檔，絕不在解析後下載移動中的 main 分支。CLI 顯示 Channel、Resolved commit、Base version 和 Installed build。VERSION 保持原值；Web footer 顯示例如 `v1.0.2-dev+a9c2d10` 和低調的 DEV / Development Build。

安裝元信息在 `/opt/clash-yaml-manager/INSTALLATION.json`：channel、base_version、完整 commit、tag、installed_at（UTC）和 source。使用原子寫入，root 擁有、644 可供服務讀取；只含公開 build 身份，不含憑據，不寫 `.env`。保留原有 auth、temporary-link state、預設 YAML、runtime 資料及服務權限模型。升級備份會包含此檔。

通道切換規則：

| 操作 | 行為 |
|---|---|
| stable → main | 明確 `--channel main` 即允許，不再詢問 yes |
| main → main | 比較 commit SHA；相同為 Already up to date，不看 VERSION 是否相同 |
| main → 較新 stable（例如 1.1.0） | 普通 remote-update 即可回到 stable |
| main → 同 base version 或更舊 stable | 預設拒絕；只有 `--channel stable --allow-downgrade` 明確允許 |
| stable → 較舊 stable | 仍需要 `--allow-downgrade` |

`--version vX.Y.Z` 仍只指定 Stable Release，不可與 `--channel main` 合用。不支援任意分支名。尚未發布較新 Stable 時，返回舊 Stable 的明確命令為：

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --channel stable --allow-downgrade
```

降級許可不代表舊程式理解新 state，先保留協調一致的備份。不要刪除 INSTALLATION.json 來繞過檢查。沒有元信息的歷史安裝沿用 VERSION；直接從本機源码執行 install/update 則標為 `-local`，不冒用上一次 main commit。完整規則見 [部署文件](docs/RELEASE.md)。

## 開發驗證

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app.py core tests
for script in install.sh update.sh remote-install.sh remote-update.sh uninstall.sh scripts/deploy-common.sh; do
  bash -n "$script"
done
```

Node 可用時 pytest 也會執行草稿與搜尋 JS 測試（可單獨 `node tests/test_draft.js`）。如有 shellcheck，另執行 `shellcheck install.sh update.sh remote-install.sh remote-update.sh uninstall.sh scripts/deploy-common.sh`。測試使用臨時資料，包含真實 YAML 全量 round trip、下載、訂閱及並發輸出；部署腳本測試使用 systemctl/curl/pip 替身，不能取代 Ubuntu systemd 驗收。

處理模式仍為 Replace。錯誤 YAML 結構、重複策略組、節點與組名稱衝突，或 rules 仍指向刪除的舊節點時會阻止生成並提供位置，避免靜默丟設定；先在來源 YAML 處理衝突再重試。未涉及部分的註解和引號盡量保留；這還不是完整 Mihomo validator。main 已有節點 Parse Preview；Merge、完整 YAML 差異預覽和新協議尚未實作。

---

## 常見問題

### 瀏覽器打不開

```bash
systemctl status clash-yaml-manager
journalctl -u clash-yaml-manager -f
ss -tulnp | grep 8899
```

### 提示 `proxy not found`

說明策略組裡還有不存在的節點或策略組引用。工具會盡量自動清理，但遇到特殊 YAML 結構時，建議檢查產生後的 `proxy-groups`。

### 想修改預設 YAML

修改：

```text
/opt/clash-yaml-manager/defaults/default.yaml
```

然後重啟：

```bash
systemctl restart clash-yaml-manager
```

### 想修改頁面樣式

修改：

```text
/opt/clash-yaml-manager/templates/index.html
```

然後重啟：

```bash
systemctl restart clash-yaml-manager
```
