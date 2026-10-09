# Offline Sidecar Collector

v1.8.0 Phase 3D-1 開發功能，尚未發布；Latest Stable 保持 v1.7.0。
`scripts/backup_collect.py` 是獨立 stdlib 工具，從操作者明確指定、已確認 quiet 的
本機離線 fixture，依固定 `updater-sidecar-v1` allowlist 建立新的私人 representation。
沒有 updater 整合、production collection、服務控制、帳戶建立、restore 或備份 retention。
成功不表示完整 runtime 一致、完整 updater backup、rollback ready 或 restore proven。

## 使用與可信離線聲明

CLI 的必要輸入只有 `--source`、`--destination`、`--profile`；沒有自動搜尋、任意
include／exclude 或權限放寬開關。結果固定輸出 JSON，不回顯任意輸入路徑／內容。

```bash
python3 scripts/backup_collect.py \
  --source /path/to/quiet-offline-fixture \
  --destination /path/to/private-parent/new-representation \
  --profile updater-sidecar-v1
```

來源根必須由執行者的 numeric UID／GID 擁有，mode 恰為 0700。操作者事先在該
離線根準備 `COLLECTOR_SOURCE.json`，owner 為執行者 UID／GID，mode 0600，單一
link、同 filesystem 的普通檔案。Collector 不替來源建立、修復或更新這個聲明。
根的私人保護與操作者獨立確認是信任前提，不從可被服務帳戶控制的 state 推導權限。
下例是全部資料由執行者擁有的合成來源，並非 production 操作：

```json
{"schema_version":1,"profile":"updater-sidecar-v1","offline":true,"writers_quiet":true,"service_account":null}
```

Schema 恰含上述五個 keys，拒絕重複 JSON key、非有限數、未知 schema、額外 keys、
非 boolean 的 offline／quiet 或 false。這是操作者對 offline／quiet 的明確 attestation，
不是 Collector 已停止服務／偵測所有外部 writer 的證明。不得對 live 來源做假聲明。

Source／destination 及祖先都必須是實體目錄，拒絕 lexical `..`、symlink ancestor、
已知 `/opt/clash-yaml-manager` 及其子路徑。自訂 live install 位置仍須由操作者避免。
macOS 使用實體 `/private/tmp` 或 `/private/var` 路徑，不經 symlink `/tmp`／`/var`。
不接受 source `/` 或 destination parent 位於 source 內。Destination 必須不存在；
parent 已存在、owner 為執行 UID、mode 恰為 0700，工具不建立或修復它。

## 固定 scope 與 state 生命週期

Allowlist 根據目前 `core/security.py`、`fixed_subscriptions.py`、`fixed_sources.py`、
`node_health.py`、`proxy_health.py`、`geoip_store.py`、`notifications.py`、
`rate_limit.py`、`temporary_links.py` 及 `state.py` 的檔案配置／生命週期審閱。
工具不 import 這些 runtime modules，也不執行來源程式、YAML、`.env` 或配置。

| 路徑／角色 | 規則 |
| --- | --- |
| `COLLECTOR_SOURCE.json`、`.env`、`VERSION` | REQUIRED；來源聲明、原始環境 bytes、installed version。`.env` 不解析、不 strip、不重新生成；必須非空。VERSION 僅接受既有 semver 格式。 |
| `defaults/default.yaml` | REQUIRED，含 defaults directory；保存原始非空 bytes，不生成／轉換 YAML。 |
| `state/`、`state/auth.json` | REQUIRED；認證持久 bytes。只檢查 JSON version envelope，不雜湊／驗證密碼或遷移認證。 |
| `INSTALLATION.json` | OPTIONAL；存在時，要求既有六個欄位、合法 channel/source/tag/commit/timestamp，base_version 必須等於 VERSION。格式吻合不認證 GitHub 來源。 |
| `.service-account` | 同 UID 來源 OPTIONAL；聲明 foreign service identity 時 REQUIRED，詳見所有權契約。 |
| `state/fixed_subscriptions.json` | OPTIONAL，known envelope versions 1–6；含 bearer、retired token、revision/source pointers、Policy／schedule 等敏感業務 bytes。 |
| `state/node_health.json`、`state/proxy_health.json` | OPTIONAL，versions 1–2；持久設定、scheduler 與 observation bytes，不執行 probe。 |
| `state/settings.json`、`state/notifications.json` | OPTIONAL，version 1；GeoIP metadata、Telegram 設定／秘密及 delivery state，不發送通知。 |
| `state/login_attempts.json`、`state/temporary_links.json` | OPTIONAL，version 1；安全限制／tombstones／既有 output 指標；不延長、刪除、恢復或啟用。 |
| `state/geoip/active.mmdb` | OPTIONAL；只保存 opaque bytes，不載入 MMDB／DNS／GeoIP engine。GeoIP directory 只允許該檔案。 |
| `state/fixed_subscriptions/<id>/<revision>/base.yaml`、`current.yaml` | OPTIONAL，id／revision 都必須恰為 32 個 lowercase hex；只收集已審閱的 revision 結構。 |
| 同 revision 下 `sources/<source-id>/payload.bin` | OPTIONAL，source-id 同樣 32 lowercase hex；保存 remote last-good／uploaded cache bytes，不 fetch／parse nodes。 |

