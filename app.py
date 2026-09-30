import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any, Dict

from flask import jsonify, Flask, Response, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect, CSRFError

from core import parser, generator
from core import yaml_utils
from core.security import AuthStore, CREDENTIAL_KEYS
from core.state import StateError, file_lock, atomic_write
from core.temporary_links import TemporaryLinks
from core.fixed_subscriptions import FixedSubscriptions, FixedBearerFilter, SLUG as FIXED_SLUG
from core.fixed_views import blueprint as fixed_blueprint
from core.retention import seconds_from_env
from core.rate_limit import LoginLimiter
from core import policy_engine, geoip, yaml_diff
from core.geoip_store import GeoIPStore
from core.notifications import Notifications
from core.settings_views import blueprint as settings_blueprint
from core import settings_status, https_metadata
from core.deployment_config import bind_host
from core.proxy_health import ProxyHealth
from core.version import read_version
from core.install_info import read_install_info, display_build
from core.subscriptions import SubscriptionSigner, safe_filename

# ==========================================
# 环境变量与应用配置
# ==========================================
APP_PORT = int(os.environ.get("APP_PORT", 8899))
try:
    APP_BIND_HOST = bind_host(os.environ.get("APP_BIND_HOST", "0.0.0.0"))
except ValueError:
    sys.exit("APP_BIND_HOST 必须为 0.0.0.0 或 127.0.0.1。")
SECRET_KEY = os.environ.get("SECRET_KEY")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
DOWNLOAD_BASE_URL = os.environ.get("DOWNLOAD_BASE_URL", "").rstrip("/")
DOWNLOAD_URL_SCHEME = os.environ.get("DOWNLOAD_URL_SCHEME", "").lower()
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() == "true"
if DOWNLOAD_URL_SCHEME not in ("", "http", "https"):
    sys.exit("DOWNLOAD_URL_SCHEME 必须为空、http 或 https。")
UPLOAD_RETENTION_SECONDS = seconds_from_env(os.environ, 'UPLOAD_RETENTION_HOURS', 1, 'FILE_RETENTION_DAYS')
OUTPUT_RETENTION_SECONDS = seconds_from_env(os.environ, 'OUTPUT_RETENTION_HOURS', 24, 'FILE_RETENTION_DAYS')
CLEANUP_INTERVAL_SECONDS = seconds_from_env(os.environ, 'CLEANUP_INTERVAL_HOURS', 1, 'CLEANUP_INTERVAL_DAYS')
BACKUP_RETENTION_SECONDS = seconds_from_env(os.environ, 'BACKUP_RETENTION_HOURS', 168, 'BACKUP_RETENTION_DAYS')


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
APP_VERSION = read_version(os.path.join(BASE_DIR, "VERSION"))
DIR_UPLOADS = os.path.join(BASE_DIR, "uploads")
DIR_OUTPUTS = os.path.join(BASE_DIR, "outputs")
DIR_BACKUPS = os.path.join(BASE_DIR, "backups")
DIR_LOGS = os.path.join(BASE_DIR, "logs")
DIR_DEFAULTS = os.path.join(BASE_DIR, "defaults")
DIR_STATE = os.path.join(BASE_DIR, "state")
DEFAULT_YAML_PATH = os.path.join(DIR_DEFAULTS, "default.yaml")
CLEANUP_MARKER = os.path.join(DIR_STATE, ".last_cleanup")

