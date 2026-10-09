# Updater opt-in verified Sidecar

v1.8.0 Phase 3D-3R 開發功能，尚未發布或部署；Latest Stable 保持 v1.7.0。
`update.sh` 的獨立 `backup_sidecar_update.py` hook 串接既有 Collector、Writer、
Manifest v1 Verifier 與 Protected Catalog。只驗證離線 subset 的完整性，
**legacy cp -a backup 仍是原人工 rollback 材料**；沒有 restore、備份刪除或完整 VPS 保證。

## 明確 opt-in 與生命週期

Root 操作者透過程序環境選擇 `CLASH_BACKUP_SIDECAR_MODE`，不讀取 app `.env`
來決定模式。未設定為 `OFF`，值只接受精確 `OFF`／`OPTIONAL`／`STRICT`。
非 OFF 另需 `CLASH_BACKUP_EXTERNAL_WRITERS_QUIET=YES`：操作者已確認沒有
歷史 updater、installer、uninstaller、管理工具或手動 root writer 並行。
這是信任前提，不代表工具能偵測任意外部程式。操作示例僅用於已審閱的隔離來源：

```bash
sudo env CLASH_BACKUP_SIDECAR_MODE=STRICT \
  CLASH_BACKUP_EXTERNAL_WRITERS_QUIET=YES bash update.sh
```

Remote wrapper 原有環境交接亦保留這兩個 opt-in 值；它沒有新增 channel 或
CLI 選項。只有包含新 hook 的目標 updater 能使用本功能，歷史 Stable child
不因此取得 Sidecar 能力。本文件不是 production deployment 授權。

| 模式 | 行為 |
| --- | --- |
| OFF | 不呼叫 Adapter／Collector／Writer／Verifier／Catalog，不建立 Sidecar 物件；原 cp -a、依賴、state、auth、service/timer 與 remote finalization 行為保留。 |
| OPTIONAL | 全域 gates 成立時，普通 subset／資源／驗證／Catalog 失敗可以保留 legacy 並繼續，明列失敗，不能標為 VERIFIED。 |
| STRICT | 必須完整 Writer CREATED、獨立 Verifier、Catalog register／verify 成功，且最後 quiet／legacy 重查完成，才允許 auth migration。 |

既有共同 Deployment Guard 仍從首次部署副作用前持有到 remote 最終 metadata
寫入／核對完成。固定路徑、root checks、FD inheritance、nonblocking flock、
75／78 與關閉 references 的契約未改，沒有第二套 updater lock。
歷史 updater、install/uninstall 與不遵守協定的 root writer 仍在保護範圍外。

Hook 僅位於 `backup_private_state` **返回成功後、`core.migrate` 前**：
guard → 原 legacy code/venv/config/units backup → pip → 原 service/timer stops →
legacy state backup → opt-in Sidecar → auth migration → code copy／service recovery →
remote metadata finalization → guard release。没有提前或推遲 legacy backup。

Strict 拒絕時，依賴可能已更新、服務／timers 可能已停止；沒有自動重新啟動、
downgrade 或 restore。錯誤路徑查詢並回報 app 的當前 `SERVICE_STATE`，無法查詢
時明列 CHECK_ERROR。依原 rollback 文件人工核對 legacy venv、auth 與 units，
不得把 Snapshot 當可直接覆蓋的恢復格式。

## Supported quiet gate

初始支援 Linux cgroup v2、五個 **loaded** units，服務在 system.slice：app、
refresh timer/oneshot、health timer/oneshot。沒有猜測舊版本 missing-unit 例外。

- Unit 必須 inactive/dead、沒有 Job；services 的 MainPID／ControlPID 為 0、
  ControlGroup 空、KillMode=control-group、Result=success。
- 對預期 service cgroup 正面確認不存在，或 `cgroup.events` 的 populated=0；
  結合上述 systemd 事實涵蓋原 app threads、DNS／Mihomo descendants。
- 有界檢查 systemd pending jobs，以及 ps 中的 auto_refresh／auto_health／migrate、
  Mihomo 與已知其他 deployment CLI；目前 updater 的可觀察 ancestor chain 可排除。
- 每次確認實際 inherited guard，而非相信環境的「已持鎖」字串；capture 前、
  attestation 前與返回 migration 前重查。Missing、failed、unknown、active、
  malformed output／check error 都拒絕，OPTIONAL 也不能繞過。

Adapter 不負責停止 writers；停止順序仍由原 updater 管理。未識別的 root script、
忽略 guard 的 writer、惡意 root、mount spoofing 或 I/O 掃描間的競態不在自動證明
範圍。沒有原子 filesystem snapshot、完整 runtime consistency 或 hostile-root isolation。

## Offline scope、ownership 與原始 metadata

