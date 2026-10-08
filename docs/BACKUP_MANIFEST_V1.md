# Backup Manifest v1 — Offline Verification Protocol

v1.8.0 Phase 3A／3B 開發功能，尚未發布；Latest Stable 保持 v1.7.0。
Phase 3A 提供獨立 protocol、[JSON Schema](../schemas/backup-manifest-v1.schema.json)
及離線 verifier；Phase 3B 新增 [Offline Verified Snapshot Writer](BACKUP_WRITER.md)，
僅在隔離合成 fixtures 驗證。沒有 production backup writer、restore 或 updater 整合。
所有結果固定 `restore_proven=false`。

## Schema 與範圍

備份根中的 control file 固定為 `BACKUP_MANIFEST.json`。
`scripts/backup_manifest.py` 與本文件共同定義完整規範；JSON Schema 描述物件
結構，路徑規範化、唯一性、階層、排序及確切序列化仍須由 protocol 驗證。
不接受未知欄位、重複 JSON key、NaN／Infinity 或不支援的 schema version。

| 欄位 | v1 契約 |
| --- | --- |
| `schema_version` | 必須是 integer `1`；boolean、浮點、字串均拒絕。 |
| `snapshot_type` | `UPDATER_SNAPSHOT`、`UNINSTALL_DATA_SNAPSHOT` 或 `UI_OVERLAY_BACKUP`。這是清單宣告的用途，不從目錄名稱猜測，也不保證有可啟動的完整應用。 |
| `snapshot_scope` | `FULL_TREE` 或 `DECLARED_EXCLUSIONS`。 |
| `root_metadata` | 根目錄的 `mode`、`uid`、`gid`，不使用 `.` 路徑 entry。 |
| `entries` | 按規範化 `path` 的 UTF-8 bytes 升冪排列；列出每個範圍內的普通檔案與目錄，包括空目錄與 exclusion 根。 |
| `exclusions` | 按 `path` 相同排序的明確目錄子樹排除清單。 |

每個 entry 必須恰有七個欄位：

| 欄位 | 普通檔案 | 目錄 |
| --- | --- | --- |
| `path` | 規範化相對 POSIX 路徑 | 相同 |
| `type` | `file` | `directory` |
| `size` | 0 至 2^63−1 的精確 integer bytes；實際 verifier 預算更小 | `null` |
| `sha256` | 64 個小寫 ASCII hex 字元 | `null` |
| `mode` | 四字元 octal `0000` 至 `0777`；不支援特殊 permission bits | 相同 |
| `uid`／`gid` | 0 至 2^32−2 的精確 integer，不接受 boolean | 相同 |

權限 metadata 指儲存於備份樹中的實際 numeric UID／GID 和 mode；不是原系統
帳戶映射或 restore ownership policy。Directory size 不具有跨 filesystem 穩定意義，
因此不作 digest／size 比較。ACL、xattrs、capabilities、SELinux labels、timestamps
等不屬於本版 manifest 的受驗證 metadata。

路徑必須為 Unicode NFC，最多 1,024 UTF-8 bytes／12 個分段。不接受 absolute
path、空分段、`.`／`..`、前後 slash、backslash、colon、C0／C1 control characters、
surrogate、分段前後 ASCII space 或分段末尾 dot。拒絕，不自動修正或 normalize。
每個非根 entry 的所有 parent 必須另列為 `directory`，不能使用隱含目錄。
同一路徑不能出現兩次。Symlink、FIFO、socket、device 等不能作為合法 entry。

`BACKUP_MANIFEST.json` 根 control file 不得列為 entry 或 exclusion。
Manifest 沒有自身 checksum 欄位；避免把自己的 SHA-256 循環放入自己。
Verifier 另外檢查 control file 是單一 link 的普通檔案，並偵測它在讀取後被修改。

## Canonical serialization

確定性 bytes 定義如下：

1. 先完整驗證 schema、path、階層、排序與 exclusions；不自動排序錯序陣列。
2. 所有 object keys 按 ASCII 升冪排列。`entries`／`exclusions` 已按 path UTF-8 bytes 排序。
3. JSON 不含縮排或其他空白；separators 為 `,` 與 `:`。
4. `ensure_ascii=true`：非 ASCII 字元用小寫 `\uXXXX` escapes，astral 字元使用 surrogate pair。其餘 escaping 採 Python JSON 的字串規則；slash 不額外 escape。
5. 數字為精確非負十進位 integer，禁止浮點／指數形式；`null` 使用 JSON 字面值。
6. ASCII bytes（亦為有效 UTF-8），無 BOM、無末尾 LF。

參考實作為 `canonical_bytes(value)`；它只回傳記憶體中的 bytes，不建立檔案。
外部 expected digest 是對上述完整 canonical bytes 計算的 SHA-256。
Verifier 要求實際 control file bytes 與 canonical serialization 完全相等；
即使只有增加換行、縮排或改用 Unicode literal，也回報 `NOT_VERIFIED`。

測試中的空清單 golden vector 為：

