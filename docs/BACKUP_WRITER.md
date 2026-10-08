# Offline Verified Snapshot Writer

v1.8.0 Phase 3B 開發功能，尚未發布；Latest Stable 保持 v1.7.0。
`scripts/backup_create.py` 是獨立的 stdlib CLI，只從操作者明確指定、已停止寫入的
離線目錄建立全新 snapshot。本 Phase 僅在隔離合成 fixtures 執行，沒有 production
updater 整合、SSH、部署、restore、state／authentication migration 或自動回滾。

## 使用與來源

在開發版本原始碼中執行；下列路徑是操作者準備的離線資料與私人備份 parent：

```bash
python3 scripts/backup_create.py \
  --source /path/to/quiet-offline-source \
  --destination /path/to/private-parent/new-snapshot \
  --snapshot-type UPDATER_SNAPSHOT --json

# 若來源含無法完整複製的 venv，必須明確排除。
python3 scripts/backup_create.py \
  --source /path/to/quiet-offline-source \
  --destination /path/to/private-parent/another-new-snapshot \
  --snapshot-type UPDATER_SNAPSHOT \
  --exclude venv VENV_NOT_VERIFIED --json
```

`--source`、`--destination`、`--snapshot-type` 都是必要參數。Snapshot type 可為
`UPDATER_SNAPSHOT`、`UNINSTALL_DATA_SNAPSHOT` 或 `UI_OVERLAY_BACKUP`；它只宣告用途，
不保證來源具有該類型的部署元件、有效業務 schema 或可啟動的應用。

來源及所有被盤點的目錄必須由執行者的 numeric UID 擁有，且不能讓 group／other
寫入。Writer 不停止任何 writers，也不自動搜尋 production；來源已 quiet 是操作者
必須先成立的條件。它拒絕已知 `/opt/clash-yaml-manager` 及子路徑；其他自訂 live
位置仍必須由操作者避免。禁止 source 為 `/` 或 destination parent 位於 source 內。
含既有根 `BACKUP_MANIFEST.json` 的來源會拒絕，不能用此工具改寫歷史清單。

路徑及所有祖先必須是實體目錄，拒絕 lexical `..`、symlink、FIFO、socket、device、
普通檔案 hardlink、來源內跨 filesystem 的物件與不符合 Manifest v1 的 entry paths。
macOS 請使用 `/private/tmp`，不要經由 symlink `/tmp` 或 `/var`。
每一層採 directory fd 與 `O_NOFOLLOW`／`O_NONBLOCK`，開啟前後核對 fingerprint；
複製後及發布前重新盤點來源，核對 inode、device、mode、owner、link count、size、
mtime／ctime 和根路徑。可偵測的並發新增、刪除、替換或修改均 fail closed。
來源只讀取 bytes，不 import／執行其 Python、shell、unit 或 `.env`；OS 可能更新 atime。

這不是原子 filesystem snapshot，也不是來源 provenance、惡意系統權限 writer、
bind mount 或遠端 filesystem 的安全保證。ACL、xattrs、capabilities、SELinux labels、
timestamps 與原帳戶映射不在這個 copy／manifest metadata 契約內。

## Exclusions 與 stored metadata

`--exclude PATH REASON` 可重複；PATH 必須是實際存在的普通目錄，REASON 必須為
`VENV_NOT_VERIFIED`、`EPHEMERAL_RUNTIME` 或 `OUT_OF_SCOPE`。重複、互相包含、缺失
或非目錄 exclusion 均拒絕。Writer 保留其**空目錄根**，不讀取、不複製內部 payload；
因此排除的 venv **沒有被保存**，不能當作已備份或已驗證的環境。
沒有 exclusion 時 venv 與其他目錄一樣完整檢查，其內 symlink 會使建立失敗。

有 exclusions 使用 `DECLARED_EXCLUSIONS`，verifier 的 `full_file_coverage=false`。
沒有 exclusions 才使用 `FULL_TREE`，完整覆蓋明確提供的輸入樹；這不表示整台 VPS、
應用依賴、業務關聯或所有 OS metadata 都已收集。

Stored root 與所有目錄固定 `0700`，普通檔案與 control file 固定 `0600`。
不保留來源的 owner／mode；manifest 記錄建立後實際的 numeric UID／GID 和 permissions。
檔案先以 chunk 串流複製，再重讀 staging bytes 並與複製 digest 核對；manifest 記錄
實際 stored size／SHA-256。空檔案及空目錄皆保留；directory size／hash 為 `null`。
Canonical bytes 一律使用既有 `backup_manifest.canonical_bytes()`。

## 私人 staging 與原子發布

Destination 必須不存在，包括既有空目錄、檔案或 symlink 都不能覆蓋／合併。
其 parent 必須已存在、由執行者擁有且 mode 恰為 `0700`；工具不自動建立或修復 parent。
所有寫入透過已開啟的 parent／staging directory fd，不靠可被替換的字串路徑寫入。

流程為：

1. 在同一 parent 建立隨機 `.backup-create-<32 hex>` staging，mode `0700`。
2. 用 exclusive no-follow create 複製範圍內檔案／目錄，完成來源與 stored-byte 檢查。
3. 寫入 canonical `BACKUP_MANIFEST.json`。使用無 buffer 的 `os.write`，核對短寫入，
   `fsync` 所有普通檔案、control file、由內而外的目錄及 parent。
