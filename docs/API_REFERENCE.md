# 医疗结构化中枢 -  核心包开发者指导手册

本手册详细说明了目录下各核心底层模块的功能定位、类结构及函数接口输入输出规范。

---

## 1. `app/__init__.py`
**文件功能**：Python 包初始化文件。
**说明**：仅保留空文件或基础注释，使得 Python 解释器能将 `app` 文件夹识别为标准模块包，允许外部通过 `from app.xxx import yyy` 进行跨文件调用。

---

## 2. `app/config_manager.py`
**文件功能**：全局配置中心。采用单例模式（Singleton）管理系统配置，支持动态读取 JSON 并在不重启服务的情况下进行热重载。

### 类：`ConfigManager`
* **功能**：单例配置管理器，在内存中维护所有配置项字典（统管 `model.json`、`rules.json`、`global_settings.json`）。
* **方法接口**：
    * `__new__(cls, config_dir="configs")`
        * **功能**：单例实例化，确保全局共用同一套配置。
    * `_load_all(self)`
        * **功能**：遍历 `configs/` 目录，将所有 `.json` 序列化为内存字典。
    * `get_section(self, section_name: str) -> dict`
        * **功能**：获取指定模块的配置信息。
        * **输入**：`section_name` (str) - 配置文件中的顶级键名（例如 `"ner"`, `"ocr"`, `"rules"`）。
        * **输出**：(dict) - 解析后的配置字典。
    * `reload(self)`
        * **功能**：触发内存热重载机制，重新扫描磁盘 JSON 文件覆盖现有内存，无入参无返回值。

---

## 3. `app/exceptions.py`
**文件功能**：系统自定义异常拦截器。
**说明**：定义了系统在各层级运行中可能出现的特有异常类，便于主调度器进行精细化的 `try-except` 捕获与排查。

### 异常类定义
* `MedicalSystemError(Exception)`: 医疗病历系统基础异常基类。
* `OCRProcessError(MedicalSystemError)`: 感知层异常（图像读取、字符提取失败时抛出）。
* `NERModelError(MedicalSystemError)`: 认知层异常（权重加载失败、张量推断报错时抛出）。
* `StorageError(MedicalSystemError)`: 持久层异常（磁盘 I/O 阻断、无读写权限时抛出）。

---

## 4. `app/model.py`
**文件功能**：神经网络架构定义模块。包含大模型底层的网络结构代码。

### 类：`GlobalPointer(nn.Module)`
* **功能**：自定义的实体识别解码头。基于 RoPE (旋转位置编码) 的全局指针网络，专门用于解决医疗文本的高频“实体嵌套”痛点。
* **初始化输入**：
    * `encoder` (nn.Module) - 预训练的语言模型编码器（如 MacBERT）。
    * `ent_type_size` (int) - 需要识别的实体类别总数。
    * `inner_dim` (int) - 内部投影的维度大小（默认 64）。
    * `device` (str) - 运行设备标识 (`"cpu"` 或 `"cuda"`)。
* **方法接口**：
    * `forward(self, input_ids, attention_mask) -> torch.Tensor`
        * **功能**：执行神经网络前向传播，计算序列中任意两点间的内积关联概率。
        * **输入**：`input_ids` (Tensor), `attention_mask` (Tensor) - 编码后的文本张量。
        * **输出**：(Tensor) - 形状为 `(batch_size, ent_type_size, seq_len, seq_len)` 的实体得分矩阵。

---

## 5. `app/ner.py`
**文件功能**：神经符号推理引擎封装模块。

### 类：`NEREngine`
* **功能**：加载预训练语言模型与 GlobalPointer 权重，处理文本的分词（Tokenize）与张量推理。
* **初始化输入**：无直接入参（依赖 `ConfigManager` 读取模型路径与阈值）。
* **方法接口**：
    * `predict_chunk(self, text: str) -> list`
        * **功能**：对输入的单句切片文本进行特征编码与实体解码。
        * **输入**：`text` (str) - 待推断的短文本字符串。
        * **输出**：(list[dict]) - 提取出的实体字典列表。
        * **输出示例**：`[{"text": "高血压", "type": "疾病", "score": 0.98, "start": 0, "end": 3}]`

---

## 6. `app/ocr.py`
**文件功能**：光学字符感知引擎封装模块。

