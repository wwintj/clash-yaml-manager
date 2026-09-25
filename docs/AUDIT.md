# Repository audit and staged delivery

审计基点：`dc69e7f`（main，2026-06-02）。本地指定目录最初为空，经授权 clone 原仓库到当前目录；初始工作树干净，未 init、未更改 remote、未覆盖用户修改。

## A. 当前架构

Flask 单进程模块 `app.py` 在 import 时读取环境变量、创建目录、初始化日志、清理过期文件；systemd 启动两个 Gunicorn worker。没有数据库。Jinja2 + Bootstrap CDN + 原生 JS，只有 `templates/index.html` 被 route 调用。`core/parser.py` 负责协议和国家映射，`core/yaml_utils.py` 负责 ruamel.yaml round trip、备份、替换、组清理及输出。

已读 README、CHANGELOG、requirements、全部 Python、四个 shell 脚本、三个模板和唯一静态文件 favicon.svg。默认 YAML 完整加载并逐条检查规则类型/目标：525388 bytes、28 groups、10410 rules，原始规则没有悬空目标；测试比较所有非节点/策略组顶层字段和源文件字节。

历史共 37 个提交：2026-05-26 的上传版本逐步调整 core 路径和多版 UI；`a111190` 加入默认 YAML、Base64 密码、升级流程；`a48232a` 调整默认规则/特殊组；6 月 2 日依次加入结果页、URL 修复、PRG/清理、签名下载、订阅、短链接和 favicon，`39d26ea` 将短签名从 12 降到 8 个十六进制字符；最终提交只调整繁体 README 和删除确认。核心 parser 自首次提交后基本未演进，CHANGELOG 未逐一反映后续变化。

## B. 已有行为（回归保护对象）

1. 环境 `APP_PASSWORD_B64` 优先，回退 `APP_PASSWORD`，UTF-8 恒定时间比较；cookie session 存 logged_in。
2. `.yaml/.yml` 上传，50 MB request 限制，secure_filename、时间戳和短 UUID 命名，落盘后 chmod 600。
3. 不上传即使用 `defaults/default.yaml`；模板缺失返回错误。
4. VMess standard/URL-safe Base64、JSON、WS Host/path/TLS；VLESS URL、TCP/WS/TLS/Reality、IPv4/IPv6。
5. 十一个国家代码统一在 parser 中定义；对应国旗已存在时不重复加入；批量重复名报错。
6. 原 proxies 整体替换，旧节点从组 proxies 中清理；保留 DIRECT/REJECT 等内置目标和组引用。
7. 一般顶层 rules/rule-providers/proxy-providers/dns/hosts/tun/profile/自定义字段通过 ruamel 保留。旧国旗名会修改组及部分 rules。
8. 三个通用组固定在 yaml_utils；八个特殊组在 app，UI 已从后端循环渲染，并非两边重复硬编码。
9. 特殊组存在时保留 type/url/interval/use 等字段并追加新节点；不存在则创建 select。
10. 处理前 copy2 备份原文，输出 `tim_YYYYMMDD_N.yaml`，600 权限。
11. 下载 token 为 filename 的 HMAC-SHA256，支持全长、历史 8/12 hex；登录 session 也可下载。
12. `/sub/<token>/<filename>`、compact `/s/<date><base36><sig>` 和历史 `<stem>-<sig>` 可访问。
13. import 和 /process 触发间隔清理：uploads/outputs/backups 默认保留 7 天，每 7 天检查；手动删除只处理上传/输出。
14. 改密码写 .env 的 Base64，并只更新当前 worker 的全局变量；当前浏览器 logged_in 被清除。
15. install 在 /opt 部署、venv、root systemd；update 复制代码及更新依赖；remote-update 先 clone；uninstall 询问删除目录和是否保存 backups/outputs。

## C–G. 风险与优先级