Known state JSON 必須是有界、無重複 key／非有限數的 object，version 為上述精確
integer 集合。這只檢查 envelope，不重實作完整業務 validator、schema migration 或
密碼 hash 規則；unsupported envelope／未知檔案／未知目錄直接拒絕，不靜默收集。
不因此宣稱認證、Fixed、Health、Policy 或通知狀態可恢復。

Fixed lifecycle 以 registry 的 revision pointer 提交，舊／crash orphan revisions 可以
在下次管理 mutation 才被 GC。本 profile 保存所有符合上述路徑文法、實際存在的
revision／cache，包括空目錄及 orphan，不選擇、改寫或刪除它們。文法檢查不驗證
registry→revision→source closure、必要 payload、token 關係或 YAML 語義；optional
檔案不存在也不補造。Scope metadata 固定 `business_closure_verified=false`。
Temporary link 指向的 top-level outputs 不在此 subset，不能把 registry copy 當完整
業務恢復材料。Versions 及路徑支援不表示其他未來 runtime schema 已被批准。

### 明列省略與 unsupported

以下已知根僅做 bounded lstat／type／single-link／device 檢查，不開啟或遍歷 payload，
不在 representation 保留空 exclusion root；`COLLECTION_SCOPE.json` 記錄實際
`omitted_roots` 與 `contents_inspected=false`。它們不是已收集或已驗證資料：

- venv、uploads、outputs、backups、logs、bin。
- core、templates、static、scripts、app.py、requirements.txt 及 install/update/uninstall/
  remote/HTTPS/Mihomo 入口腳本；不保存完整 app、依賴或執行環境。
- 若離線根含 nginx、certificates、HTTPS_DEPLOYMENT.json、`.httpsctl.lock`，也省略。
  不讀取外部 Nginx、憑證、系統設定或任何系統依賴。
- state 中固定 lock 名稱：auth、fixed_subscriptions、node_health、proxy_health、
  proxy_probe、geoip、notifications、temporary_links、login_attempts、auto_refresh、
  auto_health 的 `.lock`。鎖 inode 不是 portable scheduler／quiet 證明。
- state 中 `.proxy-probe-*`、`.fixed-candidate-*`、`.geoip-upload-*` 普通 scratch
  directory，以及 `.<known-state-json>-*` atomic-write temporary file；suffix 限 1–64
  個 ASCII alphanumeric／underscore／hyphen。這些沒有持久 commit pointer。

省略根若是 symlink、特殊物件、hardlinked 普通檔案或跨 filesystem，仍拒絕；不為
取得內容而跟隨。省略根內部完全未盤點，允許正常 venv 的內部 symlink，但沒有遍歷。
未知且符合 canonical path 規則的路徑（包括任意新 state directory、陌生 revision
檔案或 metadata 名稱衝突）一律 UNSUPPORTED／`UNEXPECTED_COMPONENT`。
不符合 Manifest 路徑規則或含根 manifest 的來源，也會以對應固定錯誤碼拒絕；
不把任意 tree 當 allowlist。

## 所有權與 source role ledger

單 UID 模型：配置、來源根、聲明以及所有受收集 state 都屬執行 UID／GID。
Root-compatible 表示 root 執行時產生 root-owned representation；一般使用者的
合成測試也支援同 UID/GID 私人資料，不假裝其 output 是 root-owned。

混合模型只允許 root 執行，並由上述受保護聲明指定：

```json
{"schema_version":1,"profile":"updater-sidecar-v1","offline":true,"writers_quiet":true,"service_account":{"name":"clashyaml","uid":12345,"gid":12345}}
```

12345 僅為 synthetic example，操作者須使用離線來源原先已確認的 numeric identity。
UID／GID 都是非零精確 integer，不能是 boolean，UID 不能等於執行 UID。聲明須與
來源根的 root-owned 0600 `.service-account` bytes
`clashyaml:<captured-uid>:<captured-gid>` 加末尾 LF 完全相符。無標記／錯誤標記即拒絕。
不從 state file 的 owner 猜帳戶，不因 root 可讀就接受其他 UID；不查詢／建立／更改
本機 system account。這個 root-controlled 離線 captured mapping 是操作者 attestation，
不是外部來源認證或可直接套到另一主機的 restore 帳戶。

