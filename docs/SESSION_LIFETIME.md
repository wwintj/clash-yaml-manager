# 長期登入與 CSRF 表單體驗

v1.8.0 功能範圍；正式可用版本以 [README Latest Stable](../README.md) 為準。

## 有限、可配置的 Session

`SESSION_LIFETIME_DAYS` 由啟動環境讀取，未設定時為 **30 天**，保留既有行為。
可在私人、root 管理的 `.env` 設定：

```dotenv
SESSION_LIFETIME_DAYS=3650
```

值必須為 1–3650 的 ASCII 十進位整數（最多四個字元）；0、負值、空值、空格、
小數、NaN、Infinity、無效字串及過大數字會使啟動失敗，錯誤不回顯設定值。
這是 runtime 環境設定，Settings 不提供寫入 `.env` 的表單。合法設定需依原服務
管理方式重新啟動才能生效；本輪沒有修改 `.env`、部署或重啟 production。
Settings → Runtime → `Session lifetime` 顯示實際 Flask lifetime，不固定顯示 30 days。

登入仍使用 Flask 的 permanent signed-cookie session；沒有新增 session database、
持久 state schema、明文密碼、永不過期的 bearer credential 或新的 Secret Key。
`PERMANENT_SESSION_LIFETIME` 同時控制 Cookie `Expires` 和伺服器簽章 `max_age`，
活動請求由 `SESSION_REFRESH_EACH_REQUEST=True` 滑動續期。相同 Secret Key 與
AuthStore 身份下，既有相容 Session、其他 Gunicorn worker 及重新啟動後可繼續登入。
縮短 lifetime 會讓超過新簽章期限的舊 Cookie 被拒絕；延長不會使已丟失的 Cookie 復活。

長期登入仍可撤銷：Logout 清除目前瀏覽器的 Session；修改密碼後所有舊 Session
會在下次請求經 `auth_version`／`auth_instance` 檢查失效；變更 `SECRET_KEY`
也會使原簽章無效。所有 worker 必須共用原固定 Secret Key，不要為延長期限重新生成。
Logout 沒有新增全域撤銷資料庫，不承諾撤銷已被外部複製的 Cookie。
密碼仍只要求非空，完整保留空格與 Unicode。

Cookie 保持 HttpOnly、SameSite=Lax；HTTPS 部署仍需 `COOKIE_SECURE=true`。
瀏覽器政策、清除資料、隱私模式或使用者設定可能縮短保存時間。Chrome 會把新設或
更新的 Cookie 到期日限制為最多 400 天，因此設定 3650 天**不能保證閒置 3650 天
後仍保持登入**。[Chrome 官方說明](https://developer.chrome.com/blog/cookie-max-age-expires)
Cookie 與簽章的共同設定見 [Flask 官方設定](https://flask.palletsprojects.com/en/stable/config/)。

## 提交前取得 fresh CSRF token

Flask-WTF CSRF 保持啟用、預設 **3600 秒**、正常 POST／HTTPS Referer 驗證，
未設定為 None，也沒有 exempt 認證後的表單或 AJAX。
[Flask-WTF 官方設定](https://flask-wtf.readthedocs.io/en/stable/config/)

已登入頁面載入共用 `static/csrf.js`。正常 POST 表單先保留 Generate 草稿，
取得 fresh token，然後使用 `requestSubmit` 執行原生驗證及既有表單 handler，
保留原 submitter、確認對話框和明確 Generate 行為。Parse／Diff AJAX 也先刷新，
再建立 FormData，只發送一次原請求。沒有背景 polling、自動重新登入或失敗 POST replay。
JavaScript 停用時仍使用原有表單及有限 CSRF 錯誤復原流程。

`GET /api/csrf-token`：

- 每次先驗證現有登入及 AuthStore version／instance；過期或撤銷返回 JSON 401，
  不發令牌、不重新認證。
- 要求 `X-CSRF-Refresh: 1`。如有 Origin 必須等於實際請求 origin；如有
  Sec-Fetch-Site 必須為 same-origin，same-site 亦拒絕。無 Fetch Metadata 的舊客戶端
  仍需自訂 header。跨 origin 的瀏覽器自訂 header 需要 CORS preflight；本 endpoint
  不允許 CORS。HEAD 拒絕；沒有可變更資料的 POST 入口。
- JSON 只含 Session 綁定的 CSRF token，不含密碼、簽名 Session Cookie、Secret Key
  或 AuthStore credentials。HttpOnly Cookie 仍由 Flask 正常續期，前端不能讀取
  Set-Cookie。回應 no-store、no-referrer、nosniff／Vary: Cookie。
- 只對既有 nonce 重新簽章，不為正常 refresh 旋轉 nonce，所以多個開啟的表單可以
  在各自操作前取得有效令牌。原有 CSRF 拒絕處理仍可旋轉 nonce；其他頁下次操作再刷新。
- 不觸發檔案 cleanup，不新增持久業務狀態。Same-origin XSS 不在 CSRF 保護能力內。

刷新失敗時沒有 business POST、重試迴圈或自動導覽；表單保留目前輸入與所選檔案，
顯示可存取的錯誤，操作者可明確重試／重載／登入。Generate 的既有本機草稿仍可在
登入或重載後恢復，預設期限為 30 天（可選 keep 見 [Retention Policy](RETENTION_POLICY.md)），不儲存檔案、帳戶密碼、CSRF 或 Session Cookie。
Fixed／Settings 不新增私人內容的瀏覽器持久草稿：刷新失敗時保持目前頁面輸入，
手動重載仍可能失去未儲存的輸入；上傳檔案也須在重載後重新選取。

已發送而被伺服器拒絕的 POST 不會自動重送，原 CSRF recovery／草稿提示維持。
令牌只存在受保護回應及表單 hidden input；不放入 URL、localStorage／sessionStorage、
console 或可見訊息。此功能沒有改 backup allowlist、AuthStore JSON schema、排程、
retention、網路 timeout、SECRET_KEY 或 production。

## 驗證範圍

隔離 Flask test client 驗證上下界、真實 Cookie attributes／expiry／signature age、
滑動續期、閒置拒絕、舊 Session、獨立 Flask instances、實際雙 Gunicorn worker／master
restart、Logout、密碼／key rotation、CSRF expiry、same-origin、multi-form 與 readonly
business state。Playwright 在 disposable Flask 驗證刷新後首次提交、失敗保留草稿／檔案、
明確重試一次、已拒絕 POST 不重送、跨 tab nonce recovery、登出後拒絕與 token 不外洩。
Ubuntu RC 必須對最終精確 commit 通過才可推 main；不表示已部署或 restore 已驗證。
