# 第一阶段交付记录

完成日期：2026-09-25。基于 main `dc69e7f`。本轮完成完整仓库审计、测试基线和限定范围的 P0 修复；没有宣称全部安全问题已解决，也没有实现 Merge、Preview、新协议或 UI 重设计。

## 修改文件、内容与原因

|文件|修改|原因|
|---|---|---|
|`.gitignore`|排除本地 venv、缓存、.env、运行数据|避免把秘密和生成文件纳入版本管理|
|`requirements-dev.txt`|复用运行依赖，新增 pytest 8|分离测试依赖，兼容本次 Python 3.9 环境|
|`pytest.ini`|固定 tests 目录，声明 p0 marker|分开运行既有行为基线与缺陷复现|
|`tests/conftest.py`|测试输入、隔离 Flask import、临时目录和 CSRF 提交辅助|不触碰真实 .env、日志、备份或清理真实数据|
|`tests/test_parser.py`|Base64、VMess/VLESS TCP/WS/TLS/Reality、IPv4/IPv6、端口、路径、批量输入|锁定兼容性，复现解析缺陷|
|`tests/test_yaml_utils.py`|替换/引用/组类型/动态 provider 组/规则/注释/引号/默认模板全量 round trip；并发和失败注入|验证保留行为、无覆盖和失败时不发布半成品|
|`tests/test_app.py`|登录/失败/退出/改密码/上传/大小/清理/下载/短订阅/CSRF/代理/session|验证端到端请求流程和旧 URL 兼容|
|`tests/test_deployment.py`|在临时路径执行四个脚本的测试副本，替换外部系统命令|实际验证脚本分支、数据保留及失败顺序，不部署当前电脑|
|`core/parser.py`|严格端口、必填字符串和 JSON 对象检查；拒绝空名；VLESS path 只解码一次；固定脱敏错误|避免无效节点及异常回显秘密，保留现有 parser 结构|
|`core/yaml_utils.py`|输入形状和名称冲突保护；拒绝重复组；阻止规则继续指向删除节点；修正 MATCH 旗标；组引用原位删除；识别 include-all 三种字段|不再静默抛弃不认识的数据或重复组设置，保留更多注释，针对 Replace 引入的悬空规则设保护|
|`core/yaml_utils.py`（文件 IO）|600 临时文件序列化、fsync、原子发布；并发重试不覆盖；备份私有创建|避免半成品及并发覆盖；备份时间按创建时记录，避免继承旧模板 mtime 后被提早清理|
|`app.py`|Flask-WTF CSRF；POST-only logout；登录/退出/改密清理 session；12 小时登录 session；ProxyFix opt-in；请求协议默认；token 字符验证；私有创建上传；减少日志回显|修复请求保护、直接 HTTP URL 不匹配、异常泄露和 token 500|
|`requirements.txt`|新增 Flask-WTF>=1.2.2,<2，统一原文件 CRLF 为 LF|使用成熟 CSRF 实现；未引入其他应用框架|
|`templates/index.html`|五个现有表单各增加一个 hidden csrf_token|配合后端保护，维持原布局、风格与 JavaScript|
|`install.sh`|已有安装提前拒绝；复制排除配置/venv；默认 URL 协议留空、代理关闭；umask；启动健康检查|避免重复安装破坏原配置，修正 HTTP 默认并检测启动失败|
|`update.sh`|原地升级及配置预检；排除 .env/.venv 等；唯一私有备份含 venv/static/service；停服前依赖更新及 pip check；健康检查及回滚提示|减少升级自毁和配置覆盖，失败时有可恢复材料|
|`remote-update.sh`|mktemp 独立目录；退出清理自己的目录；检查下载结果再执行|不再删除外部传入的任意 TMP 路径，下载失败不运行 update|
|`README.md`|URL/代理/CSRF 配置、升级回滚、测试命令及剩余安全局限|部署配置与实现同步，明确兼容迁移边界|
|`CHANGELOG.md`|Unreleased 阶段记录|不虚构 release/tag，记录行为改变|
|`docs/AUDIT.md`|架构、已有功能、C–G 风险、P0–P3 排序、分阶段计划和历史演进|供后续开发及上线决策使用|
|`docs/PHASE1.md`|本交付记录|集中保留验证证据和未完成工作|

`defaults/default.yaml`、`templates/index-cn.html`、`templates/index-backup.html`、`uninstall.sh` 未修改。两个旧模板已确认无运行引用，但本轮未删除。uninstall 的“保留目录”分支已执行测试。

## 实际执行的验证

环境：macOS ARM64，Python 3.9.6、pytest 8.4.2、Flask 3.1.3、Werkzeug 3.1.8、ruamel.yaml 0.19.1、Flask-WTF 1.2.2、Gunicorn 23.0.0。

