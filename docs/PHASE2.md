# Phase 2 — Remaining P0 Security & Runtime Hardening

本轮在现有项目完成剩余 P0，不改 Replace 业务流程，不实现 Merge、Preview、新协议或 UI 重构。Phase 1 基线先复验为 **117 passed**，`git diff --check` 通过，再独立提交 `f73b766`（`test: establish regression baseline and fix phase1 p0 issues`）；开始 Phase 2 时工作树干净。未 push。

## A. Authentication architecture

历史认证依赖 `.env` 的明文或 Base64，以及进程级密码变量。Base64 可逆；单个 worker 改变量不能同步其他 Gunicorn worker，清除当前 cookie 也不能撤销其他浏览器。

现在使用 `state/auth.json`，字段为 `version=1`、`password_hash`、单调递增的 `auth_version`、随机 `instance_id`、UTC `updated_at`。新密码由 Werkzeug 生成 `pbkdf2:sha256:1000000`，使用随机 salt，通过 `check_password_hash` 校验，不自行实现密码哈希。明确选择 PBKDF2 是为了在当前没有 hashlib.scrypt 的 Python 环境与 Ubuntu 之间兼容；Werkzeug 支持该方法，见 [官方安全工具文档](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash)。已有受支持的 PBKDF2/Scrypt hash 可直接迁入，运行环境必须支持对应算法。

所有读取都取共享文件，无进程密码缓存。初始化、校验、改密使用独立 `auth.lock` 的 `fcntl.flock`；不锁被替换的 JSON inode。写入使用同目录 600 临时文件、flush/fsync、`os.replace`，再 fsync 父目录。读者只看到完整的前一版或后一版。目录 700，数据和锁 600。故障返回固定提示，不输出底层异常和秘密；损坏 state 不降级采用旧密码。

认证来源优先级：既有有效 state > `APP_PASSWORD_HASH` > `APP_PASSWORD_B64` > `APP_PASSWORD`。较高优先级存在但无效时停止，防止意外降级。root 升级工具先持久提交 hash，成功后才原子移除 `.env` 中三种凭据记录。其余记录按原始字节保留，支持特殊字符、引号、换行及续行，不 source/eval `.env`。重复迁移保留当前 state。

直接更新代码而没有跑升级脚本时，runtime 可以从进程环境旧凭据初始化 state，随后移除自身环境字典中的凭据键；它不会清理磁盘 `.env`，管理员仍需运行迁移。新安装密码通过 stdin 交给 hash 初始化工具，不写入 argv、环境或 `.env`。runtime 改密永远不改 `.env`。

登录 cookie 保存当前 `auth_version` 和 `instance_id`。每个携带登录态的请求在 CSRF 和路由前核对共享状态；改密在同一个原子提交内增加版本，当前浏览器立即 logout，其他浏览器下次请求清除旧会话，包括原先不带 token 的已登录下载入口。无须重启 worker。替换为全新 state 时随机 instance 也使旧 cookie 失效。已经开始处理的请求不会被追溯中断。

固定 `SECRET_KEY` 必须保留，各 worker 一致；缺失时停止启动。密码更新不会撤销独立签名订阅，删除输出文件可撤销对应订阅。

## B. Login rate limiter

默认 `LOGIN_MAX_FAILURES=5`、`LOGIN_WINDOW_SECONDS=600`、`LOGIN_LOCKOUT_SECONDS=900`，允许正整数环境变量覆盖。10 分钟内第五次失败立即返回 HTTP 429 和 `Retry-After`，固定锁定 15 分钟；被阻止的请求不延长锁定。窗口过期、锁定过期时自动清理，成功登录删除该 IP 的失败记录。锁定期间即使输入正确密码也需等待解除。

所有 worker 使用 `state/login_attempts.json` 和单独锁文件，复用原子写工具。在一次 flock 内完成检查、认证回调和失败记录，避免并发请求越过门槛。只存规范化 IP、失败时间与 `blocked_until`，不存密码、hash 或完整凭据。每次尝试都会 prune，无须额外调度服务。

最多保存 4096 个活跃 IP；容量满时对未知 IP 返回 429，等待现有记录过期，不驱逐现有锁定记录。单 IP 列表受失败门槛约束。这是可用性取舍，不能抵御分布式攻击或替代边缘流量保护。共享 NAT 的用户共享限额；全局文件锁加上密码计算使登录串行，适用于轻量单管理员面板。

仅使用 `request.remote_addr`。默认忽略伪造 X-Forwarded-For；只有显式 `TRUST_PROXY_HEADERS=true` 才沿用 Phase 1 的单层 ProxyFix。此时必须由可信代理覆盖转发头，并阻止公网绕过代理直连 Gunicorn。

