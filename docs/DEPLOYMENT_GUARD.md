# Shared Deployment Guard（v1.8.0 Phase 3D-3G 開發功能）

Latest Stable 仍為 v1.7.0。本功能只保護參與新協定的 updater，尚未部署到
production；沒有接入 Sidecar、改變備份格式或證明 restore。

## 入場與鎖的生命週期

`update.sh` 在只讀 root／source／installed preflight 後，於 legacy backup、pip、
帳戶建立、service stop、auth migration、程式複製與 metadata 之前取得 guard。
`remote-update.sh` 的 Python lifecycle 在 Release／commit lookup 與下載前取得
相同 guard，持有至 Bash 子程序返回、安裝 VERSION 核對、最終 INSTALLATION.json
寫入／核對與最後 guard identity 檢查完成。Stable/main、降級與 Release identity
判準保持原樣；`--resolve-only` 仍唯讀且不建立 guard。

固定位置是本機 filesystem 的 `/var/lib/clash-yaml-manager-deployment/`（root:root，
0700）與空的 `update.lock`（root:root，0600，single hardlink）。不得把這個位置
放在不提供可靠 flock 語義的 network filesystem；Linux 合成驗證不涵蓋 NFS／SMB。
helper 沒有 CLI／環境 path 或 UID override，也不讀入配置來選擇鎖。

從 `/` 開始使用 descriptor-relative no-follow IO，逐層核對祖先的 directory type、
root ownership 與非 group/world-writable 權限；root-owned sticky 祖先可接受，但固定
production 路徑本身不依賴 sticky directory。stat/open inode identity 必須相符。
最終目錄與檔案逐項核對 UID/GID、精確 mode、object type、device 與 inode；拒絕
symlink、FIFO、socket、device、非空 payload、unsafe hardlink、錯誤 owner/mode。
既有不安全物件不會被 chmod/chown 修復或刪除；首次建立的己有物件才設私人 mode
並 fsync。持久鎖沒有 PID、credentials、state 或 bearer URL。

目錄及檔案都取得 `flock(LOCK_EX | LOCK_NB)`。目錄鎖使現有 holder 的 lock file
即使被外部 root 換 inode，第二個參與 updater 仍被拒絕；holder 的重新核對也拒絕
已換 inode。這不對抗惡意 root：root 能替換整個目錄、修改程式或繞過協定。
日常操作不可移動、unlink 或重建任何持久 guard 物件。

## Direct／remote FD 交接

Direct helper 取得鎖後執行原 Bash 流程；remote parent 透過 `pass_fds` 傳入同一對
open-file descriptions。環境中的 `CLASH_DEPLOYMENT_GUARD_FDS` 只是 FD locator：
內部 helper 必須 duplicate FD、核對私人物件與目前固定路徑的身份，並對實際 FD
執行 nonblocking flock。純字串、已關閉／不相干 FD 或其他 holder 期間 fresh-open
的 FD 都不能跳過 guard。有效但尚未上鎖的 FD 也必須真的取得排他鎖。

同一 open-file description 的驗證不會再次獨立 acquire，因而沒有 nested deadlock。
helper 只 close 自己的 FD references，**不使用 LOCK_UN**；顯式 unlock 會錯誤釋放
parent 共用的鎖。所有參與程序最後的 references 關閉才由 kernel 釋放，包括正常
返回、失敗、例外與程序終止。若 supervisor 被 kill 而子程序仍在執行，子程序保留
FD 會繼續阻擋其他 updater；不能因 parent PID 已消失而認定可以更新。
Detached descendant 若保留 FD，鎖也會保守延長，需人工確認作業完成；不設 expiry。
上述 FD／dup／exec／close 語義與 advisory 限制見 [Linux flock(2)](https://man7.org/linux/man-pages/man2/flock.2.html)；不是所有 filesystem／平台都提供相同行為。

## 拒絕與 OFF 相容性

鎖衝突固定返回 **75 / DEPLOYMENT_GUARD_CONFLICT**；unsafe path／FD／ownership／
缺少能力等返回 **78** 與固定 guard code。普通 updater 的原 preflight／部署錯誤
保留原行為。Guard 拒絕不回報「備份已建立」，也不建立 legacy backup、不執行 pip、
不停止 systemd、不進入 core.migrate、不複製程式、不寫安裝 metadata、不清理備份。

使用者明確授權的唯一 OFF 例外是共同入場 guard 與衝突拒絕。無衝突時原 update.sh
body 保持逐字相同，保留 cp -a、venv、auth migration 與 service/timer 的原順序。
沒有新的 Sidecar／Collector／Writer／Catalog 呼叫。`build_bootstraps.py` 只增加共用
helper 的 standalone embedding，依倉庫同步規則機械重建兩個 bootstrap；install
分支及 resolve-only 不取得鎖，不增加 install admission policy。

## 未參與的 writer 與操作邊界

| 入口 | 邊界與評估 |
| --- | --- |
| 歷史 v1.7.0 update.sh／remote-update.sh | 不自動遵守新協定。新 remote parent 呼叫歷史 child 時其 parent 鎖仍涵蓋 child／finalization，但不能阻擋另一個獨立歷史 updater。 |
| install.sh／remote-install.sh | 完整既有 app／.env／auth 安裝會拒絕重新安裝；partial install、unit 或明確覆寫情況可能修改相同路徑。此輪未改 installer 行為，必須由操作者避免與 updater 並行。 |
| uninstall.sh | 可能停止服務、移動／刪除安裝；未接入協定，禁止與 updater 並行。 |
| httpsctl.sh／mihomoctl.sh、手動 root writer | 各有自身操作／鎖，未參與全域 admission；不得假定本 guard 能阻擋。 |
| Web、refresh／health、其他 state writers | 本 guard 不是 runtime snapshot 鎖。原 updater 的 stop／migration 時序不變，沒有增加 quiet／一致性保證。 |

沒有 lease 搶佔、逾時刪鎖、取消歷史 updater 或自動恢復。Guard 只避免新協定 updater
重疊，不是完整 runtime consistency、production backup ready 或 rollback ready。

## 合成驗證

`tests/test_deployment_guard.py` 使用可信 test-copy 路徑／本機 UID policy；production
程式没有環境開關。執行實際 kernel flock、真實 update.sh 和隔離外部命令 doubles：
四種 direct／remote 並發組合僅一個 updater 進入修改階段，另一個在 migration 前
拒絕且安裝 bytes／事件／backup 清單不變；另在 remote child 結束與最終 metadata
寫入間設 barrier，證明仍被鎖保護。對 START revision 比對無衝突成功與 pip 失敗的
命令、legacy backup bytes/modes、unit 與 .env；既有 lifecycle regression 仍完整執行。

涵蓋 FD forgery／交接不 unlock parent、symlink ancestors、unsafe objects／ownership、
inode replacement、stale empty lock、fsync failure、例外、正常／SIGKILL 結束及
supervisor 死亡但 child 仍持鎖。Linux gate 額外用 sudo 在 `/tmp` 的 root-only fixtures
執行真實 root UID/GID、0700／0600、flock／O_NOFOLLOW 與降權 child 的 read/write
拒絕；不操作系統服務、帳戶、/opt、固定 production 鎖或 VPS。

READY 只代表新版共同協定的合成開發驗收，歷史並發、production、Sidecar 和 restore
仍不在本輪驗收內。
