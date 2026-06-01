import base64
import hmac
import logging
import os
import sys
import time
import uuid
from functools import wraps
from typing import Any, Dict

from flask import Flask, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

from core import parser
from core import yaml_utils

# ==========================================
# 环境变量与应用配置
# ==========================================
def load_app_password() -> str:
    """Load password from env. APP_PASSWORD_B64 supports spaces and special characters."""
    password_b64 = os.environ.get("APP_PASSWORD_B64", "")
    if password_b64:
        try:
            return base64.b64decode(password_b64.encode("ascii")).decode("utf-8")
        except Exception:
            print("❌ 启动失败: APP_PASSWORD_B64 不是有效的 Base64 UTF-8 字符串。")
            sys.exit(1)

    return os.environ.get("APP_PASSWORD", "")


APP_PASSWORD = load_app_password()
if not APP_PASSWORD:
    print("❌ 启动失败: 请务必设置环境变量 APP_PASSWORD 以保护 Web 面板。")
    sys.exit(1)

APP_PORT = int(os.environ.get("APP_PORT", 8899))
SECRET_KEY = os.environ.get("SECRET_KEY")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DIR_UPLOADS = os.path.join(BASE_DIR, "uploads")
DIR_OUTPUTS = os.path.join(BASE_DIR, "outputs")
DIR_BACKUPS = os.path.join(BASE_DIR, "backups")
DIR_LOGS = os.path.join(BASE_DIR, "logs")
DIR_DEFAULTS = os.path.join(BASE_DIR, "defaults")
ENV_FILE = os.path.join(BASE_DIR, ".env")
DEFAULT_YAML_PATH = os.path.join(DIR_DEFAULTS, "default.yaml")

ALLOWED_EXTENSIONS = {"yaml", "yml"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

DEFAULT_SPECIAL_GROUPS = [
    "🎥 奈飞节点",
    "📹 油管视频",
    "💬 Ai平台",
    "📲 电报消息",
    "🎵 TikTok",
    "🎬 HBO",
    "𝕏 X/Twitter",
]


# ==========================================
# 模块级初始化
# ==========================================
def ensure_directories() -> None:
    """确保必要目录存在。"""
    for directory in [DIR_UPLOADS, DIR_OUTPUTS, DIR_BACKUPS, DIR_LOGS, DIR_DEFAULTS]:
        os.makedirs(directory, exist_ok=True)


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


ensure_directories()
setup_logging()


# ==========================================
# Flask 应用初始化
# ==========================================
app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = COOKIE_SECURE

if not SECRET_KEY:
    app.secret_key = os.urandom(24)
    logging.warning("未设置 SECRET_KEY 环境变量，已生成临时 Key。生产环境建议设置固定 SECRET_KEY。")
else:
    app.secret_key = SECRET_KEY


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
        except Exception as e:
            logging.error(f"删除文件失败 {safe_filename}: {str(e)}")
            return False

    return False


def secure_password_equals(candidate: str, expected: str) -> bool:
    """Compare passwords as UTF-8 bytes so non-ASCII characters are supported."""
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def write_env_password(new_password: str) -> None:
    """Persist password to .env using Base64 so spaces and symbols are safe."""
    password_b64 = base64.b64encode(new_password.encode("utf-8")).decode("ascii")
    existing_values: Dict[str, str] = {
        "APP_PORT": str(APP_PORT),
        "SECRET_KEY": SECRET_KEY or "",
        "COOKIE_SECURE": "true" if COOKIE_SECURE else "false",
    }

    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key != "APP_PASSWORD":
                    existing_values[key] = value

    existing_values["APP_PASSWORD_B64"] = password_b64

    preferred_order = ["APP_PASSWORD_B64", "APP_PORT", "SECRET_KEY", "COOKIE_SECURE"]
    ordered_keys = preferred_order + [key for key in existing_values if key not in preferred_order]

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for key in ordered_keys:
            f.write(f"{key}={existing_values.get(key, '')}\n")

    os.chmod(ENV_FILE, 0o600)


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
        "upload_filename": "",
        "country_mapping": parser.get_country_mapping(),
        "default_special_groups": DEFAULT_SPECIAL_GROUPS,
    }


# ==========================================
# 路由
# ==========================================
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", **get_base_context())


@app.route("/login", methods=["POST"])
def login():
    password = request.form.get("password", "")
    context = get_base_context()

    if secure_password_equals(password, APP_PASSWORD):
        session["logged_in"] = True
        logging.info(f"登录成功 (IP: {request.remote_addr})")
        return redirect(url_for("index"))

    logging.warning(f"密码尝试失败 (IP: {request.remote_addr})")
    context["error_messages"].append("登录失败，密码错误。")
    return render_template("index.html", **context)


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("index"))