## C. systemd security model

| 对象 | owner / group | 权限与用途 |
|---|---|---|
| 安装根目录 | root:root | 755，服务不能替换代码或 runtime 目录 |
| app.py、core、templates、static、defaults、脚本、venv | root:root | 目录 755；普通文件 644，保留必要可执行位；服务只读 |
| `.env`、`.service-account` | root:root | 600；root 管理配置和账户归属标记 |
| uploads、outputs、backups、logs、state | clashyaml:clashyaml | 目录 700，文件 600；仅运行数据可写 |
| systemd unit | root 管理 | 644 |

`clashyaml` 是 system account，无 home、无交互密码，shell `/usr/sbin/nologin`。安装创建时保存用户名、UID、GID 标记；更新及卸载核对标记和账户属性。遇到不属于本项目的同名用户/组停止，不接管或删除其他账户。权限修复不对整个应用执行 service-owned chown，也不跟随符号链接修改外部文件。

unit 设置 `User=clashyaml`、`Group=clashyaml`、`UMask=0077`、`NoNewPrivileges=true`、`PrivateTmp=true`，保持 `gunicorn -w 2`。systemd 系统管理器读取 root 私有的 EnvironmentFile 后将变量传入服务，Web 进程无须读取它。`PYTHONDONTWRITEBYTECODE=1` 避免尝试向只读代码目录写 pycache。

UMask 只收紧新文件；NoNewPrivileges 不影响正常文件访问；PrivateTmp 只隔离 /tmp 与 /var/tmp。五个 runtime 目录仍在安装路径，由服务拥有，因此这些设置不会阻断上传、输出、备份、日志或 state。未加入激进文件系统 sandbox 指令。若端口小于 1024，增加 `AmbientCapabilities=CAP_NET_BIND_SERVICE` 与同名 CapabilityBoundingSet，仅为兼容已有低端口安装；普通端口不加。设置语义参考 [systemd.exec 官方源文档](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml)。这些设计仍需真实 Ubuntu 验收。

## D. Subscription V2

新文件：`tim_YYYYMMDD_N_<nonce>.yaml`，保留日期与大致序号。nonce 来自 `secrets.token_urlsafe(16)`，128 个随机 bit、22 个 base64url 字符。扫描旧/新文件估算下一序号；并发可有相同序号，但有独立 nonce。完整 YAML 仍以 600 临时文件写好，再硬链接独占发布；遇到名字已存在则重试，不覆盖其他 worker。删除全部输出后序号可从 1 重来，身份由 nonce 区分，不能只靠秒级时间戳。

新短链：`/s/v2.YYYYMMDD.<base36 N>.<nonce>.<signature>`。签名为 HMAC-SHA256 的前 16 字节，128-bit authentication strength，base64url 无 padding 共 22 字符。签名输入为域分隔符 `subscription-v2\0` 和完整文件名；日期、序号、nonce 的修改都会改变签名。解析器要求明确版本与固定格式，使用 `hmac.compare_digest`，不接受任意长度前缀、非规范序号或路径别名。

三个入口分开验证：

| 入口 | 允许的凭据 |
|---|---|
| `/download/<filename>?token=...` | 完整 64 hex HMAC；或仅旧文件的 8/12 hex；仍支持有效登录会话的浏览器下载 |
| `/sub/<token>/<filename>` | 同上，返回 YAML 订阅正文 |
| `/s/<slug>` | 明确 V2 解析/验证；或独立 legacy compact/stem 格式验证 |

完整 token 沿用原 HMAC 算法，因此历史完整链接不失效。legacy compact `/s/<YYMMDD><base36 N><8 hex>` 与 stem-8/12/64 hex 继续支持旧文件；nonce 文件名命名空间不能降级为 legacy，即使提供正确的旧算法前缀也拒绝。V2 的签名也不能当作完整下载 token 混用。所有新生成文件只生成 V2 短链。

已签名但已删除文件返回 404；无效签名返回 403。实际文件服务拒绝符号链接和路径别名。旧、新文件分别测试删除后重新生成，三个入口的旧地址都保持 404。随机身份的不可复用依赖安全随机数，碰撞概率可忽略而非数学上的零；管理员手工恢复同名旧文件或使用旧版生成器属于本实现之外。历史弱签名仍有其原有强度风险，仅为已有旧文件兼容保留；敏感旧输出可重新生成并更换链接。

## E. Migration

### 旧安装升级

