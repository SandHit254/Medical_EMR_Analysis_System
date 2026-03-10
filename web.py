"""
模块名称：医疗命名实体识别 (NER) 模型表现与交互层
"""

import os
import json
import logging
import shutil
from flask import Flask, request, render_template, jsonify, send_from_directory
from werkzeug.utils import secure_filename

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_UPDATE_DEFAULT_BETA"] = "False"

from main import run_medical_pipeline
from app.config_manager import ConfigManager
from app.storage import StorageEngine

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads_temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "patient_records")
CONFIGS_DIR = os.path.join(BASE_DIR, "configs")

os.makedirs(UPLOAD_DIR, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "tiff"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_emr_config():
    rules_cfg = ConfigManager().get_section("rules")
    emr_struct = rules_cfg.get("emr_structure", {})
    if not emr_struct:
        emr_struct = {
            "standard_fields": [
                "姓名",
                "性别",
                "年龄",
                "主诉",
                "现病史",
                "既往史",
                "过敏史",
                "体格检查",
                "辅助检查",
                "初步诊断",
                "处理",
            ],
            "required_fields": ["姓名", "性别", "年龄", "主诉", "过敏史", "初步诊断"],
        }
    return emr_struct


@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        record=None,
        error=None,
        image_filename=None,
        history_img_url=None,
        emr_config=get_emr_config(),
    )


