import hmac
import subprocess
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
APP_PASSWORD = os.environ.get("APP_PASSWORD")
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
ENV_FILE = os.path.join(BASE_DIR, ".env")

ALLOWED_EXTENSIONS = {"yaml", "yml"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

DEFAULT_SPECIAL_GROUPS = [
    "🎥 奈飞节点",
    "📹 油管视频",
    "💬 Ai平台",
    "📲 电报消息",
]


# ==========================================
# 模块级初始化
# ==========================================
def ensure_directories() -> None:
    """确保必要目录存在。"""
    for directory in [DIR_UPLOADS, DIR_OUTPUTS, DIR_BACKUPS, DIR_LOGS]:
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

    if hmac.compare_digest(password, APP_PASSWORD):
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


@app.route("/process", methods=["POST"])
@login_required
def process_config():
    context = get_base_context()

    if "yaml_file" not in request.files:
        context["error_messages"].append("未找到文件上传字段。")
        return render_template("index.html", **context)

    file = request.files["yaml_file"]

    if file.filename == "":
        context["error_messages"].append("请选择一个 YAML 文件进行上传。")
        return render_template("index.html", **context)

    if not allowed_file(file.filename):
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
    context["error_messages"].append("上传文件过大，最大支持 5MB。")
    return render_template("index.html", **context), 413


if __name__ == "__main__":
    logging.info(f"启动 clash-yaml-manager (Port: {APP_PORT})")
    app.run(host="0.0.0.0", port=APP_PORT, debug=False)