1. 修改生产逻辑前：`pytest -q -m 'not p0'`，**43 passed**。
2. 修改生产逻辑前：`pytest -q -m p0 --tb=short`，**24 failed、4 passed**，复现并发覆盖、丢配置、错误解析、CSRF/会话等问题。
3. 修复并扩展边界用例后：`.venv/bin/python -m pytest -q`，**117 passed in 9.77s**，无跳过/xfail。
4. `.venv/bin/python -m compileall -q app.py core tests`，**通过**。首次因 macOS 编译缓存路径不在沙箱内失败，授权后重跑成功。
5. `.venv/bin/python -m pip check`，**No broken requirements found**。
6. 四个脚本分别 `bash -n`，**全部通过**，同时纳入 pytest；本机未安装 shellcheck，**未执行 shellcheck**。
7. `git diff --check`，**通过**。
8. `git diff --exit-code -- defaults/default.yaml templates/index-cn.html templates/index-backup.html uninstall.sh`，**通过，无差异**。

默认 YAML 525388 bytes，28 groups，10410 rules；测试完整比较除 proxies/proxy-groups 外所有顶层字段，确认源文件字节未变。signed download、旧 8/12/64 hex token、历史 stem URL、compact `/s/...`、未授权访问、删除后 404、默认 YAML fallback、上传模式均实际经过 Flask test client。

输出并发测试强制两个线程同时选择文件名，验证两份输出各保留自己的内容；序列化失败测试验证旧文件不变、没有正式半成品。文件权限测试覆盖 600 的输出/备份/.env 及 700 的运行目录。脚本测试检查生成 service 的安装路径、gunicorn 命令、APP_PORT 引用、UMask，以及 daemon-reload/restart/health 的顺序。

**验证边界**：没有真实部署到 VPS，没有执行 Linux `systemd-analyze verify` 或真正的 systemd 启停；没有专用用户迁移测试，也没有 Mihomo 内核加载测试。系统命令替身测试验证的是控制流程和文件结果，不是 Linux 服务可用性的证明。

## 尚未解决的问题

- **认证 P0**：APP_PASSWORD_B64 仍为 Base64；改密码跨 worker 不一致；没有 IP 登录限速；其他浏览器 session 不会随改密立即失效。下一阶段应一起迁移 hash、共享持久化凭据和 session 版本，避免只改存储格式。
- **权限 P0**：服务仍为 root；专用 clashyaml 用户及 .env/defaults/运行目录 owner/group 升级迁移尚未实现。
- **订阅 P0**：继续兼容旧 32 位短签名；没有过期/撤销机制。删除当天最大序号输出后，文件名可能复用，因此旧签名可能访问后续同名文件。需要持久递增序号与版本化高熵订阅一起解决。
- **升级风险**：依赖在现有 venv 更新，失败可能部分改变依赖；已备份 venv，但未做 staging/自动回滚。健康检查只检查本地首页及服务状态。升级仍保留旧 `.env` 的 HTTPS 设置，直接 HTTP 用户需显式清空/改为 http。
- **YAML**：本轮是结构保护及 Replace 悬空旧节点保护，不是完整 validator；规则语法、规则提供者、use 提供者引用、循环引用、所有协议必填项以及 anchors/aliases 的完整保留仍需加强。拒绝重复组是刻意的安全变化，不再静默合并。
- **功能**：Merge、Preview、集中 policies、解析器 dispatch、新协议、Recent Outputs 未实现。
- **兼容边界**：表单提交需要 CSRF token，旧的无 token POST 自动化必须先获取页面 token；GET /logout 返回 405。现有正常浏览器表单及 signed/short GET 下载继续可用。rootless/systemd 和 Mihomo 内核仍待 Ubuntu 验收。

## 下一阶段与提交建议

下一阶段优先处理剩余认证/权限 P0：旧 B64 登录兼容 → hash 写入 → 多 worker 一致性/session 失效 → 有过期的进程内 IP 限速（明确多 worker 局限）→ system user + owner/group 迁移与真实 Ubuntu 验证。随后处理短签名/序号复用、分层 validator，再进入 Merge/Preview。

建议本轮按 tests → core correctness → Web request protection → deployment guards 分为独立 commits，文档跟随对应改动。本轮未自动 commit、push、创建 PR 或部署。

## git diff --stat

以下为已跟踪文件的真实输出；Git 默认不把未跟踪新文件计入 diff stat，新测试和文档在下方 status 中单列。

```text
 CHANGELOG.md         |  11 ++++
 README.md            |  39 ++++++++++++-
 app.py               |  63 ++++++++++++++-------
 core/parser.py       |  66 +++++++++++++---------
 core/yaml_utils.py   | 153 ++++++++++++++++++++++++++++++++++++++-------------
 install.sh           |  27 ++++++++-
 remote-update.sh     |  10 ++--
 requirements.txt     |   9 +--
 templates/index.html |   5 ++
 update.sh            |  97 +++++++++++++++++++++++++++-----
 10 files changed, 370 insertions(+), 110 deletions(-)
```

## git status --short --branch

```text
## main...origin/main
 M CHANGELOG.md
 M README.md
 M app.py
 M core/parser.py
 M core/yaml_utils.py
 M install.sh
 M remote-update.sh
 M requirements.txt
 M templates/index.html
 M update.sh
?? .gitignore
?? docs/
?? pytest.ini
?? requirements-dev.txt
?? tests/
```
