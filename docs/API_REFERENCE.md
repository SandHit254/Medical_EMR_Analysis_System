# 医疗智能结构化中枢 - 核心包开发者参考手册 (API Reference)

本手册详细说明了系统目录下各核心底层模块的功能定位、类结构、函数接口规范及输入输出协议。适用于二次开发、学术复现与系统级集成。

---

## 1. 核心应用包 (`app/`)

### 1.1 `app/__init__.py`
**模块定位**：Python 包初始化文件。
**架构说明**：仅保留基础注释，确保 Python 解释器将 `app` 识别为标准模块包，允许外部控制器通过 `from app.module import class` 进行跨域调用。

### 1.2 `app/config_manager.py`
**模块定位**：全局配置动态分发总线。
**架构说明**：采用结合 `threading.Lock` 的并发安全单例模式（Singleton）管理系统配置，支持动态读取 JSON 并在不重启服务的情况下进行内存级热重载。
* **核心类：`ConfigManager`**
    * `__new__(cls, config_dir="configs")`：线程安全单例实例化，确保高并发下唯一 I/O 句柄。
    * `_load_all(self)`：遍历物理目录，将 `.json` 序列化为内存字典。
    * `get_section(self, section_name: str) -> dict`：配置分发器，返回指定模块的字典快照。
    * `reload(self)`：触发内存热更新，使 Web 端下发的新规则即刻贯穿至所有推理算子。

### 1.3 `app/exceptions.py`
**模块定位**：全局自定义异常拦截器。
**架构说明**：定义系统各层级运行中可能出现的特有异常类，建立标准的错误隔离与向上传导机制。
* `MedicalSystemError(Exception)`：医疗病历系统基础异常基类。
* `OCRProcessError`：感知层异常（如底层 C++ ONNX 运行时崩溃）。
* `NERModelError`：认知层异常（如安全权重反序列化失败、张量切片越界）。
* `StorageError`：持久层异常（如目录寻址失败、I/O 读写越权）。

### 1.4 `app/model.py`
**模块定位**：神经网络算子架构定义。
**架构说明**：构建基于深度学习的实体识别（NER）底层张量计算图。
* **核心类：`GlobalPointer(nn.Module)`**
    * **机制**：基于 RoPE (旋转位置编码) 的全局指针网络，将 NER 转化为序列中任意 Token-Pair 的二分类问题，从数学底层解决“实体嵌套”痛点。
    * `sinusoidal_position_embedding(...)`：生成绝对位置的正弦/余弦嵌入张量。
    * `forward(self, input_ids, attention_mask) -> torch.Tensor`：执行特征投影与旋转位置编码注入，输出形状为 `(batch_size, ent_type_size, seq_len, seq_len)` 的关联得分矩阵，并自动屏蔽下三角与 Padding 区域的无效计算。

### 1.5 `app/ner.py`
**模块定位**：神经认知推理引擎。
**架构说明**：管理大语言模型（MacBERT）与 GlobalPointer 权重的生命周期，负责文本切片的特征编码与实体解码。
* **核心类：`NEREngine`**
    * `__init__(self)`：依据 `ConfigManager` 初始化算力设备 (CPU/CUDA)，加载 `weights_only=True` 的安全张量字典。
    * `predict_chunk(self, text: str) -> list`：包含空值短路拦截。对输入的单句切片进行前向推断，输出标准化实体字典列表 `[{"text": str, "type": str, "score": float, "start": int, "end": int}]`。

### 1.6 `app/ocr.py`
**模块定位**：视觉特征感知引擎。
**架构说明**：封装 RapidOCR 库，提供从非结构化医学影像中提取文本张量的统一接口。
* **核心类：`OCREngine`**
    * `extract(self, image_path: str) -> str`：调用 ONNX 引擎执行检测与识别，内置异常包装器，提取所有文本块并以全角标点进行线性拼接。

### 1.7 `app/processor.py`
**模块定位**：NLP 数据逻辑中台。
**架构说明**：提供高度解耦的无状态字符串处理与逻辑判定方法。
* **核心类：`DataProcessor`**
    * `clean_text(self, raw_text: str) -> str`：基于字典执行清洗降噪与硬纠错。
    * `extract_clinical_sections(self, text: str) -> dict`：基于动态正则锚点，对长文本执行段落截断与防贪婪匹配隔离。
    * `resolve_nested_entities(self, entities: list) -> list`：执行最大长度优先 (MLF) 的实体嵌套消解与启发式黑名单拦截。
    * `detect_entity_polarity(self, entities: list, text: str, window_size: int = 5) -> list`：基于滑动窗口与枚举连词寻址的极性辖域传导算法，输出带有 `polarity` (阳性/阴性) 属性的增强实体列表。