4. 呼叫**既有實際 verifier**；必須為 `INTERNALLY_CONSISTENT` 且
   `file_hash_match=true`、`declared_scope_verified=true`，否則不發布。
5. 重查來源、parent 與 staging 身份，使用 Linux `renameat2(RENAME_NOREPLACE)` 或
   macOS `renameatx_np(RENAME_EXCL)` 原子發布。不退回可覆蓋空目錄的普通 POSIX rename。
   介面／filesystem 不支援時失敗；目的地在競態中出現也失敗，保留既有物件。
6. 再 `fsync` parent，核對 published root／control 身份，並再次執行完整 verifier。
   成功才回報 `creation_status=CREATED` 與 `MANIFEST_SHA256`。

Atomic 指完成的 staging 名稱在同一 filesystem 的一次 no-replace rename 中出現。
`fsync` 失敗不回報成功；不保證超出 OS／filesystem 契約的斷電或硬體故障恢復，
也不聲稱抵抗同 UID 或系統權限的惡意 concurrent writer。

## 結果、清理及失敗處理

| 結果 | 行為 |
| --- | --- |
| `CREATED`／`PUBLISHED` | 已完成前後驗證。Exit 0；仍無 external anchor、restore 未驗證。 |
| `FAILED`／`NOT_PUBLISHED` | Exit 1；沒有發布成功結果。可建立 staging 的失敗會嘗試清理。 |
| `cleanup_status=CLEANED` | 已刪除本次可核對 inode 的 staging 項目及根；其他目錄不動。 |
| `cleanup_status=FAILED` | 固定 `CLEANUP_FAILED`，`residual_staging_name` 提供安全的自建隨機 basename；不能聲稱已無殘留。 |
| `FAILED`／`PUBLISHED` | Rename 已完成，但後續 fsync／身份／驗證失敗。`retained_destination=true`、`NOT_ATTEMPTED_PUBLISHED`，保留目的地供人工隔離檢查，不當作 verified 成品。 |
| `FAILED`／`UNCERTAIN` | 失敗後無法確認目的地身份；`NOT_ATTEMPTED_UNCERTAIN`、`retained_destination=true`，也回報可能殘留的 staging basename，需檢查 parent 與目的地。 |
| 命令列錯誤 | Exit 64，固定 `INVALID_ARGUMENTS`，不回顯參數。 |

清理只使用本次建立的 bounded inode ledger，逐層 no-follow 核對目錄／檔案身份。
不使用任意 `rmtree`；陌生新增物件、遺失／被替換的 inode 或 cleanup 中斷會保守報告
失敗，不能刪除替換物或其他備份。若名稱被外部 writer 移動／替換，已知 basename
未必仍指向原 staging；需人工核查私人 parent，不能盲目 `rm -rf` 該名稱。
重試必須另選不存在的 destination；不得覆寫先前備份或把未確認成品當作已成功。

輸出只包含固定狀態／codes、boolean、既有 verifier 報告、成功的 manifest digest
及必要時的隨機 staging basename；不輸出 source／destination 原始路徑、任意檔名、
內容、密碼、token、bearer URL 或原始 exception。Standalone CLI 不建立 pycache。

## 資源與 trust anchor handoff

沿用 verifier 上限：4,096 個物件（含 root 和 control，最多 4,094 entries）、
12 分段、1,024 UTF-8 bytes entry path、2 MiB manifest、128 MiB 單檔、512 MiB
範圍內檔案 bytes **加 control bytes**。每次 hash／copy 最多 64 KiB chunk。
Writer 整個流程採 10 秒合作式預算，包含重讀與 verifier；verifier 也保留自己的
10 秒／讀取預算。達到任一限制都失敗，不截斷／漏檔後宣稱成功。
這是合作式檢查，不是 kernel syscall 硬逾時；cleanup 是 bounded 恢復操作，
不因原時間預算已耗盡而直接略過。大型樹可能較早因重讀耗時失敗。

`MANIFEST_SHA256` 是 SHA-256(canonical manifest bytes)，**writer 輸出不是自動可信 anchor**。
操作者必須在建立時把它獨立保存到受保護、與可修改 snapshot 分離的位置，保護其
來源與生命週期，才可向 verifier 明確提供 `--trusted-manifest-sha256`：

```bash
python3 scripts/backup_verify.py --path /path/to/private-parent/new-snapshot --json
python3 scripts/backup_verify.py --path /path/to/private-parent/new-snapshot \
  --trusted-manifest-sha256 "$BACKUP_TRUSTED_MANIFEST_SHA256" --json
```

Writer 不建立 trust store，不在同 snapshot 內寫 checksum 當作 anchor，所有結果固定
`trust_anchor_verified=false`、`restore_proven=false`。成功只證明 declared scope 的檔案
一致性；另提供獨立 anchor 後的 `TRUSTED_SCOPE_VERIFIED` 仍不等於 restore test passed。
測試中的獨立 digest 檔案僅模擬 handoff，沒有建立 production trust anchor。
真正 restore／啟動／依賴／認證與 Fixed／Health 業務驗收都要另行授權。

## Legacy 相容性

既有 `update.sh`、`uninstall.sh`、`scripts/deploy-common.sh`、備份格式及歷史備份
完全不變。舊備份使用 [Phase 2 結構 audit](BACKUP_READINESS.md)，新 Manifest v1
snapshot 使用 [既有 verifier](BACKUP_MANIFEST_V1.md)；舊 CLI 不自動辨識新格式。
