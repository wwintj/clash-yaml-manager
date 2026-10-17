# Managed Recovery Package — Phase B

`managed-upgrade-v1` 是**獨立離線格式**，自 v1.9.0 起以開發預覽隨程式碼提供，不是任何版本升級流程的一部分。它不改 Manifest v1、Sidecar、Catalog 或 Legacy Backup；Sidecar 仍預設 OFF。Phase B 只保存材料及驗證 bytes，不停止服務、不升級、不 Restore、不刪除、不啟用 Retention。

## 操作者與來源契約

只接受操作者明確準備的 root-private `0700` **離線 fixture**。來源不得為 `/opt/clash-yaml-manager`，工具不搜尋安裝目錄。`capture.json` 為 root-owned `0600` canonical JSON，必須明確 `offline_quiet=true`。此聲明不是 systemd quiet gate，也不是原子 snapshot；來源盤點、每檔 metadata 與內容重讀不能證明全部 runtime 一致性。

CLI 固定 root UID/GID 0，固定 `/var/lib/clash-yaml-manager-upgrade-backups/{packages,records}`；父目錄必須已存在且安全。所有祖先 no-follow，拒絕不可信 owner、可寫祖先（root-owned sticky 臨時祖先除外）；受管目錄 `0700`，普通檔案 `0600`。沒有環境變數、CLI 管理路徑／UID override。Mac 測試只由可信 Python fixture monkeypatch 內部常數，不能從來源配置降低儲存安全限制。

不提供從 live 安裝自動建立 fixture 的命令。未來控制器在部署副作用前捕獲失敗，必須恢復並核驗原 service/timer policy；目前沒有控制器或 systemd 操作。

```bash
# 僅限事先準備、已停止寫入的合成離線來源，並以可信已安裝工具執行
sudo python3 -m scripts.recovery_package create --source /private/offline-fixture
sudo python3 -m scripts.recovery_package verify --operation-id <32-lowercase-hex>
```

## 固定來源 layout 與範圍

| Root / role | 必需 | 可選 / 允許 |
|---|---|---|
| `application` / APPLICATION | `app.py`, `VERSION`, `INSTALLATION.json`, `requirements.txt`；`core`, `scripts`, `templates`, `static` 目錄 | 四個子樹的普通檔案及目錄；現有七個頂層 lifecycle `.sh` 名稱 |
| `venv` / VENV | `pyvenv.cfg`, `bin`, `bin/python`, `bin/python3` | 有界 venv 普通檔案／目錄，以及受驗證的 link metadata |
| `configuration` / CONFIGURATION | `.env`, `.service-account`（內容只允許 `clashyaml` 及可選換行） | 無其他路徑 |
| `default` / DEFAULT | `default.yaml` | 無其他路徑 |
| `units` / UNITS | `clash-yaml-manager.service` | refresh／health 的 service 與 timer 固定四個名稱 |
| `state` / STATE | `auth.json` | 固定 JSON allowlist、Fixed revision／source cache grammar、GeoIP `active.mmdb`；`.last_cleanup` |

State path grammar 複用既有 Collector 的唯讀 path policy，但**不修改其安全契約**。只有其 `selected=true` 路徑可捕獲；auth、fixed_subscriptions、node_health、proxy_health、settings、notifications、temporary_links、login_attempts JSON bytes 保存，業務 schema／關聯完整性尚未評估。lock、ephemeral candidate、未知 state、其他未知 root **拒絕**，不靜默略過。`.last_cleanup` 是明確的新格式 marker；不能用它當升級完成時間或直接重建 cleanup policy。

根目錄只有上述六個 root 與 `capture.json`；沒有任意 exclusions。來源必須由操作者依此 scope 準備。來源同 filesystem；regular file nlink 必須為 1，拒絕 FIFO、socket、device。所有配置、程式、state、unit symlink 拒絕。一般來源 mode 不允許 setuid/setgid/sticky 或 group/other write；link 的原始 mode 例外只作 metadata。所有 root 與非 state 材料要求可信 root owner；state 可為 root 或明確 `clashyaml` role 的 UID/GID 組合。

`capture.json` declaration 必需欄位：`source_identity`, `target_identity`, `installation_binding`, `account_roles`, `runtime_requirements`, `offline_quiet`。來源／目標 identity 為 `{version,channel,commit,tag}`，channel 為 stable/main，commit 為 40 位小寫 hex；Stable tag 必須與 version 相符。來源 VERSION／INSTALLATION.json bytes 再核對來源 identity，保留 installed_at 與 source 一致性。這些只是離線身份綁定，沒有查詢 GitHub 或驗證 Release 簽章。