@app.route("/uploads_temp/<filename>")
def serve_image(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/analyze", methods=["POST"])
def analyze_view():
    if "image" not in request.files:
        return render_template(
            "index.html", error="I/O 异常：缺失图像。", emr_config=get_emr_config()
        )
    file = request.files["image"]
    if file.filename == "" or not allowed_file(file.filename):
        return render_template(
            "index.html",
            error="I/O 异常：文件为空或格式不支持。",
            emr_config=get_emr_config(),
        )

    patient_id = request.form.get("patient_id", "").strip()
    if not patient_id:
        from main import generate_patient_id

        patient_id = generate_patient_id()

    patient_info = {
        "姓名": request.form.get("patient_name", "").strip(),
        "性别": request.form.get("patient_gender", "").strip(),
        "年龄": request.form.get("patient_age", "").strip(),
    }

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    try:
        snapshot_dir = run_medical_pipeline(
            file_path, patient_id=patient_id, patient_info=patient_info
        )
        json_target_path = os.path.join(snapshot_dir, "05_final_summary.json")
        if os.path.exists(json_target_path):
            with open(json_target_path, "r", encoding="utf-8") as f:
                record_data = json.load(f)
            return render_template(
                "index.html",
                record=record_data,
                error=None,
                image_filename=filename,
                history_img_url=None,
                emr_config=get_emr_config(),
            )
        else:
            return render_template(
                "index.html",
                error=f"缺失状态机文件 {json_target_path}",
                emr_config=get_emr_config(),
            )
    except Exception as e:
        logging.error(f"视图渲染层捕获异常: {str(e)}", exc_info=True)
        return render_template(
            "index.html", error=f"内核级错误: {str(e)}", emr_config=get_emr_config()
        )


@app.route("/save_report", methods=["POST"])
def save_report():
    try:
        payload = request.json
        visit_id = payload.get("就诊编号")
        patient_id = payload.get("患者ID", "UNKNOWN")
        if not visit_id or not visit_id.startswith("V_"):
            return jsonify({"status": "error", "message": "非法的就诊批次。"})
        patient_folder_name = (
            patient_id if patient_id.startswith("PID_") else f"PID_{patient_id}"
        )
        target_dir = os.path.join(OUTPUT_DIR, patient_folder_name, visit_id)
        if not os.path.exists(target_dir):
            return jsonify({"status": "error", "message": "无法寻址存储目录。"})
        save_path = os.path.join(target_dir, "06_human_verified.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
        return jsonify({"status": "success", "message": "修正数据回存完毕。"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"持久化 I/O 错误: {str(e)}"})


# =====================================================================
# 左侧栏：病例库树状图与多模态搜索引擎 API
# =====================================================================
@app.route("/api/library/tree", methods=["GET"])
def get_library_tree():
    try:
        tree = StorageEngine().get_patient_tree()
        return jsonify({"code": 200, "tree": tree})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/library/search", methods=["POST"])
def search_library():
    try:
        query = request.json.get("query", "")
        results = StorageEngine().search_records(query)
        return jsonify({"code": 200, "results": results})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/records/<patient_id>/<visit_id>/image")
def serve_record_image(patient_id, visit_id):
    """单独提供历史影像的渲染流"""
    engine = StorageEngine()
    patient_folder = (
        patient_id if patient_id.startswith("PID_") else f"PID_{patient_id}"
    )
    visit_dir = os.path.join(engine.root, patient_folder, visit_id)
    return send_from_directory(visit_dir, "01_source.jpg")


@app.route("/view/<patient_id>/<visit_id>", methods=["GET"])
def view_record(patient_id, visit_id):
    """历史病历回溯系统：自动加载旧版 JSON 并无缝渲染至工作站"""
    try:
        engine = StorageEngine()
        patient_folder = (
            patient_id if patient_id.startswith("PID_") else f"PID_{patient_id}"
        )
        visit_dir = os.path.join(engine.root, patient_folder, visit_id)

        target_file = os.path.join(visit_dir, "06_human_verified.json")
        if not os.path.exists(target_file):
            target_file = os.path.join(visit_dir, "05_final_summary.json")

        if os.path.exists(target_file):
            with open(target_file, "r", encoding="utf-8") as f:
                record_data = json.load(f)

            img_url = None
            if os.path.exists(os.path.join(visit_dir, "01_source.jpg")):
                img_url = f"/records/{patient_folder}/{visit_id}/image"

            return render_template(
                "index.html",
                record=record_data,
                error=None,
                image_filename=None,
                history_img_url=img_url,
                emr_config=get_emr_config(),
            )
        else:
            return render_template(
                "index.html",
                error="检索的病历已被删除或损坏。",
                emr_config=get_emr_config(),
            )
    except Exception as e:
        return render_template(
            "index.html",
            error=f"加载历史病历失败: {str(e)}",
            emr_config=get_emr_config(),
        )


@app.route("/api/patients", methods=["GET"])
def get_patients_list():
    try:
        patients = StorageEngine().get_all_patients_info()
        return jsonify({"code": 200, "patients": patients})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/patients/new", methods=["GET"])
def create_new_patient():
    from main import generate_patient_id

    return jsonify({"code": 200, "patient_id": generate_patient_id()})


@app.route("/api/settings/all", methods=["GET"])
def get_all_settings():
    try:
        config_data = {}
        for fname in ["rules.json", "global_settings.json", "model.json"]:
            path = os.path.join(CONFIGS_DIR, fname)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    config_data[fname.replace(".json", "")] = json.load(f)
        return jsonify({"code": 200, "message": "success", "data": config_data})
    except Exception as e:
        return jsonify({"code": 500, "message": f"读取配置失败: {str(e)}"})


@app.route("/api/settings/all", methods=["POST"])
def update_all_settings():
    try:
        new_data = request.json
        for fname in ["rules.json", "global_settings.json", "model.json"]:
            key = fname.replace(".json", "")
            if key in new_data:
                path = os.path.join(CONFIGS_DIR, fname)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(new_data[key], f, ensure_ascii=False, indent=4)
        ConfigManager().reload()
        return jsonify({"code": 200, "message": "所有全局配置已覆写并热重载完毕。"})
    except Exception as e:
        return jsonify({"code": 500, "message": f"配置下发失败: {str(e)}"})


@app.route("/api/settings/restore", methods=["POST"])
def restore_settings():
    try:
        restored_files = []
        for fname in ["rules", "global_settings", "model"]:
            default_path = os.path.join(CONFIGS_DIR, f"{fname}_default.json")
            target_path = os.path.join(CONFIGS_DIR, f"{fname}.json")
            if os.path.exists(default_path):
                shutil.copyfile(default_path, target_path)
                restored_files.append(fname)
        if not restored_files:
            return jsonify({"code": 404, "message": "未找到 _default.json。"})
        ConfigManager().reload()
        return jsonify(
            {"code": 200, "message": f"已成功恢复：{', '.join(restored_files)}！"}
        )
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/ocr/correct", methods=["POST"])
def add_ocr_correction():
    try:
        payload = request.json
        wrong_text, right_text = payload.get("wrong"), payload.get("right")
        rules_path = os.path.join(CONFIGS_DIR, "rules.json")
        with open(rules_path, "r", encoding="utf-8") as f:
            rule_data = json.load(f)
        if "corrections" not in rule_data:
            rule_data["corrections"] = {}
        rule_data["corrections"][wrong_text] = right_text
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(rule_data, f, ensure_ascii=False, indent=4)
        ConfigManager().reload()
        return jsonify({"code": 200, "message": "反哺成功"})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/dynamic_ner", methods=["POST"])
def dynamic_ner():
    try:
        payload = request.json
        section, content = payload.get("section"), payload.get("text")
        from main import run_partial_ner

        return jsonify({"code": 200, "entities": run_partial_ner(section, content)})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/dynamic_cdss", methods=["POST"])
def dynamic_cdss():
    try:
        payload = request.json
        emr_text, entities = payload.get("emr_text", ""), payload.get("entities", [])
        rules_cfg = ConfigManager().get_section("rules")
        cdss_rules, cdss_warnings = rules_cfg.get("cdss_rules", []), []
        extracted_texts = [e["text"] for e in entities]
        for rule in cdss_rules:
            if rule["allergy"] in emr_text:
                for drug in rule["drugs"]:
                    if drug in emr_text or any(
                        drug in ent_text for ent_text in extracted_texts
                    ):
                        cdss_warnings.append(rule["warning"].replace("{drug}", drug))
        return jsonify({"code": 200, "warnings": list(set(cdss_warnings))})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
