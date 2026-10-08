# Backup Audit & Restore Readiness

v1.8.0 Phase 2 開發功能，尚未發布；Latest Stable 保持 v1.7.0。
`scripts/backup_audit.py` 使用 Python 標準函式庫，只讀檢查指定的本機備份。
它不建立備份、不修改備份格式，也不恢復任何資料。

v1.8.0 Phase 3A 另提供 [Manifest v1 離線 verifier](BACKUP_MANIFEST_V1.md)，
只驗證有清單的合成離線 fixture，區分 file hashes、manifest digest 與操作者
提供的外部 trust anchor。未整合至 updater／uninstall，也不替歷史備份補寫
manifest；本頁的 Phase 2 結構檢查行為保持不變，所有工具仍是 `restore_proven=false`。

## 既有備份契約

本輪已審閱 `update.sh`、`uninstall.sh`、`scripts/deploy-common.sh`、
`core/state.py`、[認證與遷移契約](PHASE2.md#e-migration)及
[版本回滾邊界](RELEASE.md#downgrade-and-rollback)。這些既有實作維持不變。

| 類型 | 既有結構與時間點 | 一致性及恢復限制 |
| --- | --- | --- |
| `UPDATER_SNAPSHOT` | `/root/clash-yaml-manager-update-backup-YYYYmmdd_HHMMSS.XXXXXX`。先以 `cp -a` 保存存在的 VERSION、INSTALLATION.json、HTTPS_DEPLOYMENT.json、app.py、requirements、core、templates、static、部署腳本／scripts、venv、帳戶標記、五個 systemd unit、`.env` 與 `defaults/default.yaml`。接著更新現有 venv 依賴，停止 refresh／health writers 與應用程式，才保存既有 state。 | 程式、設定與 state 的複製時間不同，沒有整份備份的原子發布或可信 manifest。未保存安裝中的 uploads／outputs／backups／logs，升級會保留那些目錄。venv 複本不代表可以搬移或執行；沒有自動完整回滾。 |
| `UNINSTALL_DATA_SNAPSHOT` | `/root/clash-yaml-manager-backup-YYYYmmdd_HHMMSS`。使用者選擇刪除應用並保留資料時，在停止／禁用服務及 writers、移除 unit 後，複製存在的 backups、outputs、state、`.env`、VERSION、INSTALLATION.json 與 HTTPS_DEPLOYMENT.json，再歸 root 所有、收緊權限。 | 只有資料及識別／設定，不含應用程式、venv 或原 unit；不能單獨重建完整安裝。不存在的項目會被略過。HTTPS 卸載清理可能已先執行；metadata 不證明外部 Nginx 設定仍存在。 |
| `UI_OVERLAY_BACKUP` | 已知 UI 驗收命名：`clash-yaml-manager-vX.Y[.Z]-ui-acceptance-YYYYmmdd-HHMMSS`。本輪接受 VERSION、可選 INSTALLATION.json／baseline.json、`templates/index.html` 及 `static/ui.css` 的介面備份形狀。 | 手動建立的局部覆蓋備份，只能提供那些介面檔案的恢復材料；沒有 state、`.env`、完整程式或部署環境。baseline.json 不作可信 manifest 使用。 |
| `UNKNOWN` | 名稱或結構無法可靠對應上述契約，包括其他 manual／production／Default migration 備份、改名後的備份、混合資料與程式的卸載目錄、空目錄。 | 不猜測用途，不讀取內部檔案內容，也不遞迴檢查。不代表資料損壞或安全。 |

已知名稱只協助識別備份的預期用途，不能證明來源真實。
Updater 還必須具有程式／版本／設定／state 的已知外層項目，且不能混入
outputs／backups；uninstall 和 UI 備份的外層項目必須符合各自允許的集合。
不能把所有 `/root` 備份視為完整 updater 備份。

`backup_private_state` 在 updater 停止 writers 後、認證遷移之前，以 `cp -a`
保存 state 中的項目，包含隱藏項目，但排除 `.proxy-probe-*` 敏感暫存目錄。
Uninstall 也在停止 writers 後使用此 helper。Helper 不產生 manifest、不驗證
業務 schema，也不保證外部／手動 writer 已停止；CLI 無法從結果重建當時時序。

## 使用方式

在開發版本原始碼內執行，指向已完成且不再寫入的本機備份：

```bash
python3 scripts/backup_audit.py --path /path/to/backup
python3 scripts/backup_audit.py --path /path/to/backup --json
```

不需要 Flask、PyYAML 或額外 dependencies；支援具備 descriptor-relative open、
`O_NOFOLLOW`、`O_NONBLOCK` 等必要介面的 Linux／macOS 本機檔案系統。
請使用實體路徑，路徑本身及祖先均不能是 symlink；例如 macOS 的 `/tmp`
通常是連結，應使用 `/private/tmp`。不得指向正在運行的安裝或 live state。
工具直接拒絕 `/opt/clash-yaml-manager` 及其子路徑；任意其他位置是否正在
被程式使用，必須由操作者確認。CLI 不連線 VPS，也不呼叫 systemd 或網路服務。

兩種輸出只含固定備份類型、結構狀態、元件分類、數量和 validation codes。
不輸出輸入路徑、任意檔名、版本／識別值、雜湊或解析內容；錯誤也不輸出原始
exception 或命令列參數。`--json` 可供其他唯讀工具解析。

| 結構狀態 | exit code | 意義 |
| --- | --- | --- |
| `STRUCTURALLY_COMPLETE` | 0 | 符合該類型的最低結構判準，已檢查項目未發現失敗。 |
| `STRUCTURALLY_INCOMPLETE` | 1 | 缺少 required、存在但檢查失敗、無法讀取，或達到資源限制。 |
| `UNSAFE` | 2 | 發現不安全物件／路徑、跨 filesystem 遞迴，或檢查期間發生可偵測的變更。 |
| `UNKNOWN` | 3 | 無法識別用途，或無法完成辨識。 |
| 命令列用法錯誤 | 64 | 固定 `INVALID_ARGUMENTS`，不回顯參數。 |

所有結果都包含 `restore_proven=false`。結構完整不等於真正可恢復；本工具
不能宣稱 cryptographic verification、fully restorable 或 restore test passed。

## 元件判準

`requirement` 與 `status` 分開呈現。`REQUIRED` 是本工具的最低檢查 profile，
不是保證歷史 writer 一定複製了該項；legacy 備份可能不符合此 profile。
缺少 optional 只標為 `MISSING`／`MISSING_OPTIONAL`，不令整份備份失敗。
已存在的 optional 若損壞或不安全，仍會影響結果，不能因 optional 而忽略。

| 元件 | Updater | Uninstall data | UI overlay |
| --- | --- | --- | --- |
| VERSION | REQUIRED | OPTIONAL | REQUIRED |
| INSTALLATION.json | OPTIONAL（legacy 可能沒有） | OPTIONAL | OPTIONAL |
| `.env` | REQUIRED | REQUIRED | NOT_APPLICABLE |
| defaults/default.yaml | REQUIRED | NOT_APPLICABLE | NOT_APPLICABLE |
| app.py／core | REQUIRED | NOT_APPLICABLE | NOT_APPLICABLE |
| templates／index.html、static／ui.css | REQUIRED | NOT_APPLICABLE | REQUIRED |
| state | REQUIRED | REQUIRED | NOT_APPLICABLE |
| app service unit | REQUIRED | NOT_APPLICABLE | NOT_APPLICABLE |
| refresh／health service + timer | OPTIONAL（legacy 可能沒有） | NOT_APPLICABLE | NOT_APPLICABLE |
| requirements.txt | REQUIRED | NOT_APPLICABLE | NOT_APPLICABLE |
| venv、scripts | OPTIONAL | NOT_APPLICABLE | NOT_APPLICABLE |
| HTTPS_DEPLOYMENT.json | OPTIONAL | OPTIONAL | NOT_APPLICABLE |
| outputs、backups | NOT_APPLICABLE | OPTIONAL | NOT_APPLICABLE |

此 profile 要求 state 中至少有一份可解析 JSON，以及 core 中至少有一份
可解析 Python；空 state、只有 lock 的 state 或空 core 不會通過。
不逐項要求所有可能的業務檔案。VERSION 為嚴格三段版本；INSTALLATION.json
檢查既有六欄位 schema、channel／source／tag／commit 格式、帶時區時間及
與存在且有效 VERSION 的一致性，但不驗證 GitHub 來源真實性。

state 與 HTTPS metadata 的 JSON 只檢查有界 UTF-8／JSON 語法，拒絕重複 key
及非標準 NaN／Infinity；不驗證任意 state 的業務 schema、認證有效性、
Fixed revision／retired token／輸出檔案之間的關聯。
app.py／core 的 Python 只解析語法，絕不 import 或執行備份中的程式。
unit 只檢查 `[Unit]` 與 `[Service]`／`[Timer]` section，未做 systemd 語義驗證。

`.env`、Default YAML、介面入口和 requirements 只檢查非空 UTF-8，並標示
`CONTENT_SEMANTICS_NOT_CHECKED`；沒有評估設定、解析 YAML 或檢查依賴是否可用。
其他安全普通檔案只盤點 metadata，`CONTENTS_NOT_INSPECTED` 表示未讀取內容。
因此 `PRESENT` 不代表有效業務資料，必須同時閱讀 validation codes。
venv 只檢查外層為真實目錄，標示 `VENV_CONTENTS_NOT_INSPECTED`，連內容數量都
不盤點；正常 Python symlink 不會被盲目遞迴或讀到備份外。

## 唯讀與安全邊界

CLI 不引用 `core.state`、store 或初始化 helper，不建目錄／lock／pycache／manifest，
不 chmod／chown／刪除／恢復，不停止服務、改 timer 或觸發 Health。測試使用
`tmp_path` 合成資料，核對執行前後 bytes 與非 atime metadata 一致。
讀取或列目錄可能由作業系統更新 atime；工具不修改它，也不將 atime 變動判作損壞。

逐層使用 directory fd 和 no-follow open，先檢查物件類型，再做有界普通檔案
讀取；不開啟 FIFO、device、socket 或其他特殊物件，不跟隨任何受檢查的
symlink（包含 broken link），並拒絕普通檔案 hardlink，避免讀到其他位置共享的 inode。
除了明確排除的 venv 內容，已辨識備份中的額外項目也會作 metadata 安全掃描。
已知 file 位置若是 directory，也直接拒絕，不遞迴它。

限制為每輪最多 4,096 個物件（含根）、12 層遞迴、單一內容檔案 1 MiB、
合計內容讀取 16 MiB；路徑最多 4,096 bytes／64 個分段。
10 秒合作式時間預算在掃描、讀取 chunk 與最後掃描時檢查；超限保守失敗，
不能把截斷結果報為完整。JSON／Python 解析及 kernel syscall 無法在這個
合作式預算中硬中斷；不支援以此工具保證網路／惡意檔案系統的硬逾時。

開啟前後核對 inode／device／mode／owner／link count／size／mtime／ctime，
結束時重新盤點及核對根路徑，以偵測讀取中覆寫、替換、改名或新增／刪除。
這不是原子 filesystem snapshot，不能保證抵抗具有系統權限的惡意 concurrent
writer、bind mount 或 filesystem 故障；請只檢查不再寫入的受保護本機備份。
觸發變更時回報 `BACKUP_CHANGED`／`UNSAFE`，不自動修復或取得會寫入檔案的 lock。

## 真正恢復驗證及未來 manifest

目前沒有可信的原始清單／雜湊，不能證明任意普通檔案內容與備份建立當時相同，
也不能證明所有當時存在的 optional／業務檔案都被收集。
Updater 的分階段複製、uninstall 的資料範圍與 UI 局部覆蓋必須分別理解。
真正恢復需另行授權，在隔離環境確認版本與 state 相容、依賴、unit、權限、
固定密鑰及資料關聯，並測試啟動與業務行為；本 Phase 未做這些操作。
恢復舊 auth state 可能恢復舊密碼／版本並令舊 session 再次有效；不能盲目覆蓋最新 state。

Phase 3A 已定義 Manifest v1 schema／canonical bytes 和獨立離線 verifier；
真正 writer 與一致性收集流程仍未實作。未來若修改備份 writer，可在 writers 已 quiet 的一致性邊界建立有版本的 manifest，
記錄檔案集合、bytes 雜湊、必要 metadata、應用識別與備份範圍，原子發布完成標記，
並將簽章／可信 digest 放在受保護的外部 trust anchor。Verifier 必須有界解析、
拒絕 traversal／重複項目、驗證信任來源，再做獨立的隔離恢復測試。
不能事後替舊備份產生 manifest，然後把它稱為原始可信校驗資料。
本 Phase 沒有修改 writer、加入 manifest、實作 restore 或操作 production。
