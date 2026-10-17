# Phase D2：獨立唯讀相容性評估（開發預覽，自 v1.9.0 起提供）

D2 在可信工具 checkout 中使用標準庫，復用 Phase C 的 descriptor-relative／no-follow IO、canonical Manifest、獨立 Record digest、Package 內容及私人目錄退出復核。它只分析操作者明確準備的離線 Package 與 `synthetic=true` Target；不是 live production probe、Restore Apply 或完整 runtime closure。

```bash
python3 -B -m scripts.recovery_assess --id <operation-id> --target-fixture /private/offline-target
```

固定沿用 Phase C root-private managed namespace；沒有 root／provider／管理路徑的 CLI 或環境覆寫。工具必須來自獨立可信 checkout，不能執行 Package 裡的工具。報告寫到 stdout，操作者若保存須自行使用私人 0600 檔案。未完成或證據不足返回非零，不寫入 Package、Record 或 Target。讀取可能更新 atime；不變性保證涵蓋內容、inode、mode、ownership、mtime／ctime，而非 atime。

## 受限策略與成功標誌

獨立 policy v1 限定 SAME_HOST、SAME_INSTALL_PREFIX、EXACT_TRUSTED_APPLICATION_IDENTITY，並保留 live state、.env/Auth、runtime、units 及外部元件。這與 Phase C 原有 APPLICATION／VENV／CONFIGURATION／DEFAULT／UNITS 材料清單不同；沒有改寫 Phase C 的輸出或授權。

四個完整性與 Record 信任標誌只在全部安全 FD 退出檢查完成後發布。任何安全拒絕均清除成功標誌。即使 integrity 通過，`RUNTIME_REQUIREMENTS_READY`、`RESTORE_PLAN_READY`、`RESTORE_PROVEN`、`RESTORE_APPLY_IMPLEMENTED` 仍為 false。

目前 Package 的捕獲 host binding 只是操作者聲明，不能獨立證明 SAME_HOST。正常合成評估可以完成而返回 `ASSESSMENT_BLOCKED`、`ASSESSMENT_SUPPORTED=false`；不能以合成 fixture 填補可信證據取得 true。Runtime／State 最多 PARTIAL。此限制不表示拒絕分支未執行。

## 證據來源

| 分類 | 真正來源及限制 |
| --- | --- |
| OBSERVED_TRUSTED_HOST_FACT | 可信 assessment 程序的 OS／architecture／Python／SOABI；只描述目前 interpreter，絕不冒充 Ubuntu 服務 Target |
| VERIFIED_PACKAGE_FACT | 真實 IO／Verifier 通過的 Package bytes 與 link metadata；不是 Release provenance |
| VERIFIED_TRUSTED_RELEASE_FACT | 工具內先前獨立接受的 Stable annotated tag object／commit pin（目前為 v1.8.0、v1.8.1、v1.8.2），加上本地唯讀 Git immutable blobs；只涵蓋 application bytes |
| STATIC_DERIVED_FACT | bounded DATA 解析結果；不是 loader、ABI closure 或業務可恢復性 |
| OPERATOR_DECLARED | Manifest runtime、帳戶、host 等聲明；未觀測 |
| SYNTHETIC_DECLARED | Target environment.json；不能提升為真正 host 證明 |
| UNKNOWN／UNSUPPORTED | 未捕獲、不能安全推導或超出支持範圍 |

沒有網路請求；獨立 Release pin 不由 Package digest、版本名稱或輸入檔案提供。Pin 未知時保留 UNKNOWN；pin 已知但 application bytes 不一致時拒絕。Release 缺失不自動下載。可信系統 Git 使用隔離環境、禁止 hooks／replace／lazy fetch，不執行備份程式。

報告綁定 schema、policy digest、接受的 baseline commit 加實際 scripts source digest、operation ID、Package／Record dev/inode、Manifest／Record digest、Target exact identity、Target metadata/content inventory digest、證據來源／取得時間／digest。未提交候選 digest 不冒充 commit SHA。證據分類接口不允許 synthetic／operator source 標為 trusted observation；測試只在受控程序中替換 fixture policy，不存在產品繞過入口。

