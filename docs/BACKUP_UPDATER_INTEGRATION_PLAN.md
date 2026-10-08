# Verified Backup：Linux 驗證與 updater 整合評估

v1.8.0 Phase 3C 為調查、合成驗證與設計階段，尚未發布；Latest Stable
保持 v1.7.0。本輪不修改 updater、uninstall、Writer、Manifest v1 或 verifier，
不存取 production／歷史真實備份，也不實作 collector、trust store 或 restore。

目前結論：**READY FOR PHASE 3D DESIGN/IMPLEMENTATION REVIEW**。
Phase 3C-R1 的 exact-SHA Ubuntu recovery RC 已通過完整驗證與真實 kernel ENOSYS／
Writer refusal gate；歷史失敗與本輪證據見下節。這僅允許審閱
**A：明確 opt-in、範圍受限的 verified sidecar**，不是 Phase 3D 已實作，也不是
production deployment approval。**B：取代 legacy updater backup 不相容**。
Sidecar 只驗證宣告範圍的 stored bytes，不能稱整個 updater backup 已驗證，
更不能稱恢復已證明。所有結果仍為 `restore_proven=false`。
本頁記錄 recovery RC 的已完成結果；文件更新後的 final candidate 仍須另行通過
exact-SHA Ubuntu RC。最終 SHA 與該 run 的 identity／結果由外部驗收報告記錄，
不預先宣稱尚未執行的 final candidate RC 通過。

## 既有契約與實際順序

已審閱 [Writer](BACKUP_WRITER.md)、[Manifest v1](BACKUP_MANIFEST_V1.md)、
[Backup Audit](BACKUP_READINESS.md)、[認證遷移](PHASE2.md)，以及
`scripts/backup_create.py`、`backup_verify.py`、`backup_manifest.py`、
`backup_audit.py`、`update.sh`、`uninstall.sh`、`scripts/deploy-common.sh`
與 `scripts/remote_lifecycle.py`。三種備份類型不是可互換的恢復格式。

`update.sh` 的既有順序如下；參照本 Phase 的 START commit
`19e6aab573387c70127ab59bfbe7dbfa0c091163`，不以未來變動行號作契約：

1. 預檢後，以 `umask 077`／`mktemp -d` 建立 root 私有 legacy backup。
   用 `cp -a` 保存存在的 VERSION、INSTALLATION.json、HTTPS metadata、
   程式／部署檔案、core、templates、static、scripts、venv、帳戶標記，
   五個 service／timer unit、`.env` 與 Default。此時 app 與 scheduler
   尚未停止；這批物件並非共同的原子時間點。
2. 在 live venv 安裝並檢查新版依賴，然後確保服務帳戶存在。
   之前保存的 venv 是回滾材料；此後 live venv 可能已改變。
3. `stop_refresh_units keep-enabled`、`stop_health_units keep-enabled`
   停 timer，再 `systemctl stop` oneshot。這不是僅等待自然完成的承諾；
   systemd stop 可以終止作業。App stop 受原 service 檔存在的條件控制。
4. 停止已知 writers 後，`backup_private_state` 以 `cp -a` 保存 state
   子項（含隱藏項），略過 `.proxy-probe-*`；接著才執行 `core.migrate`。
   Helper 建立 root-owned 0700 外層目錄，但子目錄／檔案仍保留原所有權。
5. 複製新版程式，保留既有 Default、`.env` 與 runtime 資料，更新 units
   並啟動服務／timers。升級保留 uploads、outputs、backups、logs，
   但這些不在上述 legacy updater backup 的複製清單。

Remote lifecycle 預設解析 GitHub Release 與精確 tag commit；明確 main channel
才解析 main commit。目標安裝 metadata 與下載來源另行核對，不能由 snapshot
類型名稱推導真實來源。備份中的 VERSION／INSTALLATION.json 表示舊 installed
identity；目標 Release identity 必須另外記錄。Manifest v1 不驗證 GitHub 來源。

