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
* **功能**：单例配置管理器，在内存中维护所有配置项字典。
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
        * **输入**：`raw_text` (str) - 原始脏文本。
        * **输出**：(str) - 纠错后的纯净文本。
    * `extract_clinical_sections(self, text: str) -> dict`
        * **功能**：采用“锚点截断法”将长文本划分为独立病历段落。
        * **输入**：`text` (str) - 待切分的全量文本。
        * **输出**：(dict) - 键值对结构，如 `{"现病史": "...", "既往史": "..."}`。
    * `split_into_chunks(self, text: str) -> list`
        * **功能**：按标点符号切分长段落，避免显存溢出（OOM）。
        * **输入**：`text` (str) - 长段落文本。
        * **输出**：(list[str]) - 短句列表。
    * `resolve_nested_entities(self, entities: list) -> list`
        * **功能**：嵌套消解与黑名单过滤，消除模型过召回脏数据。
        * **输入**：`entities` (list) - 原始 NER 输出实体集合。
        * **输出**：(list) - 降噪并去重后的实体集合。
    * `detect_entity_polarity(self, entities: list, text: str, window_size: int = 5) -> list`
        * **功能**：极性辖域传导分析，计算实体是否存在被“否定/排除”的语境。
        * **输入**：`entities` (list) 待测实体列表；`text` (str) 所属段落原文；`window_size` (int) 前置扫描窗口大小。
        * **输出**：(list) - 附加了 `"polarity": "阳性" | "阴性"` 字段的实体列表。

---

## 8. `app/storage.py`
**文件功能**：持久层与文件控制模块。

### 类：`StorageEngine`
* **功能**：控制底层文件系统，对系统管线的执行结果进行统一归档与多节点快照落盘。
* **方法接口**：
    * `save_visit_snapshot(self, patient_id: str, image_path: str, raw_ocr: str, chunks: list, chunked_results: list, sections: dict, aggregated_issues: list) -> str`
        * **功能**：持久化单次就诊的全量业务数据。并在此处触发 CDSS (临床决策支持系统) 的过敏冲突拦截逻辑。
        * **输入**：各项流转节点的中间态数据对象（图径、OCR 文本、实体列表、段落字典等）。
        * **输出**：(str) - 生成的就诊批次存储根目录路径（如 `output/patient_records/PID_XXX/V_XXX`）。

## 9. `main.py` (主程序调度器)
**文件功能**：系统的“中央处理器”与管线编排总线。负责串联底层各个互相独立的 AI 算子和数据处理引擎，构建出一条完整的有向无环图（DAG）流水线。

### 核心函数接口
* `run_medical_pipeline(image_path: str) -> str`
    * **功能**：批处理全链路调度（Batch Processing）。涵盖图像感知、清洗、截断、长文切片、实体提取、极性传导与持久化快照全流程。
    * **输入**：`image_path` (str) - 前端上传并缓存至本地的医疗影像绝对物理路径。
    * **输出**：(str) - 生成的单次就诊数据存档目录路径（如 `output/patient_records/PID_XXX/V_XXX`）。
* `run_partial_ner(section_name: str, content: str) -> list`
    * **功能**：局部微服务调度（Microservice Reload）。脱离主干流程，仅对指定的一段文本执行短句切分、实体推理与极性传导。
    * **输入**：`section_name` (str) - 触发重载的病历段落名；`content` (str) - 需要重新推断的新文本。
    * **输出**：(list[dict]) - 重新提取并计算好绝对坐标和极性的实体字典列表。

---

## 10. `web.py` (Flask 宿主与微服务路由)
**文件功能**：Web 容器层。在环境变量级别强制切断 HuggingFace 的外网连接以保证本地私有化部署。向上提供 RESTful API，向下驱动 AI 算子。

### 核心路由接口 (Routes)
* `POST /analyze`
    * **功能**：全模态分析主入口。接收前端上传的影像文件，阻塞调用 `run_medical_pipeline`，随后将结构化草案（`05_final_summary.json`）交由 Jinja2 引擎渲染至前端 HTML。
    * **输入**：`multipart/form-data`（包含 `image` 文件流）。
* `POST /save_report`
    * **功能**：人工复核签发入库。接收医生干预后的最终状态数据，生成不可篡改的 `06_human_verified.json`。
    * **输入**：`JSON {"就诊编号": "...", "患者ID": "...", "结构化病历": {...}, "提取实体": [...]}`。
