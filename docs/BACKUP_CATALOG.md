# Independent Trust Anchor Catalog

v1.8.0 功能範圍；正式可用版本以 [README Latest Stable](../README.md) 為準。
`scripts/backup_catalog.py` 是獨立、有界、離線工具，只登記操作者明確指定且已完成的
Manifest v1 Snapshot，或從受保護 record 取得 expected digest 交既有 Verifier 查驗。
Catalog 本身不做 live collection、network、retention pruning、rollback 或 restore；
目前 [opt-in Sidecar](BACKUP_UPDATER_SIDECAR.md) 重用 register／verify，安全契約不變。

## Trust bootstrap 與身份

登記的信任前提是操作者先獨立取得／核對 Writer 的 digest handoff，確認其來源與
Snapshot 對應，並明確確認 Snapshot 已發布完成且 offline/quiet。
**不得從同一個可修改 Snapshot 讀取 digest，再把該值稱為獨立 anchor。**
`--expected-manifest-sha256` 的輸入契約包含操作者對獨立 handoff 的明確聲明。
Catalog 驗證明確提供的 expected digest，而非自行選擇讀到的 manifest digest；
工具不能自行證明該參數的歷史取得方式，record 將此聲明與可觀察的參數來源分開。
這建立登記後的比對基準，不能證明登記前從未被篡改或來源具有可信 provenance。

工具拒絕已知 `.backup-create-*`／`.backup-collect-*` staging 路徑，完整檢查 Manifest
及 actual declared scope；`--completed-offline-snapshot` 是操作者對 Writer 已完成與
quiet 的 attestation。沒有重新構造 Writer publication history 或新增 signed completion
marker，也不能以名稱猜測 completion、installed identity 或捕捉時點。
Verifier success 不能把一份未確認完成的 staging 自動升格為已發布 Snapshot。

操作者還必須提供明確的原始 offline representation/source 根，才能檢查 Catalog
與 representation／Snapshot 都分離。這只驗證指定根的本機身份與位置，不證明它
必然是 Writer 的歷史來源；該來源關聯仍由操作者提供，不能由目錄名稱推導。

## CLI 與模式

Catalog root 必須預先存在；工具不建立或修復根目錄。下列都是操作者準備的
私人離線位置，沒有 `/opt` 或 production 預設值。先獨立保存 expected digest：

```bash
python3 scripts/backup_catalog.py register \
  --catalog /path/to/private-catalog \
  --snapshot /path/to/completed-snapshot \
  --representation /path/to/offline-representation \
  --operation-id "$BACKUP_OPERATION_ID" \
  --scope-profile updater-sidecar-v1 \
  --expected-manifest-sha256 "$BACKUP_TRUSTED_MANIFEST_SHA256" \
  --completed-offline-snapshot

python3 scripts/backup_catalog.py verify \
  --catalog /path/to/private-catalog \
  --snapshot /path/to/completed-snapshot \
  --snapshot-id "$BACKUP_SNAPSHOT_ID"

python3 scripts/backup_catalog.py inspect --catalog /path/to/private-catalog
python3 scripts/backup_catalog.py inspect \
  --catalog /path/to/private-catalog --snapshot-id "$BACKUP_SNAPSHOT_ID"
```

Operation ID 恰為 32 lowercase hex，操作者選擇新的非秘密識別碼，不使用 credentials。
Snapshot ID 由工具以 128-bit randomness 生成；register 不接受任意 record path 或
指定 snapshot ID。Record filename 固定 `<snapshot-id>.json`，不得覆寫。
Verify 明確要求 Snapshot 路徑及 snapshot ID，不自動尋找／掃描任何備份。
Inspect 唯讀顯示 counts、residue 診斷與指定 record 的固定安全 metadata；不查 Snapshot
是否存在，明列 `SNAPSHOT_EXISTENCE_NOT_CHECKED`，不假裝已驗證所有 records 的 payload。
非該模式的 status 欄位為 `NOT_RUN`。

Scope profiles 均為 version 1：

- `updater-sidecar-v1`：要求 Snapshot 的 digest-covered `COLLECTION_SCOPE.json`
  header 與已知 Collector subset/profile 相符。這仍是 scope 聲明，不驗證業務 closure。