|级别|领域|已确认问题 / 风险|阶段|
|---|---|---|---|
|P0|数据|序号先扫描再 w 写入，并发请求可覆盖同名输出；删除最大序号后可能复用旧订阅文件名|1 修复并发；持久序号防复用在后续|
|P0|YAML|错误结构被置空；重复组只合并 proxies，后一个 type/use/自定义项被丢弃|1 拒绝损坏输入及重名组|
|P0|YAML|rules 直接引用被删除节点时照样成功；MATCH 两字段没有同步旗标修正|1 针对替换产生的悬空引用设保护|
|P0|解析|VMess 端口越界、bool/浮点可接受；VLESS path 被二次解码；空节点名称被国旗掩盖|1|
|P0|秘密|URL port 异常回显输入；YAML 异常可能带原文；文件名/输入名可能含 token 并进入日志或错误|1 使用固定、带位置的错误|
|P0|Web|五个 POST 无 CSRF；GET logout 修改状态；登录未清 session|1 Flask-WTF、POST-only、会话清理|
|P0|Web|ProxyFix 无条件信任 X-Forwarded-*；默认 HTTPS 与直接 HTTP 部署不符|1 显式可信代理配置、默认跟随请求|
|P0|下载|非 ASCII token 可触发 compare_digest TypeError；32-bit 短签名易枚举且无限期有效|1 修复异常；后续版本化高熵 token，保留旧 URL|
|P0|升级|源目录=安装目录时 rm 后 cp 自删源文件；未排除 .env；源 .venv 可混入|1 提前拒绝、排除运行文件|
|P0|安装|重复 install 在确认前停服，会重写 .env/default/SECRET_KEY|1 引导已有安装使用 update|
|P0|升级|依赖安装在停服后；备份漏 static/remote/service；无 preflight/healthcheck/rollback 指引|1 小幅加强保护；完整 staging 留后续|
|P0|认证|Base64 非 hash；改密码多 worker 状态不一致；其他登录 session 不失效；无限速|2 一起处理，避免仅改存储产生半套迁移|
|P0|权限|systemd root；文件 create 到 chmod 间有权限窗口；应用无固定 SECRET_KEY 时 workers 各自随机|1 私有创建文件；2 专用用户、固定密钥验证|
|P1|兼容|组序列重建丢局部 comments；aliases/anchors 共享可能意外连带修改|3 回归 fixtures + 最小修改策略|
|P1|验证|无完整规则语法、provider、循环组、协议字段校验；支持 include-all，不识别 include-all-proxies/providers|3 ERROR/WARNING/INFO，避免误修|
|P1|策略|所有新节点加入所选特殊组；空国家组可能指向全局手动组；自动改国旗可能造成命名碰撞|3 集中策略定义和显式行为|
|P1|体验|仅 Replace；没有 Merge 冲突提示和 dry-run；后端结果只在生成后出现|4|
|P2|扩展|parser dispatch 写在批量入口；新增协议需要修改分支|5 先小步 dispatch，按官方字段增加协议|
|P3|技术债|两个旧模板无 runtime/include/docs 依赖，但脚本复制整个 templates；先保留|5 稳定后单独清理|
|P3|体验|无 Recent Outputs；模拟进度非实际任务进度；大批错误可能超 cookie 大小；前端重试可能重复合并辅助行|5|

Mihomo 对照来源：[代理组通用字段](https://wiki.metacubex.one/config/proxy-groups/)（包括 use、include-all 系列和空组行为）。目前验证器不等于 Mihomo 内核验证，不应宣传任意配置完全无损。CSRF 使用 [Flask-WTF 官方方案](https://flask-wtf.readthedocs.io/en/1.2.x/csrf/)。

## 小步迭代计划

1. **当前阶段**：先测试，再修上述直接可复现 P0。保持 Replace、现有 API/目录/URL、原 UI 和部署结构。提交建议依次为 tests、core correctness、request security、deployment guards。测试使用临时目录，不读取真实凭据或清理真实数据。
2. **认证与部署权限**：APP_PASSWORD_HASH 优先、B64 兼容；原子持久化和跨 worker 读取；密码版本失效 session；IP 限速及 worker 局限文档；专用 clashyaml system user 与 owner/group 迁移一并验证。每项有旧安装升级/失败测试；备份 .env/service 可回滚。
3. **校验与保留**：分 load/analyze/transform/validate/save；先 backend summary；新增 validator/policies，保留组类型和 provider 字段，覆盖 aliases/comments 和新式 Mihomo 字段。错误阻止输出，警告不擅自修复。
4. **Merge 与 Preview**：默认仍 Replace；明确拒绝同名冲突；预览不产生正式文件，确认才保存；按模式独立测试，UI 仅加必要控件。
5. **扩展与 polish**：解析器注册、官方字段核对的新协议、Recent Outputs 无数据库 metadata；移动端和历史模板清理分开提交。

每阶段独立提交/回归/回滚，不混入默认 YAML 格式改动；不自动提交或发布本轮工作。上线 Linux systemd/用户权限检查需独立 Ubuntu 环境，本机 macOS 的模拟脚本测试不能替代真实部署验证。

## 修复前实测

Python 3.9.6 / Flask 3.1.3 / Werkzeug 3.1.8 / ruamel.yaml 0.19.1 / pytest 8.4.2。
`pytest -m 'not p0'`：43 passed。`pytest -m p0`：24 failed、4 passed，随后据此修复。未通过的 24 个测试覆盖直接缺陷，4 个通过的边界仍保留为回归保护。默认 YAML 全量 round trip 保持 10410 条规则及源字节不变。
