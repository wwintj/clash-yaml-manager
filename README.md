# Clash YAML Manager

適合部署在 Ubuntu VPS 上的輕量級 Clash/Mihomo YAML 節點管理面板。

可上傳現有 YAML，也可直接使用內建預設 YAML。輸入 `vmess://` / `vless://` 節點後，系統會自動替換 `proxies`、清理舊節點引用、補齊策略組，並產生新的 Clash/Mihomo 設定檔。

**聯絡信箱：** wwintj@gmail.com

**GitHub About 建議：**

- Description: `輕量級 Clash/Mihomo YAML 節點管理面板，支援預設規則、一鍵安裝、一鍵升級、vmess/vless 節點注入。`
- Topics: `clash`, `mihomo`, `yaml`, `flask`, `proxy`, `vmess`, `vless`, `vps`

---

## 一鍵安裝

在 Ubuntu VPS 上執行：

```bash
sudo bash -c 'apt-get update -y && apt-get install -y git ca-certificates && rm -rf /tmp/clash-yaml-manager && git clone https://github.com/wwintj/clash-yaml-manager.git /tmp/clash-yaml-manager && cd /tmp/clash-yaml-manager && bash install.sh'
```

安裝時會提示輸入：

- Web 連接埠，預設 `8899`
- Web 管理密碼

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

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash
```

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

目前版本發布說明請看 [CHANGELOG.md](CHANGELOG.md)。

建議首個 GitHub Release：

- Tag: `v1.0.0`
- Title: `v1.0.0 - Default YAML and Update Flow`
- Notes: 複製 [CHANGELOG.md](CHANGELOG.md) 中 `v1.0.0` 小節

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
國家代碼|節點名稱|節點連結
```

範例：

```text
US|tim|vmess://xxxx
TW|TW55|vmess://xxxx
JP|JP2|vless://xxxx
HK|GIA|vmess://xxxx
```

支援的國家 / 地區代碼：

| 代碼 | 策略組 |
|---|---|
| US | 美國節點 |
| HK | 香港節點 |
| TW | 台灣節點 |
| JP | 日本節點 |
| KR | 韓國節點 |
| SG | 獅城節點 |
| KP | 朝鮮節點 |
| MY | 馬來西亞節點 |
| DE | 德國節點 |
| GB | 英國節點 |
| CA | 加拿大節點 |

---

## 功能說明

- 可以上傳現有 Clash/Mihomo YAML，也可以不上傳，直接使用內建預設 YAML。
- 自動刪除原 `proxies` 中的舊節點。
- 自動清理 `proxy-groups` 裡失效的舊節點引用。
- 支援解析 `vmess://` 和 `vless://`。
- 自動為節點名稱加入國旗。
- 自動把節點加入通用策略組和對應國家 / 地區策略組。
- 可選加入 Netflix、YouTube、AI、Telegram、TikTok、HBO、Disney+、X/Twitter 等特殊策略組。
- 產生 V2 帶簽名 YAML 訂閱直鏈，格式為 `/s/v2.日期.序號.隨機標識.簽名`，可複製到 Clash/Mihomo 客戶端使用。
- 產生 YAML 和刪除臨時檔案時都會顯示進度提示。
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

- 建議使用複雜密碼。
- 不建議長期把管理面板直接暴露在公網。
- 推薦透過 Nginx HTTPS、Tailscale、WireGuard 或 SSH 隧道訪問。
- 如果啟用 HTTPS，可以在 `/opt/clash-yaml-manager/.env` 中設定：

```text
COOKIE_SECURE=true
DOWNLOAD_URL_SCHEME=https
DOWNLOAD_BASE_URL=https://你的網域
TRUST_PROXY_HEADERS=true
FILE_RETENTION_DAYS=7
CLEANUP_INTERVAL_DAYS=7
```

`DOWNLOAD_BASE_URL` 優先於其他 URL 設定。新安裝的 `DOWNLOAD_URL_SCHEME` 預設留空，按請求協議產生連結：直接 IP:PORT 訪問為 HTTP。只透過單層可信 Nginx HTTPS 代理訪問時，才設定 `TRUST_PROXY_HEADERS=true`，由 Nginx 覆寫 `X-Forwarded-For`、`X-Forwarded-Proto`、`X-Forwarded-Host` 和 `X-Forwarded-Port`，並限制外部直接連到 Gunicorn。直接訪問時維持 `false`，不信任用戶傳入的轉發標頭。

升級保留原 `.env`：如果舊安裝是直接 HTTP，卻已有 `DOWNLOAD_URL_SCHEME=https`，請手動改為空值或 `http` 並重啟服務。固定 `SECRET_KEY` 必須在所有 worker 間一致，且不能隨意更換，否則既有簽名訂閱和 session 會失效。

五個 POST 表單已使用 Flask-WTF CSRF 保護；表單過期請重新整理。登出只接受 POST。session 使用 HttpOnly、SameSite=Lax，登入時清除舊狀態，登入 session 的有效期為 12 小時（活動時刷新）；HTTPS 部署需設定 `COOKIE_SECURE=true`。

新安裝只將 Werkzeug PBKDF2-SHA256（1,000,000 次）密碼雜湊存入 `state/auth.json`，不將明文或 Base64 密碼寫入 `.env`。所有 worker 每次認證都讀取共享檔案，修改密碼後立即生效，無需重啟；其他瀏覽器的舊 session 在下一次請求時失效。runtime 不修改 `.env`。只更新程式而略過升級腳本時，可以從舊環境憑據初始化 state，但仍需管理員完成 `.env` 清理。

