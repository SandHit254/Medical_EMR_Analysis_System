> ### ⚠️ 重要声明 (Disclaimer)
>
> **本项目仅作为毕业设计作品，旨在展示人工智能（NLP）算法落地逻辑、人机协同架构与医疗信息化工程，不具备任何实际医疗用途。**
>
> - **非临床建议**：系统生成的推断结论（如用药目的、临床结论等）均基于预训练模型与专家规则，未经临床验证，**严禁**直接用于真实医疗诊断、用药指导或治疗建议。
> - **学术研究性质**：本项目所有识别结果、推断逻辑仅供学术交流与技术探讨使用，使用者需承担因误用而产生的风险。
> - **数据隐私**：请勿将含有真实敏感个人信息的病历上传至公共环境。
>
> **This project is for academic demonstration purposes ONLY and is NOT intended for actual clinical use or medical diagnosis.**

---

# 🏥 基于 OCR 与大模型 NER 的医疗病历智能结构化与人机协同中枢 
**(Medical EMR Intelligence & Human-in-the-Loop System)**

基于深度学习（MacBERT + GlobalPointer）与动态规则引擎的双驱架构，专为医疗场景设计的自动化信息抽取、逻辑推理与全链路快照归档系统。本项目探索了 AI 算法在垂直行业落地的工程化范式，实现了从静态模型到具备“持续演化”能力的 MLOps 架构跃迁。

---

## 一、 🌟 项目目的与意义 (Project Purpose & Significance)

1. **规范化基层医疗数据资产**：针对非结构化的手写/打印病历，提供低门槛的数字化与结构化解决方案，解决纸质病历易丢失、难检索的痛点。
2. **打通院际信息孤岛**：将杂乱的文本转化为标准结构化 JSON 数据，方便向更高级别医院转院时的病史精准查阅与系统级数据对接。
3. **突破静态 AI 落地局限（核心探索）**：传统的 AI 模型在部署后往往成为“黑盒”，本项目通过引入**主动学习（Active Learning）**与**动态配置**机制，探索了一条轻量级医疗 AI 系统的持续演化路径，有效降低了模型在垂直领域的水土不服。

---

## 二、 ✨ 核心技术突破与工程亮点 (Core Engineering Innovations)

本项目在算法表现层与业务逻辑层实现了多项工业级设计，全面超越常规 CRUD 或单次推理脚本：

### 2.1 🔄 数据飞轮与主动学习 (Data Flywheel & Human-in-the-Loop)
- **痛点**：轻量级 OCR 模型在面对医学专有名词时存在固有盲区（如将“颌面”误识为“领面”）。
- **创新**：系统在 Web 交互端构筑了一键划词纠错机制。医生在前端修正的错词将静默反哺至底层 `rules.json` 知识库。系统在随后的管线任务中会自动前置拦截并修复同类错误，实现 AI 知识库的**持续自我进化**。

### 2.2 ⚡ 参数动态热重载 (Dynamic Parameter Hot-Swapping)
- **痛点**：传统 AI 系统的阈值调优或规则修改往往需要重启整个后端服务进程。
- **创新**：依托基于单例模式构建的 `ConfigManager`，系统支持通过 Web RESTful API 直接覆写底层配置（如 NER 置信度阈值、实体白名单）。重写完成后触发内存级热重载，实现真正的 **Zero-Downtime（零停机时间）** 业务更新。

### 2.3 🧬 跨场景领域适应 (Domain Adaptation)
-   **基于锚点的容错截断算法**：通过动态构建包含序号与特殊符号的正则边界，兼容门诊与住院出院记录的结构差异，实现 100% 的物理段落隔离。
-   **后置黑名单防御**：引入实体清洗降噪层，通过交叉验证拦截模型在 Out-of-Distribution (OOD) 数据上产生的荒谬预测（如纯数字、特定专科缩写），大幅提升 Precision（精确率）。

---

## 三、 🧠 系统架构与管线工作流 (Architecture & Workflow)

系统采用高度解耦的流水线（Pipeline）设计。以下为本系统的人机协同与数据流转拓扑图：

```mermaid
graph TD
    %% 样式定义
    classDef c_input fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    classDef c_ai fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef c_rule fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef c_human fill:#f3e5f5,stroke:#4a148c,stroke-width:2px;
    classDef c_storage fill:#eceff1,stroke:#37474f,stroke-width:2px;

    %% 节点定义 (纯净字符串，无内联样式干扰)
    A("多模态录入: 扫描件或纯文本")
    B{"身份网关 EMPI"}
    C["感知层: RapidOCR 引擎"]
    D["前置过滤: 纠错字典正则清洗"]
    E["认知层: MacBERT + GlobalPointer"]
    F["中置截断: 锚点段落隔离"]
    G["后置降噪: 实体消解与逻辑推断"]
    H["人机中枢: Web 结构化核对与补全"]
    I(("Data Flywheel: 主动学习反馈"))
    J[("持久层: 06_Human_Verified.json")]

    %% 流程连接
    A --> B
    B -->|"构建 V_时间戳"| C
    C --> D
    D -->|"纯净文本"| E
    E --> F
    F --> G
    G -->|"生成 05_AI_Draft"| H
    
    H -.->|"发现 OCR 盲区"| I
    I -.->|"触发热重载"| D
    
    H -->|"医生签署终审"| J

    %% 底部统一绑定样式 (最安全的语法)
    class A,B c_input;
    class C,E c_ai;
    class D,F,G c_rule;
    class H,I c_human;
    class J c_storage;
```
### 🌊 管线流转解析 (Pipeline Breakdown)