### 类：`OCREngine`
* **功能**：封装 RapidOCR 库，提供从医学影像中提取结构化文本的统一接口。
* **初始化输入**：无直接入参（依赖 `ConfigManager` 读取方向分类器等参数）。
* **方法接口**：
    * `extract(self, image_path: str) -> str`
        * **功能**：从目标图像中提取文本信息。
        * **输入**：`image_path` (str) - 图像的绝对或相对文件物理路径。
        * **输出**：(str) - 提取出的全部文本（内部默认以全角逗号拼接多框内容）。

---

## 7. `app/processor.py`
**文件功能**：NLP 文本工程管家模块。负责正则表达式切分、清洗降噪以及上下文极性逻辑计算。

### 类：`DataProcessor`
* **功能**：提供一系列无状态的纯文本数据结构化处理方法。
* **方法接口**：
    * `clean_text(self, raw_text: str) -> str`
        * **功能**：利用字典规则对 OCR 原始乱码进行硬纠错。
        * **输出**：(str) - 纠错后的纯净文本。
    * `extract_clinical_sections(self, text: str) -> dict`
        * **功能**：采用“锚点截断法”将长文本划分为独立病历段落。
    * `split_into_chunks(self, text: str) -> list`
        * **功能**：按标点符号切分长段落，避免显存溢出（OOM）。
    * `resolve_nested_entities(self, entities: list) -> list`
        * **功能**：嵌套消解与黑名单过滤，消除模型过召回脏数据。
    * `detect_entity_polarity(self, entities: list, text: str, window_size: int = 5) -> list`
        * **功能**：极性辖域传导分析，计算实体是否存在被“否定/排除”的语境，支持连词传染推断。
        * **输出**：(list) - 附加了 `"polarity": "阳性" | "阴性"` 字段的实体列表。

---

## 8. `app/storage.py`
**文件功能**：持久层与文件控制模块。

### 类：`StorageEngine`
* **功能**：控制底层文件系统，对系统管线的执行结果进行统一归档与多节点快照落盘。
* **方法接口**：
    * `save_visit_snapshot(self, patient_id: str, image_path: str, raw_ocr: str, chunks: list, chunked_results: list, sections: dict, aggregated_issues: list) -> str`
        * **功能**：持久化单次就诊的全量业务数据。并在此处触发 CDSS (临床决策支持系统) 的过敏冲突拦截逻辑。
        * **输入**：各项流转节点的中间态数据对象（图径、OCR 文本、实体列表、段落字典、**智能诊断草稿列表**等）。
        * **输出**：(str) - 生成的就诊批次存储根目录路径（如 `output/patient_records/PID_XXX/V_XXX`）。

---

## 9. `main.py` (主程序调度器)
**文件功能**：系统的“中央处理器”与管线编排总线。负责串联底层各个互相独立的 AI 算子和数据处理引擎，构建出一条完整的有向无环图（DAG）流水线。

### 核心函数接口
* `run_medical_pipeline(image_path: str) -> str`
    * **功能**：批处理全链路调度（Batch Processing）。涵盖图像感知、清洗、截断、长文切片、实体提取、极性传导、**阳性指征聚合总结（智能辅诊）** 与持久化快照全流程。
    * **输入**：`image_path` (str) - 前端上传的医疗影像绝对物理路径。
    * **输出**：(str) - 存档目录路径。
* `run_partial_ner(section_name: str, content: str) -> list`
    * **功能**：局部微服务调度（Microservice Reload）。仅对指定的一段文本执行短句切分、实体推理与极性传导。

---

## 10. `web.py` (Flask 宿主与微服务路由)
**文件功能**：Web 容器层。在环境变量级别强制切断 HuggingFace 外网连接以保证本地私有化部署。向上提供 RESTful API，向下驱动 AI 算子。

### 核心路由接口 (Routes)
* `POST /analyze`
    * **功能**：全模态分析主入口。接收影像文件，阻塞调用 `run_medical_pipeline`，将结构化草案交由 Jinja2 引擎渲染至前端 HTML。
* `POST /save_report`
    * **功能**：人工复核签发入库。接收医生干预后的最终状态数据（包含医生最终手写诊断签名）。
    * **输入**：`JSON {"就诊编号": "...", "患者ID": "...", "结构化病历": {...}, "提取实体": [...], "医生最终诊断": "..."}`。