```json
{"entries":[],"exclusions":[],"root_metadata":{"gid":0,"mode":"0700","uid":0},"schema_version":1,"snapshot_scope":"FULL_TREE","snapshot_type":"UI_OVERLAY_BACKUP"}
```

這只展示 canonical bytes；空樹也不表示有可恢復的應用程式。
JSON code block 的呈現換行不屬於 serialized bytes。

## Exclusions 與全量覆蓋

`FULL_TREE` 必須具有空 exclusions。除了 control file，實際樹中每個物件都要
出現在 entries；缺失、額外未列檔案／目錄、type／size／permissions／digest 不符
均失敗。不能只檢查清單中的一部分後回報完整。

`DECLARED_EXCLUSIONS` 必須至少有一個 exclusion，每個恰含：

- `path`：已列為 directory 的相對路徑。其根必須存在且不是 symlink。
- `reason`：`VENV_NOT_VERIFIED`、`EPHEMERAL_RUNTIME` 或 `OUT_OF_SCOPE`。

Exclusion 根本身的 type／permissions 仍檢查，但其內部完全不讀取／盤點。
Exclusions 不能重複、互相包含，也不能與被列入 entries 的後代衝突。
例如 venv 內可能有指向系統 Python 的合法 symlink，Phase 3B writer 要求操作者明列
venv exclusion 才能略過其內部，保留空根但不複製 payload；verifier 不跟隨它，
也不把它算作已驗證的環境。

有 exclusions 時，成功結果必須含 `EXCLUDED_CONTENT_NOT_VERIFIED`，並固定
`full_file_coverage=false`。`declared_scope_verified=true` 只表示其餘宣告範圍一致。
沒有明列 exclusion 時，venv 和其他目錄一樣完整遍歷，不會默默忽略 symlink。

## Trust model 與結果

同目錄內的 manifest 和檔案可以一起被修改；相符只證明內部一致。
SHA-256 的比對不會自動賦予資料可信來源，也不證明業務 schema 或安全可執行性。

| 欄位／代碼 | 意義 |
| --- | --- |
| `file_hash_match`／`FILE_HASH_MATCH` | 所有宣告範圍內的檔案 hash、完整清單、type／size／選定 permission metadata 和最終變更檢查皆通過。失敗或中途停止時固定 false。 |
| `manifest_digest_match`／`MANIFEST_DIGEST_MATCH` | Canonical manifest bytes 的 SHA-256 與操作者提供的 expected digest 相符。未提供時是 `null`，格式錯誤／不符時 false。 |
| `trust_anchor_verified`／`TRUST_ANCHOR_VERIFIED` | 與操作者明確提交的 anchor 相符。Anchor 必須由操作者獨立取得且受保護；CLI 無法證明命令列數值的原始取得位置或保護方式。 |
| `declared_scope_verified`／`DECLARED_SCOPE_VERIFIED` | 宣告範圍已全部通過；不是整個部署、排除目錄或 restore 的保證。 |
| `full_file_coverage`／`FULL_FILE_COVERAGE` | 沒有 exclusions，且整個受檢查樹（control file 另行驗證）完成檔案覆蓋；不是完整 production backup 或所有 OS metadata。 |
| `restore_proven`／`RESTORE_NOT_PROVEN` | 永遠 false。沒有執行 restore。 |

Anchor 比對可以成功、但檔案驗證失敗，此時 `verification_status=NOT_VERIFIED`；
`TRUST_ANCHOR_VERIFIED` 僅表示 manifest 的綁定，不能替檔案失敗背書。
失敗時 boolean false 表示未完整確認，不能解讀成每個檔案都已證實不符。

| verification_status | 意義 | exit code |
| --- | --- | --- |
| `INTERNALLY_CONSISTENT` | 所有宣告範圍一致，但沒有外部 trust anchor；不得宣稱 authenticated integrity。 | 0 |
| `TRUSTED_SCOPE_VERIFIED` | 宣告範圍一致，且符合操作者明確提供的 anchor；信任前提是該 anchor 真正獨立且受保護。 | 0 |
| `NOT_VERIFIED` | Schema、canonical bytes、anchor、file coverage／hash／metadata、安全或資源限制失敗；不回報部分成功為完整成功。 | 1 |
| 命令列用法錯誤 | 固定 `INVALID_ARGUMENTS`，不回顯參數。 | 64 |

使用方式；先由獨立且受保護的來源取得 expected digest，設定
`BACKUP_TRUSTED_MANIFEST_SHA256`：

```bash
python3 scripts/backup_verify.py --path /path/to/offline-fixture --json
python3 scripts/backup_verify.py --path /path/to/offline-fixture \
  --trusted-manifest-sha256 "$BACKUP_TRUSTED_MANIFEST_SHA256" --json
```

Expected digest 必須是 64 個小寫 hex 字元，只接受明確的數值參數，不接受
expected-digest file path、不自動讀取同備份的 checksum／metadata。
同目錄的 digest 檔案即使被列入 entries，也只是普通資料。
若操作者自己從該可修改目錄取值後傳入，不能據此宣稱來源已獨立可信。
本 CLI 沒有建立簽章、trust store 或可信來源下載流程。