- `manifest-v1-declared-scope`：一般 Manifest v1 的宣告範圍，不聲稱經 Collector 收集。

Register 可另提供 `--original-identity`／`--target-identity` 的 bounded JSON 值。
只接受既有六欄 INSTALLATION identity 形狀、固定 channel/source、semver、tag、commit
與有時區時間，每個 string 最多 128 字元；拒絕未知欄位，不接受 arbitrary label、URL、
password 或 token 欄位。這是 operator claim，不自動驗證 GitHub 來源或部署。
不提供時存 null。Snapshot 內存在合法 INSTALLATION metadata 時另列為 Snapshot claim；
沒有 metadata 就不補造，不從 Snapshot 名稱猜測。

固定 JSON console output、成功 exit 0、失敗 exit 1、用法錯誤 exit 64；不回顯任意
輸入路徑／例外、state、password、bearer URL。非秘密 IDs 與固定 category metadata
可出現在成功報告。CLI 不建立 bytecode cache。

## Root protection 與 IO

正式同主機模型：執行者 root UID/GID 0，Catalog root root:root / 0700，records
root:root / 0600，服務帳戶沒有讀寫權。非 root 合成 fixture 要求精確 executor UID/GID
和相同私人 modes，輸出 `LOCAL_UID_FIXTURE`；不能把它當作 production root protection。
`protection_model` 識別執行身份所採模型；`ROOT_PRIVATE` 本身不是成功證明，
失敗結果仍須依各 gate／codes 判讀，不能因此宣稱 production 權限已通過。

所有祖先逐段 descriptor-relative no-follow 開啟，拒絕 lexical `..`、symlink、FIFO、
socket、device、多 hardlink、未知 Catalog objects 與 filesystem boundary。
Catalog／Snapshot／representation 根都要求 executor-owned 0700；manifest control
要求 executor-owned 0600，其他 Snapshot 物件沿用既有 Verifier 的全部安全檢查。
不得指向 live state；已知 `/opt/clash-yaml-manager` 及子路徑在任何 open 前拒絕，
自訂 live 位置仍由操作者避免。macOS 使用實體 `/private/tmp`，不要經 symlink `/tmp`。
Snapshot／representation 不改寫或修復權限；只讀可能令 OS 更新 atime，不嘗試重設。

Catalog 不得與 Snapshot／representation 相同、互為 ancestor 或 descendant；所有
指定 roots 必須分離。記錄以 bounded canonical absolute path 的 SHA-256 加本機
dev/inode/UID/GID/mode 綁定 Snapshot、Catalog 及明確指定 representation。
不保存任意完整路徑、basename、URL 或原始 state。工具不為查孤兒而掃描外部樹。
位置最多 1,024 UTF-8 bytes／32 分段，各分段遵守 Manifest canonical path 規則。
移動／複製／更換 Catalog 或 Snapshot 根會拒絕 binding，不自動遷移／重建可信關聯。
Representation 可在登記後不存在，verify 不讀它；不能把其 binding 當 restore 材料。

同主機 mode/owner 保護可阻止服務帳戶，但不抵抗 root compromise、同 UID 惡意
writer、mount spoofing、硬體故障或 filesystem 不遵守 syscall 契約。Catalog 沒有簽章、
外部時間證明或 off-host DR；連同主機／磁碟遺失仍可能一起遺失。UID/GID/inode binding
不是跨主機 portable identity。沒有 ACL/xattr 還原、帳戶建立或自動認證恢復。

## Record schema v1

嚴格 keys、精確 integer version 1、拒絕 duplicate JSON keys、非標準 NaN/Infinity，
sorted keys / ASCII escapes / compact separators、無 BOM／尾端 LF。Load 必須與
canonical serialization bytes 完全相同；單 record 最多 16 KiB。