Adapter 只讀取**已完成的 legacy backup**，不把 live `/opt` tree 交給 Collector。
`--installed` 僅作 filesystem headroom probe；`--target-source` 僅讀有界 VERSION。
Remote 目標身份來自 root 受保護的部署 metadata；direct 使用誠實 local identity。
舊 installed identity、尚未部署的 target operator claim 分別記錄，不宣稱 GitHub provenance。

受控位置為 `/root/clash-yaml-manager-sidecars/operations/<random-operation-id>/`，
分成 `source`、`collected`、`snapshot`；獨立 Catalog 在同根下的 `catalog/`，
與這三個資料根分離。目錄 root:root／0700；Collected／Snapshot／records 檔案 0600。
Adapter source 保留 captured ownership／mode，外層 root 私有；不 chmod/chown
live 或 legacy 物件。目的地使用新 128-bit operation ID，不覆寫或復用殘留。

配置只接受 root UID/GID；state 另可接受 root-controlled `.service-account` 與
trusted getent 身份共同核對的 clashyaml UID/GID pair，含 comment、home、shell。
不從任意 state owner 猜身份，不因 root 能讀而接受其他 UID；不建立系統帳戶。
新物件複製、雜湊重讀與 metadata 設定採 descriptor-relative no-follow、exclusive
create；拒絕 symlink、unsafe hardlink、特殊物件、跨 filesystem 與來源變更。

使用既有 `updater-sidecar-v1` allowlist：必要 `.env`、VERSION、Default、state/auth，
條件 INSTALLATION／service marker，已審閱 persistent JSON、Fixed revisions/cache、
GeoIP opaque bytes。Unknown paths/envelopes 拒絕，不能省略後宣稱完整成功。
venv、code、uploads、outputs、backups、logs、Nginx、憑證、系統依賴，以及已知
locks／scratch 不收集；legacy 五個 unit 額外明列 LEGACY_ONLY_UNIT，仍留在 legacy。

Collector 原 scope／ownership ledger 保留原格式。Adapter 另加入 digest-covered 的
`UPDATER_CAPTURE.json`，明列 legacy omissions、quiet evidence、身份與 captured
UID/GID/mode／source roles。三種 metadata 明確分開：

1. `UPDATER_CAPTURE.json` 是 **legacy captured metadata**，不是 live filesystem metadata。
2. `SOURCE_OWNERSHIP.json` 的 original entries 是 **Adapter offline source metadata**。
3. Manifest v1 描述的是 **最後 stored representation metadata**。

Legacy state 外層是 helper 新建的 root 0700，與 live state 原目錄的 UID 不等價；
子項的 cp -a metadata 保留。早期配置／venv 與後期 quiet state 分階段捕捉，
不能宣稱同一原子時間點。Generated capture file 是 Adapter metadata，沒有冒充
Collector 曾對它作 source collection。Writer 的 FULL_TREE 僅覆蓋最後 representation
與這些私人 metadata，不是全 VPS／完整 rollback／業務 closure；不自動套用 UID/GID、
ACL/xattrs、密碼、Session 或 token。來源前後 fingerprint 不比較 atime，也不重設它。

## Digest 與 Catalog

只有本次 Writer `CREATED` 且回傳合法 MANIFEST_SHA256，才可將該值交給
Verifier／Catalog register；再以受保護 record 呼叫 Catalog verify，要求
TRUSTED_SCOPE_VERIFIED、Snapshot identity、digest 與 operation association 一致。
不從已發布 Snapshot 重新讀 digest 冒充信任來源。
這是**同一可信 root 操作中的 Writer handoff**，不是獨立外部見證、signed provenance
或 off-host DR。Snapshot／Catalog 的發布不是原子雙重交易。

## 預算與磁碟全域條件

Collector 不變：512 entries、depth 8、16 MiB/file、64 MiB stored、256 MiB reads、
10 秒合作式預算；Writer／Verifier／Catalog 也保留原上限。Adapter 的來源階段
另受相同有界掃描／copy limits，為 generated metadata／manifest 預留空間，重讀
新檔案 hash 並重新盤點 legacy；不截斷、不因超限省略後成功。最終 legacy 重查
仍服從來源階段的合作式 deadline；各工具自己的 budgets 沒有放寬。
Diagnostic commands 設定每次 5 秒等待預算（kernel 阻塞不保證硬性 wall-clock 上限）、systemctl output 8 KiB／jobs 64 KiB、ps 2 MiB／
8192 rows；這些是新的本機診斷界線，不改現有網路 timeout。