ALLOWED_EXTENSIONS = {"yaml", "yml"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

DEFAULT_SPECIAL_GROUPS = [
    "🎥 奈飞节点",
    "📹 油管视频",
    "💬 Ai平台",
    "📲 电报消息",
    "🎵 TikTok",
    "🎬 HBO",
    "🏰 Disney+",
    "𝕏 X/Twitter",
]


# ==========================================
# 模块级初始化
# ==========================================
def ensure_directories() -> None:
    """确保必要目录存在。"""
    for directory in [DIR_UPLOADS, DIR_OUTPUTS, DIR_BACKUPS, DIR_LOGS, DIR_STATE]:
        os.makedirs(directory, mode=0o700, exist_ok=True)


def setup_logging() -> None:
    """配置应用日志。日志不记录完整节点链接、UUID 或密码。"""
    log_file = os.path.join(DIR_LOGS, "app.log")

    logging.getLogger().handlers.clear()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(FixedBearerFilter())
    for name in ('werkzeug', 'gunicorn.access', 'gunicorn.error'):
        logger = logging.getLogger(name)
        if not any(isinstance(f, FixedBearerFilter) for f in logger.filters):
            logger.addFilter(FixedBearerFilter())


def cleanup_old_files() -> None:
    """Throttled process/request cleanup; state and logs are never scanned."""
    now = time.time()
    try:
        # Fast path avoids directory scans and locks on ordinary requests.
        if os.path.exists(CLEANUP_MARKER) and now - os.path.getmtime(CLEANUP_MARKER) < CLEANUP_INTERVAL_SECONDS:
            return
        with file_lock(os.path.join(DIR_STATE, 'cleanup.lock')):
            if os.path.exists(CLEANUP_MARKER) and now - os.path.getmtime(CLEANUP_MARKER) < CLEANUP_INTERVAL_SECONDS:
                return
            deleted_count = 0
            for directory, retention in ((DIR_UPLOADS, UPLOAD_RETENTION_SECONDS),
                                         (DIR_OUTPUTS, OUTPUT_RETENTION_SECONDS),
                                         (DIR_BACKUPS, BACKUP_RETENTION_SECONDS)):
                for entry in os.scandir(directory):
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        if now - entry.stat(follow_symlinks=False).st_mtime >= retention:
                            os.remove(entry.path)
                            if directory == DIR_OUTPUTS:
                                temporary_links.revoke_file(entry.name)
                            deleted_count += 1
                    except FileNotFoundError:
                        continue  # Concurrent explicit deletion is harmless.
            temporary_links.prune(now)
            atomic_write(CLEANUP_MARKER, str(now).encode())
            if deleted_count:
                logging.info('自动清理过期文件: %d 个文件', deleted_count)
    except (OSError, StateError):
        logging.warning('自动清理文件失败，请检查目录权限或共享状态。')


ensure_directories()
temporary_links = TemporaryLinks(DIR_STATE)
fixed_subscriptions = FixedSubscriptions(DIR_STATE)
geoip_store = GeoIPStore(DIR_STATE)
proxy_health = ProxyHealth(fixed_subscriptions)
auth_store = AuthStore(DIR_STATE)
login_limiter = LoginLimiter(
    DIR_STATE,
    max_failures=int(os.environ.get('LOGIN_MAX_FAILURES', '5')),
    window=int(os.environ.get('LOGIN_WINDOW_SECONDS', '600')),
    lockout=int(os.environ.get('LOGIN_LOCKOUT_SECONDS', '900')),
)
try:
    auth_store.initialize(os.environ)
except (StateError, OSError):
    sys.exit("认证状态初始化失败，请检查 state/ 权限或执行凭据迁移。")
# Compatibility bootstrap is one-way: stale environment credentials are not reused.
for credential_key in CREDENTIAL_KEYS:
    os.environ.pop(credential_key, None)
setup_logging()
cleanup_old_files()


# ==========================================
# Flask 应用初始化
# ==========================================
app = Flask(__name__)
app.jinja_env.policies["json.dumps_kwargs"] = {"sort_keys": False}
if TRUST_PROXY_HEADERS:
    # Enable only behind exactly one trusted proxy that overwrites these headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = COOKIE_SECURE
app.config["PREFERRED_URL_SCHEME"] = DOWNLOAD_URL_SCHEME or "http"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_REFRESH_EACH_REQUEST"] = True

if not SECRET_KEY:
    sys.exit("请设置固定 SECRET_KEY，所有 worker 必须使用同一密钥。")
else:
    app.secret_key = SECRET_KEY

@app.before_request
def invalidate_old_sessions():
    if request.endpoint == 'healthz':
        return None
    if request.path != '/api/preview-yaml-diff':
        cleanup_old_files()
    if session.get('logged_in'):
        state = auth_store.read()
        if (session.get('auth_version') != state['auth_version'] or
                session.get('auth_instance') != state['instance_id']):
            session.clear()


CSRFProtect(app)


@app.route('/healthz', methods=['GET'])
def healthz():
    """Readiness only: Flask loaded and can serve requests, without auth or I/O."""
    return 'OK\n', 200, {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}


# ==========================================
# 辅助函数
# ==========================================
def allowed_file(filename: str) -> bool:
    """只允许上传 .yaml / .yml 文件。"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_safe_upload_filename(original_filename: str) -> str:
    """生成安全上传文件名，防止覆盖和路径穿越。"""
    safe_name = secure_filename(original_filename)

    if not safe_name:
        safe_name = "config.yaml"

    name_part, ext_part = os.path.splitext(safe_name)

    if not name_part:
        name_part = "config"
    if not ext_part:
        ext_part = ".yaml"

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]

    return f"upload_{name_part}_{timestamp}_{short_uuid}{ext_part}"


def safe_delete_file(directory: str, filename: str) -> bool:
    """安全删除指定目录内的文件，避免路径穿越。"""
    if not filename:
        return False

    safe_filename = os.path.basename(filename)
    target_path = os.path.join(directory, safe_filename)

    if os.path.exists(target_path) and os.path.isfile(target_path):
        try:
            os.remove(target_path)
            if directory == DIR_OUTPUTS:
                temporary_links.revoke_file(safe_filename)
            return True
        except Exception:
            logging.error("删除临时文件失败，请检查目录权限。")
            return False

    return False


def login_required(func):
    """登录保护装饰器。"""
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("index"))
        return func(*args, **kwargs)

    return decorated_function


def get_base_context() -> Dict[str, Any]:
    """模板基础上下文。"""
    try:
        install_info = read_install_info(BASE_DIR, APP_VERSION)
        version_label = display_build(APP_VERSION, install_info)
        build_channel = install_info['channel'] if install_info else 'stable'
    except (ValueError, OSError, TypeError):
        version_label, build_channel = APP_VERSION, 'unknown'
    return {
        "build_channel": build_channel,
        "logged_in": session.get("logged_in", False),
        "app_version": version_label,
        "base_version": APP_VERSION,
        "error_messages": [],
        "success_message": "",
        "result": None,
        "output_filename": "",
        "download_url": "",
        "file_download_url": "",
        "upload_filename": "",
        "country_mapping": parser.get_country_mapping(),
        "default_special_groups": DEFAULT_SPECIAL_GROUPS,
        "policy_fields": policy_engine.form_values(policy_engine.defaults()),
        "country_geoip": "off",
        "geoip_status": settings_status.geoip_status(geoip_store) if session.get("logged_in") else {"status": "Not installed"},
    }


def flash_page_context(context: Dict[str, Any]) -> None:
    """暂存一次性页面状态，用于 POST 后重定向回首页。"""
    session["page_context"] = {
        "error_messages": context.get("error_messages", []),
        "success_message": context.get("success_message", ""),
        "result": context.get("result"),
        "output_filename": context.get("output_filename", ""),
        "download_url": context.get("download_url", ""),
        "file_download_url": context.get("file_download_url", ""),
        "upload_filename": context.get("upload_filename", ""),
    }


def redirect_to_index(context: Dict[str, Any], anchor: str = ""):
    """POST/Redirect/GET，避免刷新时重复提交表单。"""
    flash_page_context(context)
    target = url_for("index")
    if anchor:
        target = f"{target}#{anchor}"
    return redirect(target)


def build_download_url(filename: str) -> str:
    slug = build_short_subscription_slug(filename)
    path = url_for("short_subscribe_file", slug=slug)
    if DOWNLOAD_BASE_URL:
        return f"{DOWNLOAD_BASE_URL}{path}"
    return url_for("short_subscribe_file", slug=slug, _external=True, _scheme=DOWNLOAD_URL_SCHEME or request.scheme)


def build_file_download_url(filename: str) -> str:
    """生成浏览器下载按钮链接。"""
    token = generate_download_token(filename)
    path = url_for("download_file", filename=filename, token=token)
    if DOWNLOAD_BASE_URL:
        return f"{DOWNLOAD_BASE_URL}{path}"
    return url_for("download_file", filename=filename, token=token, _external=True, _scheme=DOWNLOAD_URL_SCHEME or request.scheme)


def get_secret_key_bytes() -> bytes:
    key = app.secret_key
    if isinstance(key, bytes):
        return key
    return str(key).encode("utf-8")


def subscription_signer() -> SubscriptionSigner:
    return SubscriptionSigner(get_secret_key_bytes())


def generate_download_token(filename: str) -> str:
    return subscription_signer().full_token(filename)


def is_valid_download_token(filename: str, token: str) -> bool:
    return subscription_signer().valid_full_token(filename, token)


def is_valid_legacy_download_token(filename: str, token: str) -> bool:
    return subscription_signer().valid_legacy_token(filename, token)


def build_short_subscription_slug(filename: str) -> str:
    return subscription_signer().build_slug(filename)


def parse_short_subscription_slug(slug: str) -> tuple[str, str]:
    return subscription_signer().parse_slug(slug)


def invalid_download():
    return "Invalid download token.", 403, {"Content-Type": "text/plain; charset=utf-8"}


def authorized_download(filename: str, token: str, as_attachment: bool):
    if not safe_filename(filename):
        return invalid_download()
    if not (session.get("logged_in") or is_valid_download_token(filename, token)
            or is_valid_legacy_download_token(filename, token)):
        return invalid_download()
    return send_yaml_output(filename, as_attachment)


def send_yaml_output(filename: str, as_attachment: bool):
    """Serve only after the route has verified its specific credential format."""
    if not safe_filename(filename):
        return invalid_download()
    output_path = os.path.join(DIR_OUTPUTS, filename)
    if os.path.islink(output_path) or not os.path.isfile(output_path):
        return "YAML file not found.", 404, {"Content-Type": "text/plain; charset=utf-8"}
    return send_from_directory(
        DIR_OUTPUTS,
        filename,
        as_attachment=as_attachment,
        mimetype="application/x-yaml",
    )


# ==========================================
# 路由
# ==========================================
@app.route("/", methods=["GET"])
def index():
    context = get_base_context()
    context.update(session.pop("page_context", {}))
    context['csrf_notice'] = session.pop('csrf_notice', '')
    return render_template("index.html", **context)


@app.route("/login", methods=["POST"])
def login():
    password = request.form.get("password", "")
    context = get_base_context()

    authenticated, retry = login_limiter.attempt(request.remote_addr or 'unknown',
                                                lambda: auth_store.authenticate(password))
    if retry:
        context['error_messages'].append(f'登录尝试过多，请在 {retry} 秒后重试。')
        return render_template('index.html', **context), 429, {'Retry-After': str(retry)}
    if authenticated:
        session.clear()
        session.permanent = True
        session["logged_in"] = True
        session["auth_version"] = authenticated["auth_version"]
        session["auth_instance"] = authenticated["instance_id"]
        logging.info(f"登录成功 (IP: {request.remote_addr})")
        return redirect(url_for("index"))

    logging.warning(f"密码尝试失败 (IP: {request.remote_addr})")
    context["error_messages"].append("登录失败，密码错误。")
    return redirect_to_index(context)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/change-password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    context = get_base_context()

    if new_password != confirm_password:
        context["error_messages"].append("两次输入的新密码不一致。")
        return redirect_to_index(context)

    if not new_password:
        context["error_messages"].append("新密码不能为空。")
        return redirect_to_index(context)

    try:
        changed = auth_store.change_password(current_password, new_password,
                                             session.get('auth_version'), session.get('auth_instance'))
        if not changed:
            context['error_messages'].append('当前密码不正确或登录状态已失效。')
            return redirect_to_index(context)
    except Exception:
        logging.error("更新密码失败，请检查认证状态文件权限。")
        context["error_messages"].append("密码保存失败，请检查认证状态文件权限。")
        return redirect_to_index(context)

    session.clear()
    logging.info(f"管理密码已更新 (IP: {request.remote_addr})")
    context["success_message"] = "管理密码已更新，请使用新密码重新登录。"
    return redirect_to_index(context)


def parse_form_nodes(*, readonly=False):
    detection = geoip.parse_form(request.form)
    with geoip_store.lookup(detection['geoip'], readonly=readonly) as country_lookup:
        return generator.parse_form_nodes(request.form, country_lookup)


@app.route('/parse-nodes', methods=['POST'])
@login_required
def parse_nodes():
    try:
        result = parse_form_nodes()
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(nodes=result['preview'], errors=result['errors'])


class GenerateInputError(ValueError):
    """Reviewed source-selection messages shared with normal Generate."""


def selected_yaml_file():
    file = request.files.get('yaml_file')
    if file is None or file.filename == '':
        if request.form.get('yaml_source') == 'custom':
            raise GenerateInputError('Custom YAML needs to be selected again.')
        return None
    if not allowed_file(file.filename):
        raise GenerateInputError('不支持的文件格式，仅支持 .yaml 或 .yml 文件。')
    return file


def generation_special_groups():
    return [group for group in request.form.getlist('special_groups') if group in DEFAULT_SPECIAL_GROUPS]


@app.route('/api/preview-yaml-diff', methods=['POST'])
@login_required
def preview_yaml_diff():
    try:
        yaml_diff.check_form_size(request.form)
        policy = policy_engine.parse_form(request.form)
        file = selected_yaml_file()
        parsed = parse_form_nodes(readonly=True)
    except (GenerateInputError, yaml_diff.PreviewValidationError, policy_engine.PolicyError) as error:
        return jsonify(ok=False, error=str(error)), 400
    except ValueError as error:
        # Existing country/form parsers intentionally raise these fixed messages.
        # Unexpected ValueErrors must never reveal an exception's private text.
        safe = (geoip.MESSAGE, '辅助节点或手工修改格式无效，请检查名称、国家及链接。')
        message = str(error) if str(error) in safe else yaml_diff.PROCESSING_ERROR
        return jsonify(ok=False, error=message), 400
    except Exception:
        return jsonify(ok=False, error=yaml_diff.PROCESSING_ERROR), 400
    if parsed['errors']:
        return jsonify(ok=False, error=' '.join(parsed['errors'])), 400
    if not parsed['nodes']:
        return jsonify(ok=False, error='没有提供任何有效的新节点信息。'), 400
    try:
        if file is None:
            if not os.path.exists(DEFAULT_YAML_PATH):
                raise yaml_diff.PreviewValidationError('未上传 YAML，且默认 YAML 模板不存在。请先放置 defaults/default.yaml。')
            with open(DEFAULT_YAML_PATH, 'rb') as stream:
                source = yaml_diff.read_source(stream)
        else:
            source = yaml_diff.read_source(file.stream)
        result = yaml_diff.preview(source, parsed, generation_special_groups(), policy)
        response = jsonify(ok=True, **result)
        if len(response.get_data()) > yaml_diff.MAX_RESPONSE_BYTES:
            raise yaml_diff.PreviewLimitError(yaml_diff.TOO_LARGE)
        return response
    except yaml_diff.PreviewValidationError as error:
        return jsonify(ok=False, error=str(error)), 400
    except Exception:
        return jsonify(ok=False, error=yaml_diff.PROCESSING_ERROR), 400


@app.route("/process", methods=["POST"])
@login_required
def process_config():
    context = get_base_context()
    cleanup_old_files()

    def generation_error():
        context['country_geoip'] = request.form.get('country_geoip', 'off')[:64]
        # Redisplay policies in this response only; no new persisted temp state.
        if 'country_geoip' in request.form or any(key.startswith('policy_') for key in request.form):
            context['policy_fields'] = policy_engine.submitted_values(request.form)
            return render_template('index.html', **context), 400
        return redirect_to_index(context)

    try:
        policy = policy_engine.parse_form(request.form)
    except policy_engine.PolicyError as error:
        context['error_messages'].append(str(error))
        return generation_error()

    try:
        file = selected_yaml_file()
    except ValueError as error:
        context['error_messages'].append(str(error))
        return generation_error()
    use_default_yaml = file is None

    try:
        parsed_result = parse_form_nodes()
    except ValueError as error:
        context['error_messages'].append(str(error))
        return generation_error()
    if parsed_result['errors']:
        context['error_messages'].extend(parsed_result['errors'])
        return generation_error()
    if not parsed_result['nodes']:
        context['error_messages'].append('没有提供任何有效的新节点信息。')
        return generation_error()

    if use_default_yaml:
        if not os.path.exists(DEFAULT_YAML_PATH):
            context["error_messages"].append("未上传 YAML，且默认 YAML 模板不存在。请先放置 defaults/default.yaml。")
            return generation_error()
        upload_filename = ""
        upload_path = DEFAULT_YAML_PATH
    else:
        upload_filename = generate_safe_upload_filename(file.filename)
        upload_path = os.path.join(DIR_UPLOADS, upload_filename)

        try:
            fd = os.open(upload_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as target:
                file.save(target)
        except Exception:
            context["error_messages"].append("文件保存失败，请检查磁盘空间和目录权限。")
            return generation_error()

        context["upload_filename"] = upload_filename

    special_groups = generation_special_groups()

    yaml_result = generator.generate(upload_path, DIR_OUTPUTS, DIR_BACKUPS, parsed_result, special_groups, policy)

    if not yaml_result["success"]:
        context["error_messages"].extend(yaml_result["errors"])
        return generation_error()

    output_filename = os.path.basename(yaml_result["output_path"])

    context["success_message"] = "配置已成功更新，您可以下载或清理临时文件。"
    context["output_filename"] = output_filename
    short_id, metadata = temporary_links.create(output_filename, OUTPUT_RETENTION_SECONDS)
    path = url_for('temporary_subscribe', short_id=short_id)
    context['download_url'] = (DOWNLOAD_BASE_URL + path if DOWNLOAD_BASE_URL else
        url_for('temporary_subscribe', short_id=short_id, _external=True, _scheme=DOWNLOAD_URL_SCHEME or request.scheme))
    context['file_download_url'] = context['download_url'] + '?download=1'
    context["result"] = {
        "expires_at": datetime.fromtimestamp(metadata["expires_at"], timezone.utc).isoformat(timespec="minutes"),
        "old_node_count": yaml_result["old_node_count"],
        "new_node_count": yaml_result["new_node_count"],
        "group_count": yaml_result["group_count"],
        "rule_count": yaml_result["rule_count"],
    }

    logging.info(
        f"成功处理配置 | "
        f"输出文件: {output_filename} | "
        f"清洗旧节点: {yaml_result['old_node_count']} 个 | "
        f"注入新节点: {yaml_result['new_node_count']} 个"
    )

    return redirect_to_index(context, anchor="generate-result")


@app.route('/t/<short_id>', methods=['GET'])
def temporary_subscribe(short_id):
    entry = temporary_links.resolve(short_id)
    if entry is None:
        return 'Temporary YAML not found or expired.', 404, {'Cache-Control': 'no-store'}
    response = send_yaml_output(entry['filename'], as_attachment=request.args.get('download') == '1')
    if not isinstance(response, tuple):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    return authorized_download(filename, request.args.get("token", ""), as_attachment=True)


@app.route("/sub/<token>/<path:filename>", methods=["GET"])
def subscribe_file(token, filename):
    return authorized_download(filename, token, as_attachment=False)


@app.route("/s/<slug>", methods=["GET"])
def short_subscribe_file(slug):
    if FIXED_SLUG.fullmatch(slug):
        content = fixed_subscriptions.resolve(slug)
        if content is not None:
            response = Response(content, content_type='application/x-yaml; charset=utf-8')
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            if request.args.get('download') == '1':
                response.headers['Content-Disposition'] = 'attachment; filename="subscription.yaml"'
            return response
    filename, _signature = parse_short_subscription_slug(slug)
    if not filename:
        if '-fs_' in slug:
            return 'Not found.', 404, {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
        return "Invalid download token.", 403, {"Content-Type": "text/plain; charset=utf-8"}
    return send_yaml_output(filename, as_attachment=False)


@app.route("/delete-temp", methods=["POST"])
@login_required
def delete_temp():
    upload_filename = request.form.get("upload_filename", "")
    output_filename = request.form.get("output_filename", "")

    deleted_count = 0

    if upload_filename and safe_delete_file(DIR_UPLOADS, upload_filename):
        deleted_count += 1

    if output_filename and safe_delete_file(DIR_OUTPUTS, output_filename):
        deleted_count += 1

    context = get_base_context()

    if deleted_count > 0:
        context["success_message"] = f"已成功删除 {deleted_count} 个服务器临时文件。"
        logging.info("手动清理临时文件: %d 个", deleted_count)
    else:
        context["error_messages"].append("未找到可删除的文件或文件已被清理。")

    return redirect_to_index(context)


@app.errorhandler(StateError)
@app.errorhandler(OSError)
def state_unavailable(error):
    logging.error('共享安全状态不可用，请检查权限或恢复备份。')
    if request.path == '/api/preview-yaml-diff':
        return jsonify(ok=False, error='安全状态暂不可用，请联系管理员检查 state/。'), 503
    return '安全状态暂不可用，请联系管理员检查 state/。', 503


@app.errorhandler(413)
def request_entity_too_large(error):
    if request.path == '/api/preview-yaml-diff':
        return jsonify(ok=False, error=yaml_diff.TOO_LARGE), 413
    if request.blueprint == 'settings' and session.get('logged_in'):
        session['settings_error'] = 'GeoIP upload too large. Maximum database size is 32 MiB; previous database is unchanged.'
        return redirect(url_for('settings.index'), code=303)
    context = get_base_context()
    context["error_messages"].append("上传文件过大，最大支持 50MB。")
    return redirect_to_index(context)


@app.errorhandler(CSRFError)
def csrf_failed(error):
    # Rotate the token on the next GET; never replay or persist the rejected body.
    # Keep Flask-WTF's finite expiry and the existing authentication session.
    session.pop(app.config['WTF_CSRF_FIELD_NAME'], None)
    session['csrf_notice'] = (
        '安全令牌已刷新，请重试；如有草稿，将自动恢复。' if session.get('logged_in') else
        '请重新登录；如有草稿，将在登录后自动恢复。'
    )
    if request.endpoint in ('parse_nodes', 'preview_yaml_diff'):
        return jsonify(code='csrf_failed', error='Session or security token expired; refresh or log in again. Any saved draft will be restored.'), 400
    if request.blueprint == 'settings' and session.get('logged_in'):
        return redirect(url_for('settings.index'), code=303)
    if request.blueprint == 'fixed' and session.get('logged_in'):
        if request.endpoint in ('fixed.create', 'fixed.edit'):
            return redirect(url_for(request.endpoint, **(request.view_args or {})), code=303)
        return redirect(url_for('fixed.index'), code=303)
    return redirect(url_for('index'), code=303)


def fixed_public_url(slug):
    path = url_for('short_subscribe_file', slug=slug)
    return DOWNLOAD_BASE_URL + path if DOWNLOAD_BASE_URL else url_for(
        'short_subscribe_file', slug=slug, _external=True, _scheme=DOWNLOAD_URL_SCHEME or request.scheme)


def settings_runtime():
    return settings_status.runtime(port=APP_PORT, cookie_secure=COOKIE_SECURE,
        trust_proxy=TRUST_PROXY_HEADERS, download_base=DOWNLOAD_BASE_URL,
        download_scheme=DOWNLOAD_URL_SCHEME, upload_retention=UPLOAD_RETENTION_SECONDS,
        output_retention=OUTPUT_RETENTION_SECONDS, cleanup_interval=CLEANUP_INTERVAL_SECONDS,
        backup_retention=BACKUP_RETENTION_SECONDS, bind=APP_BIND_HOST,
        managed_https=https_metadata.status(BASE_DIR))


app.register_blueprint(settings_blueprint(geoip_store, get_base_context, login_required,
    proxy_health=proxy_health, fixed=fixed_subscriptions, runtime_context=settings_runtime, notifications=Notifications(DIR_STATE)))

app.register_blueprint(fixed_blueprint(fixed_subscriptions, get_base_context, login_required,
                                      DEFAULT_YAML_PATH, DEFAULT_SPECIAL_GROUPS, fixed_public_url,
                                      proxy_store=proxy_health))


@app.after_request
def private_fixed_pages(response):
    if request.path == '/api/preview-yaml-diff' and response.status_code == 302:
        # Keep an expired API session from following a GET that runs cleanup.
        response = jsonify(ok=False, code='session_expired', error='Session expired; refresh or log in again.')
        response.status_code = 401
    if request.blueprint in ('fixed', 'settings') or request.path == '/api/preview-yaml-diff':
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response


if __name__ == "__main__":
    logging.info(f"启动 clash-yaml-manager (Port: {APP_PORT})")
    app.run(host=APP_BIND_HOST, port=APP_PORT, debug=False)