Uninstall data backup 在停止服務／writers 與移除 units 後保存資料，再歸 root
並收緊權限；缺少程式、venv 與原 units，不能當完整 updater rollback。
UI overlay 只含局部介面材料，也不能冒充完整備份。Phase 2 的結構完整、
Phase 3A 的內部一致、獨立 anchor 比對與真實恢復分屬不同證據。

## 相容性矩陣

`COMPATIBLE` 僅表示符合該工具的輸入／bytes 驗證能力，不表示可恢復。
`CONDITIONAL` 的條件必須逐項成立；`NOT TESTED` 不以推測補成 PASS。

| 元件／用途 | 判定 | 條件與恢復後果 |
| --- | --- | --- |
| 已完成且 quiet 的 root-owned 普通程式目錄 | CONDITIONAL | 每個來源目錄屬執行 UID、無 group/world write；沒有 symlink、hardlink、特殊物件或跨 filesystem，符合所有資源限制。Stored bytes 可驗證，但執行位元與原 metadata 不由 Writer 保存。 |
| root 私有 legacy backup 外層 | COMPATIBLE | 典型 root 0700 外層符合來源要求；不因此推定所有後代符合。 |
| `clashyaml`-owned state 子目錄（若存在） | INCOMPATIBLE（直接輸入 root Writer） | `cp -a` 保留服務 UID 的子目錄；Writer 要求每個來源目錄屬執行 UID。單有服務 UID 的普通檔案不是這項 directory gate 的拒絕理由；不能從 root 外層推定所有後代安全。Root 執行不繞過此規則，不修改 live／legacy ownership 迎合工具。 |
| `cp -a` 的 ownership／mode／其他 metadata | INCOMPATIBLE（替代恢復格式） | Writer 新建目錄 0700、檔案 0600，記錄的是 stored metadata；不保存原 UID/GID、mode、ACL、xattrs、timestamps。Bytes 相同不代表 `cp -a` 等價。 |
| 新收集的 root-owned offline representation | CONDITIONAL | 需要獨立、安全、有界 collector 與 writer quiet 證據；詳細設計見下節。本輪未實作。 |
| 一般 Python venv | INCOMPATIBLE | `bin/python*` 常為 symlink；可能有 hardlinks／過多物件／深度／容量。Writer 不跟隨 symlink。排除 venv 會省略 payload，不是保存 recovery material。 |
| app／refresh／health 五個 unit 的 bytes | CONDITIONAL | 可放進 root offline representation；需記錄缺少的舊 unit。Manifest 不驗證 systemd 語義、帳戶、安裝路徑、enablement 或啟動結果。 |
| `.env` 與 auth migration 前 state | CONDITIONAL | 必須同一明確捕捉邊界、私有保存，不輸出內容；回滾須核對密鑰、認證版本與 session 影響。 |
| VERSION／INSTALLATION.json bytes | CONDITIONAL | 可驗證收集後 bytes；舊 installed identity 與新 target identity 分開，不冒充來源認證。 |
| Fixed registry／retired tokens／outputs 的業務關聯 | NOT TESTED | Registry integrity 不證明 output/revision closure；outputs 不在既有 updater 備份內。需另訂一致範圍與隔離恢復測試。 |
| 原始 systemd、Nginx、依賴與完整還原 | NOT TESTED | 本輪不啟動／恢復 production，不宣稱整機重建、帳戶還原或實際 routing 已驗證。 |
| 整份 legacy updater backup 作 Writer 直接輸入 | INCOMPATIBLE（一般情況） | 混合 ownership、venv links、資源及 metadata 復原問題；逐步收集時序也不是單一時間點。 |
| 既有手動 rollback | CONDITIONAL | 繼續使用原 legacy code、venv、設定與 units；保留最新 runtime data，state rollback 需人工核對版本與密碼，不以 sidecar 自動取代。 |