* `POST /api/dynamic_ner`
    * **功能**：局部 NER 神经重载端点。响应前端的“向下传导”请求。
    * **输入**：`JSON {"section": "现病史", "text": "新增的一句文本..."}`。
    * **输出**：`JSON {"code": 200, "entities": [...]}`。
* `POST /api/dynamic_cdss`
    * **功能**：CDSS 实时过敏/禁忌拦截网关。无需走数据库，直接在内存中执行实体文本与规则库的碰撞校验。
    * **输入**：`JSON {"emr_text": "全文本...", "entities": [...]}`。
    * **输出**：`JSON {"code": 200, "warnings": ["⚠️ 致命拦截..."]}`。
* `POST /api/ocr/correct`
    * **功能**：主动学习数据飞轮端点。接收错词反馈，覆写 `rules.json` 并立刻调用 `ConfigManager().reload()` 执行内存热更新。

---

## 11. `templates/index.html` (视图呈现层)
**文件功能**：医疗工作站的 UI 骨架。基于 Bootstrap 5 构建的响应式视图，融合了 Jinja2 模板引擎进行初次渲染加载。

### 核心架构块
* **动态宏渲染**：使用 `{% if record %}` 等 Jinja 语法动态生成溯源对比图、右侧渲染区及结构化表单。
* **状态机桥接 (Data Hydration)**：通过 `<script> window.SYSTEM_CONTEXT = {...} </script>` 标签，安全地将后端生成的 Python 字典（EMR 数据与实体数据）序列化注入到前端 JavaScript 的内存空间中，实现前后端状态分离。
* **隐藏式交互舱**：内置四个隐藏的模态框（Modal）和一个绝对定位的悬浮气泡（Bubble），用于无刷新承载所有的“增删改查”交互。

---

## 12. `static/js/main.js` (前端状态机与逻辑层)
**文件功能**：前端的“大脑”。接管 `window.SYSTEM_CONTEXT` 中的实体状态树，并负责所有高阶鼠标交互、坐标重组及微服务异步调用。

### 核心函数模块
* **渲染引擎**：
    * `renderEntityHighlights()`：底层核心渲染器。遍历 EMR 文本，对比实体坐标 (`start`, `end`)，动态插入 HTML 标签。负责渲染带有删除线的极性状态和不同颜色的实体标签。
* **文本增删与自适应重组**：
    * `openOcrEditor(section)` / `saveOcrText(triggerNerReload)`：文本校对流。当用户仅保存文本不触发 NER 时，通过字符串匹配算法（`newText.indexOf(ent.text)`）在前端内存中强行修正所有受影响实体的坐标漂移。
* **沉浸式悬浮舱监听**：
    * `mouseup` 事件监听器：计算用户划词选中区域 (`window.getSelection()`)，通过 `getBoundingClientRect()` 获取物理坐标，将悬浮气泡精准弹射在文字上方。
* **实体全生命周期管理**：
    * `triggerAddEntity()` / `saveNewEntity()`：拦截划词内容，计算段落内相对坐标并注入全局状态树。
    * `openEntityEditor()` / `updateEntity()` / `deleteEntity()`：实现点击高亮实体进行极性翻转或直接剔除。
* **动态流转触发器**：
    * `triggerDynamicCDSS()`：在任何实体发生增、删、改操作后静默调用，请求后端网关校验，如果命中规则立刻操作 DOM 渲染血红预警横幅。

---

## 13. `static/css/style.css` (UI 动效与美学工程)
**文件功能**：工作站视觉样式表。提供“医疗工业级”的清爽界面定义。

### 核心视觉定义
* **材质与层级 (Glassmorphism)**：通过 `backdrop-filter: blur(20px)` 与微弱阴影打造类 iOS 的玻璃拟物态卡片 (`.glass-card`)，提升信息层级对比度。
* **实体分类着色系统**：针对不同的医疗实体类型（`.type-疾病`, `.type-药物` 等）定义了高辨识度的柔和渐变底色与加粗描边。
* **高危警报动画**：定义了 `@keyframes pulse-red`，为 CDSS 拦截预警提供规律的红色呼吸发光动效，确保医生绝对不会遗漏致命警告。