@app.route("/change-password", methods=["POST"])
@login_required
def change_password():
    global APP_PASSWORD

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    context = get_base_context()

    if not secure_password_equals(current_password, APP_PASSWORD):
        context["error_messages"].append("当前密码不正确。")
        return render_template("index.html", **context)

    if new_password != confirm_password:
        context["error_messages"].append("两次输入的新密码不一致。")
        return render_template("index.html", **context)

    if not new_password:
        context["error_messages"].append("新密码不能为空。")
        return render_template("index.html", **context)

    try:
        write_env_password(new_password)
    except Exception as e:
        logging.error(f"更新密码失败: {str(e)}")
        context["error_messages"].append(f"密码保存失败: {str(e)}")
        return render_template("index.html", **context)

    APP_PASSWORD = new_password
    session.pop("logged_in", None)
    logging.info(f"管理密码已更新 (IP: {request.remote_addr})")
    context["success_message"] = "管理密码已更新，请使用新密码重新登录。"
    context["logged_in"] = False
    return render_template("index.html", **context)


@app.route("/process", methods=["POST"])
@login_required
def process_config():
    context = get_base_context()

    file = request.files.get("yaml_file")
    use_default_yaml = file is None or file.filename == ""

    if not use_default_yaml and not allowed_file(file.filename):
        context["error_messages"].append("不支持的文件格式，仅支持 .yaml 或 .yml 文件。")
        return render_template("index.html", **context)

    batch_text = request.form.get("batch_nodes", "").strip()
    single_country = request.form.get("single_country", "").strip()
    single_name = request.form.get("single_name", "").strip()
    single_link = request.form.get("single_link", "").strip()

    if single_country and single_name and single_link:
        single_line = f"{single_country}|{single_name}|{single_link}"
        batch_text = f"{batch_text}\n{single_line}" if batch_text else single_line

    if not batch_text.strip():
        context["error_messages"].append("没有提供任何有效的新节点信息。")
        return render_template("index.html", **context)

    if use_default_yaml:
        if not os.path.exists(DEFAULT_YAML_PATH):
            context["error_messages"].append("未上传 YAML，且默认 YAML 模板不存在。请先放置 defaults/default.yaml。")
            return render_template("index.html", **context)
        upload_filename = ""
        upload_path = DEFAULT_YAML_PATH
    else:
        upload_filename = generate_safe_upload_filename(file.filename)
        upload_path = os.path.join(DIR_UPLOADS, upload_filename)

        try:
            file.save(upload_path)
            os.chmod(upload_path, 0o600)
        except Exception as e:
            context["error_messages"].append(f"文件保存失败: {str(e)}")
            return render_template("index.html", **context)

        context["upload_filename"] = upload_filename

    parsed_result = parser.parse_batch_nodes(batch_text)

    if parsed_result["errors"]:
        context["error_messages"].extend(parsed_result["errors"])
        return render_template("index.html", **context)

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
        return render_template("index.html", **context)

    output_filename = os.path.basename(yaml_result["output_path"])

    context["success_message"] = "配置已成功更新，您可以下载或清理临时文件。"
    context["output_filename"] = output_filename
    context["result"] = {
        "old_node_count": yaml_result["old_node_count"],
        "new_node_count": yaml_result["new_node_count"],
        "group_count": yaml_result["group_count"],
        "rule_count": yaml_result["rule_count"],
    }

    logging.info(
        f"成功处理配置 | "
        f"原始文件: {upload_filename} | "
        f"输出文件: {output_filename} | "
        f"清洗旧节点: {yaml_result['old_node_count']} 个 | "
        f"注入新节点: {yaml_result['new_node_count']} 个"
    )

    return render_template("index.html", **context)


@app.route("/download/<path:filename>", methods=["GET"])
@login_required
def download_file(filename):
    safe_filename = os.path.basename(filename)
    return send_from_directory(DIR_OUTPUTS, safe_filename, as_attachment=True)


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
        logging.info(f"清理临时文件: {upload_filename}, {output_filename}")
    else:
        context["error_messages"].append("未找到可删除的文件或文件已被清理。")

    return render_template("index.html", **context)


@app.errorhandler(413)
def request_entity_too_large(error):
    context = get_base_context()
    context["error_messages"].append("上传文件过大，最大支持 50MB。")
    return render_template("index.html", **context), 413


if __name__ == "__main__":
    logging.info(f"启动 clash-yaml-manager (Port: {APP_PORT})")
    app.run(host="0.0.0.0", port=APP_PORT, debug=False)