## Ownership 與 offline collector 設計

Phase 3D 若實作 A，collector 必須在 writers quiet 後，從明確 allowlist
收集到全新、root-owned 0700 的私有 offline tree，檔案為 0600。對每個來源
採 descriptor-relative、no-follow、普通物件／link count／filesystem／變更檢查，
限制數量與讀取 bytes。不得為適應 Writer 放寬來源目錄 UID 或安全路徑判準，
不得 chown production 或 legacy backup。

候選 subset 是 `.env`、Default、VERSION、INSTALLATION.json 與明確列出的
persistent state；最終 allowlist、必要資料關聯與 exclusions 必須在實作前
審閱。認證、Fixed、來源快取、Health／Policy／scheduler 的關聯不能因只是
「state-only」就忽略；`.proxy-probe-*` 只屬明列的 ephemeral scope omission。
不收集 venv，不聲稱包含 uploads／outputs／logs／外部 Nginx／憑證或整機環境。

新表示保存 file bytes 與收集後的安全 metadata；原 source UID/GID、mode、
執行位元、ACL/xattrs/timestamps 不在 Manifest v1 的 stored metadata 中。
若未來需要還原，另設有版本、root 私有、與 snapshot ID/digest 綁定的 source
role／original ownership-mode ledger 及 restore mapping；不擅自擴充 Manifest v1。
Numeric UID 不能直接套到另一主機，需核對服務帳戶與安裝標記；ACL 等未收集
項仍是明確限制。該 ledger 的格式／容量／可信保存也需獨立 review。

Writer 只接收已收集完成的 quiet offline tree，不直接指向 live 安裝。
其來源／stored bytes 重查是變更偵測，無法替代 filesystem snapshot 或對抗
惡意 root concurrent writer。Collector 未實作，因此本輪沒有新的 production
收集路徑，也沒有聲稱 ownership 或恢復映射已被驗收。

## Linux native gate

新增 `tests/test_backup_create_linux.py`，原 90 Writer、97 Manifest 與 62 Audit
tests 保持原樣。全部 fixtures 都是 test temporary directory 內的 synthetic data：

- 實際呼叫 Writer 的 Linux `libc.renameat2(..., RENAME_NOREPLACE)` 分支；
  在 wrapper 中觀察 inode identity，實際 fsync 普通檔案、staging 目錄與 parent，
  發布後再以既有 verifier 檢查。
- 另一個 Python 子行程在最終 publication 前建立空目的地。Kernel 拒絕覆蓋；
  既有目的地 inode／bytes 保留，Writer 只清理自己的 staging。
- 實際 descriptor-relative `O_NOFOLLOW` open 拒絕 file／directory symlinks，
  安全普通檔案的 fd identity 與 bytes 保持一致。
- 僅在獨立子行程設定 seccomp filter，讓 kernel 對 renameat2 回傳 ENOSYS。
  在 Writer 呼叫前分別記錄直接 syscall 與 libc wrapper 的 rc／errno；raw syscall
  必須精確為 ENOSYS，wrapper 也必須拒絕。再呼叫未改動的 Writer，要求拒絕發布、
  清理己有 staging、來源與既有目的地完整。普通 rename／renameat 設 SIGSYS
  tripwires，並由 forked grandchildren 實際觸發證明；Writer 必須在同一 filter 下
  正常回報 refusal。主測試行程／runner policy 不變，未新增 skip／xfail。
- 四個資源 profile 呼叫真實 copy、stored-byte scan、manifest、fsync、
  pre-/post-publication verifier；timing wrapper 不模擬成功或放寬限制。

