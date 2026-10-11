# Independent Backup Verification & Restore Readiness — Phase C

此為本地離線開發候選，未發布、未部署。Phase B 已由使用者有條件接受供本地開發；歷史 Browser `/process` HTTP 400 仍為 `HISTORICAL_BROWSER_400_ROOT_CAUSE_UNKNOWN`，不是已修復。原永久失敗診斷保留。Linux 原生驗收尚未執行。

## 可信工具與唯讀命令

在可信且獨立保存的工具 checkout 執行 `python3 -B -m scripts.recovery_inspect`。只依賴 Python 標準庫及可信工具模組，不需要 Flask、Gunicorn 或被備份的 venv，不 import／執行包內程式、shell、`.env` 或 interpreter。不要從待驗包啟動工具。沒有全域安裝、副作用命令、管理目錄／UID 環境 override。

```bash
python3 -B -m scripts.recovery_inspect list
python3 -B -m scripts.recovery_inspect status
python3 -B -m scripts.recovery_inspect verify latest
python3 -B -m scripts.recovery_inspect verify --id <32-lowercase-hex>
python3 -B -m scripts.recovery_inspect restore latest --dry-run --target-fixture /private/offline-target
```

管理根沿用 Phase B 的固定 root-owned `/var/lib/clash-yaml-manager-upgrade-backups`，只讀已有 `packages`／`records`，不建立任何目錄。開發測試僅以可信 in-process fixture policy 指向合成資料；不建立真實 `/var/lib`、`/opt` 或 `/root`。`--target-fixture` 只接受明確的私人離線合成目錄，拒絕上述三個 live 路徑範圍。安裝路徑欄位僅比較字串，絕不據此開啟 live installation。

`list`／`status` 只列合法 Record ID，**不表示已驗證**；顯示孤立 Package／私人 staging 數量，不納管、不刪除、不推論整體升級成功或 retention。`latest` 對有界 Record 集合全部驗證後，以 capture ended_at 加 ID 排序選擇；不是最新成功升級，也不是自動 restore 選擇。任何集合內驗證異常即拒絕，不跳過損壞 Record。未完成 Record staging、未知名稱明確拒絕。

## 驗證層次

沿用原 canonical／schema → 獨立 Record digest → 全部 Blob → installation identity／Record binding 順序。新增有界私人樹盤點、same-device 檢查、驗證後 metadata 重盤點、全內容重讀與 Record 再讀。原 Verifier、Writer、Manifest、Sidecar／Catalog 拒絕規則不變。

| 狀態 | 意義 |
|---|---|
| STRUCTURAL_VALID | managed-upgrade-v1 schema、路徑、必要 entries、directory closure、原始 role／mode／UID/GID、venv link metadata 符合契約 |
| CONTENT_INTEGRITY_VALID | 所有普通 Blob bytes 的大小／SHA 與 manifest 相符，VERSION／INSTALLATION.json 互相綁定 |
| MANAGEMENT_RECORD_MATCHED | 外部私人 Record 與 operation、source／target／installation、package dev／inode 一致 |
| TRUST_ANCHOR_VERIFIED | 符合 Phase B 同機 root-private Writer digest handoff；不是惡意 root 防護、簽章 provenance 或異地 DR |
| RUNTIME_REQUIREMENTS_READY | 本階段維持 false；合成描述吻合不是 host ABI／dependency 證明 |
| RESTORE_PLAN_READY | 本階段維持 false；尚有明確 prerequisites／blockers，沒有可執行 Apply |
| RESTORE_PROVEN | 永遠 false；沒有做實際恢復演練 |

失敗保守不提升驗證旗標。Manifest 自校驗不能建立 trust anchor；缺少 Record 拒絕。Record 可在同機以 root 權限修改，因此工具不聲稱可識別能同步偽造 Package 與 Record 的惡意 root。Capture 只代表操作者 quiet 聲明、前後盤點，非 systemd quiet 證據或原子 snapshot。來源／目標 Release identity 綁定是離線一致性，不查 GitHub、不下載包、不驗證 Release 簽章。

## 合成目標契約

目標根及全部目錄必須可信 root-owned `0700`，普通檔案 `0600`、單一 hardlink、same filesystem。拒絕 symlink、special object、未知頂層項目；允許 `environment.json`、`state`、`configuration`、`uploads`、`outputs`、`backups`、`logs`、`bin`。所有讀取採 descriptor-relative no-follow，受資源預算限制，前後盤點和全檔兩次 hash，不輸出 bytes。讀取可能更新 atime；內容、mode、owner、mtime、ctime、inode 不得變更。

`environment.json` 為 32 KiB 以下 canonical JSON、精確欄位：