先查 Sidecar parent 與安裝 filesystem 的 available bytes/inodes，保守保留 1 GiB
後續部署餘量與三份最大 64 MiB Sidecar 空間；每個 pipeline stage 及返回前再次
確認至少部署餘量。沒有原子 reservation 或任意 hardware／filesystem SLA。
不足即全域阻擋，禁止為騰出空間刪備份。既有 Writer 的 generic IO refusal 可能把
ENOSPC 歸為 READ_FAILED；因此所有不明 IO／READ_FAILED 一律 blocking，
不改 Writer、不把它當可忽略的 OPTIONAL failure。這個保守模型會拒絕部分其他 IO 失敗。

## 結果、failure matrix 與保留

JSON 分開列 LEGACY_BACKUP_STATUS、SIDECAR_STATUS、CATALOG_STATUS、
PUBLICATION_STATUS、CLEANUP_STATUS、UPGRADE_STATUS；permission-to-proceed
不是 upgrade completed。Shell 成功另列 APP_STEP_COMPLETED；remote metadata
仍需 parent 正常完成。Guard 75／78 在 hook 前拒絕，Sidecar 全部 NOT_RUN。
Legacy copy／pip／stop 失敗且 hook 未到達時，legacy 為 NOT_CONFIRMED，其餘 NOT_RUN。

| Failure | 結果與邊界 |
| --- | --- |
| Quiet／missing／unknown unit、known/manual writer、guard、source mutation／unsafe ownership | 全域拒絕；無 migration／new code copy，不造 quiet attestation。 |
| Collector unknown envelope/path、required missing、resource limit | 明確 subset refusal；STRICT blocking，OPTIONAL 僅在全域重查成功後允許繼續。 |
| Writer pre-publication／manifest／verifier failure、unsupported no-replace/FS | 不建立成功 anchor；依工具回報 NOT_PUBLISHED 或 PUBLISHED，STRICT 拒絕，符合全域 gates 才可 OPTIONAL。 |
| Snapshot published-but-unconfirmed／Catalog register/verify/full failure | 保留 Snapshot／可能 record，標示 failed/unanchored；不從現存 checksum 補造信任、不自動刪除。 |
| ENOSPC／headroom／generic IO/fsync | 全域阻擋，可能已發布的物件保留供人工核對。 |
| Cleanup failure | 工具只依自己的 inode ledger 清理本次 staging，失敗保留／報 CLEANUP_FAILED；Adapter 不自動清理私人 operation。 |
| Caught interruption／SIGKILL／crash | 不允許繼續；SIGKILL 沒有成功 JSON 時 shell 明列 UNCONFIRMED／publication UNCERTAIN。私人 staging 不等於成品，不能自動重用或 sweep。 |
| Destination collision | 不覆寫、不取得既有物件的清理身份，保留原物件。 |

Adapter 操作根一律保留，報 `RETAINED_PRIVATE_OPERATION_NO_AUTO_DELETE`；子工具
沿用自己的前／後發布 cleanup 契約。沒有 backup retention 或刪除 API。
Console 不輸出 .env、payload、password、token、bearer URL 或任意 exception。

## 驗證及未解觀察

隔離 tests 比較精確 START `874ab75b78d50a4941d5d0a2abb0ceba38ca9f13` 的 OFF
body、事件與 legacy bytes/mode/ownership。Linux root fixtures 使用真實 updater shell、
guard FD/flock、mixed numeric ownership、Collector／Writer／Verifier／Catalog；
systemd／account／network 是明確 command doubles，不操作主機真正 services/accounts。
另測普通／strict refusal、磁碟故障注入、metadata finalization lock、中斷與原生
kernel ENOSYS/no-fallback。macOS skip 不冒充 Linux PASS，最終需 exact-SHA Ubuntu RC。

Phase 3T-2 歷史首個 macOS 失敗為
`tests/test_backup_verify.py::test_noncanonical_or_traversal_paths[parent]`：預期
NON_CANONICAL_PATH，實際 BACKUP_CHANGED／NOT_VERIFIED／RESTORE_NOT_PROVEN。
始終沒有成功驗證。祖先 directory fingerprint 的並發變動是可能機制，舊 log
沒有足夠階段／inode 證據，**root cause unknown，保持開放觀察**。
後續通過不能宣稱已修復；本輪重跑 macOS 與 Ubuntu，任何再失敗即保留首個證據並 STOP。
沒有 xfail／skip／放寬該斷言／更改 Verifier 拒絕碼。

VERSION／Latest Stable 仍為 1.7.0／v1.7.0；沒有 SSH tim、production state collection、
deployment、restore、真實備份刪除、tag 或 Release。Session／Retention、其他 runtime
schema、Default 與部署工具的既有安全契約維持不變。READY 僅表示合成開發驗收，
不代表 production backup ready、完整 VPS consistency、rollback ready 或 restore proven。