## 第一層 Runtime 排除

pyvenv.cfg 要求唯一、已知且有界欄位；檢查 version、home、executable 和 include-system-site-packages。初始僅支持 `/usr/bin`／`/usr/local/bin` base interpreter 聲明，system site packages 明確 UNSUPPORTED。link closure 沿用既有規則，外部 interpreter 只對 Target 聲明核對，不能證明實際存在。絕對 Python script shebang 必須符合聲明的 install prefix。

Wheel 基本 headers／tags、METADATA 基本欄位與 ELF64 header／machine 只排除明顯錯誤。未知組合 fail-closed；複合 tag／其他 native format 未支持。ELF machine、SOABI 名稱或 Wheel tags 一致不能證明 CPU 指令、libc／符號版本、動態載入路徑、完整 dependency closure。這些持續 UNKNOWN。

`.pth` 的 executable import、sitecustomize／usercustomize 明確拒絕；其他 path-only `.pth` 只是資料，路徑解析仍 UNKNOWN。不執行備份 Python、app、pip、shell 或 .env；不 import Store、不使用 ldd。

## State 關聯範圍

只支持 exact application identity 的合成 DATA；跨版本／commit Target 先拒絕。Auth instance 必須一致，version 不得回退，同 version hash 不得改變；live Auth／.env 不恢復。Fixed 初始支持 v6，revision base/current、uploaded／remote cache 必須存在，重複或 retired active token 拒絕，既有 retired digest 不得消失，失去的舊 token 必須有退休證據。同 immutable revision/cache 路徑 bytes 不一致拒絕。

Temporary Link 結構／current output references 與舊 tombstone 保留；Package 未捕獲 archived outputs，所以其存在 UNKNOWN。GeoIP metadata／active.mmdb size/hash 關聯；Health v2 的 Fixed ID、fingerprint 形狀與 scheduler 邊界；Notifications／Login Attempts 的有限形狀及時間檢查。未知 State 路徑拒絕，不遷移、不補預設、不清理。

YAML/cache 的完整業務語義、health fingerprint 對 YAML 節點的完整對應、notification transport、所有隱含配置依賴仍未證明。因此 State closure 不等於完整 state compatibility；合法舊 schema 但不在本次子集者 UNSUPPORTED。

## 資源、安全及未實作能力

繼承 4,096 Package entries、16 層、128 MiB/file、512 MiB/Package、8 MiB Manifest、60 秒 cooperative budget；Target 512 entries／16 MiB、environment 32 KiB。D2 selected analysis 最多 32 MiB、單檔 8 MiB，text 64 KiB、State JSON 1 MiB、每 mapping 4,096 項、128 checks、64 KiB canonical 報告。Tool source 最多 512 scripts、8 MiB/file、64 MiB total；Release blobs 同樣有單檔／總量／數量界限，Git 每次最多 5 秒並共享整體 budget。超限拒絕，不截斷成功。

Package、Record、Target 在返回前重新驗證；持續的 metadata/content/path 改變、EIO 等錯誤 fail-closed。不 chmod/chown、不刪除、不修復輸入。不是原子 Snapshot、writer freeze 或惡意 root 隔離；瞬時 ABA 和觀測後變更不能因此視為完全解決。

ACL／xattr／capabilities 永遠 `EXTENDED_METADATA_NOT_CAPTURED`，原樣 `EXACT_FILESYSTEM_RESTORE_UNSUPPORTED`。目標未發現 metadata 不能補造歷史 absence。未來 POSIX-policy reconstruction 需另外授權；目前無重建／Apply／journal／自動 rollback／Prune／Timer。Legacy Backup 與 Sidecar 預設 OFF 不變。

Mac 合成測試不代表 D2 Linux-native 已驗收。歷史 Gunicorn disconnect 與 Browser HTTP 400 仍 UNKNOWN／NOT_FIXED。
