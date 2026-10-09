# Time Limit Inventory（v1.8.0 開發）

原 Phase 3D-3G 為只讀盤點。Phase 3T-1 現在新增有限 Session 設定與提交前 CSRF 更新，
詳見 [Session Lifetime](SESSION_LIFETIME.md)；retention、scheduler、network timeout 與其他安全 budget 不變。
Stable 仍為 v1.7.0。以下根據 app.py、core/、scripts/、shell entrypoints、static/、
templates/ 與依賴設定盤點；生成 bootstrap 與原 source 的重複項合併。
歷史報告時間／測試等待／CI 執行時間不屬於產品使用期限，另外說明於文末。

分類：**A USER-FACING EXPIRATION**（登入／檔案／分享）；**B OPERATIONAL TIMEOUT**
（防止卡死）；**C SECURITY CONTROL**（認證與防濫用）；**D SCHEDULING**（週期與退避）。
同一功能可能同時有 A/C 影響，不得把 B/C/D 任意改成永不逾時。

## A：使用者可感知的有效期

| 項目／設定位置 | 目前預設與用途 | 使用者影響 | 可自訂／永不過期評估 |
| --- | --- | --- | --- |
| Session／Cookie：app.py `PERMANENT_SESSION_LIFETIME`、login、`SESSION_REFRESH_EACH_REQUEST` | 30 天；登入使用 permanent session，每次請求續期。簽章驗證 max age 與 Cookie expiry 由同一 lifetime 控制；没有另外設定的 idle timer。 | 有活動可滑動續期，長期閒置或瀏覽器清 Cookie 需重新登入。auth_version／instance_id 改變、logout、SECRET_KEY 改變仍失效。 | Phase 3T-1：私人 `.env` 可設 SESSION_LIFETIME_DAYS=1–3650，預設30；不合法會停止啟動，Runtime 唯讀顯示生效值。保持有限簽章與撤銷；瀏覽器可能 cap Cookie，不能保證3650天閒置登入。 |
| 本機 Generate 草稿：static/draft.js `TTL`／localStorage | 30 天，自最後 saved_at 計；超時、未來時間、schema 錯誤會移除。沒有 server draft TTL。 | 長久未編輯可能失去未提交資料；草稿含節點 link，不含密碼／CSRF／Cookie，但仍可能敏感。 | 目前 hardcoded。可提議可選較長期限、停用儲存、明確清除；永存須使用者 opt-in 並提示共享瀏覽器風險。 |
| Upload：app.py、core/retention.py `UPLOAD_RETENTION_HOURS` | 1 小時，未設定 hour 時相容 `FILE_RETENTION_DAYS`。按 file mtime 清理。 | 過期暫存上傳會刪除。 | 可設正且有限的小時值；0／負值／invalid 現在 fallback，**不表示永不過期**。未來另設 explicit keep policy 加磁碟管理，不能偷偷重新解釋 0。 |
| Output：`OUTPUT_RETENTION_HOURS`，同上 | 24 小時，legacy `FILE_RETENTION_DAYS`；普通 output mtime 清理。 | 過期生成檔不可再下載；不是 Fixed revision retention。 | 同上；可增加可選持久輸出模式，但須磁碟／secret URL 管理。 |
| 臨時 bearer `/t/`：app.py process／core/temporary_links.py create/resolve/prune | app 使用 OUTPUT_RETENTION_SECONDS；工具 create 預設 86400 秒，expires_at 固定於建立時，不隨下載續期。expire／file revoke 後 permanent tombstone，ID 永不重用。 | 即使清理尚未執行也會 404；改 env 不追溯延長既有 link；檔案 mtime 清理亦可先使 link 不可用。 | 現 schema 要求 finite expires_at > created_at，沒有 never-expire 值。長期共享已有 Fixed；持久 `/t/` 需新契約、撤銷及 output 保留共同設計，不能只停 prune。 |
| UI overlay backup：`BACKUP_RETENTION_HOURS`／`BACKUP_RETENTION_DAYS` | 168 小時／7 天；install.sh 生成 legacy BACKUP_RETENTION_DAYS=7。app 只掃描其 backups/ 普通檔案。 | Web overlay backup 超時會清除。 | 正有限值可配置；同 retention 的 0 fallback。**不是** /root legacy updater/uninstall 備份或新 offline snapshots/catalog 的自動清理。永存需明確容量 policy。 |
| Fixed／source cache：core/fixed_subscriptions.py | 沒有 wall-clock expiry；Fixed bearer、已提交 YAML、Uploaded payload、Remote last-good cache 不受 output retention。 | URL 可長期使用；Disable／Delete／Regenerate／prefix 變更會按契約阻止／撤銷。失敗 refresh 可保留 last-good。 | 已無時間期限；不需修改。orphan revision 在合法管理 mutation 時清理屬 lifecycle，非 TTL；不能為「永存」取消撤銷。 |
| 離線 snapshot／catalog、/root legacy backup、logs、GeoIP MMDB | 沒有自動時間 retention／到期；catalog 的 128 records 等是容量限制。GeoIP uploaded_at、installed_at、backup timestamp 是記錄。 | 操作者管理容量與備份／資料更新；不因時間自行刪除。 | 保持現狀；若未來 retention 需獨立明確授權。MMDB 不自動下載或到期，來源的時效由操作者判斷。 |