登入限速跨 worker 共用 `state/login_attempts.json`，預設 600 秒內失敗 5 次即封鎖該 IP 900 秒，回傳 HTTP 429 與 `Retry-After`；成功登入清除該 IP 紀錄。可用 `LOGIN_MAX_FAILURES`、`LOGIN_WINDOW_SECONDS`、`LOGIN_LOCKOUT_SECONDS` 覆蓋。只採用 `request.remote_addr`（可信代理模式下由 ProxyFix 解析），不自行相信 X-Forwarded-For。共用 IP 的使用者也會共用限額。

systemd 使用專用 `clashyaml:clashyaml`，無登入 shell。程式、預設 YAML、venv 由 root 擁有，服務唯讀；五個 runtime 目錄由服務擁有、mode 700，檔案 mode 600。`.env` 由 root 管理、mode 600，由 systemd 讀取後傳入環境。服務設定 `UMask=0077`、`NoNewPrivileges=true`、`PrivateTmp=true`；若使用低於 1024 的端口，只授予綁定低端口所需 capability。

新輸出檔名為 `tim_YYYYMMDD_N_<128-bit nonce>.yaml`，V2 短鏈使用 128-bit HMAC。刪除後再生成會得到新隨機 identity，原地址不會因序號重設而讀到新輸出。歷史 8/12 hex 簽名只相容舊檔名，新檔不接受弱 token；完整 64 hex 下載 token 仍可使用。訂閱地址屬於持有者憑據，請勿公開；改管理密碼不撤銷訂閱地址，刪除對應輸出可以撤銷。詳細設計與驗收限制見 [Phase 2](docs/PHASE2.md)。

`uploads/`、`outputs/`、`backups/` 會按上面的設定自動清理：預設最多每 7 天檢查一次，並刪除 7 天前的檔案。`state/` 不參與檔案保留期清理；登入嘗試由 limiter 自行淘汰。

## 升級保護與回滾

已有安裝請使用 `update.sh` 或 `remote-update.sh`；`install.sh` 會拒絕覆蓋已有應用或 `.env`。本地升級必須從獨立的新版本原始碼目錄執行，不能在 `/opt/clash-yaml-manager` 原地執行。`remote-update.sh` 使用獨立臨時目錄，下載失敗不執行升級。

升級前會檢查原始碼語法、既有 `.env`、端口、固定 SECRET_KEY 及必要工具；備份程式、templates、static、部署腳本與共用 helper、requirements、venv、`.env`、預設 YAML、帳戶標記和原 systemd service。備份放在腳本輸出的 `/root/clash-yaml-manager-update-backup-*` 私有目錄。接著更新依賴並 `pip check`，再確認專用帳戶、停止服務、備份既有 state，先提交認證雜湊再原子刪除舊憑據，然後複製程式、修復所有權與權限、daemon-reload、重啟並檢查本機 HTTP 回應。備份 venv 需要额外磁碟空間。依賴仍在現有 venv 更新，失敗可能部分改動依賴；尚未實作完整 staging 或自動回滾。

失敗時不要重新執行安裝。依照輸出的備份目錄手動回滾：

1. 停止 `clash-yaml-manager`。
2. 恢復備份中的應用程式檔案和目錄；將目前 `venv` 移到另一個保留目錄，再把備份 `venv` 放回原安裝路徑。
3. 核對備份 `.env` 和 `defaults/default.yaml`；回到舊版 root 服務時必須恢復含舊憑據的備份 `.env`。回到支援 state 的版本時，優先保留最新 state；恢復舊 state 會回復舊密碼版本，可能讓舊 session 再次有效。
4. 將備份的 `clash-yaml-manager.service` 恢復到 `/etc/systemd/system/`；執行 `systemctl daemon-reload` 和 `systemctl restart clash-yaml-manager`。
5. 檢查 `systemctl status`、日誌和原本訪問地址。保留 `uploads/outputs/backups/logs/state`，不用刪除它們。若舊 root 服務寫入過資料，往後再次升級要重新修復 runtime 所有權。升級備份可能包含舊明文/Base64 密碼，僅供 root 復原，確認穩定後按自己的保留政策處理。完整步驟見 [Phase 2 遷移](docs/PHASE2.md#e-migration)。

## 開發驗證

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app.py core tests
for script in install.sh update.sh remote-update.sh uninstall.sh scripts/deploy-common.sh; do
  bash -n "$script"
done
```

如有 shellcheck，另執行 `shellcheck install.sh update.sh remote-update.sh uninstall.sh scripts/deploy-common.sh`。測試使用臨時資料和測試密碼，包含真實預設 YAML 的全量 round trip、下載、訂閱及並發輸出；部署腳本測試使用替代 systemctl/curl/pip，不能取代 Ubuntu 上的 systemd 驗收。

處理模式仍為 Replace。錯誤 YAML 結構、重複策略組、節點與組名稱衝突，或 rules 仍指向刪除的舊節點時會阻止生成並提供位置，避免靜默丟設定；先在來源 YAML 處理衝突再重試。未涉及部分的註解和引號盡量保留；這還不是完整 Mihomo validator。Merge、Preview 和新協議會分階段加入。

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