1. 从独立的新源码目录以 root 运行 `update.sh`，不能在安装目录原地执行。远程脚本下载至独立临时目录，再运行相同流程。已有安装不能重跑 install。
2. 在停服前检查源码语法、配置、端口、固定 SECRET_KEY、认证来源及必要工具。保留 `.env`、默认模板、代码、venv、旧 unit、部署 helper 和已有账户标记至 root 私有备份目录。
3. 更新依赖并 `pip check`，创建或核对专用用户。冲突账户在停服前报错。
4. 停止旧服务，备份既有 state。运行 `core.migrate`：先 durable auth.json，再原子移除旧密码变量，保留其他 `.env` 字节。任何迁移错误停止升级；不会在新 state 保存成功之前删除旧凭据。
5. 复制新代码，排除源码中的 `.env`、state、runtime、venv 等本地文件。保留安装中的默认 YAML、uploads、outputs、backups、logs 和已有 state。修复代码/root 与运行数据/service 权限，生成非 root unit。
6. daemon-reload、enable、restart；检查 is-active 与本机 HTTP 响应。失败给出备份路径及手工回滚指引。
7. 在真实 VPS 核对 `systemctl show clash-yaml-manager -p User -p Group -p MainPID`、`systemctl status`、journal、目录 owner/mode；实际测试上传、生成、下载、改密、跨浏览器退出和限速。当前开发环境只验证了模拟脚本流程，不能替代这一步。

### 回滚与备份

失败时先停止服务，不重跑 install。按打印的备份目录恢复应用、部署脚本、venv（移开当前 venv，备份恢复到原路径）及原 unit，核对默认模板与非认证配置是否有更新。回滚到旧 root 版本必须恢复备份 `.env` 中旧凭据；旧版不认识 auth.json。随后 daemon-reload、restart、检查日志与 HTTP。

保留 uploads/outputs/backups/logs/state，不通过删除数据来回滚。回到支持 state 的版本时优先保留最新 state；若必须恢复 auth 备份，需要清楚旧密码/版本也会恢复，旧 session 可能重新有效，应在恢复后再次改密。不要为了回滚删除已创建的专用账户。旧 root 版本运行后可能写入 root-owned 数据，再次升级时需要权限修复。不得在仍运行 worker 时覆盖 state。

现有 venv 在停服前更新，虽已备份但依赖失败可能部分改变它；当前无完整 staging 或自动回滚。root 备份可能含历史明文/Base64 密码，必须保护并按管理员保留政策清理，脚本不自动删除恢复材料。

### State 与卸载生命周期

state 不进入上传/输出/备份的 7 天清理，auth 永久保留；limiter 内部 prune。cleanup 时间标记迁入 state，以适应只读代码根目录。升级保留 state 并在停服后备份，不复制源码目录的 state。

卸载先停止/禁用服务并移除 unit。保留项目时同时保留服务账户与权限；完全删除项目时默认将 backups、outputs、state、`.env` 备份至 root 私有目录，重新归 root，避免删除账户后备份成为无主 UID。只有账户归属标记匹配且没有该 UID 的进程，才调用 `userdel`；不使用 `-r`，不删除 home 或本项目外的文件。没有标记、属性不符或仍有进程则保留账户，空私有组是否被移除遵循系统 userdel 策略。

## F. Files changed

相对 Phase 1 checkpoint，修改文件：

| 文件 | 改动 |
|---|---|
| `.gitignore` | 忽略 state |
| `app.py` | 共享认证、会话版本核对、限速、state cleanup marker、分离订阅授权 |
| `core/yaml_utils.py` | 新输出 nonce 与兼容序号扫描，保留独占原子发布 |
| `install.sh` | hash-only 安装与专用账户部署 |
| `update.sh` | 安全迁移、state 保留/备份、权限修复、unit 更新 |
| `remote-update.sh` | 验证新部署 helper 存在 |
| `uninstall.sh` | 账户归属检查、state 与配置备份、安全卸载 |
| `templates/index.html` | 仅更新输出文件名格式说明 |
| `tests/test_app.py` | 适配共享认证及显式 token 验证；新增会话、限速、state 保留测试 |
| `tests/test_deployment.py` | 安装/迁移/权限指令/卸载与失败流程测试 |
| `tests/test_yaml_utils.py` | nonce 后仍强制同名碰撞以验证并发不覆盖 |
| `README.md` | 更新安全模型、state 生命周期、迁移及回滚指导 |
| `CHANGELOG.md` | Phase 2 记录，保留历史 Phase 1 说明 |

新增文件：

