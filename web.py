"""
模块名称：Web 展示与人机交互接口层
功能描述：基于 Flask 框架实现的轻量级 Web 服务。负责约束底层引擎的网络行为，
         提供图像上传、结果解析呈现、原始影像溯源以及人工核对后报告的归档功能。
"""

import os
import json
from flask import Flask, request, render_template, jsonify, send_from_directory
from werkzeug.utils import secure_filename

# =====================================================================
# 环境约束声明
# 强制隔离 HuggingFace 外网连接，确保底层 NEREngine 加载本地微调权重。
# 此段代码必须位于底层业务模块导入之前。
# =====================================================================
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_UPDATE_DEFAULT_BETA"] = "False"

from main import run_medical_pipeline

app = Flask(__name__)

# 配置系统路径与上传参数
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads_temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "patient_records")

os.makedirs(UPLOAD_DIR, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 限制最大文件体积为 16MB


@app.route("/", methods=["GET"])
def index():
    """渲染系统初始视图"""
    return render_template("index.html", record=None, error=None, image_filename=None)


@app.route("/uploads_temp/<filename>")
def serve_image(filename):
    """
    提供静态文件路由，用于前端溯源展示原始医疗影像。
    """
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    处理影像上传请求，调度核心识别引擎，并读取生成的结构化病历数据。
    """
    if "image" not in request.files:
        return render_template(
            "index.html", error="系统异常：未在请求体中检测到图像文件。"
        )

    file = request.files["image"]
    if file.filename == "":
        return render_template("index.html", error="系统异常：未选择待上传的影像文件。")

    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        try:
            # 调度底层管线并获取输出快照目录
            snapshot_dir = run_medical_pipeline(file_path)

            # 定位并读取 05 阶段的最终结构化 JSON 文件
            json_target_path = os.path.join(snapshot_dir, "05_final_summary.json")
            if os.path.exists(json_target_path):
                with open(json_target_path, "r", encoding="utf-8") as f:
                    record_data = json.load(f)
                return render_template(
                    "index.html",
                    record=record_data,
                    error=None,
                    image_filename=filename,
                )
            else:
                return render_template(
                    "index.html",
                    error=f"底层引擎执行完毕，但缺失目标数据文件: {json_target_path}",
                )

        except Exception as e:
            return render_template("index.html", error=f"底层调度异常阻断: {str(e)}")


@app.route("/save_report", methods=["POST"])
def save_report():
    """
    接收前端人工核对后的结构化数据，并作为最终临床报告进行持久化归档。
    存储格式规范：保留原始 05 文件，生成人工确认的 06 文件。
    """
    try:
        payload = request.json
        visit_id = payload.get("就诊编号")
        patient_id = payload.get("患者ID", "UNKNOWN")

        if not visit_id or not visit_id.startswith("V_"):
            return jsonify(
                {"status": "error", "message": "无效的就诊编号，归档被拒绝。"}
            )

        # 目录寻址修正：确保解析后的患者 ID 具备底层引擎规范的 PID_ 前缀
        if not patient_id.startswith("PID_"):
            patient_folder_name = f"PID_{patient_id}"
        else:
            patient_folder_name = patient_id

        # 根据系统目录规范定位快照文件夹
        target_dir = os.path.join(OUTPUT_DIR, patient_folder_name, visit_id)

        if not os.path.exists(target_dir):
            return jsonify(
                {"status": "error", "message": f"未找到就诊记录物理目录: {target_dir}"}
            )

        # 执行 06_human_verified 文件持久化
        save_path = os.path.join(target_dir, "06_human_verified.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)

        return jsonify({"status": "success", "message": "人工复核报告已成功归档入库。"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"持久化存储异常: {str(e)}"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
