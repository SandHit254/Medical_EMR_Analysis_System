"""
模块名称：医疗病历智能分析系统 - 交互界面 (Web UI)
功能描述：基于 Gradio 构建的 Web 前端，提供图像上传、实体高亮可视化、
         结构化段落展示及临床逻辑推断结果输出。
"""

import os

# 必须在导入任何 AI 相关库之前设置离线环境变量
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import gradio as gr
from app.ocr import OCREngine
from app.ner import NEREngine
from app.processor import DataProcessor

# 初始化核心引擎
OCR = OCREngine()
NER = NEREngine()
PROCESSOR = DataProcessor()


def analyze_medical_record(image):
    """
    处理流程：执行 OCR 识别、文本分段、实体提取与逻辑推断。
    """
    if image is None:
        return "请上传病历图像", None, None, {"text": "", "entities": []}

    temp_path = "temp_upload.jpg"
    image.save(temp_path)

    try:
        # 文本提取与清洗
        raw_text = OCR.extract(temp_path)
        cleaned_text = PROCESSOR.clean_text(raw_text)
        sections = PROCESSOR.extract_clinical_sections(cleaned_text)

        all_entities_for_highlight = []
        structured_report = ""
        aggregated_issues = []
        global_search_offset = 0

        # 遍历结构化段落进行深度分析
        for sec_name, sec_content in sections.items():
            if not sec_content.strip():
                continue

            structured_report += f"### 【{sec_name}】\n{sec_content}\n\n"

            chunks = PROCESSOR.split_into_chunks(sec_content)
            for chunk in chunks:
                # 确定短句在全文中的绝对起始坐标
                chunk_start_idx = cleaned_text.find(chunk, global_search_offset)
                if chunk_start_idx == -1:
                    chunk_start_idx = global_search_offset

                # 执行模型推理与后处理
                entities = NER.predict_chunk(chunk)
                entities = PROCESSOR.resolve_nested_entities(entities)
                entities = PROCESSOR.flag_negations(chunk, entities)

                # 收集临床关系推断结论
                issues = PROCESSOR.aggregate_relations(entities, chunk_text=chunk)
                for iss in issues:
                    aggregated_issues.append(
                        [sec_name, iss["逻辑类型"], iss["临床结论"]]
                    )

                # 将相对坐标转换为全文绝对坐标，并适配 Gradio 数据格式
                for ent in entities:
                    all_entities_for_highlight.append(
                        {
                            "start": chunk_start_idx + ent["start"],
                            "end": chunk_start_idx + ent["end"],
                            "entity": ent["type"],
                        }
                    )

                global_search_offset = chunk_start_idx + len(chunk)

        # 格式化逻辑推理表格
        issue_md = "#### 临床逻辑推断结论\n"
        if aggregated_issues:
            issue_md += "| 所属段落 | 逻辑维度 | 临床推断结果 |\n| --- | --- | --- |\n"
            for row in aggregated_issues:
                issue_md += f"| {row[0]} | {row[1]} | **{row[2]}** |\n"
        else:
            issue_md += "*未检测到显著的逻辑关联结论*"

        # 实体冲突过滤（剔除坐标重叠的实体以确保前端渲染正常）
        all_entities_for_highlight.sort(key=lambda x: (x["start"], -x["end"]))
        filtered_highlights = []
        last_end = -1
        for ent in all_entities_for_highlight:
            if ent["start"] >= last_end:
                filtered_highlights.append(ent)
                last_end = ent["end"]

        # 构造 Gradio 高亮组件所需的标准数据结构
        highlight_output = {"text": cleaned_text, "entities": filtered_highlights}

        return cleaned_text, structured_report, issue_md, highlight_output

    except Exception as e:
        return f"系统处理异常: {str(e)}", None, None, {"text": "", "entities": []}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# 构建 Gradio 交互界面
with gr.Blocks(title="医疗病历结构化系统") as demo:
    gr.Markdown(
        """
    # 智能门诊病历结构化分析系统
    ### [毕业设计演示版本 - 非真实医疗用途]
    """
    )

    with gr.Row():
        with gr.Column(scale=1):
            input_img = gr.Image(type="pil", label="上传病历影像")
            btn = gr.Button("执行分析", variant="primary")

            with gr.Accordion("免责声明", open=True):
                gr.Markdown(
                    """
                1. 本系统仅作为毕业设计学术展示。
                2. 识别与推理结论不具备医疗效力，严禁作为临床诊断依据。
                3. 请勿上传涉及个人隐私的真实医疗数据。
                """
                )

        with gr.Column(scale=2):
            with gr.Tabs():
                with gr.TabItem("实体高亮可视化"):
                    output_text = gr.HighlightedText(
                        label="医疗实体识别分布",
                        combine_adjacent=True,
                        show_legend=True,
                        color_map={
                            "疾病": "red",
                            "症状": "orange",
                            "药物": "blue",
                            "身体部位": "green",
                            "手术/检查": "purple",
                            "医学检验项目": "cyan",
                            "科室": "magenta",
                        },
                    )

                with gr.TabItem("结构化报告"):
                    output_report = gr.Markdown(label="分段报告")

                with gr.TabItem("逻辑推理"):
                    output_issues = gr.Markdown(label="临床推断结果")

                with gr.TabItem("清洗后原文"):
                    output_raw = gr.Textbox(label="OCR 清洗文本", lines=10)

    btn.click(
        fn=analyze_medical_record,
        inputs=[input_img],
        outputs=[output_raw, output_report, output_issues, output_text],
    )

if __name__ == "__main__":
    # Gradio 6.0 规范：theme 参数需在 launch() 中传递
    demo.launch(
        server_name="127.0.0.1", server_port=7860, share=False, theme=gr.themes.Soft()
    )