## 安全、預算與唯讀

Verifier 只使用 stdlib 與 Phase 2 已有的唯讀 no-follow 路徑 primitives；
Phase 2 的 CLI／測試行為維持不變。它不 import snapshot 程式或 project runtime，
不執行 `.env`／Python／unit，不使用 network、systemd 或 subprocess。
Standalone CLI 在匯入本地 protocol 前停用 bytecode cache，避免建立 pycache。
不建目錄、lock、manifest，不 chmod／chown／刪除／restore。

每一層採 descriptor-relative `O_NOFOLLOW`／`O_NONBLOCK`，開啟前後核對 metadata，
拒絕 symlink（含根及祖先）、普通檔案 hardlink、FIFO、socket、device、跨 filesystem
物件及 traversal。不要指向 live install；已知 `/opt/clash-yaml-manager` 及子路徑
在任何檔案 open 之前直接拒絕。其他自訂 live 位置必須由操作者避免。
路徑及祖先須使用實體目錄；macOS 可使用 `/private/tmp` 而非 symlink `/tmp`。

| 預算 | v1 verifier |
| --- | --- |
| Manifest bytes | 最多 2 MiB，超過即拒絕讀取。 |
| Entry count | 每輪最多 4,096 個物件，含 root 與 control file；manifest 最多 4,094 個 entries。 |
| Depth | 最多 12 分段。Root 路徑另受既有 4,096 bytes／64 分段限制。 |
| 單一資料檔案 | 最多 128 MiB。 |
| 合計內容讀取 | 最多 512 MiB，包含 control file。 |
| Chunk | SHA-256 以最多 64 KiB chunk 串流處理，不把大型檔案完整放進記憶體。 |
| Cooperative time | 10 秒，於掃描／chunk／解析前後及最終檢查確認；不是 kernel syscall／JSON 解析的硬逾時。 |

預算不足回報 `NOT_VERIFIED`，不略過檔案。讀取只消耗已確認的檔案 size，
開啟前後及最後的 fingerprint 檢查涵蓋 inode／device／mode／owner／link count／
size／mtime／ctime；讀取中的增長、替換或檢查後變更均保守失敗。
最後重新盤點檔案集合與根路徑。這不是原子 filesystem snapshot，不保證抵抗
系統權限惡意 writer、bind mount 或 filesystem 故障；只支援已 quiet 的本機離線樹。
讀取可能令 OS 更新 atime；不更動或比對 atime，其他 bytes／metadata 由測試確認不變。

輸出只有固定 keys、狀態／validation codes 和 boolean／null；不輸出 path、
filename、manifest／檔案內容、digest、permission 值或原始 exceptions。
所有 fixtures 都使用 `tmp_path` 合成秘密資料，沒有 SSH 或 production POST。

## Offline writer、legacy compatibility 與 production 邊界

Phase 3B 的獨立 writer 會從 quiet 離線來源建立新樹、記錄實際 stored metadata／bytes，
用本 protocol 的 canonical bytes 與實際 verifier 驗證後 no-replace 原子發布。
Digest 只作獨立保存的 handoff，不自動成為 trusted anchor；失敗清理、exclusions
與資源要求見 [Writer 契約](BACKUP_WRITER.md)。Writer 不改變本頁 verifier 的信任模型。

既有 updater／uninstall／manual snapshots 仍沒有 Manifest v1。
請用 [Phase 2 結構 audit](BACKUP_READINESS.md)，不能事後補寫 manifest 並宣稱
它是備份當時的可信原始校驗資料。缺少 control file 時 verifier 只回報
`MANIFEST_MISSING`／`NOT_VERIFIED`，不產生任何檔案。
Phase 2 的舊分類規則不因此放寬；具有新 manifest 的 fixture 使用本 verifier，
不能假定舊 CLI 已整合新格式。現有 backup writer 檔案完全未改動。

未來 production writer 至少需要：

1. 在明確授權與停止 writers 的一致性邊界收集適當 snapshot scope，保護敏感材料。
2. 完整列出 stored tree 的檔案及目錄，定義 venv／ephemeral exclusions，不把被排除的內容當成已驗證。
3. 在完成所有複製／ownership 處理後計算 bytes digest 和 metadata，以 canonical bytes 原子發布 manifest／完成標記；不發出半成品。
4. 建立與可修改備份分離的受保護 digest catalog 或簽章／trust anchor，於建立時綁定清單與範圍，另行保護其生命週期。
5. 與部署格式、原帳戶映射及 legacy 相容性協調，在隔離環境另行授權執行真正的 restore／啟動／業務驗證。

獨立 offline writer 不等於上述 production 一致性收集、trust store 或 restore 整合；
本輪未聲稱依賴、認證版本、Fixed revision／
retired token、輸出關聯或應用啟動已被驗證。檔案一致性不代表 state 相容或可恢復。