Installation binding 為 `{origin:ROOT_OPERATOR_DECLARATION,install_path,system_id}`。account_roles 的 root/service 均為 `{name,uid,gid,origin:ROOT_OPERATOR_DECLARATION}`，名稱分別 root/clashyaml，service UID/GID 不可等於 root。只有受信任 root declaration 授權混合 owner；不是因 root 能讀便接納任意 ownership。UID/GID 是操作者聲明，不是本機 account database 驗證，亦不自動建立／恢復帳戶。

Runtime requirements 為 `{os,architecture,python_version,python_abi,system_libraries,origin:ROOT_OPERATOR_DECLARATION}`；libraries 最多 64 個、每個 bounded string。Runtime 與原 system_id 是聲明；目前不執行 ABI／library 相容性檢查。

## Manifest / canonical 格式

固定欄位在 `scripts/recovery_manifest.py` 定義，unknown／missing field 與 duplicate JSON key 一律拒絕。`format_version=1` **屬新 profile，與 Sidecar Manifest v1 無關**。另含 profile、operation_id、上述五組 declaration、capture_interval、capture_evidence、roots、entries、omissions、retention、restore_proven。

Canonical bytes：UTF-8 的 ASCII subset、`json.dumps(sort_keys=True,ensure_ascii=True,allow_nan=False,separators=(',',':'))`，無空白或尾端換行。負例包含 duplicate key、NaN、非 canonical whitespace、unknown field。Manifest 先 parse／schema，再比獨立 digest，再驗證所有 Blob；schema 合法的 canonical 篡改仍須得到 digest mismatch。

Entries 依 path UTF-8 bytes 升冪，無重複；輸入 path 必須已為相對 component，拒絕絕對、空 component、`.`、`..`、backslash、控制字元，**不正規化後接受**。祖先 entry 必須存在且為 directory；所有 root 必須存在。每個 entry 固定 `{path,role,kind,original,blob,size,sha256,link_target,link_type}`。`original` 固定 `{mode,uid,gid,mtime_ns,metadata_origin:OBSERVED_OFFLINE_FIXTURE}`，mode 為四位 octal、UID/GID/mtime 為非負整數。只代表實際離線 fixture，不冒充原 production filesystem metadata。

Regular file 的 Blob 是 entry index 對應八位 decimal 名稱，size 為實際 byte count，sha256 為所有 bytes 的 64 位小寫 hex digest。directory／symlink 無 Blob、size=0、sha256=null；directory 的 link 欄位亦 null。Package 只有 `manifest.json` 與 `blobs/`；Blob 必須完整、精確對應 entries，不接受多餘、缺失、symlink 或 hardlink payload。原始 executable mode 與 Blob 的 `0600` 分開保存，**不自動 restore 原始 UID/GID 或認證狀態**。

capture_interval 為有 timezone 的 started_at/ended_at，順序必須合法。capture_evidence 保存 observed source device/inode、`source_reinventoried=true`、`offline_quiet=OPERATOR_DECLARED`、`consistency=NOT_ATOMIC_SNAPSHOT`、外部 Python link dependencies，以及 `extended_metadata=NOT_CAPTURED_RESTORE_UNSUPPORTED`。

## venv link 與未支持的 metadata

只在 venv scope 記錄 symlink 的原始 target，不跟隨、不複製 target bytes、不在 Package 建立實際 link。內部相對 link 必須解析至存在的 venv entry，拒絕 escape、cycle、缺失目標及非目錄中間節點；解析本身有 depth 上限。相對 target 可含 `..`，但不得離開 venv。

外部 absolute target 僅限 `venv/bin/python`、`python3`、`python3.N` interpreter links，且 target 為 `/usr/bin/python3[.N]` 或 `/usr/local/bin/python3[.N]`。解析鏈的每個外部依賴都固定寫入 external_python_links，**不檢查／讀取主機 target**。不支持其他 external link；ABI、存在性與可執行性留 Phase C。

ACL、xattr、capabilities 未捕獲，所有 Package 明確 `NOT_CAPTURED_RESTORE_UNSUPPORTED`，omissions 同時寫入對應限制。不得宣稱 POSIX mode 足以完整重建 filesystem metadata；即使 fixture 沒有擴充 metadata，Phase B 也不將其標為 restore-ready。