`RENAME_NOREPLACE` 的支援也依 filesystem 而定；runner 成功不等於任意 Linux
掛載均支援。檔案 fsync 不自行保證 parent directory entry 的 durability，
因此明確同步 directory。這些測試不證明電力中斷、硬體故障或遠端 filesystem
的行為。[Linux rename 文件](https://man7.org/linux/man-pages/man2/rename.2.html)、
[fsync 文件](https://man7.org/linux/man-pages/man2/fsync.2.html)
支持這些 syscall 邊界。ENOSYS probe 使用 kernel 的 ERRNO filter，檢查 ABI，
並在 child 設定 no-new-privileges；[kernel seccomp 文件](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html)
說明其 errno 與架構條件。這是合成缺失能力測試，不修改主機系統政策。

最終 gate 使用既有 `release-candidate.yml` 的 `workflow_dispatch`。GitHub dispatch
API 要求 branch／tag ref，不能直接傳 commit SHA；dispatch 前核對 `main` 仍精確
指向最終 SHA，並將 checkout input `ref` 設為最終 40-character SHA，不用 floating
checkout。Run metadata SHA、checkout SHA、
`Validated commit SHA` 必須全部相等；等待 completed/success。若失敗，STOP，
不得透過擴大修改 Writer／updater 範圍繞過。本頁不會為填入 run URL 再變更已驗證 SHA。

## Phase 3C-R1：ENOSYS gate recovery 證據

| Run | 精確 SHA | 已完成結果 |
| --- | --- | --- |
| [37827445213](https://github.com/wwintj/clash-yaml-manager/actions/runs/37827445213)（Phase 3C） | `d35b01678b4f43550cc17c5530082734499907f0` | **FAIL**；3490 passed、1 failed。保留原 run，不改寫歷史。 |
| [37852424366](https://github.com/wwintj/clash-yaml-manager/actions/runs/37852424366)（Phase 3C-R1 recovery） | `2e87f27bafd996fa4f8368cee95f38afd4316d7c` | **completed/success**；3491 passed、0 failed，936.11 s；`LINUX_NATIVE_UNAVAILABLE: PASS`。 |

Recovery run 的 metadata head SHA、checkout SHA 與 `Validated commit SHA` 都是
`2e87f27bafd996fa4f8368cee95f38afd4316d7c`。實際環境為 Ubuntu 24.04、
x86_64、kernel `6.17.0-1022-azure`、Python `3.12.15`、glibc `2.39`。
macOS 本機完整 pytest 為 3483 passed、8 個 Linux-only skipped；跳過不當成
Linux 證據。Browser 21/21、static checks、validate-only 與 diff check 均 PASS。

原失敗是測試要求 `libc.renameat2` 的 errno 必須等於 raw kernel ENOSYS。
舊 log 未記錄實際 rc／errno，且失敗發生在 Writer 呼叫之前，不能把舊 run
描述成已量到 EINVAL 或已確認 Writer 缺陷。本輪同類 runner 的實測為
raw syscall `rc=-1 / errno=38 (ENOSYS)`，而實際 libc wrapper
`rc=-1 / errno=22 (EINVAL)`；兩者都拒絕。
[glibc 2.39 renameat2 原始碼](https://github.com/bminor/glibc/blob/glibc-2.39/sysdeps/unix/sysv/linux/renameat2.c)
中的條件分支會在 nonzero flags 的 kernel ENOSYS 後改設 EINVAL。
因此修正的是 wrapper 與 kernel errno 相同的錯誤假設；保留精確 raw ENOSYS，
再驗證 Writer 實際使用的 wrapper 與真實 Writer，沒有只測 raw syscall。

獨立檢查與實測證據如下：

- `AUDIT_ARCH=0xc000003e`；`sock_filter` 8 bytes、`sock_fprog` 16 bytes，
  pointer offset 8、little endian。BPF 先讀 arch，正確架構跳到 syscall load；
  不符則 KILL_PROCESS。匹配 renameat2 才回 `SECCOMP_RET_ERRNO | 38`，
  其餘普通 rename tripwires 後才 ALLOW，未發現原架構或 jump offset 錯誤。
- 實際 syscall numbers：renameat2 `316`、rename `82`、renameat `264`，
  由 runner 系統 header 解析，與
  [Linux x86_64 syscall table](https://raw.githubusercontent.com/torvalds/linux/v6.17/arch/x86/entry/syscalls/syscall_64.tbl)
  一致。aarch64 分支僅做靜態審閱，沒有宣稱 ARM Linux native PASS。
- `PR_SET_NO_NEW_PRIVS` 與 `PR_SET_SECCOMP` 都是 `rc=0 / errno=0`；
  getter 確認 NNP state `1`、seccomp mode `2`。直接 syscall 的實測 ENOSYS
  證明 filter 確實攔截預期 syscall；安裝失敗不忽略。
- `ctypes.CDLL(..., use_errno=True)`，各 rc／errno probe 前 reset errno，返回後立即
  `get_errno()`；generic syscall 使用 `c_long` return 與明確 variadic argument
  types，wrapper 使用其實際 C signature。PRE_WRITER bounded JSON 在任何
  Writer 呼叫前 flush，只含固定技術欄位，沒有 source payload 或任意路徑。
- 兩個 forked grandchildren 的實際 rename／renameat syscalls 均被 SIGSYS 終止，
  證明 no-fallback tripwires 生效；core limit 只在 child 與其 descendants 設定。
  在同一 filter 下，未改動的 `writer.create(...)` 實際執行並正常回報
  `FAILED / NOT_PUBLISHED / NO_REPLACE_UNAVAILABLE`，不是 mock。
- Cleanup `CLEANED`、目的地未產生、無本次 staging；來源 bytes／重要 metadata、
  既有 empty target 與 unrelated synthetic backup 保持完整。
  `restore_proven=false`、沒有成功 manifest digest。Writer、verifier、Manifest v1、
  updater 與 runtime 均未修改，沒有 production 存取／restore／真實備份刪除。

[Kernel seccomp 文件](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html)、
[generic syscall 文件](https://man7.org/linux/man-pages/man2/syscall.2.html) 與
[Python ctypes 文件](https://docs.python.org/3.12/library/ctypes.html)
分別支持 filter／inheritance、raw syscall 路徑與 errno handling 的檢查。
本輪沒有發現需要修改 Writer 的缺陷。這個合成 unavailable-syscall gate 不證明
production filesystem、off-host disaster recovery 或 restore。

## 資源可行性

現有限制不變：4096 objects（含 root 與 manifest control file）、12-level depth、
128 MiB/file、512 MiB total content、manifest 最多 2 MiB。普通 entries 至多
4094；total 包含 payload 與 control bytes。Writer 的 10 秒 cooperative budget
涵蓋掃描、copy、stored-byte 重讀、manifest、fsync 與兩次 verifier；不是只計
copy。各 verifier 也有自己的限制，Writer 在呼叫前後仍檢查整體 elapsed time。
Kernel I/O／解析不能硬中斷；10 秒不是最壞 wall-clock 保證。

令 payload 為 S、canonical manifest 為 M：copy 讀 S／寫 S；manifest 建立
重讀 stored S；pre-verifier 與 post-verifier 各讀 S+M。最低內容讀取約
`4S+2M`、寫入 `S+M`，合計約 `5S+3M`，另有 metadata scans、hash CPU 與每檔
fsync。Collector 還需另一輪 read/write；其時間不在 Writer 開始後的 10 秒內，
但計入 updater outage。64 MiB payload 即約 320 MiB aggregate content I/O；
接近 512 MiB 的 payload 還須留 control 空間，約 2.5 GiB I/O 在 10 秒內完成
所需最低頻寬並不足以保證成功。很多小檔的 fsync／metadata 成本也不可忽略。

本輪 macOS arm64／Python 3.12.14 的單次 warm-cache synthetic 測量如下。
不包含 fixture 建立；包含完整 Writer 呼叫，無 production throughput／SLA 宣稱。
`manifest` 時間包含 stored-byte 重讀與 canonical generation。

| Profile | files / objects | Payload | Copy s | Manifest s | Pre-verify s | Post-verify s | Directory sync s | Total s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small-config | 32 / 35 | 128 KiB | 0.004294 | 0.001268 | 0.001410 | 0.001649 | 0.000022 | 0.011905 |
| state-shaped | 128 / 131 | 4 MiB | 0.019891 | 0.005496 | 0.005880 | 0.006868 | 0.000023 | 0.040598 |
| byte-heavy | 4 / 7 | 64 MiB | 0.050687 | 0.024459 | 0.024206 | 0.024345 | 0.000025 | 0.125168 |
| object-heavy | 4000 / 4003 | 250 KiB | 0.471211 | 0.180169 | 0.152218 | 0.172470 | 0.000103 | 1.021835 |

四者皆 CREATED，但無 trust anchor／restore 證明。Linux RC 會輸出同樣四組
`LINUX_SNAPSHOT_BENCHMARK` records，實際數字另存最終驗收報告。若 profile
達 TIME_LIMIT，測試要求明確 refusal 與相應清理／保留行為，報告不得把 refusal
當成 snapshot 成功。Linux 與 macOS 的資料不得相互冒充。

| 用途 | 可行性 |
| --- | --- |
| 小型 offline configuration | CONDITIONAL：安全物件、ownership、全部 budgets 與 quiet 邊界成立時適用。 |
| state-only subset | CONDITIONAL：需 collector、業務 closure、容量與耗時檢查；名稱為 state 不代表天然小或完整。 |
| 完整 updater backup | INCOMPATIBLE：不只效能問題，還有 mixed ownership、venv、metadata 與分階段 capture。 |
| venv-inclusive snapshot | INCOMPATIBLE（一般 venv）：symlink／容量／物件數以及執行 metadata；不得擴大限制或跟隨 links。 |

Preflight 的預估無法保證實際 syscall 時間；超限仍安全失敗。沒有真實 production
資料測量，不能據此承諾特定 VPS 的容量／停機時間。

## A 與 B、捕捉一致性邊界

**A** 保留 legacy backup 的路徑、`cp -a` 內容、venv 與既有 rollback 完整不變，
另在 root 私有、獨立位置保存明確 subset。預設 off，操作者 opt-in 選 optional
sidecar；若未來提供 strict sidecar gate，必須另有明確選項，不改既有預設升級
契約。Sidecar 的成功只表示其新收集 scope 的 integrity。

**B** 丟失原 ownership／mode／venv recovery material，與既有 rollback 不等價。
Exclusion 會略過 venv payload；`FULL_TREE` 也只指傳入的新 source tree，不能
證明完整安裝。因此本設計拒絕 B，不以「已排除 venv」包裝成完整驗證。

候選整合點是 `backup_private_state` **完成後、`core.migrate` 之前**，並新增
正面確認 app、refresh timer/oneshot、health timer/oneshot 均 quiet 的 acceptance
gate。App unit 檔不存在不能作為 app 已停的證據；不得僅停 timer 就開始。
需要 deployment exclusivity 與外部 manual CLI／root 編輯者的 quiet 約定；
fingerprint 重查不能保證任意管理員不再寫入。

在此處 collector 新收集宣告的設定／persistent state，完成 offline representation
後才交 Writer。這能宣告該 subset 在受控 quiet interval 捕捉，不能宣告全 filesystem
原子 snapshot。之前保存的 legacy code、units、`.env`、venv 與之後保存的 state
仍分屬不同時點；live venv 先前已更新，不能冒充原依賴。範圍外 outputs 等資料
不因 sidecar 完成而取得一致性或恢復證明。

未來記錄原 timer enablement／activity 與 policy，sidecar failure/cleanup 必須
回到原 updater 的 lifecycle 控制路徑，不新增 enable／disable 或改 scheduler
policy；相容既有 upgrade 行為另以 command-double tests 確認。本 Phase 不停止
任何服務，也不修改現有 timer policy。

## 獨立 trust anchor 生命周期（設計，未實作）

在 snapshot／collector tree 外設 root-owned 0700 catalog，records 0600。
Record 包含有版本的 schema、隨機 snapshot ID、canonical manifest SHA-256、
scope profile/version、固定 type、capture/update operation ID、capture time、
舊 installed identity 與另列的新 target identity。Snapshot-to-digest association
以受保護 catalog 的 ID、限定 private root 下的生成名稱及 digest 明確绑定；
inode 可作本機 audit 證據，不是跨主機 portable identity。

只在 Writer CREATED、post-verifier 通過後接受 digest handoff。Record 用 exclusive
temporary file 寫入、flush／file fsync，以 no-replace atomic publication 發布，
再 fsync catalog directory。Snapshot 與 catalog 位於不同位置，兩次發布不是
跨目錄原子交易：snapshot 成功而 anchor 失敗必須標為 retained/unanchored，
不得將 snapshot 內的 digest 再讀出當作獨立 trusted anchor。

建議設計上界是每 record 16 KiB、最多 128 records，具體 schema／bounds 在
Phase 3D review 後才實作。達上限不自動刪除備份或 anchor；需要操作員另行
授權 archive／retention 行為，snapshot 留存期間保留對應 anchor。Crash／孤兒
records 以明確 operation ID 對照，不靠 glob 猜測並刪除舊備份。

Console 只輸出固定 status/codes、非秘密 ID、必要 count 與 manifest digest；
不輸出 `.env`、credentials、state payload、bearer URLs 或任意 exception/path。
Anchor digest 仍需由 catalog 的受信來源取得。Same-host root protection 能防止
服務帳戶修改，不能抵抗 root compromise 或主機／磁碟遺失；不是 off-host
disaster recovery。加密外部保存與獨立 anchor 備援屬另外的未驗證工作。

## 失敗與 rollback policy

既有 legacy backup 失敗仍是 blocking。Optional sidecar 的普通失敗只在 legacy
backup 已成功、必要 writers quiet／部署安全 gate 成立、磁碟 headroom 足夠時
可回報 optional-feature failure 並繼續；strict opt-in 則在 migration／新 code copy
前停止。不得自動 downgrade、restore 或刪除 legacy backup。

| 事件 | 明確行為／blocking 邊界 |
| --- | --- |
| Writer 發布前失敗 | 回報 NOT_PUBLISHED；只依自身 inode ledger 清理 staging。Cleanup 失敗則保留私有 residue 並報固定 code。符合上述條件時 optional；strict blocking。 |
| 發布後失敗／post-verification failure | 保留 published destination，標示 unconfirmed，禁止建立成功 anchor 或 VERIFIED 宣稱；不以清理名義刪除。Optional/strict 邊界同上。 |
| Pre-verification／stored-byte mismatch | 禁止發布成功，走前述清理邊界；不修復／截斷 snapshot 假裝通過。 |
| ENOSPC／fsync failure | Sidecar 不成功；若磁碟不足影響 legacy backup 或後續部署 headroom，屬全域 blocking，不能因 optional 而忽略。可能發布的 snapshot 保留並標未確認。 |
| Permission／unsafe ownership／path failure | 不 chmod/chown legacy 或 live tree；sidecar refusal。涉及 collector/source authenticity 或 global deployment invariant 時 blocking。 |
| renameat2 不支援／ENOSYS／filesystem 不支援 | Refuse，不 fallback 到可能覆蓋的 rename。可為 optional-feature failure；strict blocking。 |
| 數量／深度／bytes／time 上限 | 拒絕，不擴大 limits、不靜默排除 payload；optional refusal 或 strict blocking。 |
| Timer／oneshot／app／manual writer conflict | Quiet gate 不成立，blocking；不能建立「consistent」sidecar，也不能把不安全 capture 當普通 optional failure。 |
| Staging 時 crash | 新私人 staging 不是已發布 snapshot；重新開始不得覆蓋既有目的地。殘留清理需確定己有 identity／operation ledger，另行 review，不刪 unrelated backup。 |
| Snapshot 完成、anchor record 失敗／catalog 滿 | 保留未錨定 snapshot，報 optional failure 或 strict blocking；不借用 snapshot 自有 checksum 充當外部信任。 |
| Legacy 成功、sidecar 失敗 | Legacy 完整保留；僅在 optional 明確選用且 global gates 成立時繼續，回報兩者不同結果。不得宣称完整 verified rollback。 |

Rollback 沿用原人工邊界：先停止所有 writers，核對版本、恢復 legacy code／venv／
設定與原 units，再核對依賴／帳戶。保留最新 runtime data；若要回滾 state，
另核對 auth、password、session、Fixed revisions、retired tokens、outputs 與版本
相容性。恢復舊 auth 可能使舊 session 再有效。Sidecar integrity 不授權自動還原，
本輪 `RESTORE: NOT RUN`。

## 剩餘 blockers 與 Phase 3D acceptance

| 等級 | 判定與下一步 |
| --- | --- |
| HIGH | B／完整 legacy replacement 不相容，拒絕該方向。全量業務 closure 與完整 restore 未驗證，禁止相應宣稱。A 的實作必須先通過 final exact-SHA Ubuntu gate；若 native syscall／Writer 缺陷浮現，本 Phase STOP。 |
| MEDIUM | A 的 collector、quiet/exclusivity gate、scope allowlist、ownership ledger、獨立 catalog 交易／crash／retention 尚未實作；這些是 Phase 3D 必須完成的工作，不能省略。資源 refusal 與不同 filesystem 支援需保留，warm-cache 不提供 production SLA。 |
| LOW | 真實 VPS performance、off-host DR、實際 restore／電力故障均 NOT TESTED；不在此次合成完整性／設計 gate 的宣稱中。 |

Phase 3D 只能在另行授權後實作 A，acceptance 至少包含：

1. Opt-in default off、明確 optional/strict failure contract；原 legacy backup paths、
   bytes、ownership、venv、units 與 rollback 材料不變。禁止用 sidecar 取代它。
2. 根據明確 bounded allowlist 新建 root offline representation；不弱化 no-follow、
   UID、link 或 budgets。缺項、排除範圍與 source role 可解讀；不擴充 Manifest v1。
3. 在 legacy state backup 完成後、auth migration／code copy 前，驗證所有 writers
   quiet 與 deployment exclusivity；測試 timer conflict、缺少 unit、manual writer、
   exception recovery，保持原 timer policy。
4. 獨立 catalog 的 digest association、atomic no-replace／fsync、容量、transaction
   failure、crash orphan 與受保護 retention 測試；不自動刪 legacy backup／restore。
5. 覆蓋前／後 publication、ENOSPC、permission、unsupported syscall、limits、
   verification／cleanup／anchor failure；原 updater 的既有失敗契約不減弱。
6. Synthetic Linux 與 lifecycle command doubles、完整 pytest、browser 21/21、
   static／validate-only、exact-SHA Ubuntu RC 通過；沒有 production access／credentials
   洩漏。Production rollout 與 restore acceptance 各需另行授權。

目前的「READY FOR PHASE 3D DESIGN/IMPLEMENTATION REVIEW」僅適用於上述
受限 A 設計；recovery gate 已取得真實 Linux 證據，文件更新後的 final candidate
仍需 exact-SHA Ubuntu PASS。Phase 3D 實作另需授權；不是 integration 已存在、
production 部署就緒、complete backup verified 或 restore proven。
