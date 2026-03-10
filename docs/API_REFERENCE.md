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
* **功能**：控制底层文件系统，基于**绝对路径动态寻址**，确保跨目录调用的 I/O 安全。涵盖快照落盘、CDSS 规则碰撞拦截，以及 EMPI 历史档案检索。
* **方法接口**：
    * `get_all_patients_info(self) -> list`
        * **新增功能**：EMPI 接口，遍历解析存储库，返回包含 `id`, `name`, `gender`, `age` 的历史患者字典列表。
    * `get_patient_history(self, patient_id: str) -> dict`
        * **新增功能**：EMPI 接口，溯源目标患者最近一次的 `06_human_verified.json`，提取并返回其人口统计学信息与过敏史。
    * `save_visit_snapshot(self, ...) -> str`
        * **强化功能**：执行双向 CDSS 拦截检验。不仅比对模型提取的实体字典，还会**全局检索前端表单的手写纯文本**，确保不漏掉任何未被 AI 识别的禁忌药物输入。

---

## 9. `main.py` (主程序调度器)
**文件功能**：系统的“中央处理器”与管线编排总线。负责串联底层各个互相独立的 AI 算子和数据处理引擎，构建出一条完整的有向无环图（DAG）流水线。

### 核心函数接口
* `run_medical_pipeline(image_path: str, patient_id: str = None, patient_info: dict = None) -> str`
    * **功能**：批处理全链路调度。在 OCR 清洗后、NER 识别前，执行 **EMPI 历史档案继承机制**。将入参的 `patient_info` 及历史过敏史强制拼接入当前的病历段落字典中，补全上下文。
    * **输入**：`image_path` (物理图径), `patient_id` (选填，患者流水号), `patient_info` (选填，包含姓名、性别、年龄的基础字典)。
* `run_partial_ner(section_name: str, content: str) -> list`
    * **功能**：局部微服务调度（Microservice Reload）。仅对指定的一段文本执行短句切分、实体推理与极性传导。

---

## 10. `web.py` (Flask 宿主与微服务路由)
**文件功能**：Web 容器层。在环境变量级别强制切断 HuggingFace 外网连接以保证本地私有化部署。向上提供 RESTful API，向下驱动 AI 算子。

* `GET /api/patients` & `GET /api/patients/new`
    * **功能**：EMPI 网关患者主索引微服务。分别用于下发格式化的历史患者列表树，以及使用 UUID 算法生成全新的防篡改患者流水号。
* 动态模板上下文注入 (`get_emr_config`)
    * **功能**：在 `/` 与 `/analyze` 路由响应中，拦截读取 `rules.json`，并将动态表单配置 (`standard_fields` 和 `required_fields`) 注入 Jinja2 渲染引擎。

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
**文件功能**：医疗工作站的 UI 骨架。基于 Bootstrap 5 构建的响应式视图，全面采用现代类 IDE 的非对称双栏网格布局 (`col-xl-3` + `col-xl-9`)。

### 核心架构块
* **全局左侧控制台 (Sidebar)**：高度聚合业务入口。包含：
    * `EMPI 身份网关` (锁定/切换患者上下文)
    * `影像采集节点` (拦截器阻止无患者上传)
    * `元数据与生命周期面板` (归档信息展示与重启工作站后门)
    * `多维病例库引擎` (集成手风琴目录树与跨病历多模态检索组件)
* **右侧沉浸式工作区 (Workspace)**：动态响应数据并横向铺开。包含：
    * 动态患者身份横幅 (`#dynamic-patient-banner`) 与全局 CDSS 预警展示容器。
    * 三大核心流转 Tab：`溯源视图` (图文双列对照)、`结构化复核` (动态读取 rules.json 生成表单与右侧吸顶实体药丸池)、`逻辑入库` (交互式 AI 草稿垫与医生手写签名)。
* **状态机桥接 (Data Hydration)**：通过 `<script> window.SYSTEM_CONTEXT = {...} </script>` 标签将后端生成的 Python 字典序列化注入前端内存空间，实现前后端状态分离。
* **全局交互外挂组件**：隐藏的 Toast 系统提示器、划词选区悬浮舱 (`#selection-bubble`)、以及挂载底层的增删改查 Modal 模态框群。

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
* **EMPI 前置网关与锁屏机制 (Identity Lock)**：
    * `openEmpiGateway()` / `setPatientContext()`：初始化系统时阻塞图片上传表单（`e.preventDefault()`），强制唤起模态框确认身份。并接管 DOM 更新顶部状态横幅。
* **输入框实时侦听与动态 CDSS (Real-time Observation)**：
    * 为所有带有 `.emr-input-target` 类的文本框绑定 `input` 事件，医生打字时即刻更新 `window.SYSTEM_CONTEXT` 内存树，并无延迟高频触发 `triggerDynamicCDSS()`。
* **动态质控巡检 (Dynamic Quality Gate)**：
* `executeArchiveProtocol()`：放弃写死的字段名，改为基于 `querySelectorAll('textarea[data-required="true"]')` 实施全页面动态循环检视，遇空值直接拦截。

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