| 欄位 | 信任角色與規則 |
| --- | --- |
| schema_version | 精確 integer 1 |
| snapshot_id / operation_id | random 工具 ID／明確 operator operation ID；各 32 lowercase hex |
| manifest_sha256 | 明確獨立 handoff 的 64 lowercase hex canonical Manifest v1 digest；登記前由真實 Verifier 比對 |
| snapshot_binding | 此次觀察的本機位置 hash、dev/inode、UID/GID/mode |
| catalog_binding | 同樣綁定受保護 Catalog 根，防止不經確認的搬移／複製 |
| representation_binding | 此次觀察的 operator 指定原始離線根；歷史 source 關聯是 operator 前提 |
| enrolled_at | 工具取得的 UTC enrollment time，不冒充原始 capture timestamp |
| snapshot_claims | Manifest 自身 snapshot_type/snapshot_scope 與 optional installed_identity；不是 GitHub provenance |
| operator_claims | completed_offline_snapshot、independent_digest_handoff、scope profile/version、optional original/target identity；不冒充工具自動驗證事實 |
| verified_facts | Manifest schema 1、expected digest origin = OPERATOR_ARGUMENT、digest/scope checks true；source provenance authenticated = false |
| restore_proven | 永遠 false |

Records 不保存 `.env`、auth、Fixed tokens、nodes 或敏感 state；安全 identity whitelist
也不因此認證來源。Canonical schema 不等於 digital signature：能以 root 權限改寫一個
合法 record 並改寫 Snapshot 的攻擊者不在此同主機 protection 的抵抗範圍。
普通毀損、格式／filename／binding 或 expected digest 不符都會拒絕。

## 登記、鎖、發布與 durability

以 Catalog directory fd 的 nonblocking exclusive flock 保護 register 全流程；verify/
inspect 使用 shared flock，不建立額外 lock file。並發操作可能回報 `CATALOG_BUSY`，
不等待無界時間。所有 cooperative writers 必須採相同鎖；不能抵抗忽略鎖的 root。

1. 有界盤點所有 Catalog entries，驗證全部 records／private modes／root binding。
   拒絕 ID、operation ID、Snapshot location/inode association 重複；滿額或 staging residue
   fail closed，不以清理舊資料空出位置。
2. Snapshot 的 path/root/manifest identity 與 canonical Manifest 語法檢查，呼叫未改動的
   `backup_verify.verify(snapshot, operator_expected_digest)` 完整查驗。
   提取 INSTALLATION／Collector scope metadata 時另將原始讀取 bytes 的 size/hash 及
   stored permission metadata 綁定該已錨定 Manifest entry，不能將短暫不同值存為 claim。
3. 以隨機 `.catalog-stage-<32 hex>.tmp`、exclusive no-follow create、0600 寫入 canonical
   record，處理短寫入並 fsync file；重讀比對 staging bytes。
4. 再完整呼叫既有 Verifier，核對 Snapshot/root/control 未變，重盤點 Catalog，確認
   原 records fingerprints 未變且唯一 residue 是本次 staging。
5. Linux renameat2(RENAME_NOREPLACE)／macOS renameatx_np(RENAME_EXCL) 發布，然後
   fsync Catalog directory。Unavailable syscall／collision 拒絕，不 fallback 普通 rename。
6. 重讀全 Catalog、核對 published inode／canonical bytes／existing record fingerprints；
   再完整 Verifier 及最後 Catalog 重查。只有所有檢查和 handles 關閉成功才 REGISTERED。

Snapshot 與 Catalog 的兩次發布**不是原子交易**。Snapshot success／Catalog failure
留下 retained/unanchored Snapshot；不能自動從 Snapshot 重建 anchor。Published record
之後 fsync、身份或查驗失敗會保留未確認結果，報 NOT_REGISTERED／PUBLISHED 或 UNCERTAIN，
不能宣稱登記成功。Private record 的存在本身不證明原登記後 directory fsync 曾成功。
之後查驗檢查的是當前受保護 record 和當前 Snapshot，不證明過去 power-loss durability。

## Verify 與孤兒

Verify 只從已驗證安全、canonical、filename/root binding 相符的受保護 record 取得
expected digest；實際 Snapshot identity 必須與 record 相符，再呼叫未改動的完整 Verifier。
前後 root/control 與 Catalog fingerprints checks 失敗也撤回完整成功。