每個 state／revision／cache 物件只接受 executor UID/GID 或已聲明且核對的 service
UID/GID pair；state directory 恰為 0700、state 普通檔案恰為 0600。配置只能由
executor UID/GID 擁有；`.env`／聲明／marker 恰為 0600，其餘配置不能 group/other
write，不能有 setuid／setgid／sticky special bits。未知 pair／unsafe mode fail closed。
源物件 ownership／permissions 不修改，不對 live／legacy tree chmod／chown 迎合工具。

Output 根及目錄恰為 0700，普通檔案恰為 0600，由 executor UID/GID 新建。
`SOURCE_OWNERSHIP.json` 私人 ledger 分開記錄：

- 每個被收集的原始 path、type、role、original UID/GID/mode（根以 `.` 表示）。
- 原始受保護的 operator declaration；角色分為 OPERATOR_ROOT、
  OPERATOR_CONFIGURATION、PERSISTENT_STATE、FIXED_REVISION、FIXED_SOURCE_CACHE。
- collected owner、固定 collected modes，以及 `restore_mapping_applied=false`。

原始 UID/GID/mode 不冒充 collected filesystem metadata；Ledger 不是可執行的 restore
指令。ACL、xattrs、capabilities、SELinux labels、原 timestamps 與其他帳戶／環境資料
不保存／恢復。需要還原時，另行審閱帳戶與 role mapping；沒有自動恢復 UID/GID、
密碼、認證狀態、session、token 或 scheduler policy。

## Representation 與 Writer／Verifier

成功 representation 含 allowlist payload 的原始 bytes、來源聲明／條件 marker，另加
兩個 0600 普通資料檔：`COLLECTION_SCOPE.json` 與 `SOURCE_OWNERSHIP.json`。
Scope metadata 包含 profile/schema、missing optional、實際 omissions／未讀範圍，固定：

- `source_scope=ALLOWLIST_SUBSET`
- `writer_full_tree_means=COLLECTED_REPRESENTATION_ONLY`
- `writers_quiet=OPERATOR_ATTESTED`
- `atomic_source_snapshot=false`
- `business_closure_verified=false`、`source_provenance_authenticated=false`
- `restore_proven=false`

Collector 不建立 Manifest、trust catalog 或獨立 anchor。成功後操作者才可在另一個
不存在的目的地使用既有 [Writer](BACKUP_WRITER.md)：

```bash
python3 scripts/backup_create.py \
  --source /path/to/private-parent/new-representation \
  --destination /path/to/private-parent/new-snapshot \
  --snapshot-type UPDATER_SNAPSHOT --json
python3 scripts/backup_verify.py --path /path/to/private-parent/new-snapshot --json
```

Manifest v1 的 `FULL_TREE` 此時只覆蓋 collected representation 全樹，包括普通的
scope／ownership 檔，**不是完整原始安裝／VPS**。Metadata 沒有擴充 Manifest schema、
新增 exclusion reason 或削弱原 Writer／Verifier gates。Verifier 檢查其 stored bytes，
不因此驗證 ledger 的語義、外部身份、資料完整業務關聯或 restore。獨立 trust anchor
仍需另外取得／保存，不能借用同 snapshot metadata 當可信來源。

## IO、安全與一致性

所有來源／輸出 IO 採 descriptor-relative no-follow、nonblocking flags、open 前後
fingerprint 與同 filesystem 檢查，拒絕 symlink traversal、普通檔案多 link、FIFO、
socket、device。遍歷前先分類 allowlist，未知路徑不開啟 payload；大型檔案按已確認
size、最多 64 KiB chunk 讀取，不讀至任意 EOF。來源 `.env` 的每一 bytes 保留。

Collector 重用未改動 Writer 的 fd／inode ledger、exclusive file create、短寫入處理、
private directory、fsync、cleanup 與 native no-replace primitives；使用自身的較小預算。
流程：初次來源盤點 → 新 staging／copy → scope／ownership metadata → 重查來源 →
重讀／hash 全部 staged bytes → file／directory／parent fsync → 再查 source/parent/stage →
Linux renameat2(RENAME_NOREPLACE)／macOS renameatx_np(RENAME_EXCL) 發布 → parent fsync →
重讀／hash output／再次 source check → 才回報 `COLLECTED`。不 fallback 普通 rename。

來源集合與 dev/inode/mode/UID/GID/nlink/size/mtime_ns/ctime_ns 比對，根路徑重新
no-follow 開啟，能偵測一般並發新增、刪除、替換或修改。來源只讀；OS 可能更新 atime，
atime 不比較，也不嘗試重設。省略根的後代完全不讀，不能宣稱偵測其 payload 變動。
這不是原子 filesystem snapshot、filesystem/bind-mount authenticity、惡意 root／同 UID
writer、硬體故障或遠端 filesystem 的保證。操作者必須先確保可信本機離線來源 quiet；
沒有服務停止、production lock 或全域部署 exclusivity implementation。

