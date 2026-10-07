# 預設 YAML 國家策略組

本功能目前在 main，屬於 v1.6.0 Phase 1 開發；尚未發布。
VERSION 與 Latest Stable 仍為 `1.5.0`／`v1.5.0`。

內建 `defaults/default.yaml` 不再預建 HK、TW、SG、JP、US、KR 六個國家
placeholder，也移除其他功能組對這六組的靜態引用。`proxies` 仍為空清單。
功能組及其順序保持原樣，包括 `🎥 奈飞节点`；DNS、連接埠與全部
10,410 條 rules 的內容、順序及 targets 均不變。

## 依實際節點建立

沿用既有 parser、完整國家資料集與 YAML 生成流程。Default 的 Replace／Merge
只建立本次實際解析到的國家組；不假定固定六國。例如 US、US、SG、DE 輸入
建立 `🇺🇸 美国节点`、`🇸🇬 狮城节点`、`🇩🇪 德国节点`，各組僅包含相應真實
節點，成員按輸入順序排列，不加入 DIRECT 假成員。FR、CA、AU 等既有資料集
支援的國家也依同一流程建立。

國家判定優先級維持 Manual COUNTRY → Name／URI metadata → optional offline
GeoIP → Unknown。名稱與 URI metadata 依既有 parser 選用；手動選擇優先。
GeoIP 預設 Off，仍只按既有契約查離線 MMDB 的公共字面 IP，沒有 DNS、
外部 API 或線上 GeoIP。無法判定時使用既有 `Unknown`／`🌐 其他节点`，不猜國家。

特殊組仍依使用者選擇加入新節點；未選中的既有功能組保留原本成員。
本輪沒有自動把國家組引用加入各功能 selector，也沒有改變路由策略。

## 新安裝與既有升級

安裝此 main 版本會使用清理後的 built-in default；未來包含本功能的 Stable
發布後，新 Stable 安裝才會使用新模板。目前普通 Stable 安裝仍為 v1.5.0。

既有安裝的更新繼續保留安裝目錄中的 `defaults/default.yaml`。即使程式升級，
也不會自動採用新模板，因為該檔可能由使用者自訂。本輪未改 deployment、
remote-update 或 preservation 契約，也沒有自動 migration。

若正式發布後要讓既有 VPS 採用新模板，需另行明確授權獨立操作：備份原檔、
驗證目前 hash、確認是已知舊 stock template 後替換，再執行 health／config
驗證，失敗時 rollback。本輪此操作與 tim 部署均為 **NOT RUN**。

## Custom、Merge 與 Fixed

Custom YAML 不會被這次 built-in template 清理。來源既有國家組、metadata
與原本節點追加行為保持既有契約；Merge 保留來源 proxy objects、順序及引用。
通用 `add_node_to_group()` append 行為未改。

既有 Fixed revision 已儲存 `base.yaml`／已提交輸出，built-in default 改動
不會重寫其 snapshot。新建 Default-source Fixed 使用當時安裝的 default；
明確重新儲存 Default-source Fixed 時，才按既有契約選用當時的 default。
Custom-source Fixed 則沿用既有 custom snapshot 契約。

## Phase 2 selector 排序候選

實測 Default 加入 US、SG、DE 三節點後，`🚀 节点选择` 的順序為：

```text
🚀 手动切换
DIRECT
🇺🇸 Node-0
🇸🇬 Node-1
🇩🇪 Node-2
```

真實節點仍在 `🚀 手动切换`／DIRECT 之後，記為 **PHASE 2 ORDERING CANDIDATE**。
這不是 Phase 1 blocker；是否調整 selector 前置排序需另行決定與驗證。

## Canonical checksum

本輪經審核的新 built-in default SHA256：

```text
bc24dc51c528f7410c7e566f91c82883d2a2574ae3b359847e7ecfd854190576
```

`scripts/release.py DEFAULT_SHA256` 與 Policy 測試的 current default checksum
同步更新；Policy Default 輸出 golden 因模板改動更新，Custom golden 不變。
`tests/test_yaml_diff.py` 的 Default 輸出 golden（與 Merge 測試共用）也按同一方式
核對凍結起始 runtime 後更新，Custom checksum 不變。
過往 acceptance report 中的舊 checksum 保留為當時的歷史證據。