| 診斷 | 意義 |
| --- | --- |
| RECORD_FOUND | 指定 ID 的 record 存在；不是 Snapshot 已查驗 |
| CATALOG_RECORD_VALID | 全 Catalog records schema/private ownership/association checks 完成 |
| SNAPSHOT_IDENTITY_MATCH | 指定 Snapshot 的本機 path hash、dev/inode/owner/mode 相符 |
| MANIFEST_DIGEST_MATCH | canonical manifest 與受保護 expected digest 相符；payload 仍可能失敗 |
| DECLARED_SCOPE_VERIFIED | 既有 Verifier 完成宣告範圍 checks，不代表完整 VPS |
| TRUSTED_SCOPE_VERIFIED | record、binding、完整 Snapshot 與前後變更 checks 全部成功 |
| NOT_VERIFIED | 任何必要 gate 未完成；部分 digest match 不能當作完整成功 |
| UNANCHORED | Catalog／指定 record 不存在，不自動建立 anchor |
| MISSING_SNAPSHOT | 指定 record 有效，但所指定 Snapshot 根不存在；record 保留 |
| STAGING_RESIDUE | 有已知私人 staging names；不解讀為成功 record，不自動刪除 |

Inspect 不保存／輸出原始 locations，也不掃描外部樹；global counts 不等於無孤兒。
操作者需給出已知 ID／Snapshot 路徑才能查缺失。重複 operation ID、association、
unsafe/corrupt records 或超限明確拒絕；不猜測哪個 record 最新／該刪除哪個。
Restore 固定 false，沒有刪 record／Snapshot、retention、舊 backup cleanup 或 rollback API。

## 失敗清理與上限

只清理本次可核對 inode 身份的 staging file；foreign/collision/replaced/未知身份
不刪除。Cleanup failure 提供固定 code 與自建 random basename；已發布／publication
不確定時保留 record，不 unlink 成品。Caught interruption 做上述有界清理；SIGKILL/
斷電可留下私人 staging，下一次 register 拒絕 residue，不自動 sweep。

| 預算 | 上限 |
| --- | --- |
| Published records | 128；滿額 fail closed |
| Single record / identity JSON argument | 16 KiB |
| Staging residue roots | 8；超過拒絕 |
| Flat directory inventory | 136 entries；不 recurse |
| Aggregate Catalog/metadata reads | 16 MiB，包含重盤點及 Snapshot manifest/control metadata 的重讀 |
| Manifest / Collector scope metadata | 既有 2 MiB／256 KiB；INSTALLATION identity 16 KiB |
| Location | 1,024 UTF-8 bytes／32 分段 |
| Chunk | 最多 64 KiB |
| Cooperative operation time | 30 秒，包含最多三次完整 Verifier；blocking syscall/parse 不能硬中斷 |

原 Verifier 各自保留 4096 objects／12 depth／128 MiB file／512 MiB content／10 秒。
Register 最多三次其完整 payload reads、verify 一次，未擴大限制；本工具的 16 MiB 是
額外 Catalog/metadata 讀取預算。合併各項上限不保證最大容量在 timing/read budget 內
成功，超限拒絕，不截斷、不自動 prune。

## 驗證與限制

Synthetic tests 包含真實 Collector→Writer→Manifest→Catalog→Verifier 與 data/manifest/
record tampering、complete identity/schema、ownership、special objects、容量、race、
stale Snapshot、ENOSPC/fsync/cleanup/interruption/post-publication failures 與 redaction。
Linux-only tests 直接使用 native no-replace、fsync/no-follow/inode/collision；既有已審閱
seccomp prefix 的真實 ENOSYS 與 no-fallback tripwires 延伸到 Catalog，未改原 gate。
另以 root temporary fixture 和 fork/drop numeric UID/GID 證明服務讀寫拒絕；無帳戶建立。
macOS Linux-only skip 不當作 native PASS，exact-SHA Ubuntu RC 結果另存本輪驗收報告。

Phase 3D-2 歷史驗收未改原 Collector／Writer／Verifier／Manifest、runtime、updater
或 Default，未 SSH、部署、讀取真實備份或發布版本。後續 opt-in hook 見 Sidecar 文件。
完整 VPS backup、完整 updater rollback、認證／資料庫可恢復、real restore tested
與 off-host disaster recovery 均未證明；production／restore acceptance 需另行授權。
