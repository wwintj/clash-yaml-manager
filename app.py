import hashlib
import hmac
import logging
import os
import re
import sys
import time
import uuid
from datetime import timedelta
from functools import wraps
from typing import Any, Dict

from flask import Flask, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect, CSRFError

from core import parser
from core import yaml_utils
from core.security import AuthStore, CREDENTIAL_KEYS
from core.state import StateError

# ==========================================
# 环境变量与应用配置
# ==========================================
APP_PORT = int(os.environ.get("APP_PORT", 8899))
SECRET_KEY = os.environ.get("SECRET_KEY")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
DOWNLOAD_BASE_URL = os.environ.get("DOWNLOAD_BASE_URL", "").rstrip("/")
DOWNLOAD_URL_SCHEME = os.environ.get("DOWNLOAD_URL_SCHEME", "").lower()
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() == "true"
if DOWNLOAD_URL_SCHEME not in ("", "http", "https"):
    sys.exit("DOWNLOAD_URL_SCHEME 必须为空、http 或 https。")
FILE_RETENTION_DAYS = int(os.environ.get("FILE_RETENTION_DAYS", os.environ.get("BACKUP_RETENTION_DAYS", 7)))
CLEANUP_INTERVAL_DAYS = int(os.environ.get("CLEANUP_INTERVAL_DAYS", os.environ.get("BACKUP_CLEANUP_INTERVAL_DAYS", 7)))

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
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


def cleanup_old_files() -> None:
    """每隔指定天数清理一次过期上传、输出和备份文件。"""
    now = time.time()
    cleanup_interval = max(CLEANUP_INTERVAL_DAYS, 1) * 86400
    retention_seconds = max(FILE_RETENTION_DAYS, 1) * 86400

    try:
        if os.path.exists(CLEANUP_MARKER):
            last_cleanup = os.path.getmtime(CLEANUP_MARKER)
            if now - last_cleanup < cleanup_interval:
                return

        deleted_count = 0
        for directory in [DIR_UPLOADS, DIR_OUTPUTS, DIR_BACKUPS]:
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                if not os.path.isfile(file_path):
                    continue

                if now - os.path.getmtime(file_path) >= retention_seconds:
                    os.remove(file_path)
                    deleted_count += 1

        with open(CLEANUP_MARKER, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        os.chmod(CLEANUP_MARKER, 0o600)

        if deleted_count > 0:
            logging.info(f"自动清理过期文件: {deleted_count} 个文件")
    except Exception:
        logging.warning("自动清理文件失败，请检查目录权限。")


ensure_directories()
auth_store = AuthStore(DIR_STATE)
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
if TRUST_PROXY_HEADERS:
    # Enable only behind exactly one trusted proxy that overwrites these headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = COOKIE_SECURE
app.config["PREFERRED_URL_SCHEME"] = DOWNLOAD_URL_SCHEME or "http"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)

if not SECRET_KEY:
    sys.exit("请设置固定 SECRET_KEY，所有 worker 必须使用同一密钥。")
else:
    app.secret_key = SECRET_KEY

@app.before_request
def invalidate_old_sessions():
    if session.get('logged_in'):
        state = auth_store.read()
        if (session.get('auth_version') != state['auth_version'] or
                session.get('auth_instance') != state['instance_id']):
            session.clear()