* `GET /api/settings/all` & `POST /api/settings/all`
    * **功能**：全量 MLOps 配置中枢。读取/覆写 `rules.json`, `global_settings.json`, `model.json`，并触发内存热重载。
* `POST /api/settings/restore`
    * **功能**：沙盒级出厂设置恢复。自动寻址并拷贝 `_default.json` 覆盖现有配置。
* `POST /api/dynamic_ner`
    * **功能**：局部 NER 神经重载端点。响应前端的“向下传导”请求。
* `POST /api/dynamic_cdss`
    * **功能**：CDSS 实时过敏/禁忌拦截网关。无需走数据库，直接在内存中执行实体文本与规则库的碰撞校验。
* `POST /api/ocr/correct`
    * **功能**：主动学习数据飞轮端点。接收错词反馈，覆写字典并执行内存热更新。

---

## 11. `templates/index.html` (视图呈现层)
**文件功能**：医疗工作站的 UI 骨架。基于 Bootstrap 5 构建的响应式视图。

### 核心架构块
* **状态机桥接 (Data Hydration)**：通过 `<script> window.SYSTEM_CONTEXT = {...} </script>` 标签将后端字典序列化注入前端内存空间。
* **强临床约束双栏表单**：左侧提供硬编码的国家卫健委标准字段表单（含必填星号），右侧提供全局实体药丸弹药库（Entity Chips）。
* **智能辅诊交互区**：第三选项卡内的绿色 AI 摘要胶囊槽位及医生最终诊断文本框。
* **全量配置中枢**：类 Clash Verge 风格的大型交互式 Offcanvas/Modal，分离了 GUI 友好操作层与底层 JSON 编辑器层。

---

## 12. `static/js/main.js` (前端状态机与逻辑层)
**文件功能**：前端的“大脑”。接管 `window.SYSTEM_CONTEXT` 中的实体状态树，并负责所有高阶鼠标交互、坐标重组及微服务异步调用。

### 核心函数模块
* **焦点追踪与实体采纳 (Focus & Chip Engine)**：
    * `focusin` 监听器 / `activeInputField`：全局追踪医生当前选中的结构化表单输入框。
    * `renderEntityChips()`：渲染全局实体药丸库。内置智能极性判断（若点击阴性实体自动前缀“无”）及标点符号推断拼接算法。
    * `insertDiagnosis(text)`：诊断页专属辅诊胶囊采纳器。
* **强约束质控网关 (Quality Gate)**：
    * `executeArchiveProtocol()`：表单提交拦截器。强制校验【主诉】和【过敏史】是否为空，若为空触发物理拦截、强制重定向视图及血红色描边警告。
* **渲染引擎与文本重组**：
    * `renderEntityHighlights()`：底层核心渲染器。动态计算极性并插入 DOM。
    * `saveOcrText(triggerNerReload)`：文本校对流。包含字符串匹配算法，可在不调后端的情况下修复坐标漂移。
* **沉浸式交互舱**：
    * 划词气泡定位：通过 `getBoundingClientRect()` 计算物理坐标弹射气泡。
    * `triggerAddEntity() / openEntityEditor()`：实体生命周期干预（增、删、改、极性翻转）。
* **全局配置双向同步器**：
    * `buildDataFromGui()` / `populateGuiFromData()`：完成 GUI 表单与 JSON 对象的序列化/反序列化映射。拦截 `show.bs.tab` 事件实现开发模式与傻瓜模式的无缝状态同步。

---

## 13. `static/css/style.css` (UI 动效与美学工程)
**文件功能**：工作站视觉样式表。提供“医疗工业级”的清爽界面定义。

### 核心视觉定义
* **材质与层级 (Glassmorphism)**：通过 `backdrop-filter: blur(20px)` 打造玻璃拟物态卡片。
* **实体分类着色系统**：针对不同的医疗实体类型定义了高辨识度的柔和渐变底色与加粗描边。
* **微交互动效**：
    * `.entity-chip` / `.diagnosis-chip`：实现鼠标悬停 Q 弹缩放及点击下沉物理反馈。
    * `.active-input-field`：蓝色呼吸外发光，指引当前输入焦点。
* **高危警报动画**：定义了 `@keyframes pulse-red`，为 CDSS 拦截预警提供规律的红色呼吸发光动效。