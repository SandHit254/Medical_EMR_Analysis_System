"""
模块名称：医疗命名实体识别 (NER) 模型表现与交互层
"""

import os
import json
import logging
import shutil
import fitz  # PyMuPDF 用于高速解析 PDF
import docx  # 用于解析 Word 文档
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
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 提升至 32MB 以兼容较大的 PDF

# 扩展支持的文件格式
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "bmp", "tiff", "pdf"}
ALLOWED_TEXT_EXTS = {"txt", "docx"}


def allowed_file(filename: str, allowed_set: set) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set


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
    patient_id = request.form.get("patient_id", "").strip()
    if not patient_id:
        from main import generate_patient_id

        patient_id = generate_patient_id()

    patient_info = {
        "姓名": request.form.get("patient_name", "").strip(),
        "性别": request.form.get("patient_gender", "").strip(),
        "年龄": request.form.get("patient_age", "").strip(),
    }

    try:
        # =================================================================
        # 路由分支 1：图像感知 / PDF OCR 模式
        # =================================================================
        if "image" in request.files and request.files["image"].filename != "":
            file = request.files["image"]
            if not allowed_file(file.filename, ALLOWED_IMAGE_EXTS):
                return render_template(
                    "index.html",
                    error="不支持的文件格式，请上传图像或 PDF。",
                    emr_config=get_emr_config(),
                )

            ext = file.filename.rsplit(".", 1)[-1].lower()
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(file_path)

            # 【核心】：PDF 栅格化引擎。将 PDF 渲染为 2 倍超采样分辨率的图像以保证 OCR 精度
            if ext == "pdf":
                doc = fitz.open(file_path)
                page = doc.load_page(0)  # 提取第一页
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_filename = f"{filename}_page0.jpg"
                img_path = os.path.join(app.config["UPLOAD_FOLDER"], img_filename)
                pix.save(img_path)
                doc.close()
                file_path = img_path
                filename = img_filename  # 将后续渲染和 OCR 的指针移交给生成的图片

            snapshot_dir = run_medical_pipeline(
                image_path=file_path, patient_id=patient_id, patient_info=patient_info
            )
            image_filename_for_view = filename

        # =================================================================
        # 路由分支 2：纯文本 / 文档提取直通模式
        # =================================================================
        else:
            raw_text = request.form.get("raw_text", "").strip()

            # 尝试提取上传的 Word 或 TXT 文档
            if (
                "text_file" in request.files
                and request.files["text_file"].filename != ""
            ):
                t_file = request.files["text_file"]
                if allowed_file(t_file.filename, ALLOWED_TEXT_EXTS):
                    t_ext = t_file.filename.rsplit(".", 1)[-1].lower()
                    t_path = os.path.join(
                        app.config["UPLOAD_FOLDER"], secure_filename(t_file.filename)
                    )
                    t_file.save(t_path)

                    if t_ext == "txt":
                        with open(t_path, "r", encoding="utf-8") as f:
                            raw_text = f.read() + "\n\n" + raw_text
                    elif t_ext == "docx":
                        doc_obj = docx.Document(t_path)
                        full_text = "\n".join(
                            [para.text for para in doc_obj.paragraphs]
                        )
                        raw_text = full_text + "\n\n" + raw_text

            if not raw_text.strip():
                return render_template(
                    "index.html",
                    error="系统拦截：未检测到任何有效的纯文本或文档内容。",
                    emr_config=get_emr_config(),
                )

            snapshot_dir = run_medical_pipeline(
                raw_text_input=raw_text,
                patient_id=patient_id,
                patient_info=patient_info,
            )
            image_filename_for_view = None

        # 视图渲染
        json_target_path = os.path.join(snapshot_dir, "05_final_summary.json")
        if os.path.exists(json_target_path):
            with open(json_target_path, "r", encoding="utf-8") as f:
                record_data = json.load(f)
            return render_template(
                "index.html",
                record=record_data,
                error=None,
                image_filename=image_filename_for_view,
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


@app.route("/api/library/tree", methods=["GET"])
def get_library_tree():
    try:
        return jsonify({"code": 200, "tree": StorageEngine().get_patient_tree()})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/library/search", methods=["POST"])
def search_library():
    try:
        return jsonify(
            {
                "code": 200,
                "results": StorageEngine().search_records(
                    request.json.get("query", "")
                ),
            }
        )
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/records/<patient_id>/<visit_id>/image")
def serve_record_image(patient_id, visit_id):
    engine = StorageEngine()
    patient_folder = (
        patient_id if patient_id.startswith("PID_") else f"PID_{patient_id}"
    )
    visit_dir = os.path.join(engine.root, patient_folder, visit_id)
    return send_from_directory(visit_dir, "01_source.jpg")


@app.route("/view/<patient_id>/<visit_id>", methods=["GET"])
def view_record(patient_id, visit_id):
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
            img_url = (
                f"/records/{patient_folder}/{visit_id}/image"
                if os.path.exists(os.path.join(visit_dir, "01_source.jpg"))
                else None
            )
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
        return jsonify(
            {"code": 200, "patients": StorageEngine().get_all_patients_info()}
        )
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/patients/new", methods=["GET"])
def create_new_patient():
    from main import generate_patient_id

    return jsonify({"code": 200, "patient_id": generate_patient_id()})


@app.route("/api/settings/all", methods=["GET", "POST"])
def manage_settings():
    try:
        if request.method == "GET":
            config_data = {}
            for fname in ["rules.json", "global_settings.json", "model.json"]:
                path = os.path.join(CONFIGS_DIR, fname)
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        config_data[fname.replace(".json", "")] = json.load(f)
            return jsonify({"code": 200, "data": config_data})
        else:
            for fname in ["rules.json", "global_settings.json", "model.json"]:
                key = fname.replace(".json", "")
                if key in request.json:
                    with open(
                        os.path.join(CONFIGS_DIR, fname), "w", encoding="utf-8"
                    ) as f:
                        json.dump(request.json[key], f, ensure_ascii=False, indent=4)
            ConfigManager().reload()
            return jsonify({"code": 200, "message": "配置已覆写并热重载。"})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/settings/restore", methods=["POST"])
def restore_settings():
    try:
        restored = []
        for fname in ["rules", "global_settings", "model"]:
            d_path, t_path = os.path.join(
                CONFIGS_DIR, f"{fname}_default.json"
            ), os.path.join(CONFIGS_DIR, f"{fname}.json")
            if os.path.exists(d_path):
                shutil.copyfile(d_path, t_path)
                restored.append(fname)
        ConfigManager().reload()
        return jsonify({"code": 200, "message": f"成功恢复：{', '.join(restored)}"})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/ocr/correct", methods=["POST"])
def add_ocr_correction():
    try:
        w, r = request.json.get("wrong"), request.json.get("right")
        path = os.path.join(CONFIGS_DIR, "rules.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "corrections" not in data:
            data["corrections"] = {}
        data["corrections"][w] = r
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        ConfigManager().reload()
        return jsonify({"code": 200, "message": "反哺成功"})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/dynamic_ner", methods=["POST"])
def dynamic_ner():
    try:
        from main import run_partial_ner

        return jsonify(
            {
                "code": 200,
                "entities": run_partial_ner(
                    request.json.get("section"), request.json.get("text")
                ),
            }
        )
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


@app.route("/api/dynamic_cdss", methods=["POST"])
def dynamic_cdss():
    try:
        payload = request.json
        emr_text, extracted_texts = payload.get("emr_text", ""), [
            e["text"] for e in payload.get("entities", [])
        ]
        warnings = []
        for rule in ConfigManager().get_section("rules").get("cdss_rules", []):
            if rule["allergy"] in emr_text:
                for drug in rule["drugs"]:
                    if drug in emr_text or any(drug in ent for ent in extracted_texts):
                        warnings.append(rule["warning"].replace("{drug}", drug))
        return jsonify({"code": 200, "warnings": list(set(warnings))})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