- `schema_version:1`, `synthetic:true`。
- `runtime:{os,architecture,python_version,python_abi,system_libraries}`；前四欄可為 null，代表 UNKNOWN。字串有界，system_libraries 最多 64 項。
- `accounts:{root:{name,uid,gid},service:{name,uid,gid}}`，名稱 root／clashyaml；比較捕捉 role 的完整身份，不建立帳戶。
- `install_path`、`current_identity:{version,channel,commit,tag}`；比較原安裝綁定及版本，不從 semver 推論 state 相容性。
- `units`：固定五個 unit 名稱的子集；`external_python`：受允許的外部 Python 路徑列表，只比對，不執行。
- `free_space_bytes`：非負整數聲明；`filesystem_metadata`：UNKNOWN／POSIX_ONLY／EXTENDED_PRESENT。

以上都是**合成離線聲明**，不是 getent、systemd、磁碟保留、ABI 探測或依賴動態載入證據。工具逐項報 MATCH／MISMATCH／MISSING／UNKNOWN；任何未知不可宣稱 READY。`state/auth.json` 必須存在；工具只作資料式最低 auth shape、已知 state version／部分容器 shape 檢查，不載入 business store 或執行遷移。其他 state closure、Fixed revision／cache、GeoIP 語義、撤銷狀態及 exact code compatibility 尚未證明，始終 UNKNOWN；明顯非法 schema 另報 INVALID_STATE_SCHEMA，絕不轉為兼容。

## Dry-run 與缺口

預設 `PRESERVE_LIVE_STATE`。計畫列出 ID、current／restore／upgrade target version、驗證層次、磁碟需求下界、未來應停的 unit、擬恢復 material roles、原位保留的 state／uploads／outputs／backups／logs／bin、相容性、缺失 prerequisites、人工決策與 blockers。磁碟下界為兩份 payload 加 manifest reserve，不代表保存真實 current scene 的容量或 reservation。

`.env` 與 auth／Session／URL 撤銷邊界須人工確認；不直接覆蓋舊 credentials／state。ACL／xattr／capabilities 沒有捕捉、omitted runtime components 未驗證、ABI／系統 libraries／外部 Python 未實測、Linux-native 未驗證，均明確阻擋。即使所有宣告比較 MATCH，回報 PLAN_BLOCKED、executable=false。這是有用的前提清單，不能當作 Restore Apply 已經可以執行。

stdout 僅固定 codes、受 schema 約束的版本／ID／時間、固定分類／unit 與 counts；不含 input path、system_id、UID/GID、library 原文、password、token、cookie、URL、hash credentials 或完整 HTML。錯誤只回固定安全碼，不印原始 OSError／配置。拒絕時不修復、不刪除、不覆寫任何資料。

## 私人目錄退出檢查（C-L2 本地候選）

管理根、`packages`、`records` 及套件私人目錄在進入與正常退出時，均使用保留的 FD 核對 directory type、精確 `0700`、可信 UID/GID、device/inode；退出再以 parent FD 的 no-follow stat 比對原路徑身份。祖先 FD 同樣保留並重新檢查既有 owner／不可群組或其他使用者寫入策略（root-owned sticky 目錄沿用原例外）。Record 的兩次有界讀取綁定同一份原始 fingerprint；相同 bytes 的不同 inode 也拒絕。

私人目錄權限或 ownership 不合法回 `UNSAFE_STORED_METADATA`；路徑或觀察身份改變回 `OBJECT_CHANGED`；不安全祖先沿用 `UNSAFE_ANCESTOR`／`UNSAFE_PATH`。所有退出檢查成功後，才提升 VERIFIED 與 trust 旗標。拒絕不自動 chmod/chown、刪除或重試。

這是有界入口／退出觀察，並非持續凍結。目錄比較不要求 size、nlink、mtime、ctime 全部固定，因共同 IO helper 也供 Writer 合法建立 entries；C 另保留套件內容與 inventory 的完整檢查。短暫 metadata 修改後恢復原值的 ABA 可能逃過目錄安全欄位比較，退出後亦可能再變更。惡意 root 能操控資料及 Record；工具不承諾原子 snapshot、鎖定 writers、root 隔離或 Restore Proven。真實 Linux ownership 及原生 syscall 驗收仍未執行。

## 限制與後續

沿用 Phase B：4096 entries、depth 16、path 1024 bytes、128 MiB/file、512 MiB payload、8 MiB manifest；operation 60 秒 cooperative budget、總讀取 `8×512 MiB + 4×8 MiB`。最多 64 Records／128 package names；合成目標最多 512 entries、16 MiB total／state JSON、32 KiB environment JSON。不截斷後回報成功；不是 production capacity qualification。

沒有 Restore Apply、Auto Prune、72-hour timer、服務操作、updater 整合、現場保全或自動回滾。Phase D–F 未授權。v1.8.0 Stable、Sidecar 預設 OFF、Legacy Backup 及 production tim 全部保持不變；歷史 macOS Verifier 差異仍 ROOT_CAUSE_UNKNOWN。
