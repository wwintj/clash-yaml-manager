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

適用於已經安裝過的 VPS。升級會保留 `.env`、預設 YAML、上傳檔案、輸出檔案、備份和日誌。

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

---

## 一鍵卸載

```bash
sudo bash /opt/clash-yaml-manager/uninstall.sh
```

卸載腳本會停止服務、停用開機自啟、刪除 systemd service，並詢問是否刪除專案目錄。選擇刪除目錄時，可以繼續選擇是否保留 `backups/` 和 `outputs/`。

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
- 產生超短帶簽名 YAML 訂閱直鏈，例如 `/s/2606021a1b2c3d`，可複製到 Clash/Mihomo 客戶端使用。
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
│   └── yaml_utils.py
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
FILE_RETENTION_DAYS=7
CLEANUP_INTERVAL_DAYS=7
```

`DOWNLOAD_BASE_URL` 可以留空；留空時系統會按目前訪問網域產生下載連結。反向代理 HTTPS 時，建議在 Nginx 中傳遞 `X-Forwarded-Proto` 和 `X-Forwarded-Host`。

`uploads/`、`outputs/`、`backups/` 會按上面的設定自動清理：預設最多每 7 天檢查一次，並刪除 7 天前的檔案。

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
