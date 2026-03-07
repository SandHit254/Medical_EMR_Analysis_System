"""
模块名称：医疗命名实体识别 (NER) 模型表现与交互层
功能描述：基于 Flask 框架实现，承担模型仿真验证环境的宿主功能。
         向下隔离外网访问以确保加载本地微调权重；
         向上提供面向人类操作者的可视化视图路由，以及系统热重载/数据飞轮 API。
"""

import os
import json
import logging
from flask import Flask, request, render_template, jsonify, send_from_directory
from werkzeug.utils import secure_filename

# =====================================================================
# 环境变量级运行约束
# 声明：切断 HuggingFace 远端同步逻辑，强制系统运行于离线私有化部署模式，
# 确保底座模型严格加载本地基于医疗数据集微调的特定参数矩阵。
# =====================================================================
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_UPDATE_DEFAULT_BETA"] = "False"

# 引入核心模型管线调度器与配置中心
from main import run_medical_pipeline
from app.config_manager import ConfigManager

app = Flask(__name__)

# 配置运行时目录及文件 IO 限制
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads_temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "patient_records")
CONFIGS_DIR = os.path.join(BASE_DIR, "configs")

os.makedirs(UPLOAD_DIR, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 内存安全阈值：16MB

# 允许处理的图像扩展名集
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "tiff"}


def allowed_file(filename: str) -> bool:
    """校验上传文件是否符合受支持的图像格式"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/", methods=["GET"])
def index():
    """装载系统仿真验证终端的基础视图"""
    return render_template("index.html", record=None, error=None, image_filename=None)


@app.route("/uploads_temp/<filename>")
def serve_image(filename):
    """提供本地图像文件的静态访问路由，支撑前端的多模态溯源比对"""
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# =====================================================================
# 接口模块 1：面向前端工作站的可视化核心路由
# =====================================================================
@app.route("/analyze", methods=["POST"])
def analyze_view():
    """
    接收多段表单数据，调度底层模型推理管线，并将结构化参数交由 Jinja2 渲染。
    """
    if "image" not in request.files:
        return render_template(
            "index.html", error="I/O 异常：请求体中缺失图像二进制流。"
        )

    file = request.files["image"]
    if file.filename == "" or not allowed_file(file.filename):
        return render_template(
            "index.html", error="I/O 异常：文件为空或为不受支持的格式类型。"
        )

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    try:
        snapshot_dir = run_medical_pipeline(file_path)
        json_target_path = os.path.join(snapshot_dir, "05_final_summary.json")

        if os.path.exists(json_target_path):
            with open(json_target_path, "r", encoding="utf-8") as f:
                record_data = json.load(f)
            return render_template(
                "index.html", record=record_data, error=None, image_filename=filename
            )
        else:
            return render_template(
                "index.html", error=f"模型管线中断：缺失状态机文件 {json_target_path}"
            )

    except Exception as e:
        logging.error(f"视图渲染层捕获底层调度器异常: {str(e)}", exc_info=True)
        return render_template("index.html", error=f"内核级错误: {str(e)}")


@app.route("/save_report", methods=["POST"])
def save_report():
    """
    数据质控回传接口：接收经医疗人员人工核对后的修正数据并持久化落库。
    """
    try:
        payload = request.json
        visit_id = payload.get("就诊编号")
        patient_id = payload.get("患者ID", "UNKNOWN")

        if not visit_id or not visit_id.startswith("V_"):
            return (
                jsonify({"status": "error", "message": "非法的就诊批次标识符。"}),
                400,
            )

        patient_folder_name = (
            patient_id if patient_id.startswith("PID_") else f"PID_{patient_id}"
        )
        target_dir = os.path.join(OUTPUT_DIR, patient_folder_name, visit_id)

        if not os.path.exists(target_dir):
            return (
                jsonify({"status": "error", "message": "无法寻址至目标物理存储目录。"}),
                404,
            )

        save_path = os.path.join(target_dir, "06_human_verified.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)

        return jsonify({"status": "success", "message": "修正数据回存完毕。"})
    except Exception as e:
        return (
            jsonify({"status": "error", "message": f"持久化 I/O 错误: {str(e)}"}),
            500,
        )


# =====================================================================
# 接口模块 2：参数热重载与数据飞轮 API (新增机制)
# =====================================================================
@app.route("/api/settings/rules", methods=["GET"])
def get_rules_settings():
    """读取并下发底层 rules.json 配置，供前端可视化控制台渲染"""
    try:
        rules_path = os.path.join(CONFIGS_DIR, "rules.json")
        with open(rules_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"code": 200, "message": "success", "data": data}), 200
    except Exception as e:
        return jsonify({"code": 500, "message": f"读取配置失败: {str(e)}"}), 500


@app.route("/api/settings/rules", methods=["POST"])
def update_rules_settings():
    """接收前端面板参数覆写 rules.json，并即刻触发底层内存热重载"""
    try:
        new_data = request.json
        rules_path = os.path.join(CONFIGS_DIR, "rules.json")

        # 1. 覆写物理 JSON 文件
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=4)

        # 2. 调度单例对象重载内存，使新阈值/规则在下一次推理中直接生效
        ConfigManager().reload()

        return jsonify({"code": 200, "message": "业务规则已覆写，热重载完成。"}), 200
    except Exception as e:
        return jsonify({"code": 500, "message": f"配置下发失败: {str(e)}"}), 500


@app.route("/api/ocr/correct", methods=["POST"])
def add_ocr_correction():
    """
    主动学习（数据飞轮）接口：接收医生人工纠错的词对，
    静默追加至 rules.json 的 corrections 字典中。
    """
    try:
        payload = request.json
        wrong_text = payload.get("wrong")
        right_text = payload.get("right")

        if not wrong_text or not right_text:
            return (
                jsonify({"code": 400, "message": "参数异常：缺失源词或目标词。"}),
                400,
            )

        rules_path = os.path.join(CONFIGS_DIR, "rules.json")
        with open(rules_path, "r", encoding="utf-8") as f:
            rule_data = json.load(f)

        # 建立/更新字典映射关系
        if "corrections" not in rule_data:
            rule_data["corrections"] = {}
        rule_data["corrections"][wrong_text] = right_text

        # 覆写并重载
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(rule_data, f, ensure_ascii=False, indent=4)

        ConfigManager().reload()

        return (
            jsonify(
                {
                    "code": 200,
                    "message": f"主动学习记录成功：'{wrong_text}' -> '{right_text}'",
                }
            ),
            200,
        )
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)}), 500


if __name__ == "__main__":
    # 启用多线程模式以应对并发验证测试
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