## C：安全控制（不能直接取消）

| 項目／位置 | 預設／用途與使用者影響 | 可自訂／永不過期評估 |
| --- | --- | --- |
| CSRF：app.py `CSRFProtect`、Flask-WTF | app 未覆寫 WTF_CSRF_TIME_LIMIT，依賴預設 3600 秒；過期 POST 仍拒絕（Parse／Diff JSON 400、一般表單303 recovery）。Phase 3T-1 在明確操作前透過認證／same-origin GET 取得 fresh token；不是登入 Cookie 失效，Generate 草稿仍可恢復。[Flask-WTF 官方設定](https://flask-wtf.readthedocs.io/en/1.2.x/config/) | 沒有 app env 控制。不使用 None、不 exempt；只有有效 Session 可刷新，無 polling、不 replay 拒絕的 POST。Fixed／Settings 不新增持久瀏覽器草稿，刷新失敗保留目前輸入。 |
| Login limiter：app.py／core/rate_limit.py | LOGIN_MAX_FAILURES=5，LOGIN_WINDOW_SECONDS=600，LOGIN_LOCKOUT_SECONDS=900；固定 lockout，被阻擋請求不延長。返回 429／Retry-After；狀態含有限容量避免繞過。 | 三者可設正整數；不得直接設 0 停用。window／lockout 應保持有限，不屬使用期限。 |
| auth／token 撤銷：core/security.py、Fixed、temporary_links | 密碼只有 non-empty 要求，不設到期或複雜度；周圍空格與 Unicode 保留。auth_version／instance_id、Fixed retired_tokens、temporary tombstone 無時間 GC。 | 已無 password expiry；不能取消 logout／rotation／撤銷。若長期 Session 功能需證明密碼變更仍撤銷舊 Session，退休 bearer 不復活。 |
| State／HTTPS／backup/catalog locks、deployment guard | flock 依 FD 存活，沒有 PID/age expiry；部分 state lock 可 blocking，某些 job admission nonblocking。 | 保持排他性；不可加「超時刪檔」繞過 holder。卡住需有界作業與人工診斷，不是刪 lock。 |

## B：作業界限（保留有界行為）

| 項目／位置 | 目前值／用途與使用者影響 | 配置／取消評估 |
| --- | --- | --- |
| Gunicorn：core/deployment_config.py service_unit | worker timeout=300 秒；卡住 worker 會終止。未另覆寫 graceful_timeout（已核對安裝依賴預設 30 秒）、keepalive（2 秒）；sync worker 的 keepalive 不生效。systemd 主 service stop/start 採系統預設而非 repo 值。 | 不把 worker timeout 當登入期限；需要設定時獨立審 request/worker 資源。系统預設依 host／drop-in，非本輪 VPS 查驗。 |
| Source HTTP／DNS：core/source_fetch.py | connect 5 秒、whole 15 秒（跨至多 3 redirects），DNS 子程序與 socket/read 使用剩餘 deadline。超時保留 last-good、回報 failure。 | 目前 constants，無 UI/env；不能無限，未來可有限配置並保留 SSRF／DNS pinning。 |
| Endpoint：core/node_probe.py | 單節點 3 秒，DNS／connect 共用 deadline。 | 無配置；有限調整須與 whole job／systemd 上限一致，超時不是節點使用到期。 |
| Proxy probe：core/proxy_health.py、templates/settings/_health.html | 預設 8000 ms，合法 3000–15000 ms，全域／單訂閱 override；HTTP status mismatch／timeout 記為 failure。 | 已可有限配置；不能設無限。 |
| Mihomo probe：core/mihomo_probe.py | whole 235 秒、batch 55 秒、startup 5 秒、validation 5 秒；controller readiness/status ≤1 秒，detail ≤2 秒，URL-test ≤probe timeout+2 秒及剩餘 deadline；startup poll 0.1 秒，port bind 至多 5 次。 | constants；保留上限／取消及清理。讀取 thread join 1 秒；terminate/wait 2 秒、已退出 wait 1 秒、kill/wait 2 秒的兜底均是程序清理界限。 |
| Mihomo artifacts：core/mihomo_manager.py | 下載 socket 20 秒、合作式 whole deadline 180 秒；binary -v 子程序 3 秒。 | 非有效期；網路讀可受 socket timeout 影響，不能把合作式 budget 宣稱 syscall 硬中斷。有限配置需整體評估。 |
| Telegram：core/telegram.py、core/notifications.py | whole 5 秒，DNS queue 等待／TLS／socket／read 使用剩餘 deadline，watchdog 關 socket；每 scan 最多一則彙總、沒有持久佇列／auto retry TTL。 | 目前 constants、預設 Off；保留 timeout。外部 provider credential/policy 不由 app 控制，未做 live 驗證。 |
| Remote bootstrap：scripts/remote_lifecycle.py／兩 generated entrypoints | curl connect 10 秒、max-time 120 秒，API/TLS/download failure 停止、無 main fallback。 | 不增加 retry／取消 timeout；本輪 channel／identity 語義不变。 |
| Deploy readiness：scripts/deploy-common.sh wait_for_application | explicit 30 秒，最多 30 嘗試；curl connect/total ≤2 秒且不超剩餘，retry sleep 1 秒，要求 service active、HTTP 200。install.sh optional ipify max-time 3 秒。 | 不屬期限；測試不碰實際 updater，保留 deadline。 |
| Refresh／Health oneshot：scripts/deploy-common.sh | refresh TimeoutStartSec=20min；health 15min、TimeoutStopSec=10s、KillMode=control-group；stop 原時序不變。 | 有界 service life；主機 drop-in 可改但不是 Web 使用期限。不得為永存登入取消。 |
| HTTPS assistant：core/https_manager.py | command default 60 秒，apt update/install 600 秒，Certbot 300 秒；本機 curl connect3/max10，retry2/delay1/retry-max15，outer command40 秒。Nginx proxy connect10s/read300s/send300s。 | B，非登入／TLS憑證到期；不改 Nginx、Certbot 或 timeout。外部 TLS certificate expiry／certbot renewal 為 host/provider lifecycle，未查 production。 |
| Backup Audit：scripts/backup_audit.py | 10 秒合作式 whole budget。超限拒絕，無到期刪除。 | 保留 bounded scan，不能以「取消期限」放寬；blocking kernel IO 不一定由 budget 硬中斷。 |
| Collector：scripts/backup_collect.py | 10 秒合作式 collect/validation/publish budget，另有 entry/depth/bytes 限制。 | 非 snapshot retention；不改既有工具 gate。 |
| Writer／Verifier：scripts/backup_create.py／backup_verify.py | 各 10 秒；Writer whole budget 含既有 verifier calls，Verifier 每次也有其 budget。 | 合作式、不可無限；超限不截斷後宣稱成功。 |
| Catalog：scripts/backup_catalog.py | 30 秒合作式 budget，含至多三次完整 verifier；另有限容量。 | 保留 finite budget；不是 record expiry，不清理歷史 snapshots。 |
| 原 deployment 子程序／state IO | 原 pip、core.migrate、systemctl 及普通 filesystem IO 沒有新增加的 wrapper deadline；新 guard nonblocking admission，持鎖本身無 TTL。 | 盤點指出既有未有界部分，不能宣稱整個 updater 已 bounded。後續有界化是另案，不能改 OFF legacy timing。 |

## D：排程、重試與 freshness

| 項目／位置 | 預設／用途與影響 | 可自訂／取消評估 |
| --- | --- | --- |
| Auto-refresh：core/refresh_schedule.py、auto_refresh.py | Off=None；remote sources 七檔 900/1800/3600/10800/21600/43200/86400 秒。失敗退避 300/900/1800/3600/7200/21600 秒。每輪最多 32 due sources，history 20 筆。 | UI 已可 Off 或七檔；history 是數量非 TTL。不能把 backoff 歸為不必要的資料使用期限。 |
| Auto-health：core/health_schedule.py、auto_health.py | Off/Manual 無 due；Automatic 同七檔間隔／BACKOFF。每輪最多 4 Endpoint、1 Proxy、3 periodic policy reconcile，另最多 1 reactive completion。 | UI 已可選模式與間隔；不關閉 operation timeout。 |
| systemd timers：scripts/deploy-common.sh | refresh/health OnBootSec=2min、OnUnitActiveSec=5min、AccuracySec=30s、RandomizedDelaySec=30s、Persistent=true。 | 掃描 due，不等於每訂閱每5分鐘強制測試。host enablement／drop-in 可管理；本輪不改 policy。 |
| Health-aware Policy：core/health_policy.py | Off，freshness 預設 172800 秒；可選 3600/21600/86400/172800/604800；minimum candidates=2。老 observation 不用於排除，fail-open。 | 已可 Off／選有限freshness；不是刪 Health state 或 node expiry。無限 freshness 會把舊失敗當現在狀態，不能安全直接取消。 |
| Client policy YAML：core/policy_engine.py | 自動 URL-Test/Fallback/Load-Balance interval=300 秒，合法30–86400；Preserve 不新增 probe設定。 | UI 已可有限interval；這是下游客戶端排程，不是 server Session expiry。stock Default 沒有新增 probe interval。 |
| HY2 port hopping：core/parser.py | 只在明確有 ports／hop-interval 時驗證；整數或區間5–86400 秒，无 app 預設。 | 保留使用者值，下游客戶端行為；非帳戶使用期。無 live QUIC／auth／forwarding／hopping acceptance。 |
| Cleanup 掃描：app.py CLEANUP_INTERVAL_HOURS／legacy CLEANUP_INTERVAL_DAYS | 1 小時，marker 節流，startup/request 觸發；不是精確獨立定時刪除。logs／state 不掃描。 | 正有限值可設定；應與A retention分開。取消掃描也不讓 /t/ 到期失效邏輯消失。 |
| UI feedback／草稿 debounce：static/fixed.js、draft.js | Copy URL 顯示2秒；草稿輸入debounce250ms、動態列操作0ms延後保存。 | 純呈現／節流，不撤銷URL、不使草稿／Session 到期；不需修改。 |

## 其他查核與下一階段提案

`static/nodes.js` 的 browser fetch 未另設 AbortController deadline，仍受 server/network
行為影響；GeoIP 是離線 literal-IP lookup，沒有 DNS／下載 timeout 或 cache TTL。
`installed_at`、observation timestamps、updated_at 與 UTC 格式不是自動 expiry。
外部 source／proxy credential 自身有效期不由本 app 延長；未聯絡真實 provider。

Release CLI 的 git／gh 子程序未另设 Python timeout；CI／browser suite 的 subprocess
180秒、測試 doubles 的 timeout、fixture barrier、Playwright wait、GitHub-hosted runner
預設 job 上限等是開發驗證界限，不是部署產品的登入或分享期限。本輪維持全數。

Phase 3T-1 已實作下列第1、2項的有限方案，尚未發布／部署；第3、4項保持提案／既有行為：

1. 新增明確可配置的有限 Session lifetime，先保留預設30天與每請求續期；測試 Cookie
   expiry／server signature max age 同步、restart 保持登入、logout／密碼變更即撤銷。
2. 對閒置頁面的過期 CSRF 提供安全 fresh-token refresh 或保留草稿後重載；維持
   authentication、same-origin 與 finite CSRF，不因希望長期登入關閉 C。
3. 草稿／upload／output／overlay backup 分別設定 policy；若提供 never-expire，需新
   明確選項、schema與expiry UI、磁碟容量／manual revoke語義，保留舊0 fallback契約。
4. 長期 subscription 優先使用已無 TTL 的 Fixed；不要復活 retired bearer、重用 /t/ ID
   或把 scheduler/backoff、Health freshness、network／worker timeout 刪除。

Session／CSRF 開發變更見專用文件；其餘提案尚未實作。沒有部署 production，也沒有縮放或放寬任何 Backup 工具的 security budget。