### 1.8 `app/storage.py`
**模块定位**：持久层与状态控制引擎。
**架构说明**：负责文件系统 I/O 控制、CDSS 规则碰撞拦截，以及跨目录状态检索。
* **核心类：`StorageEngine`**
    * `get_all_patients_info()` / `get_patient_history()`：EMPI 接口，遍历解析存储库，溯源目标患者最近一次的终态快照，支持防崩溃隔离机制。
    * `save_visit_snapshot(...) -> str`：执行双向 CDSS 交叉校验。智能识别输入模态，生成包含归档文本、模型张量输出及人类核验状态的生命周期目录。

### 1.9 `app/train.py`
**模块定位**：神经认知层微调管线。
**架构说明**：独立的 MLOps 训练脚本。负责挂载 CMeEE-V2 数据集，初始化模型架构，执行混合精度计算、全局指针损失 (GlobalPointer Loss) 评估及最佳权重落盘。

---

## 2. 调度总线与微服务路由

### 2.1 `main.py`
**模块定位**：主程序调度器与 DAG 管线编排。
**核心接口**：`run_medical_pipeline(image_path, raw_text_input, patient_id, patient_info) -> str`
* **智能分流机制**：根据入参侦测模态，若检测到 `raw_text_input`，则物理熔断并跳过 OCR 视觉感知层，直接唤醒认知网络。
* **容错沙箱兜底**：若直通文本未能命中任何正则截断锚点，系统自动生成 `{"综合病历文本": raw_text}` 的兜底沙箱以防止信息丢失。
* **时空继承融合**：跨生命周期提取历史过敏史并注入当前上下文，形成闭环防线。

### 2.2 `web.py`
**模块定位**：Flask 宿主与 RESTful 路由网关。
**核心机制与接口**：
* **多并发防污染机制**：在 `/analyze` 接口对上传的文档与图像注入 UUID 盐值，防止多用户并发请求导致的文件读写竞态条件 (Race Condition)。
* **多模态预处理**：内嵌 PyMuPDF 引擎执行 PDF 的 2x 矩阵超采样栅格化；内嵌 `python-docx` 引擎提取富文本并执行段落合并防粘连逻辑。
* **微服务端点**：
    * `POST /api/settings/all`：接收 GUI 序列化数据，覆写底层 JSON 并触发 `ConfigManager.reload()`。
    * `POST /api/dynamic_ner`：接收单段文本重组请求，执行局部 NER 神经重载。
    * `POST /api/dynamic_cdss`：纯内存态的 CDSS 冲突碰撞探测，返回高危预警集。

---

## 3. 表现与交互层 (Frontend Layer)

### 3.1 `templates/index.html`
**模块定位**：主工作站视图骨架。
**架构说明**：基于 Bootstrap 5 构建的现代非对称双栏响应式网格。
* **动态自适应视口**：具备视图侦测能力，在“文本直通模式”下自动销毁图像占位 DOM，将结构化映射区释放为 100% 满宽布局。
* **强约束表单映射**：依托 Jinja2 模板引擎，从 `rules.json` 中动态读取并渲染标准字段及 `data-required="true"` 质控必填项。
* **状态机桥接注入**：通过 `<script> window.SYSTEM_CONTEXT = {...} </script>` 标签实现 Python 后端数据结构向 JavaScript 内存空间的无缝序列化投递。

### 3.2 `static/js/main.js`
**模块定位**：前端状态机与微操交互控制核心。
**核心逻辑模块**：
* **全局变量提升 (Hoisting)**：将 `activeInputField` 定义于顶层全局作用域，确保实体双击注入事件与 DOM Focus 监听器的指针绝对安全。
* **隐式坐标漂移修正引擎**：`saveOcrText()` 函数不仅处理文本更新，更能通过字符串查找算法在不请求后端的条件下计算实体的绝对物理位移，实现无感坐标对齐。
* **CDSS 动态监听器**：为所有的表单输入框绑定高频 `input` 事件，实现“医生键盘敲击-后端校验-前端报警”的毫秒级时序响应。
* **强约束归档拦截器**：`executeArchiveProtocol()` 在提交阶段执行物理检视，一旦探测到质控核心字段为空，强制挂起并执行视觉焦点重定向。

### 3.3 `static/css/style.css`
**模块定位**：全局视觉规范与动效库。
**视觉标准**：
* 采用 `Glassmorphism` (玻璃拟物化) 物理光影设计。
* 统一定义基于线性渐变 (Linear-Gradient) 的实体医学分类着色系统与呼吸告警动画 (Keyframes)。