| 文件 | 用途 |
|---|---|
| `core/state.py` | 私有目录、锁、JSON 与原子持久化工具 |
| `core/security.py` | AuthStore 与 legacy 凭据优先级 |
| `core/envfile.py` | 不执行代码的环境文件解析与原文保留 |
| `core/migrate.py` | root 升级迁移 CLI |
| `core/rate_limit.py` | 跨进程 IP limiter |
| `core/subscriptions.py` | 完整/legacy/V2 分离的签名与解析 |
| `scripts/deploy-common.sh` | 专用账户、权限和 unit 共用函数 |
| `tests/test_security.py` | hash、并发初始化、迁移故障与多对象一致性 |
| `tests/test_envfile.py` | 引号、特殊字符、续行等解析测试 |
| `tests/test_rate_limit.py` | 多对象/真实子进程共享门槛与 prune |
| `tests/test_subscriptions.py` | V2、降级拒绝、身份与删除后 URL 回归 |
| `docs/PHASE2.md` | 本报告 |

`defaults/default.yaml`、parser、policy 业务逻辑没有 Phase 2 修改。

## G. Tests

当前开发环境执行结果：

| 检查 | 结果 |
|---|---|
| Phase 1 开始前全量 pytest | 117 passed，10.47s |
| 共享 hash 认证提交前 pytest | 142 passed |
| 共享限速提交前 pytest | 152 passed |
| 非 root 部署提交前 pytest | 159 passed，54.40s |
| V2 完成后 `.venv/bin/python -m pytest -q` | **178 passed，55.98s** |
| `.venv/bin/python -m compileall -q app.py core tests` | PASS |
| `.venv/bin/python -m pip check` | PASS，No broken requirements found |
| 四个部署脚本与 helper 的 `bash -n` | PASS |
| ShellCheck | unavailable，未安装额外系统软件 |
| `git diff --check` | PASS |
| 默认 YAML 全量 round trip | PASS，10,410 rules；其他未涉及配置相等、引用有效、源字节不变 |
| 默认 YAML 对比原提交 dc69e7f | byte-for-byte unchanged |

默认 YAML SHA-256：`a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`。

关键验收证据：独立 AuthStore A/B 共享文件，A 改密后 B 旧密码失败、新密码成功且版本增加；多浏览器在下一请求失效，包括无 token 下载。3 个真实子进程同时初始化 state，验证原子性；limiter 两对象以及真实子进程按 3+2 次失败共享门槛。迁移分别注入 auth 提交失败与 `.env` 替换失败，确认旧凭据保留、可重试。脚本实际运行在临时目录，外部 systemctl、账户管理、chown、依赖安装使用替身；文件 mode 实际检查，但没有在本机创建 Linux 系统用户或改真实安装的所有权。

订阅测试覆盖有效/无效 V2、修改各字段、长度与 Unicode、域隔离、禁止弱 token 降级、旧 compact/stem 链接、完整浏览器下载、未授权枚举、符号链接/路径别名、旧/新文件删除后所有旧入口仍 404、序号重置不复用身份，以及强制碰撞时完整输出不被覆盖。原 117 条基线保留；其中旧密码/混合 token 的预期按新架构更新，未用删除测试掩盖变化。

## H. Remaining risks

- 尚未在真实 Ubuntu systemd 环境运行安装、root→clashyaml 迁移、EnvironmentFile 注入、实际 owner/ACL、PrivateTmp、低端口 capability 或卸载；脚本替身不能证明这些系统行为。
- 已验证真实子进程锁与独立 AuthStore 一致性，尚未运行生产 Gunicorn 两 worker 加真实浏览器/反向代理的端到端部署验收；未跑 Mihomo 二进制配置校验。
- 不支持多主机共享认证或网络文件系统上的锁语义保证；目标为单机本地文件系统。磁盘满、权限错误、损坏 state 会拒绝认证，需管理员从受保护备份恢复。
- 登录文件锁和 hash 成本限制吞吐；分布式攻击仍可能消耗资源，4096 IP 上限满时新 IP 暂时被拒绝。信任代理配置错误仍可能使 IP 限制失效。
- 旧文件短签名依旧只有历史强度。新链接是 bearer 凭据，可能经分享或代理访问日志泄露；管理改密不轮换订阅密钥。SECRET_KEY 更换会使所有旧订阅和 cookie 失效。
- 新 nonce 碰撞概率极低；手工将不同内容放回旧文件名、降级到旧生成器、恢复旧 state 等管理员操作会改变相应安全保证。不要跨版本混跑旧生成器。
- 依赖使用范围约束而非完整锁定；升级 venv 尚未 staging/自动回滚。清理与日志多进程轮转、完整配置语义校验等不在本轮范围。

## I. Next Phase

先在临时 Ubuntu VPS 做部署验收：旧环境升级、两 worker 改密、可信代理限速、owner/mode 与只读代码验证、低端口（如使用）、健康检查失败回滚、保留/完全卸载。之后再评估依赖锁定和部署 staging。

Merge、Preview/Dry Run、Recent Outputs 和新协议仅列为后续建议，本轮未开始实现。Phase 1 审计与报告保留为历史基线。
