# Clash YAML Manager

適合部署在 Ubuntu VPS 上的輕量級 Clash/Mihomo YAML 節點管理面板。

可上傳現有 YAML，也可直接使用內建預設 YAML。新節點輸入支援 VMess / VLESS / Trojan / Shadowsocks（`vmess://` / `vless://` / `trojan://` / `ss://`）；Generate 預設 Replace 會替換 `proxies`、清理舊節點引用並補齊策略組；明確選擇 Merge 可保留來源節點並追加本次新節點，產生新的 Clash/Mihomo 設定檔。

<!-- RELEASE:START -->
**Latest Stable: [v1.2.1](https://github.com/wwintj/clash-yaml-manager/releases/tag/v1.2.1)**
<!-- RELEASE:END -->

main 是開發分支；以下安裝與升級預設只使用 GitHub Latest Stable Release，API 失敗不會退回 main。只有明確指定 `--channel main` 才使用開發通道，測試命令見下方 Development / Testing。

正式版本以頁首 Latest Stable 為準；功能驗收過程與限制見 [開發報告](docs/V1_1_DEVELOPMENT.md)。

## 功能與文件

v1.3.0 發布範圍包括 Diff Preview、Generate Merge、Trojan 與 Shadowsocks。普通安裝／升級使用 Latest Stable；正式可用範圍以其 Release Notes 為準。受控發布前驗收與延後的真機項目見 [v1.3 Final Audit](docs/V1_3_FINAL_AUDIT_REPORT.md)，[v1.2 歷史審計](docs/FINAL_AUDIT_REPORT.md) 保留當時記錄。

| 功能 | 行為與文件 |
| --- | --- |
| Generate / Preview | [Replace（預設）／Merge](docs/MERGE_MODE.md)、VMess/VLESS/Trojan/Shadowsocks 新輸入、可編輯國家／名稱預覽、[Full YAML Diff Preview](docs/YAML_DIFF_PREVIEW.md)、30 天本機草稿及預設 24 小時 `/t/` 臨時連結 |
| [Fixed Subscriptions](docs/FIXED_SUBSCRIPTIONS.md) | 保存 Default / Custom YAML 與節點；一般保存保持 `/s/<prefix>-fs_<secret>`，不受臨時清理影響 |
| [External Sources](docs/EXTERNAL_SOURCES.md) | 合併 Manual、Remote URL、Uploaded；Clash YAML / Raw / Base64，last-good cache |
| [Automatic Refresh](docs/AUTO_REFRESH.md) | Remote Source 預設 Off，七檔間隔、獨立 timer、失敗退避及有限歷史 |
| [Endpoint Health](docs/NODE_HEALTH.md) | 預設 Off；Manual / Automatic TCP reachability，三次失敗為 Unhealthy，保留 YAML 節點 |
| [Full Proxy Health](docs/PROXY_HEALTH.md) | 預設 Off；SSH 管理的 Mihomo v1.19.31 執行 HTTPS probe；amd64 v1/v2/v3 依 CPU 能力選擇，另支援 arm64 |
| [Automatic Health](docs/AUTOMATIC_HEALTH.md) | 獨立健康 timer，每輪最多 4 個 Endpoint、1 個 Proxy 作業；不刷新來源 |
| [Policy Engine](docs/POLICY_ENGINE.md) | Country / Selected Special Groups：Preserve（預設）、Select、URL-Test、Fallback、round-robin Load-Balance |
| [Health-aware Policy](docs/HEALTH_AWARE_POLICY.md) | 預設 Off；僅保守排除新鮮且三次失敗的 Proxy 候選，候選不足時 fail-open；頂層節點保留 |
| [GeoIP](docs/GEOIP.md) | 預設 Off；Manual → Name → GeoIP → Unknown，操作員提供離線 MMDB，只查公共字面 IP，無 DNS／下載 |
| [Settings](docs/SETTINGS.md) | 登入後的 Overview / GeoIP / Health / Runtime / Notifications；GET 只讀本地狀態，不執行探測或系統命令 |
| [HTTPS assistant](docs/HTTPS.md) | 可選 SSH/root Nginx + Certbot Webroot；普通安裝保持 HTTP，管理模式 Gunicorn 僅綁 loopback |
| [Telegram Notifications](docs/NOTIFICATIONS.md) | 預設 Off；自動掃描事故／恢復邊界每輪最多一則清理後彙總，無持久佇列或自動重送 |

Fixed 舊 registry v1–v5 只在內存補新功能預設，合法修改才寫 v6；既有 Health v1 讀作 v2，Off / Manual 不會變成 Automatic。更新保留 token、已提交 YAML、來源快取與獨立狀態。普通安裝不下載 Mihomo、GeoIP 資料庫或申請憑證，也不聯絡 Telegram。

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

節點輸入支援三種格式混用。手工 COUNTRY 優先；否則從 NAME、URI fragment / VMess ps remark 識別。缺名稱時產生確定性的 Node-01 等名稱。新 URI 輸入支援 VMess / VLESS / Trojan / Shadowsocks；Trojan TCP / WS、TLS/SNI 與密碼規則見 [Trojan Protocol](docs/TROJAN_PROTOCOL.md)。Shadowsocks 的 SIP002 userinfo／legacy Base64、cipher／password 保真與拒絕 plugin 規則見 [Shadowsocks Protocol](docs/SHADOWSOCKS_PROTOCOL.md) 及 [驗收報告](docs/SHADOWSOCKS_PROTOCOL_REPORT.md)。這是 supported input protocols，不是所有 Clash proxy types。

Generate 頁新增 **Preview YAML Changes**。它用最新輸入及同一個 Generate 轉換流程，在登入後顯示完整 unified YAML diff；不建立 output、backup 或臨時連結，也不保存 diff 草稿。Custom YAML 需仍選有實際檔案；過大會明確拒絕預覽，仍可正常 Generate。詳見 [功能及限制](docs/YAML_DIFF_PREVIEW.md) 與 [受控驗收](docs/YAML_DIFF_PREVIEW_REPORT.md)。

Generate 的 **Node Update Mode** 預設 **Replace existing nodes**；明確選 **Merge with existing nodes** 會保持來源 proxies 順序及已有引用，再依提交順序追加新節點。同名會報錯，不覆蓋、不改名、不按連線去重。新節點加入一般組、所選 Special Groups 及本次國家組；顯式自動 Policy 仍依既有 contract 只用本次新候選。Merge 僅限 Generate，Fixed 仍為 Replace；新輸入仍只解析 VMess/VLESS/Trojan/Shadowsocks，來源已存在的其他類型可原樣保留。Diff 使用同一個模式；詳見 [Merge Mode](docs/MERGE_MODE.md) 與 [驗收報告](docs/MERGE_MODE_REPORT.md)。

點 **Parse Nodes** 查看 Name、Country、Protocol、Ready / Warning / Error 和來源。修改輸入後顯示 Changes not parsed yet。Preview 可修改 Country / Name，修改立即保存；Apply edit 或 Parse Nodes 更新預覽。手工國家優先，重排未修改的輸入不會丟掉手工修正。直接 Generate 也會解析最新內容，不要求先 Parse。重複名稱或無效 URI 是 Error，阻止生成。

支援完整 249 個 ISO 國家/地區，使用同一份[離線資料](docs/COUNTRY_DATA.md)。Auxiliary 和 Preview 的搜尋欄支援 ISO、English、中文和別名，常用國家置頂；例如 tai 找 Taiwan / Thailand，美 找美國，JP 找日本。預設只依據旗幟、保守的名稱/代碼和城市別名，不使用 DNS。明確啟用 GeoIP 後，名稱未識別的公共字面 IP 可使用操作員提供的離線 MMDB；手動國家及名稱判斷仍優先。衝突或不明名稱為 **🌐 Unknown**，Warning 仍可 Generate，加入 **🌐 其他节点**。只為本次存在的國家建立策略組，保留來源 YAML 既有組。

## 草稿

Batch、全部 Auxiliary rows、Policy Options、YAML source、Node Update Mode 和 Preview 手工修正自動存到同一瀏覽器、同一網站 origin 的 localStorage，保留最後保存後 30 天。提交前同步保存；刷新、退出再登入、session / CSRF 失效後可恢復，顯示 Draft restored。沒有模式欄位的舊草稿恢復為 Replace。成功生成不清空；**Clear Draft** 需確認，清除後模式回到 Replace。

不儲存上傳 YAML 的內容；恢復 Custom YAML 時必須重新選檔，不會靜默使用預設 YAML。CSRF 保護仍在，token 過期刷新，session 過期登入後恢復。

草稿含分享連結，保存在瀏覽器本機且未加密；共用裝置用完請 Clear Draft。停用儲存、容量不足或瀏覽器清除資料會影響恢復，保存失敗會顯示提示。更換網域或連接埠不會跨 origin 恢復草稿。

---

## 可選 HTTPS / Nginx

普通安裝及升級保持 HTTP，不會自動安裝 Nginx / Certbot 或申請憑證。可在
Debian/Ubuntu VPS 以 SSH/root 執行 `sudo bash /opt/clash-yaml-manager/httpsctl.sh setup --domain example.com --email admin@example.com`。
先配置 DNS 和公開 TCP 80/443；工具不修改防火牆或 DNS。成功後 Gunicorn 仍以
clashyaml 執行，綁定 127.0.0.1；Nginx 使用 Certbot Webroot HTTPS，覆寫轉發標頭。

`httpsctl.sh status` 為唯讀；`disable` 驗證所有權與 drift 後恢復原部署設定，
保留憑證及 Certbot 帳戶。Settings Runtime 僅顯示安全元資料及執行設定，沒有
Web 部署按鈕。完整流程、私有備份、回滾和限制見 [HTTPS 文件](docs/HTTPS.md)
及 [受控驗收報告](docs/HTTPS_REPORT.md)。**REAL HTTPS VPS: NOT RUN**。

## 可選 Telegram 通知

Settings → Notifications 提供預設關閉的 Telegram 通知。保存 `<BOT_TOKEN>` 和
數字 `<CHAT_ID>` 後，可明確發送測試通知；保存本身不連網。憑據只存在私有
0600 通知狀態，頁面不回填 Token，目的地以遮罩顯示。

自動來源刷新、Endpoint / Full Proxy Health 和 scheduler 故障只在事故／恢復
邊界通知，每次掃描至多一則；訊息只含清理後的訂閱名稱和彙總數量。
Telegram 失敗不影響 YAML、健康結果或排程；無持久佇列及自動重送。
啟用後會把這些資料傳到 Telegram。設定、隱私、備份及限制見
[Notifications 文件](docs/NOTIFICATIONS.md) 和 [受控驗收報告](docs/NOTIFICATIONS_REPORT.md)。
**REAL TELEGRAM NOTIFICATION: NOT RUN**。

## 功能說明

- 可以上傳現有 Clash/Mihomo YAML，也可以不上傳，直接使用內建預設 YAML。
- Generate 預設 Replace 刪除舊節點；明確 Merge 保留來源節點並追加新節點。
- Replace 清理舊節點引用；Merge 保留已有引用，同名或無效引用會拒絕。
- 新輸入支援 `vmess://`、`vless://`、`trojan://` 和 `ss://`；保留來源其他 proxy 類型不等於支援其 URI 輸入。
- 自動為節點名稱加入國旗。
- 自動把節點加入通用策略組和對應國家 / 地區策略組。
- 可選加入 Netflix、YouTube、AI、Telegram、TikTok、HBO、Disney+、X/Twitter 等特殊策略組。
- Generate 產生 `/t/<16 位隨機 ID>` 臨時連結，預設 24 小時有效；顯示 Expires（UTC）、Download YAML / Copy Temporary Link / Clear Draft。舊 `/s/` 仍相容。
- 產生 YAML 時顯示處理提示。
- 內建瀏覽器 favicon，訪問面板時瀏覽器標籤頁會顯示圖示。
- 盡量保留原設定裡的 `rules`、`rule-providers`、`dns`、`proxy-groups` 和其他自訂欄位。
- 上傳、輸出、備份、日誌分目錄保存。
- 日誌不會記錄完整節點連結、UUID 或密碼。

---

## 專案結構

```text
clash-yaml-manager/
├── VERSION / CHANGELOG.md / requirements*.txt
├── app.py
├── install.sh / update.sh / uninstall.sh
├── remote-install.sh / remote-update.sh
├── mihomoctl.sh / mihomo-manifest.json / httpsctl.sh
├── core/
│   ├── parser.py / generator.py / yaml_utils.py / countries.py
│   ├── yaml_diff.py / node_update.py
│   ├── security.py / rate_limit.py / subscriptions.py / temporary_links.py
│   ├── state.py / envfile.py / migrate.py / install_info.py / version.py
│   ├── fixed_subscriptions.py / fixed_sources.py / fixed_views.py
│   ├── source_fetch.py / source_parser.py / source_errors.py
│   ├── auto_refresh.py / refresh_schedule.py
│   ├── node_health.py / node_probe.py / node_identity.py
│   ├── proxy_health.py / mihomo_manager.py / mihomo_probe.py
│   ├── auto_health.py / health_schedule.py / health_policy.py / policy_engine.py
│   ├── geoip.py / geoip_store.py / settings_views.py / settings_status.py
│   ├── https_manager.py / https_metadata.py / deployment_config.py
│   └── notifications.py / notification_events.py / telegram.py / retention.py
├── scripts/                 # release.py, remote_lifecycle.py, build_bootstraps.py, deploy-common.sh
├── defaults/default.yaml
├── static/                  # favicon、Generate / Fixed / Policy JS 與 CSS
├── templates/               # Generate、Fixed、Settings 及功能 partials
├── tests/
└── docs/
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
- 推薦透過可選 Nginx HTTPS、Tailscale、WireGuard 或 SSH 隧道訪問。管理模式綁定 Gunicorn 到 loopback，僅在單層可信代理後啟用轉發標頭信任。
- `/s/`、`/t/` 及簽名下載 URL 都是持有者憑據；Fixed 表單有意顯示自己的 URL 和來源設定。不要分享面板內容、來源 URL 或包含節點的 YAML。
- 啟用 Telegram 後會傳送清理後的訂閱名稱與彙總至 Telegram；憑據及私有備份仍需保密。GeoIP 資料庫由操作員提供；Mihomo 只經 SSH 管理。可選功能預設 Off。
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

POST 表單與解析 API 使用 Flask-WTF CSRF 保護；表單過期請重新整理以恢復草稿。登出只接受 POST。session 使用 HttpOnly、SameSite=Lax，登入時清除舊狀態；登入 session 為 30 天滑動有效，每次活動延長有效期。HTTPS 部署需設定 `COOKIE_SECURE=true`。

新安裝只將 Werkzeug PBKDF2-SHA256（1,000,000 次）密碼雜湊存入 `state/auth.json`，不將明文或 Base64 密碼寫入 `.env`。所有 worker 每次認證都讀取共享檔案，修改密碼後立即生效，無需重啟；其他瀏覽器的舊 session 在下一次請求時失效。runtime 不修改 `.env`。只更新程式而略過升級腳本時，可以從舊環境憑據初始化 state，但仍需管理員完成 `.env` 清理。

登入限速跨 worker 共用 `state/login_attempts.json`，預設 600 秒內失敗 5 次即封鎖該 IP 900 秒，回傳 HTTP 429 與 `Retry-After`；成功登入清除該 IP 紀錄。可用 `LOGIN_MAX_FAILURES`、`LOGIN_WINDOW_SECONDS`、`LOGIN_LOCKOUT_SECONDS` 覆蓋。只採用 `request.remote_addr`（可信代理模式下由 ProxyFix 解析），不自行相信 X-Forwarded-For。共用 IP 的使用者也會共用限額。

systemd 使用專用 `clashyaml:clashyaml`，無登入 shell。程式、預設 YAML、venv 由 root 擁有，服務唯讀；五個 runtime 目錄由服務擁有、mode 700，檔案 mode 600。`.env` 由 root 管理、mode 600，由 systemd 讀取後傳入環境。服務設定 `UMask=0077`、`NoNewPrivileges=true`、`PrivateTmp=true`；若使用低於 1024 的端口，只授予綁定低端口所需 capability。

新輸出檔名為 `tim_YYYYMMDD_N_<128-bit nonce>.yaml`，V2 短鏈使用 128-bit HMAC。刪除後再生成會得到新隨機 identity，原地址不會因序號重設而讀到新輸出。歷史 8/12 hex 簽名只相容舊檔名，新檔不接受弱 token；完整 64 hex 下載 token 仍可使用。訂閱地址屬於持有者憑據，請勿公開；改管理密碼不撤銷訂閱地址，刪除對應輸出可以撤銷。詳細設計與驗收限制見 [Phase 2](docs/PHASE2.md)。

預設上傳保留 **1 小時**、輸出 **24 小時**、備份 **7 天**。啟動/請求可觸發 cleanup，跨 worker 鎖與 `state/.last_cleanup` 保證預設每小時最多掃描一次；沒有背景 daemon，無請求時實體檔案留到下次觸發。`/t/` 獨立檢查到期時間，檔案尚未刪除也回傳 404。上傳刪除不影響已生成輸出。Logs 獨立，state/auth.json 等狀態不進入檔案清理。

HOURS 配置優先；未配置時 UPLOAD / OUTPUT 回退舊 `FILE_RETENTION_DAYS`，cleanup 回退 `CLEANUP_INTERVAL_DAYS`。升級保留舊 `.env` 的值；要改成新預設，加入上方三個 HOURS 設定並重啟。無效或非正值回退安全預設，不因歷史配置格式而啟動失敗。備份獨立使用 `BACKUP_RETENTION_DAYS`（或優先 `BACKUP_RETENTION_HOURS`），預設 7 天。

`state/temporary_links.json` 原子保存 ID → filename / created_at / expires_at。到期或刪除清掉映射內容但永久保留 ID tombstone，禁止歷史 ID 重新綁定。請保留這份 state，不要刪除或回滾；ID 使用 secrets 的 96-bit 隨機數。新下載按鈕同樣使用 `/t/`，有效期一致。歷史 `/s/v2...`、legacy `/s/...`、`/sub/`、完整簽名下載仍在檔案存在時按原規則有效，其實體刪除受輸出清理控制。完整 URL 尊重 DOWNLOAD_BASE_URL / request host，保留 HTTP 非標準連接埠。

## 升級保護與回滾

已有安裝請使用 `update.sh` 或 `remote-update.sh`；`install.sh` 會拒絕覆蓋已有應用或 `.env`。本地升級必須從獨立的新版本原始碼目錄執行，不能在 `/opt/clash-yaml-manager` 原地執行。`remote-update.sh` 使用獨立臨時目錄，下載失敗不執行升級。

升級前會檢查原始碼語法、既有 `.env`、端口、固定 SECRET_KEY 及必要工具；備份程式、templates、static、部署腳本與共用 helper、requirements、venv、`.env`、預設 YAML、帳戶標記和原 systemd service。備份放在腳本輸出的 `/root/clash-yaml-manager-update-backup-*` 私有目錄。接著更新依賴並 `pip check`，再確認專用帳戶、停止服務、備份既有 state，先提交認證雜湊再原子刪除舊憑據，然後複製程式、修復所有權與權限、daemon-reload、重啟並檢查本機 HTTP 回應。備份 venv 需要额外磁碟空間。依賴仍在現有 venv 更新，失敗可能部分改動依賴；尚未實作完整 staging 或自動回滾。

新版的安裝與升級會等待應用就緒：在約 30 秒期限內每秒重試公開的 `/healthz`，只有 HTTP 200 且 systemd active 才報告完成。失敗會顯示服務狀態與最近日誌，升級備份保留供手動回滾。v1.0.2 未包含此修復；新版的部署環境需 Python ≥3.10（Gunicorn ≥25.1.0）。

失敗時不要重新執行安裝。依照輸出的備份目錄手動回滾：

1. 先停止 refresh / health timer 和 oneshot，再停止 `clash-yaml-manager`，避免備份或恢復時仍有寫入。
2. 恢復備份中的應用程式檔案和目錄；將目前 `venv` 移到另一個保留目錄，再把備份 `venv` 放回原安裝路徑。
3. 核對備份 `.env` 和 `defaults/default.yaml`；回到舊版 root 服務時必須恢復含舊憑據的備份 `.env`。回到支援 state 的版本時，優先保留最新 state；恢復舊 state 會回復舊密碼版本，可能讓舊 session 再次有效。
4. 核對並恢復備份中的 app、refresh 和 health 共五個 unit（旧版本沒有的新增 unit 須移除）；執行 `systemctl daemon-reload` 和 `systemctl restart clash-yaml-manager`。
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

降級許可不代表舊程式理解新 state；不宣稱 v1.2 狀態可安全供 v1.1.1 使用，須保留舊程式及匹配的協調備份，沒有反向遷移。不要刪除 INSTALLATION.json 來繞過檢查。沒有元信息的歷史安裝沿用 VERSION；直接從本機源码執行 install/update 則標為 `-local`，不冒用上一次 main commit。完整規則見 [部署文件](docs/RELEASE.md)。

## 開發驗證

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app.py core scripts tests
for script in install.sh remote-install.sh update.sh remote-update.sh uninstall.sh httpsctl.sh mihomoctl.sh scripts/deploy-common.sh; do
  bash -n "$script"
done
```

Node 可用時 pytest 也會執行草稿與搜尋 JS 測試（可單獨 `node tests/test_draft.js`）。如有 shellcheck，另執行 `shellcheck install.sh remote-install.sh update.sh remote-update.sh uninstall.sh httpsctl.sh mihomoctl.sh scripts/deploy-common.sh`。測試使用臨時資料，包含真實 YAML 全量 round trip、下載、訂閱及並發輸出；部署腳本測試使用 systemctl/curl/pip 替身，不能取代 Ubuntu systemd 驗收。

Generate 支援 Replace（預設）／Merge，Fixed 仍為 Replace。錯誤 YAML 結構、重複策略組、節點與組名稱衝突會阻止生成；Replace 的 rules 若仍指向刪除的舊節點也會拒絕，Merge 保留的節點可繼續被引用。同名 Merge 必須先在來源或新輸入處理，不會自動覆蓋。未涉及部分的註解和引號盡量保留；這還不是完整 Mihomo validator。已有節點 Parse Preview 和 Full YAML Diff Preview；新輸入協議仍僅 VMess/VLESS/Trojan/Shadowsocks，其他新協議尚未實作。

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
