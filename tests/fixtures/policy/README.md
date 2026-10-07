# Preserve 相容性 golden

`base.yaml` 是公開的 synthetic Custom YAML fixture。`preserve.yaml` 由
Policy Engine 導入前的 `24fb40141c8ff85345c78864b8f38c3d49f5ff5e` 版本產生，
仍保留原始 golden，不隨 built-in default 清理而更新。

`preserve-default.sha256` 驗證目前已審核的 `defaults/default.yaml` 在未指定來源
profile 時的通用生成結果；不由 stock 檔名或內容推斷 Default profile。
v1.6.0 Phase 1 明確授權刪除六個靜態國家組及其引用，因此 Default golden
從 `e629e6d2321395cda55a671a9c5a0df1fc6efbdca4e2b9c3edc1c674ee173040`
更新為 `8a96d341c8baf33d8c084409b16ac681480e57e3683433e4c6e2a2fcee00e1f0`。
更新前已確認生成結果的非 proxy-groups 內容完全相同，並以凍結的起始版本
`8bab3bfaa428e32ad02f7be9be276bc56c54f2be` runtime 配合新模板重現相同位元組；
該次模板清理沒有修改 generator、Policy Engine 或 YAML runtime。
Phase 2 的明確 Default profile 排序由 selector 與 HTTP 測試另外驗證；
這份通用 append golden 與原 Custom golden 均保持不變。

節點、國家指派及選中的 `media` 組定義於 `tests/test_policy_engine.py`。
UUID／端點都是測試資料。測試比較省略 policy 與明確 Preserve / Preserve 的
Custom 輸出位元組、Default 輸出 SHA256；隨機檔名不影響 YAML 位元組。
不得重新產生 golden 來掩蓋 runtime regression。