## 明確預算

| 預算 | Collector v1 |
| --- | --- |
| Entry count | 最多 512，包含受盤點 roots／entries、兩個 generated metadata 及預留 future Manifest；不遍歷 omitted descendants。 |
| Depth | 最多 8 分段；entry path 同時服從 Manifest v1 canonical path／1,024 UTF-8 bytes 要求。 |
| 每資料檔案 | 最多 16 MiB。 |
| State JSON／INSTALLATION JSON | 最多 2 MiB，控制聲明／VERSION／marker 每項最多 16 KiB。 |
| 合計 stored content | 最多 64 MiB，包含 payload、generated metadata 及保守預留的完整 2 MiB future Manifest。 |
| Aggregate content reads | 最多 256 MiB，涵蓋 header 重讀、source copy 與前後 output hash；拒絕不截斷。 |
| Generated metadata | 每個最多 256 KiB；均計入 stored／read 預算。 |
| Chunk | 最多 64 KiB。 |
| Cooperative time | Collector 全流程 10 秒；cleanup 不因預算耗盡而略過，仍受 bounded inode ledger 限制。 |

均低於／相容現有 Writer／Verifier 的 4096 objects、12 depth、128 MiB/file、512 MiB
content 上限。後續 Writer 有自己的 10 秒合作式預算；符合 Collector 容量不保證
任意 hardware／filesystem 上的 Writer timing 必然成功。Blocking syscall／JSON parse
不能硬中斷，合作式 budget 不是 wall-clock SLA。超限立即拒絕，不能截斷／漏檔後成功。

## 失敗、清理與中斷

| 結果 | 行為 |
| --- | --- |
| COLLECTED / PUBLISHED | Exit 0，來源與 output checks 完成；仍是 representation，非 verified 完整 backup。 |
| FAILED / NOT_PUBLISHED | Exit 1；明列 missing/unsupported/unsafe/permission/mutation/collision/resource/IO 等固定 codes。 |
| CLEANED | 只清理本次可核對 inode 的 staging items／root；不動 source 或 unrelated backup。 |
| CLEANUP_FAILED | 保留不確定／無法清理的 staging，回報安全的自建 random basename；不 rmtree，不刪陌生新增／替換 inode。 |
| FAILED / PUBLISHED | 發布已發生但後續確認失敗；保留 unconfirmed destination，禁止成功宣稱／自動刪除。 |
| FAILED / UNCERTAIN | 無法確認 publication；保留可能 destination/staging，供私人人工檢查，不盲目刪除。 |
| INVALID_ARGUMENTS | Exit 64，不回顯 arguments 或任意 exception。 |

Random staging 在同一 parent，名為 `.backup-collect-<32 lowercase hex>`。
碰撞不建立 ownership，既有目錄完整保留。Caught KeyboardInterrupt 若已有 ledger，
嘗試 identity-checked cleanup；若 mkdir 成功但還未取得 inode 身份，保守報告可能殘留，
不能證明己有就不刪。SIGKILL／power loss 無法執行 Python cleanup；未發布的 private
staging 不是成功成品。下一次執行不自動搜尋／刪除舊 staging 或備份。
報告只含固定技術欄位／codes、counts、booleans、必要時自建 basename；source paths、
ledger、payload、credentials、bearer URL 與原始 exception 不輸出。CLI 不建立 pycache。

## 驗證與後續界線

`tests/test_backup_collect.py` 使用 isolated synthetic fixtures，涵蓋 required／optional、
未知項目、symlink/hardlink/FIFO/socket/device、owner／permission／filesystem boundary、
來源 mutation、真實 native destination collision、disk/copy/fsync/cleanup failure、各種
預算、caught interruption／hard-killed stage、private metadata 及原始 Default byte copy。
整合測試直接走 Collector → 未改動 Writer → Manifest v1 → 未改動 Verifier。
Linux-only root fixture test 僅以 Ubuntu runner 的 sudo 在 temporary fixture 設定 numeric
ownership，再證明真實 root/service 混合、marker missing/mismatch、陌生 UID refusal 與
原 Writer／Verifier pipeline；不建立系統帳戶，結束後恢復 fixture ownership 供測試清理。
macOS 的 Linux-only skip 不等於 native PASS；最終 exact-SHA Ubuntu RC 證據另記驗收報告。

Updater hook、全域 quiet/exclusivity、完整業務 closure、production collector provenance、
獨立 catalog／anchor transactions、retention、off-host DR 及 restore 均未實作／未驗證。
原 legacy updater backup／venv／權限與 rollback 材料不變。