## Writer、external record 與失敗邊界

使用 descriptor-relative no-follow IO、跨 filesystem 拒絕、有界 streaming SHA-256、來源首次盤點／複製後重讀／再盤點、root pathname 重綁核對。除讀取可能改變 atime，來源內容／權限不修改。這些防變更檢查不是原子 filesystem snapshot。

隨機 128-bit operation ID；private `.stage-<id>` 位於 packages。每檔及 Blob／Package directory fsync，Manifest schema 與內容完整性核驗後，使用 Linux `renameat2(RENAME_NOREPLACE)`／Darwin `renameatx_np(RENAME_EXCL)`。缺失／不支持必要原語即拒絕，沒有 ordinary rename fallback。發布後 parent fsync、inode/device 和內容再驗證。

外部 `records/<id>.json` 經私人獨立 staging、fsync、no-replace 及身份檢查，保存 Writer 在發布前計算並驗證的 Manifest digest、package inode/device、operation/source/target/installation binding。Verifier 從受保護 record 取得 anchor，**不從待驗 Package 重算 anchor**。Record 只代表同機 root-private digest handoff，不是異地 DR、惡意 root 防護或簽名發布 provenance。

沒有 cleanup／delete 程式。失敗保留本輪私人 staging 或已發布的 Package/record；碰撞物件完全不改動，殘留不能自動註冊為可信。publication 欄位區分 NOT_STARTED、STAGING、UNCERTAIN_UNTIL_DURABLE_IDENTITY_CHECK、PACKAGE_DURABLE、PACKAGE_AND_RECORD_DURABLE。rename 成功後 fsync／record 失敗可能已產生部分物件，不能把它當整個操作成功；同一 ID 重試亦不能覆蓋。Interrupted staging 保留，不自動續作或掃除。沒有 cleanup failure 的刪除路徑；測試注入拒絕 unlink，證明不會呼叫它。

## 基礎 Verifier 與資源限制

Verifier 唯讀，絕不 import 備份模組、執行 Python、啟動 backup venv、source `.env` 或印出被檢視 bytes／路徑／秘密。成功分別報 `STRUCTURAL_VALID`, `CONTENT_INTEGRITY_VALID`, `PACKAGE_VERIFIED`, `TRUST_ANCHOR_VERIFIED`；Writer 額外報 `PACKAGE_CREATED`。失敗保守不回報驗證成功。固定 `RECOVERY_REQUIREMENTS_NOT_EVALUATED=true`, `RESTORE_PROVEN=false`，**沒有 UPGRADE_SUCCEEDED**。stdout 僅 bounded JSON 狀態、safe codes、operation ID 與 digest。

初始保守限制：4096 entries、depth 16、path/link 1024 UTF-8 bytes、per-file 128 MiB、total file bytes 512 MiB、Manifest 8 MiB、control 16 KiB、record 32 KiB；stream chunk 64 KiB。每個操作 cooperative 60 秒、read bytes 至多 `8×512 MiB + 4×8 MiB`。超限拒絕，不截斷回報成功；不是 production 大型 venv 容量資格證明。

Omissions 明確排除 Nginx、TLS、UFW、OS packages、external accounts、Mihomo、uploads/outputs、Web backups/logs、off-host backups、volatile locks 及擴充 filesystem metadata。這不是完整 VPS snapshot；捕獲 state 不授權覆蓋 live state，初版恢復仍需預設保留 live state。

## Retention metadata 與下一階段

只保存 `policy=strict,keep_count=1,hours=72,completed_at=null`。數量輪換與到期是獨立條件：未來全升級成功後可輪換未滿 72 小時的舊成功備份；成功備份到期後即使唯一一份也可刪除。失敗、未完成、不確定、busy／驗證異常保護。Writer 不建立整體升級完成事件，故不能起算 72 小時；journal、trash、prune timer、Restore Apply **均未實作**。

Phase C（[唯讀檢視](RECOVERY_INSPECTION.md)）與 Phase D2（[相容性評估](RECOVERY_ASSESSMENT.md)）自 v1.9.0 起以開發預覽提供，但業務 state semantics／跨材料一致性、ABI/system dependencies 實證、recovery-ready 與 Linux root-native 正式驗收仍未完成；後續控制器、Restore／Retention 實作均未授權。Mac 的合成 POSIX 成功不能代表 production、Linux-native destructive features 或 Restore 已證明。歷史 macOS Verifier 差異繼續 `ROOT_CAUSE_UNKNOWN`。