CSRFProtect(app)


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
    return {
        "logged_in": session.get("logged_in", False),
        "error_messages": [],
        "success_message": "",
        "result": None,
        "output_filename": "",
        "download_url": "",
        "file_download_url": "",
        "upload_filename": "",
        "country_mapping": parser.get_country_mapping(),
        "default_special_groups": DEFAULT_SPECIAL_GROUPS,
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


def generate_download_token(filename: str) -> str:
    """为公开 YAML 下载链接生成签名，避免未授权枚举下载。"""
    return hmac.new(get_secret_key_bytes(), filename.encode("utf-8"), hashlib.sha256).hexdigest()


def is_valid_download_token(filename: str, token: str) -> bool:
    if not isinstance(token, str) or not re.fullmatch(r"(?:[0-9a-f]{8}|[0-9a-f]{12}|[0-9a-f]{64})", token):
        return False
    expected_token = generate_download_token(filename)
    expected_short_token = expected_token[:len(token)]
    return hmac.compare_digest(token, expected_token) or (
        len(token) in {8, 12} and hmac.compare_digest(token, expected_short_token)
    )


def generate_short_download_signature(filename: str) -> str:
    return generate_download_token(filename)[:8]


def encode_base36(number: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if number == 0:
        return "0"

    encoded = ""
    while number > 0:
        number, remainder = divmod(number, 36)
        encoded = alphabet[remainder] + encoded
    return encoded


def decode_base36(value: str) -> int:
    return int(value, 36)


def build_short_subscription_slug(filename: str) -> str:
    safe_filename = os.path.basename(filename)
    match = re.fullmatch(r"tim_(\d{8})_(\d+)\.yaml", safe_filename)
    if match:
        date_part, count_part = match.groups()
        signature = generate_short_download_signature(safe_filename)
        return f"{date_part[2:]}{encode_base36(int(count_part))}{signature}"

    stem, _ = os.path.splitext(safe_filename)
    signature = generate_short_download_signature(safe_filename)
    return f"{stem}-{signature}"


def parse_short_subscription_slug(slug: str) -> tuple[str, str]:
    safe_slug = os.path.basename(slug)
    compact_match = re.fullmatch(r"(\d{6})([0-9a-z]+)([0-9a-f]{8})", safe_slug)
    if compact_match:
        date_part, count_part, signature = compact_match.groups()
        try:
            filename = f"tim_20{date_part}_{decode_base36(count_part)}.yaml"
        except ValueError:
            return "", ""

        if is_valid_download_token(filename, signature):
            return filename, signature

        return "", ""

    if "-" not in safe_slug:
        return "", ""

    stem, signature = safe_slug.rsplit("-", 1)
    filename = f"{stem}.yaml"
    if not stem or not is_valid_download_token(filename, signature):
        return "", ""

    return filename, signature


def send_yaml_output(filename: str, token: str, as_attachment: bool):
    safe_filename = os.path.basename(filename)

    if not session.get("logged_in") and not is_valid_download_token(safe_filename, token):
        return "Invalid download token.", 403, {"Content-Type": "text/plain; charset=utf-8"}

    output_path = os.path.join(DIR_OUTPUTS, safe_filename)
    if not os.path.isfile(output_path):
        return "YAML file not found.", 404, {"Content-Type": "text/plain; charset=utf-8"}

    return send_from_directory(
        DIR_OUTPUTS,
        safe_filename,
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
    return render_template("index.html", **context)


@app.route("/login", methods=["POST"])
def login():
    password = request.form.get("password", "")
    context = get_base_context()

    authenticated = auth_store.authenticate(password)
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


@app.route("/process", methods=["POST"])
@login_required
def process_config():
    context = get_base_context()
    cleanup_old_files()

    file = request.files.get("yaml_file")
    use_default_yaml = file is None or file.filename == ""

    if not use_default_yaml and not allowed_file(file.filename):
        context["error_messages"].append("不支持的文件格式，仅支持 .yaml 或 .yml 文件。")
        return redirect_to_index(context)

    batch_text = request.form.get("batch_nodes", "").strip()
    single_country = request.form.get("single_country", "").strip()
    single_name = request.form.get("single_name", "").strip()
    single_link = request.form.get("single_link", "").strip()

    if single_country and single_name and single_link:
        single_line = f"{single_country}|{single_name}|{single_link}"
        batch_text = f"{batch_text}\n{single_line}" if batch_text else single_line

    if not batch_text.strip():
        context["error_messages"].append("没有提供任何有效的新节点信息。")
        return redirect_to_index(context)

    if use_default_yaml:
        if not os.path.exists(DEFAULT_YAML_PATH):
            context["error_messages"].append("未上传 YAML，且默认 YAML 模板不存在。请先放置 defaults/default.yaml。")
            return redirect_to_index(context)
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
            return redirect_to_index(context)

        context["upload_filename"] = upload_filename

    parsed_result = parser.parse_batch_nodes(batch_text)

    if parsed_result["errors"]:
        context["error_messages"].extend(parsed_result["errors"])
        return redirect_to_index(context)

    raw_special_groups = request.form.getlist("special_groups")
    special_groups = [group for group in raw_special_groups if group in DEFAULT_SPECIAL_GROUPS]

    yaml_result = yaml_utils.process_yaml_config(
        input_path=upload_path,
        output_dir=DIR_OUTPUTS,
        backup_dir=DIR_BACKUPS,
        new_nodes=parsed_result["nodes"],
        countries=parsed_result["countries"],
        special_groups=special_groups,
    )

    if not yaml_result["success"]:
        context["error_messages"].extend(yaml_result["errors"])
        return redirect_to_index(context)

    output_filename = os.path.basename(yaml_result["output_path"])

    context["success_message"] = "配置已成功更新，您可以下载或清理临时文件。"
    context["output_filename"] = output_filename
    context["download_url"] = build_download_url(output_filename)
    context["file_download_url"] = build_file_download_url(output_filename)
    context["result"] = {
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


@app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    return send_yaml_output(filename, request.args.get("token", ""), as_attachment=True)


@app.route("/sub/<token>/<path:filename>", methods=["GET"])
def subscribe_file(token, filename):
    return send_yaml_output(filename, token, as_attachment=False)


@app.route("/s/<slug>", methods=["GET"])
def short_subscribe_file(slug):
    filename, signature = parse_short_subscription_slug(slug)
    if not filename:
        return "Invalid download token.", 403, {"Content-Type": "text/plain; charset=utf-8"}
    return send_yaml_output(filename, signature, as_attachment=False)


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
def state_unavailable(error):
    logging.error('共享安全状态不可用，请检查权限或恢复备份。')
    return '安全状态暂不可用，请联系管理员检查 state/。', 503


@app.errorhandler(413)
def request_entity_too_large(error):
    context = get_base_context()
    context["error_messages"].append("上传文件过大，最大支持 50MB。")
    return redirect_to_index(context)


@app.errorhandler(CSRFError)
def csrf_failed(error):
    context = get_base_context()
    context['error_messages'].append('表单已过期或安全令牌无效，请刷新页面后重试。')
    return render_template('index.html', **context), 400


if __name__ == "__main__":
    logging.info(f"启动 clash-yaml-manager (Port: {APP_PORT})")
    app.run(host="0.0.0.0", port=APP_PORT, debug=False)