**[多模态感知]**：系统接收病历影像，`app/ocr.py` 驱动引擎提取坐标与文本。随即触发 DataProcessor 进行前置纠错清洗。

**[神经认知推理]**：纯净文本流进入 `app/ner.py`，加载注入了 RoPE 旋转位置编码的 GlobalPointer 网络，在特征空间完成实体张量解码。

**[逻辑处理约束]**：提取出的实体交由规则引擎，执行锚点物理切分与实体黑名单降噪，剔除假阳性数据，输出初步 AI 结构化草案。

**[人机协同干预]**：医生在 Web 智能工作站进行图文溯源比对。如有识别误差，可实时修正并经由 Data Flywheel 反哺底层库。

**[封卷持久化]**：医生补充强制结构化表单（如既往史、过敏史）后提交，系统生成防篡改追踪标签并落库至 `output/` 树状目录。

---

## 四、 📁 目录结构与模块深度解析 (Project Structure)

本项目严格遵循现代软件工程规范，实现了前后端分离、业务代码与配置解耦的底层架构设计。

```text
/Medical_EMR_System/
├── app/                           # 核心推理引擎与处理中枢
│   ├── __init__.py
│   ├── config_manager.py          # [核心] 单例模式配置管家，支撑全链路热重载
│   ├── exceptions.py              # 自定义系统异常类
│   ├── model.py                   # GlobalPointer (带 RoPE 旋转位置编码) 算子结构
│   ├── ner.py                     # MacBERT 认知层推理引擎
│   ├── ocr.py                     # RapidOCR 感知层推理引擎
│   ├── processor.py               # [核心] 逻辑处理管家 (切片、降噪、纠错清洗)
│   └── storage.py                 # 持久层 IO 控制引擎
├── configs/                       # 全局配置集 (解耦算法与业务规则)
│   ├── global_settings.json       # 系统级参数 (硬件调度、存储路径)
│   ├── model.json                 # NER 阈值与标签字典 (支持热更新)
│   └── rules.json                 # 动态规则引擎库 (包含 Data Flywheel 纠错字典)
├── models/                        # 模型权重挂载区
│   └── ner_model.pt               # 基于医疗语料微调的本地张量权重
├── static/                        # 前端静态资源 (分离关注点设计)
│   ├── css/style.css              # 毛玻璃质感 (Glassmorphism) 全局样式表
│   └── js/main.js                 # 动态交互与异步请求脚本 (数据飞轮前端触发器)
├── templates/                     # 视图渲染层
│   └── index.html                 # 智能医疗工作站与人机核对控制台
├── main.py                        # 离线业务流水线构建脚本
├── web.py                         # [入口] Flask 宿主框架与 RESTful API 路由层
└── requirements.txt               # 依赖清单
```

## 五、 🚀 部署与使用指南 (Deployment & Usage)

### 5.1 环境准备
本系统基于 Python 3.9+ 构建，建议使用 Anaconda / Miniconda 创建独立的虚拟环境。
``` bash
# 1. 克隆或下载本项目至本地
# 2. 安装核心运算与应用依赖
pip install -r requirements.txt
```

### 5.2 模型装载
由于平台限制，预训练模型权重需自行挂载：
1. 请确保已将微调后的 ner_model.pt 放置于 `/models/` 目录下。
2. 系统运行前将自动下载 `hfl/chinese-macbert-base` 基础词表（如处于内网离线环境，请提前缓存至本地并在 model.json 中更改寻址路径）。

### 5.3 启动智能中枢
在项目根目录执行以下命令唤起 Web 服务：
```bash
python web.py
```
终端提示 `Running on http://0.0.0.0:5000/` 后，使用现代浏览器（推荐 Chrome / Edge）访问 `http://127.0.0.1:5000/` 即可进入工作站。

### 5.4 操作指南与 MLOps 演示
1.  多模态分析：在左侧面板上传门诊/住院病历图像，点击“启动分析流”。

2.  人机协同核对：

    -   切换至【溯源视图】，比对原图与高亮实体。
    -   切换至【结构化复核】，补充诸如“过敏史”等必填项，修正算法偏差。

3.  主动学习 (触发数据飞轮)：

    -   若在视图中发现 OCR 识别错误，点击 **[提交纠错规则]**。
    -   输入原错误词与正确词，提交后系统将即刻重载 `rules.json` ，完成单次自我进化。

------
## 六、 📚 数据集引用与致谢 (References & Acknowledgements)
本系统在底层算法研究与模型微调阶段，深度依赖了开源社区的贡献，特此致谢：

-   CMeEE-V2 (Chinese Medical Entity Extraction)：感谢 CBLUE 平台提供的中文医疗命名实体识别开源数据集，为本项目的领域适应提供了坚实的数据基座。
-   MacBERT：感谢 HFL (哈工大讯飞联合实验室) 提供的中文预训练语言模型。
-   GlobalPointer：感谢苏剑林大佬提出的全局指针网络思想，优雅地解决了医疗文本的实体嵌套痛点。
-   RapidOCR：感谢跨平台的高效 OCR 开源框架。

------

## 七、 👨‍💻 作者与免责协议 (License)
**开发作者**：SandHit
**使用协议**：仅限学术答辩、技术交流与代码研讨使用。严禁用于任何真实的商业医疗、临床诊断与处方生成场景。