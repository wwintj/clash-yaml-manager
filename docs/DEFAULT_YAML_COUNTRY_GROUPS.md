# 預設 YAML 國家策略組

本功能目前在 main，包含 v1.6.0 Phase 1 模板清理與 Phase 2 主選擇器排序；尚未發布。
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
國家組引用僅加入 `🚀 节点选择`；其他功能 selector 可透過主選擇器選擇國家組，
不重新注入冗餘國家引用。`🐟 漏网之鱼` 與 rules 路由契約不變。

## 新安裝與既有升級

安裝此 main 版本會使用清理後的 built-in default；未來包含本功能的 Stable
發布後，新 Stable 安裝才會使用新模板。目前普通 Stable 安裝仍為 v1.5.0。

既有安裝的更新繼續保留安裝目錄中的 `defaults/default.yaml`。即使程式升級，
也不會自動採用新模板，因為該檔可能由使用者自訂。本輪未改 deployment、
remote-update 或 preservation 契約，也沒有自動 migration。

Phase 2 排序是 runtime 行為：更新至包含此功能的版本後，Default-source
重新生成會套用新主選擇器排序，但安裝目錄的 default 檔本體仍受保留契約保護。

若正式發布後要讓既有 VPS 採用新模板，需另行明確授權獨立操作：備份原檔、
驗證目前 hash、確認是已知舊 stock template 後替換，再執行 health／config
驗證，失敗時 rollback。本輪此操作與 tim 部署均為 **NOT RUN**。

## Custom、Merge 與 Fixed

Default／Custom 依 Generate、Preview 與 Fixed 已知的來源選擇明確區分，
不由檔名、checksum 或內容相似度猜測。即使上傳與 stock template 相同的
Custom YAML，也保留其來源排序與節點追加契約；Merge 保留來源 proxy objects、
順序及引用。通用 `add_node_to_group()` append 行為未改。

既有 Fixed revision 已儲存 `base.yaml`／已提交輸出，built-in default 改動
不會重寫其 snapshot。新建 Default-source Fixed 使用當時安裝的 default；
明確重新儲存 Default-source Fixed 時，才按既有契約選用當時的 default。
Default-source Fixed 的 create、explicit save、source refresh、cached regeneration
及 Health Policy reconciliation 均套用相同排序；Custom-source Fixed 保持原排序。
既有 Regenerate 只輪換 token／URL，不重新生成 YAML，仍保留原 revision 位元組。

## Phase 2 已實作：受控主選擇器排序

實測 Default 加入 US、SG、DE 三節點後，`🚀 节点选择` 的順序為：

```text
🇺🇸 Node-0
🇸🇬 Node-1
🇩🇪 Node-2
🇺🇸 美国节点
🇸🇬 狮城节点
🇩🇪 德国节点
🚀 手动切换
DIRECT
```

精確契約為：真實節點 → 動態國家組 → `🚀 手动切换` → DIRECT。
真實節點嚴格依 generator 的 input／aggregate 順序；國家組依該國第一次在
真實節點中出現的順序，只出現一次，包含實際 Unknown 的 `🌐 其他节点`。
不按國家、名稱或協定另行排序，也不建立固定國家清單。

Replace 與空來源的 Default Merge 產生相同主選擇器順序。`🚀 手动切换`
仍僅含真實節點，按原輸入順序；不加入國家組引用或 DIRECT。
Country Policy 的 Preserve、Select、URL-Test、Fallback、Load-Balance 均可
正常被主選擇器引用，automatic group 不會被攤平。

主選擇器投影在既有 Policy／Health transform 之後，只調整主 selector 的引用。
Health 已過濾的 country／special group 成員與 Policy metadata 保留；
頂層真實節點及手動切換仍可用。Preview 與 Generate 共用此流程，輸出位元組一致。
選中特殊組的「原引用 → 追加真實節點」順序保持原樣；若需調整，屬後續候選。

本輪受控驗收涵蓋本機完整回歸與 pinned Mihomo 配置驗證；
**REAL VPS DEFAULT ORDERING: NOT RUN**。Feature freeze 前仍需另行授權 main
channel 真實 VPS 或 dedicated test VPS 驗收；配置驗證不代表實際代理流量通過。

## Canonical checksum

Phase 2 的 built-in default 檔保持 Phase 1 位元組與 approved checksum：

```text
bc24dc51c528f7410c7e566f91c82883d2a2574ae3b359847e7ecfd854190576
```

`scripts/release.py DEFAULT_SHA256` 與來源檔 checksum guard 保持相同。
Phase 1 曾因模板清理更新通用 Policy golden；Phase 2 保留未指定 profile 的
通用 append golden。`tests/test_yaml_diff.py` 的 Default HTTP 輸出 golden
（與 Merge 測試共用）則按本輪僅主 selector 投影的結構差異審核更新；Custom 不變。
過往 acceptance report 中的舊 checksum 保留為當時的歷史證據。
