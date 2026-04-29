/**
 * ====================================================================
 * 模块名称：前端状态机与交互流转控制模块 (Frontend State Machine)
 * 功能描述：接管 DOM 操作、跨路由 Session 会话保持、
 * CDSS 动态预警、以及异步微服务接口 (AJAX) 的流转通信。
 * ====================================================================
 */

let activeInputField = null; // 【核心修复】：变量提升，记录当前选中的输入框，用于实体交互注入

/**
 * 唤起全局 Loading 遮罩层
 * @param {string} text - 提示文案
 */
function showLoading(text = "神经引擎介入中...") {
    document.getElementById("loading-text").innerText = text;
    document.getElementById("loading-overlay").style.display = "flex";
}

/**
 * 关闭全局 Loading 遮罩层
 */
function hideLoading() {
    document.getElementById("loading-overlay").style.display = "none";
}

/**
 * XSS 防御：HTML 字符转义
 * @param {string} text - 原始字符串
 * @returns {string} 转义后的安全字符串
 */
function escapeHtml(text) {
    if (!text) return "";
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * 唤起全局 Toast 系统提示
 * @param {string} msg - 提示信息
 * @param {boolean} isError - 是否为错误红色警示
 */
function showSystemToast(msg, isError = false) {
    const toastEl = document.getElementById("systemToast");
    const toastBody = document.getElementById("toast-message");
    toastEl.className = `toast align-items-center text-white border-0 shadow-lg ${isError ? "bg-danger" : "bg-success"}`;
    toastBody.innerHTML = `<i class="bi bi-${isError ? "exclamation-circle" : "check-circle"} me-2"></i>${msg}`;
    new bootstrap.Toast(toastEl).show();
}

/* ====================================================================
 * 左侧：电子病历库目录树与搜索引擎
 * ==================================================================== */
document.addEventListener("DOMContentLoaded", function () {
    loadLibraryTree();
});

function loadLibraryTree() {
    fetch("/api/library/tree")
        .then((r) => r.json())
        .then((data) => {
            const container = document.getElementById("patient-tree-container");
            if (!data.tree || data.tree.length === 0) {
                container.innerHTML =
                    '<div class="text-muted text-center mt-4">档案库为空</div>';
                return;
            }
            let html =
                '<div class="accordion accordion-flush border-0" id="accordionTree">';
            data.tree.forEach((p, idx) => {
                let visitList = p.visits
                    .map(
                        (v) => `
                <div class="p-2 border-bottom visit-item" style="cursor:pointer; padding-left: 1rem !important;" onclick="window.location.href='/view/${p.patient_id}/${v.visit_id}'">
                    <i class="bi bi-file-earmark-text text-primary me-2"></i> ${v.time}
                </div>
            `,
                    )
                    .join("");
                html += `
            <div class="accordion-item bg-transparent border-0 mb-1">
                <h2 class="accordion-header">
                    <button class="accordion-button collapsed py-2 px-2 bg-transparent small fw-bold rounded shadow-sm border" type="button" data-bs-toggle="collapse" data-bs-target="#flush-collapse${idx}">
                        <i class="bi bi-folder2-open text-warning me-2 fs-6"></i> ${p.name} <span class="text-muted ms-2 fw-normal" style="font-size:0.7rem;">${p.patient_id.substring(4, 12)}</span>
                    </button>
                </h2>
                <div id="flush-collapse${idx}" class="accordion-collapse collapse" data-bs-parent="#accordionTree">
                    <div class="accordion-body p-0 bg-white border-start border-2 border-primary ms-2 mt-1">
                        ${visitList}
                    </div>
                </div>
            </div>`;
            });
            html += "</div>";
            container.innerHTML = html;
        })
        .catch(() => {
            document.getElementById("patient-tree-container").innerHTML =
                '<div class="text-danger text-center mt-4">加载失败</div>';
        });
}

window.executeLibrarySearch = function () {
    const query = document.getElementById("library-search-input").value.trim();
    const container = document.getElementById("patient-search-container");
    if (!query) {
        container.innerHTML =
            '<div class="alert alert-light border text-muted text-center mt-2 p-2">请输入检索词</div>';
        return;
    }

    const searchTab = new bootstrap.Tab(
        document.querySelector('button[data-bs-target="#lib-search"]'),
    );
    searchTab.show();

    container.innerHTML =
        '<div class="text-center mt-4"><div class="spinner-border spinner-border-sm text-primary"></div></div>';

    fetch("/api/library/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query }),
    })
        .then((r) => r.json())
        .then((data) => {
            if (data.results.length === 0) {
                container.innerHTML =
                    '<div class="alert alert-light border text-muted text-center mt-2 p-2">未匹配到相关档案</div>';
                return;
            }
            let html = "";
            data.results.forEach((res) => {
                let tagsHtml = res.tags
                    .map(
                        (t) =>
                            `<span class="badge bg-info text-dark me-1 border shadow-sm">${t}</span>`,
                    )
                    .join("");
                html += `
            <div class="card mb-2 shadow-sm border rounded lib-card-hover" style="cursor:pointer; transition:all 0.2s;" onclick="window.location.href='/view/${res.patient_id}/${res.visit_id}'">
                <div class="card-body p-2">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="fw-bold text-dark"><i class="bi bi-person-fill text-secondary"></i> ${res.name}</span>
                        <span class="text-muted" style="font-size: 0.7rem;"><i class="bi bi-clock"></i> ${res.time}</span>
                    </div>
                    <div class="mb-2 text-muted" style="font-size: 0.7rem;">PID: ${res.patient_id}</div>
                    <div>${tagsHtml}</div>
                </div>
            </div>`;
            });
            container.innerHTML = html;
        })
        .catch(() => {
            container.innerHTML =
                '<div class="alert alert-danger text-center mt-2 p-2">检索异常</div>';
        });
};

/* ====================================================================
 * EMPI 患者主索引网关与跨路由会话保持机制
 * ==================================================================== */
document.addEventListener("DOMContentLoaded", function () {
    const hasRecord = document.getElementById("meta-visit-id") !== null;
    let savedPid = sessionStorage.getItem("active_pid");
    let savedPinfo = sessionStorage.getItem("active_pinfo");

    if (!hasRecord && window.location.pathname === "/") {
        if (savedPid && savedPinfo) {
            setPatientContext(savedPid, JSON.parse(savedPinfo), true);
        } else {
            openEmpiGateway();
        }
    }

    document.querySelectorAll(".upload-form").forEach((form) => {
        form.addEventListener("submit", function (e) {
            const patientIdInput = this.querySelector(".sync-pid");
            if (!patientIdInput || !patientIdInput.value.trim()) {
                e.preventDefault();
                openEmpiGateway();
            } else {
                showLoading("数据流转解析中，请稍候...");
            }
        });
    });

    document.querySelectorAll(".emr-input-target").forEach((el) => {
        el.addEventListener("input", function () {
            if (window.SYSTEM_CONTEXT && window.SYSTEM_CONTEXT.emrData) {
                window.SYSTEM_CONTEXT.emrData[this.name] = this.value;
                triggerDynamicCDSS();
            }
        });
    });
});

window.resetWorkstation = function () {
    sessionStorage.removeItem("active_pid");
    sessionStorage.removeItem("active_pinfo");
    window.location.href = "/";
};

window.openEmpiGateway = function () {
    fetch("/api/patients")
        .then((r) => r.json())
        .then((data) => {
            const select = document.getElementById("empi-patient-select");
            select.innerHTML = "";
            if (data.patients && data.patients.length > 0) {
                data.patients.forEach((p) => {
                    select.innerHTML += `<option value="${p.id}" data-name="${p.name}" data-gender="${p.gender}" data-age="${p.age}">${p.id} - ${p.name} (${p.gender}, ${p.age})</option>`;
                });
                select.disabled = false;
            } else {
                select.innerHTML =
                    '<option value="">(空) 档案库中暂无历史患者，请建档</option>';
                select.disabled = true;
            }
            new bootstrap.Modal(document.getElementById("empiModal")).show();
        });
};

window.selectPatient = function () {
    const select = document.getElementById("empi-patient-select");
    const pid = select.value;
    if (!pid)
        return alert("请选择有效的患者标识符，或切换右侧 Tab 建立新患者！");

    document.getElementById("empi-new-name").value = "";
    document.getElementById("empi-new-gender").value = "";
    document.getElementById("empi-new-age").value = "";

    const opt = select.options[select.selectedIndex];
    const info = {
        name: opt.dataset.name,
        gender: opt.dataset.gender,
        age: opt.dataset.age,
    };
    setPatientContext(pid, info);
};

window.createNewPatient = function () {
    const name = document.getElementById("empi-new-name").value.trim();
    const gender = document.getElementById("empi-new-gender").value;
    const age = document.getElementById("empi-new-age").value.trim();

    fetch("/api/patients/new")
        .then((r) => r.json())
        .then((data) => {
            setPatientContext(data.patient_id, {
                name: name || "待提取",
                gender: gender || "-",
                age: age || "-",
            });
        });
};

function setPatientContext(pid, info, skipRedirect = false) {
    sessionStorage.setItem("active_pid", pid);
    sessionStorage.setItem("active_pinfo", JSON.stringify(info));

    if (window.location.pathname.startsWith("/view/") && !skipRedirect) {
        window.location.href = "/";
        return;
    }

    document.getElementById("current-patient-id-display").innerText = pid;

    document.querySelectorAll(".sync-pid").forEach((el) => (el.value = pid));
    document
        .querySelectorAll(".sync-pname")
        .forEach((el) => (el.value = info.name));
    document
        .querySelectorAll(".sync-pgender")
        .forEach((el) => (el.value = info.gender));
    document
        .querySelectorAll(".sync-page")
        .forEach((el) => (el.value = info.age));

    const msg = document.getElementById("upload-lock-msg");
    if (msg) msg.style.display = "none";

    const dynBanner = document.getElementById("dynamic-patient-banner");
    if (dynBanner) {
        dynBanner.style.setProperty("display", "flex", "important");
        document.getElementById("dyn-banner-name").innerText = info.name;
        document.getElementById("dyn-banner-gender").innerText = info.gender;
        document.getElementById("dyn-banner-age").innerText = info.age;
        document.getElementById("dyn-banner-pid").innerText = pid;

        const genderIcon = document.getElementById("dyn-banner-gender-icon");
        if (genderIcon) {
            genderIcon.className =
                info.gender === "男"
                    ? "bi bi-gender-male text-primary"
                    : info.gender === "女"
                        ? "bi bi-gender-female text-danger"
                        : "bi bi-gender-ambiguous text-secondary";
        }
    }

    const idleStateView = document.getElementById("idle-state-view");
    if (idleStateView) {
        idleStateView.className =
            "glass-card flex-grow-1 d-flex flex-column align-items-center justify-content-center p-5 text-center shadow-sm border rounded bg-success bg-opacity-10";
        idleStateView.style.borderColor = "#86efac";
        const idleIcon = document.getElementById("idle-icon");
        if (idleIcon)
            idleIcon.className =
                "bi bi-clipboard2-check-fill text-success opacity-75";
        const idleTitle = document.getElementById("idle-title");
        if (idleTitle) {
            idleTitle.innerText = "患者档案已关联，工作站就绪";
            idleTitle.className = "fw-bold text-success mb-2 mt-3";
        }
        const idleDesc = document.getElementById("idle-desc");
        if (idleDesc) {
            idleDesc.innerHTML = `已锁定患者 <strong>${pid}</strong>，请在左侧开启分析管线。`;
            idleDesc.className = "text-success opacity-75 mx-auto";
        }
    }

    const resetContainer = document.getElementById("reset-workspace-container");
    if (resetContainer) resetContainer.style.display = "block";

    const modalEl = document.getElementById("empiModal");
    if (modalEl) {
        const modalInstance = bootstrap.Modal.getInstance(modalEl);
        if (modalInstance) modalInstance.hide();
    }
}

/* ====================================================================
 * 文本焦点捕获器
 * ==================================================================== */
document.addEventListener("focusin", function (e) {
    if (e.target && e.target.classList.contains("emr-input-target")) {
        if (activeInputField)
            activeInputField.classList.remove("active-input-field");
        activeInputField = e.target;
        activeInputField.classList.add("active-input-field");
    }
});

/* ====================================================================
 * 核心渲染引擎
 * ==================================================================== */
function renderEntityHighlights() {
    const context = window.SYSTEM_CONTEXT;
    if (!context || !context.emrData) return;
    const renderTarget = document.getElementById("highlight-render-target");
    if (!renderTarget) return;
    renderTarget.innerHTML = "";

    Object.keys(context.emrData).forEach((sectionName) => {
        const rawText = context.emrData[sectionName];
        if (!rawText || rawText.trim() === "") return;

        const rawEntities = context.entitiesData.filter(
            (ent) =>
                ent.section === sectionName || ent["所属段落"] === sectionName,
        );
        let validEntities = [];
        let searchCursor = 0;

        const sortedRaw = [...rawEntities].sort((a, b) => a.start - b.start);

        sortedRaw.forEach((ent) => {
            let actualStart = rawText.indexOf(ent.text, searchCursor);
            if (actualStart === -1) {
                actualStart = rawText.indexOf(ent.text, 0);
            }

            if (actualStart !== -1) {
                validEntities.push({
                    ...ent,
                    actualStart: actualStart,
                    actualEnd: actualStart + ent.text.length,
                });
                searchCursor = actualStart + ent.text.length;
            }
        });

        validEntities.sort((a, b) => a.actualStart - b.actualStart);

        let finalEntities = [];
        let currentEnd = 0;
        validEntities.forEach((ent) => {
            if (ent.actualStart >= currentEnd) {
                finalEntities.push(ent);
                currentEnd = ent.actualEnd;
            }
        });

        let htmlStream = "";
        let cursor = 0;

        finalEntities.forEach((ent) => {
            htmlStream += escapeHtml(
                rawText.substring(cursor, ent.actualStart),
            );

            const safeClass = ent.type.replace(/\//g, "_");
            const isNegative = ent.polarity === "阴性";
            const polarityStyle = isNegative
                ? "opacity: 0.5; text-decoration: line-through;"
                : "";
            const polarityBadge = isNegative
                ? '<span style="color:#ef4444;font-size:0.6rem;margin-left:4px;">(排除)</span>'
                : "";

            htmlStream += `<span class="entity-box type-${safeClass}" style="${polarityStyle} cursor: pointer; border-radius: 4px; padding: 2px 4px; transition: 0.2s;" onclick="openEntityEditor('${escapeHtml(ent.text)}', ${ent.actualStart}, '${sectionName}', '${ent.type}', '${ent.polarity}')"><span class="entity-text fw-bold">${escapeHtml(ent.text)}</span><span class="entity-label">${escapeHtml(ent.type)}${polarityBadge}</span></span>`;

            cursor = ent.actualEnd;
        });

        htmlStream += escapeHtml(rawText.substring(cursor));

        const sectionWrapper = document.createElement("div");
        sectionWrapper.className = "mb-4 section-block";
        sectionWrapper.dataset.section = sectionName;
        sectionWrapper.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-2">
                <div class="fw-bold text-muted small text-uppercase tracking-wide"><i class="bi bi-record-circle-fill text-primary" style="font-size: 0.6rem; margin-right: 4px;"></i> ${sectionName}</div>
                <button class="btn btn-sm btn-light py-0 px-2 text-primary border-0 shadow-sm" style="font-size: 0.8rem;" onclick="openOcrEditor('${sectionName}')"><i class="bi bi-pencil-square"></i> 增删文本</button>
            </div>
            <div class="text-dark bg-light p-3 rounded section-text-content" style="border: 1px solid #f0f0f5; line-height: 2;">${htmlStream}</div>
        `;
        renderTarget.appendChild(sectionWrapper);
    });

    renderEntityChips();
}

function renderEntityChips() {
    const context = window.SYSTEM_CONTEXT;
    const pool = document.getElementById("global-chip-pool");
    if (!pool || !context || !context.entitiesData) return;
    pool.innerHTML = "";

    context.entitiesData.forEach((ent) => {
        const safeClass = ent.type.replace(/\//g, "_");
        const isNegative = ent.polarity === "阴性";
        const chip = document.createElement("span");
        chip.className = `badge rounded-pill me-2 mb-2 px-3 py-2 entity-chip type-${safeClass}`;

        if (isNegative) {
            chip.style.opacity = "0.6";
            chip.style.textDecoration = "line-through";
            chip.innerHTML = `<i class="bi bi-dash-circle me-1"></i>${escapeHtml(ent.text)}`;
            chip.title = "阴性(排除)体征，将填入：无" + ent.text;
        } else {
            chip.innerHTML = `<i class="bi bi-plus-circle me-1"></i>${escapeHtml(ent.text)}`;
            chip.title = "阳性体征，点击填入选中框";
        }

        chip.onclick = function () {
            if (!activeInputField) {
                alert(
                    "👉 录入提示：\n请先在左侧表单中点击选中你要填写的框（如'主诉'或'过敏史'），然后再点击此处标签填入。",
                );
                return;
            }
            const currentVal = activeInputField.value.trim();
            let insertText = isNegative ? `无${ent.text}` : ent.text;

            if (
                currentVal &&
                !currentVal.endsWith("，") &&
                !currentVal.endsWith("。") &&
                !currentVal.endsWith("、")
            ) {
                activeInputField.value = currentVal + "，" + insertText;
            } else {
                activeInputField.value = currentVal + insertText;
            }
            window.SYSTEM_CONTEXT.emrData[activeInputField.name] =
                activeInputField.value;
            triggerDynamicCDSS();
        };
        pool.appendChild(chip);
    });
}

window.insertDiagnosis = function (text) {
    const textarea = document.getElementById("final-diagnosis-text");
    if (textarea) {
        const currentVal = textarea.value.trim();
        if (currentVal && !currentVal.endsWith("\n")) {
            textarea.value = currentVal + "\n" + text;
        } else {
            textarea.value = currentVal + text;
        }
        textarea.style.backgroundColor = "#dcfce7";
        setTimeout(() => (textarea.style.backgroundColor = "#f8f9fa"), 300);
    }
};

function triggerDynamicCDSS() {
    const fullText = Object.values(window.SYSTEM_CONTEXT.emrData).join(" ");
    fetch("/api/dynamic_cdss", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            emr_text: fullText,
            entities: window.SYSTEM_CONTEXT.entitiesData,
        }),
    })
        .then((r) => r.json())
        .then((data) => {
            const container = document.getElementById("cdss-alert-container");
            if (
                data.code === 200 &&
                data.warnings &&
                data.warnings.length > 0
            ) {
                let listHtml = data.warnings
                    .map((w) => `<li class="mb-1">${w}</li>`)
                    .join("");
                container.innerHTML = `<div class="alert shadow-sm border-0 m-0 rounded" style="background-color: #fef2f2; border-left: 6px solid #ef4444 !important; animation: pulse-red 2s infinite;"><div class="d-flex align-items-center mb-2"><i class="bi bi-shield-fill-x text-danger fs-4 me-2"></i><h6 class="fw-bold text-danger m-0">临床决策支持系统 (CDSS) 实时预警</h6></div><ul class="mb-0 small text-danger fw-bold" style="list-style-type: square;">${listHtml}</ul></div>`;
            } else {
                container.innerHTML = "";
            }
        });
}

window.openOcrEditor = function (sectionName) {
    document.getElementById("edit-ocr-section").value = sectionName;
    document.getElementById("edit-ocr-content").value =
        window.SYSTEM_CONTEXT.emrData[sectionName] || "";
    new bootstrap.Modal(document.getElementById("editOcrTextModal")).show();
};

window.saveOcrText = function (triggerNerReload) {
    const section = document.getElementById("edit-ocr-section").value;
    const newText = document.getElementById("edit-ocr-content").value.trim();
    if (!newText) return alert("文本不能为空！");

    window.SYSTEM_CONTEXT.emrData[section] = newText;
    const formTextarea = document.querySelector(`textarea[name="${section}"]`);
    if (formTextarea) formTextarea.value = newText;

    if (!triggerNerReload) {
        let updatedEntities = [];
        window.SYSTEM_CONTEXT.entitiesData.forEach((ent) => {
            if (ent.section === section || ent["所属段落"] === section) {
                const newStartIdx = newText.indexOf(ent.text);
                if (newStartIdx !== -1) {
                    ent.start = newStartIdx;
                    ent.end = newStartIdx + ent.text.length;
                    updatedEntities.push(ent);
                }
            } else {
                updatedEntities.push(ent);
            }
        });
        window.SYSTEM_CONTEXT.entitiesData = updatedEntities;
        renderEntityHighlights();
        triggerDynamicCDSS();
        bootstrap.Modal.getInstance(
            document.getElementById("editOcrTextModal"),
        ).hide();
        showSystemToast("文本已更新，坐标重组完毕！");
    } else {
        bootstrap.Modal.getInstance(
            document.getElementById("editOcrTextModal"),
        ).hide();
        showLoading("微服务流转中：局部 NER 推理重载...");
        fetch("/api/dynamic_ner", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ section: section, text: newText }),
        })
            .then((r) => r.json())
            .then((data) => {
                hideLoading();
                if (data.code === 200) {
                    window.SYSTEM_CONTEXT.entitiesData =
                        window.SYSTEM_CONTEXT.entitiesData.filter(
                            (e) =>
                                e.section !== section &&
                                e["所属段落"] !== section,
                        );
                    window.SYSTEM_CONTEXT.entitiesData =
                        window.SYSTEM_CONTEXT.entitiesData.concat(
                            data.entities,
                        );
                    renderEntityHighlights();
                    triggerDynamicCDSS();

                    showSystemToast("神经推理重载成功！");
                } else {
                    alert("神经推理失败: " + data.message);
                }
            })
            .catch((err) => {
                hideLoading();
                alert("网络异常");
            });
    }
};

window.openEntityEditor = function (text, start, section, type, polarity) {
    document.getElementById("edit-ent-text").value = text;
    document.getElementById("edit-ent-start").value = start;
    document.getElementById("edit-ent-section").value = section;
    document.getElementById("edit-display-text").innerText = text;
    document.getElementById("edit-ent-type").value = type;
    document.getElementById("edit-ent-polarity").value = polarity || "阳性";
    new bootstrap.Modal(document.getElementById("editEntityModal")).show();
};
window.updateEntity = function () {
    const text = document.getElementById("edit-ent-text").value;
    const section = document.getElementById("edit-ent-section").value;
    const ent = window.SYSTEM_CONTEXT.entitiesData.find(
        (e) =>
            e.text === text &&
            (e.section === section || e["所属段落"] === section),
    );
    if (ent) {
        ent.type = document.getElementById("edit-ent-type").value;
        ent.polarity = document.getElementById("edit-ent-polarity").value;
        renderEntityHighlights();
        triggerDynamicCDSS();
    }
    bootstrap.Modal.getInstance(
        document.getElementById("editEntityModal"),
    ).hide();
    showSystemToast("实体属性更新成功");
};
window.deleteEntity = function () {
    const text = document.getElementById("edit-ent-text").value;
    const section = document.getElementById("edit-ent-section").value;
    const index = window.SYSTEM_CONTEXT.entitiesData.findIndex(
        (e) =>
            e.text === text &&
            (e.section === section || e["所属段落"] === section),
    );
    if (index > -1) {
        window.SYSTEM_CONTEXT.entitiesData.splice(index, 1);
        renderEntityHighlights();
        triggerDynamicCDSS();
    }
    bootstrap.Modal.getInstance(
        document.getElementById("editEntityModal"),
    ).hide();
    showSystemToast("已成功剔除该实体");
};

let currentSelectionText = "",
    currentSelectionSection = "";
document.addEventListener("DOMContentLoaded", function () {
    if (!document.getElementById("highlight-render-target")) return;
    renderEntityHighlights();
    const renderTarget = document.getElementById("highlight-render-target");
    const bubble = document.getElementById("selection-bubble");
    if (renderTarget) {
        renderTarget.addEventListener("mouseup", function (e) {
            setTimeout(() => {
                const selection = window.getSelection();
                const selectedText = selection.toString().trim();
                if (selectedText.length > 0 && selectedText.length < 30) {
                    currentSelectionText = selectedText;
                    let targetNode = selection.anchorNode;
                    let sectionBlock =
                        targetNode.nodeType === 3
                            ? targetNode.parentNode.closest(".section-block")
                            : targetNode.closest(".section-block");
                    currentSelectionSection = sectionBlock
                        ? sectionBlock.dataset.section
                        : "";
                    const rect = selection
                        .getRangeAt(0)
                        .getBoundingClientRect();
                    bubble.style.display = "flex";
                    bubble.style.visibility = "hidden";
                    bubble.style.top =
                        rect.top +
                        window.scrollY -
                        bubble.offsetHeight -
                        8 +
                        "px";
                    bubble.style.left =
                        rect.left +
                        window.scrollX +
                        rect.width / 2 -
                        bubble.offsetWidth / 2 +
                        "px";
                    bubble.style.visibility = "visible";
                } else {
                    bubble.style.display = "none";
                }
            }, 50);
        });
        document.addEventListener("selectionchange", () => {
            if (window.getSelection().toString().trim() === "")
                bubble.style.display = "none";
        });
    }
});

window.triggerAddEntity = function () {
    document.getElementById("add-ent-text").value = currentSelectionText;
    const sectionSelect = document.getElementById("add-ent-section");
    sectionSelect.innerHTML = "";
    Object.keys(window.SYSTEM_CONTEXT.emrData).forEach((sec) => {
        const opt = document.createElement("option");
        opt.value = sec;
        opt.innerText = sec;
        if (sec === currentSelectionSection) opt.selected = true;
        sectionSelect.appendChild(opt);
    });
    new bootstrap.Modal(document.getElementById("addEntityModal")).show();
    document.getElementById("selection-bubble").style.display = "none";
};
window.saveNewEntity = function () {
    const text = document.getElementById("add-ent-text").value;
    const section = document.getElementById("add-ent-section").value;
    const rawText = window.SYSTEM_CONTEXT.emrData[section];
    const startIdx = rawText.indexOf(text);
    if (startIdx === -1)
        return alert("坐标计算失败：你选中的文本不连续或不在此段落内。");

    window.SYSTEM_CONTEXT.entitiesData.push({
        text: text,
        type: document.getElementById("add-ent-type").value,
        polarity: document.getElementById("add-ent-polarity").value,
        start: startIdx,
        end: startIdx + text.length,
        section: section,
        score: 1.0,
    });

    renderEntityHighlights();
    triggerDynamicCDSS();
    bootstrap.Modal.getInstance(
        document.getElementById("addEntityModal"),
    ).hide();
    showSystemToast(`实体 "${text}" 注入成功！`);
};

window.triggerOcrCorrection = function () {
    document.getElementById("ocr-wrong-word").value = currentSelectionText;
    document.getElementById("ocr-right-word").value = "";
    new bootstrap.Modal(document.getElementById("ocrCorrectionModal")).show();
    document.getElementById("selection-bubble").style.display = "none";
};
function submitOcrCorrection(event) {
    const btn = event.currentTarget;
    btn.disabled = true;
    fetch("/api/ocr/correct", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            wrong: document.getElementById("ocr-wrong-word").value,
            right: document.getElementById("ocr-right-word").value,
        }),
    })
        .then((r) => r.json())
        .then((data) => {
            if (data.code === 200) {
                bootstrap.Modal.getInstance(
                    document.getElementById("ocrCorrectionModal"),
                ).hide();
                showSystemToast("字典反哺成功！下次识别将生效。");
            } else alert("失败: " + data.message);
        })
        .finally(() => (btn.disabled = false));
}

function executeArchiveProtocol() {
    const requiredInputs = document.querySelectorAll(
        'textarea[data-required="true"]',
    );

    for (let i = 0; i < requiredInputs.length; i++) {
        const input = requiredInputs[i];
        if (input.value.trim() === "") {
            const fieldName = input.getAttribute("name");
            alert(
                `⛔ 临床质控阻断：\n【${fieldName}】为强约束必填项！哪怕在原始病历中缺失，系统也拒绝空值归档。\n若患者未提供，请医生核对后手动填写“无”、“未见”或“未提供”。`,
            );

            const tabTrigger = new bootstrap.Tab(
                document.querySelector(
                    '#workstationTabs button[data-bs-target="#tab-emr"]',
                ),
            );
            tabTrigger.show();

            setTimeout(() => {
                input.focus();
                input.style.boxShadow = "0 0 0 4px rgba(239, 68, 68, 0.4)";
                input.style.border = "1px solid #ef4444";
                setTimeout(() => {
                    input.style.boxShadow = "";
                    input.style.border = "";
                }, 3000);
            }, 300);
            return;
        }
    }

    const finalDiagnosisText = document.getElementById(
        "final-diagnosis-text",
    ).value;
    const statusIndicator = document.getElementById("save-status-indicator");
    const spinner = document.getElementById("save-spinner");

    statusIndicator.innerText = "数据封装与同步中...";
    statusIndicator.className = "text-primary small fw-bold";
    spinner.style.display = "inline-block";

    fetch("/save_report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            就诊编号: document.getElementById("meta-visit-id").innerText,
            患者ID: document.getElementById("meta-patient-id").innerText,
            操作行为: "通过质控网关的终态确诊",
            结构化病历: Object.fromEntries(
                new FormData(document.getElementById("emr-form")),
            ),
            提取实体: window.SYSTEM_CONTEXT.entitiesData,
            医生最终诊断: finalDiagnosisText,
        }),
    })
        .then((r) => r.json())
        .then((res) => {
            spinner.style.display = "none";
            if (res.status === "success") {
                statusIndicator.innerHTML =
                    '<i class="bi bi-check-circle-fill text-success"></i> 质控通过：已安全入库';
                statusIndicator.className = "text-success small fw-bold";
            } else {
                statusIndicator.innerText = "入库异常";
                statusIndicator.className = "text-danger small fw-bold";
            }
        })
        .catch((e) => {
            spinner.style.display = "none";
            statusIndicator.innerText = "网络阻断";
            statusIndicator.className = "text-danger small fw-bold";
        });
}

/* ====================================================================
 * 双向同步配置中心
 * ==================================================================== */
let currentGlobalSettings = {};
let isDevModeActive = false;

document.addEventListener("DOMContentLoaded", function () {
    const tabs = document.querySelectorAll(
        '#settings-tabs button[data-bs-toggle="tab"]',
    );
    const titleEl = document.getElementById("settings-title");

    tabs.forEach((tab) => {
        tab.addEventListener("show.bs.tab", function (event) {
            const targetId = event.target.getAttribute("data-bs-target");
            const prevId = event.relatedTarget
                ? event.relatedTarget.getAttribute("data-bs-target")
                : null;

            if (prevId === "#set-dev") {
                try {
                    const parsedJson = JSON.parse(
                        document.getElementById("editor-raw-json").value,
                    );
                    currentGlobalSettings = parsedJson;
                    populateGuiFromData(currentGlobalSettings);
                    isDevModeActive = false;
                } catch (e) {
                    alert(
                        "⚠️ 格式阻断：底层 JSON 语法有误。\n请修复后再切换视图！",
                    );
                    event.preventDefault();
                    return;
                }
            } else if (targetId === "#set-dev") {
                isDevModeActive = true;
                const guiData = buildDataFromGui();

                if (
                    currentGlobalSettings.global_settings &&
                    currentGlobalSettings.global_settings.system
                )
                    currentGlobalSettings.global_settings.system.device =
                        guiData.device;
                if (
                    currentGlobalSettings.model &&
                    currentGlobalSettings.model.ner
                )
                    currentGlobalSettings.model.ner.inference_threshold =
                        guiData.threshold;
                if (
                    currentGlobalSettings.rules &&
                    currentGlobalSettings.rules.post_processing
                )
                    currentGlobalSettings.rules.post_processing.enable_auto_correction =
                        guiData.enable_correction;
                if (
                    currentGlobalSettings.rules &&
                    currentGlobalSettings.rules.rules
                ) {
                    currentGlobalSettings.rules.rules.section_patterns =
                        guiData.section_patterns;
                    currentGlobalSettings.rules.rules.negation_words =
                        guiData.negation_words;
                    currentGlobalSettings.rules.rules.cdss_rules =
                        guiData.cdss_rules;
                }
                if (currentGlobalSettings.rules) {
                    currentGlobalSettings.rules.corrections =
                        guiData.corrections;
                    currentGlobalSettings.rules.emr_structure =
                        guiData.emr_structure;
                }

                document.getElementById("editor-raw-json").value =
                    JSON.stringify(currentGlobalSettings, null, 4);
                titleEl.innerText = "开发者底层核心";
                return;
            }
            titleEl.innerText = event.target.innerText.trim();
        });
    });
});

window.openSettingsConsole = function () {
    fetch("/api/settings/all")
        .then((response) => response.json())
        .then((res) => {
            if (res.code === 200) {
                currentGlobalSettings = res.data;
                populateGuiFromData(currentGlobalSettings);

                const firstTab = new bootstrap.Tab(
                    document.querySelector(
                        '#settings-tabs button[data-bs-target="#set-general"]',
                    ),
                );
                firstTab.show();
                new bootstrap.Modal(
                    document.getElementById("settingsConsoleModal"),
                ).show();
            } else {
                alert("拉取配置失败: " + res.message);
            }
        })
        .catch((err) => alert("网络异常: " + err));
};

function populateGuiFromData(data) {
    if (data.global_settings && data.global_settings.system) {
        document.getElementById("gui-device").value =
            data.global_settings.system.device || "cpu";
    }
    if (data.model && data.model.ner) {
        document.getElementById("gui-threshold").value =
            data.model.ner.inference_threshold || 0.0;
    }
    if (data.rules) {
        if (data.rules.post_processing) {
            document.getElementById("gui-enable-correction").checked =
                data.rules.post_processing.enable_auto_correction !== false;
        }
        if (data.rules.rules) {
            document.getElementById("gui-sections").value = (
                data.rules.rules.section_patterns || []
            ).join(", ");
            document.getElementById("gui-negation").value = (
                data.rules.rules.negation_words || []
            ).join(", ");

            const cdssContainer = document.getElementById("cdss-gui-container");
            cdssContainer.innerHTML = "";
            (data.rules.rules.cdss_rules || []).forEach((rule) => {
                cdssContainer.appendChild(
                    createCdssCard(
                        rule.allergy,
                        (rule.drugs || []).join(", "),
                        rule.warning,
                    ),
                );
            });
        }

        if (data.rules.emr_structure) {
            document.getElementById("gui-emr-standard").value = (
                data.rules.emr_structure.standard_fields || []
            ).join(", ");
            document.getElementById("gui-emr-required").value = (
                data.rules.emr_structure.required_fields || []
            ).join(", ");
        } else {
            document.getElementById("gui-emr-standard").value =
                "姓名, 性别, 年龄, 主诉, 现病史, 既往史, 过敏史, 体格检查, 辅助检查, 初步诊断, 处理";
            document.getElementById("gui-emr-required").value =
                "姓名, 性别, 年龄, 主诉, 过敏史, 初步诊断";
        }

        const ocrContainer = document.getElementById("ocr-gui-container");
        ocrContainer.innerHTML = "";
        const corrections = data.rules.corrections || {};
        for (let wrong in corrections) {
            ocrContainer.appendChild(createOcrRow(wrong, corrections[wrong]));
        }
    }
}

function buildDataFromGui() {
    const correctionsMap = {};
    document.querySelectorAll("#ocr-gui-container .row").forEach((row) => {
        const wrong = row.querySelector(".ocr-wrong").value.trim();
        const right = row.querySelector(".ocr-right").value.trim();
        if (wrong && right) correctionsMap[wrong] = right;
    });

    const cdssArr = [];
    document.querySelectorAll("#cdss-gui-container .card").forEach((card) => {
        const allergy = card.querySelector(".cdss-allergy").value.trim();
        const drugsStr = card.querySelector(".cdss-drugs").value;
        const warning = card.querySelector(".cdss-warning").value.trim();
        if (allergy && drugsStr)
            cdssArr.push({
                allergy: allergy,
                drugs: drugsStr
                    .split(",")
                    .map((s) => s.trim())
                    .filter((s) => s),
                warning: warning,
            });
    });

    return {
        device: document.getElementById("gui-device").value,
        threshold:
            parseFloat(document.getElementById("gui-threshold").value) || 0.0,
        enable_correction: document.getElementById("gui-enable-correction")
            .checked,
        section_patterns: document
            .getElementById("gui-sections")
            .value.split(",")
            .map((s) => s.trim())
            .filter((s) => s),
        negation_words: document
            .getElementById("gui-negation")
            .value.split(",")
            .map((s) => s.trim())
            .filter((s) => s),
        corrections: correctionsMap,
        cdss_rules: cdssArr,
        emr_structure: {
            standard_fields: document
                .getElementById("gui-emr-standard")
                .value.split(",")
                .map((s) => s.trim())
                .filter((s) => s),
            required_fields: document
                .getElementById("gui-emr-required")
                .value.split(",")
                .map((s) => s.trim())
                .filter((s) => s),
        },
    };
}

window.addOcrGuiRow = function () {
    document.getElementById("ocr-gui-container").prepend(createOcrRow("", ""));
};
function createOcrRow(wrong, right) {
    const div = document.createElement("div");
    div.className =
        "row mb-2 align-items-center bg-white p-2 rounded shadow-sm border mx-0";
    div.innerHTML = `<div class="col-5 px-1"><input type="text" class="form-control form-control-sm ocr-wrong" value="${escapeHtml(wrong)}" placeholder="错误片段"></div><div class="col-5 px-1"><input type="text" class="form-control form-control-sm text-primary fw-bold ocr-right" value="${escapeHtml(right)}" placeholder="覆盖为..."></div><div class="col-2 px-1 text-center"><button class="btn btn-sm btn-outline-danger border-0" onclick="this.closest('.row').remove()"><i class="bi bi-trash"></i></button></div>`;
    return div;
}

window.addCdssGuiCard = function () {
    document
        .getElementById("cdss-gui-container")
        .prepend(createCdssCard("", "", ""));
};
function createCdssCard(allergy, drugs, warning) {
    const div = document.createElement("div");
    div.className = "card border mb-3 shadow-sm";
    div.innerHTML = `<div class="card-header bg-white d-flex justify-content-between align-items-center py-2"><span class="fw-bold text-dark small"><i class="bi bi-diagram-2"></i> 规则簇节点</span><button class="btn btn-sm text-danger border-0 py-0" onclick="this.closest('.card').remove()"><i class="bi bi-x-circle-fill"></i></button></div><div class="card-body p-3 bg-light"><div class="row g-2 mb-2"><div class="col-6"><label class="form-label small text-muted mb-1">过敏原触发词</label><input type="text" class="form-control form-control-sm cdss-allergy" value="${escapeHtml(allergy)}" placeholder="如：青霉素过敏"></div><div class="col-6"><label class="form-label small text-muted mb-1">拦截药物群 (逗号分隔)</label><input type="text" class="form-control form-control-sm text-primary cdss-drugs" value="${escapeHtml(drugs)}" placeholder="如：阿莫西林, 青霉素G"></div></div><div><label class="form-label small text-muted mb-1">红色预警文案 (用 {drug} 代指触发词)</label><input type="text" class="form-control form-control-sm text-danger cdss-warning" value="${escapeHtml(warning)}" placeholder="⚠️ 致命拦截..."></div></div>`;
    return div;
}

window.saveSettingsConsole = function (btn) {
    const originalHtml = btn.innerHTML;
    btn.innerHTML =
        '<span class="spinner-border spinner-border-sm"></span> 烧录中...';
    btn.disabled = true;

    try {
        let finalPayload = {};
        if (isDevModeActive) {
            finalPayload = JSON.parse(
                document.getElementById("editor-raw-json").value,
            );
        } else {
            const guiData = buildDataFromGui();
            if (
                currentGlobalSettings.global_settings &&
                currentGlobalSettings.global_settings.system
            )
                currentGlobalSettings.global_settings.system.device =
                    guiData.device;
            if (currentGlobalSettings.model && currentGlobalSettings.model.ner)
                currentGlobalSettings.model.ner.inference_threshold =
                    guiData.threshold;
            if (
                currentGlobalSettings.rules &&
                currentGlobalSettings.rules.post_processing
            )
                currentGlobalSettings.rules.post_processing.enable_auto_correction =
                    guiData.enable_correction;
            if (
                currentGlobalSettings.rules &&
                currentGlobalSettings.rules.rules
            ) {
                currentGlobalSettings.rules.rules.section_patterns =
                    guiData.section_patterns;
                currentGlobalSettings.rules.rules.negation_words =
                    guiData.negation_words;
                currentGlobalSettings.rules.rules.cdss_rules =
                    guiData.cdss_rules;
            }
            if (currentGlobalSettings.rules) {
                currentGlobalSettings.rules.corrections = guiData.corrections;
                currentGlobalSettings.rules.emr_structure =
                    guiData.emr_structure;
            }
            finalPayload = currentGlobalSettings;
        }

        fetch("/api/settings/all", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(finalPayload),
        })
            .then((r) => r.json())
            .then((data) => {
                if (data.code === 200) {
                    const msg = document.getElementById("settings-save-msg");
                    msg.style.display = "inline-block";
                    setTimeout(() => (msg.style.display = "none"), 3000);
                } else {
                    alert("❌ 热重载失败: " + data.message);
                }
            })
            .catch((err) => alert("网络传输异常: " + err))
            .finally(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            });
    } catch (e) {
        alert("执行终止：底层 JSON 格式解析崩溃。\n明细: " + e.message);
        btn.innerHTML = originalHtml;
        btn.disabled = false;
    }
};

window.restoreFactorySettings = function () {
    if (
        !confirm(
            "⚠️ 高危操作确认：\n这将会清除您在此期间配置的所有自定义数据，并完全还原至出厂默认状态。\n\n确认执行吗？",
        )
    )
        return;

    fetch("/api/settings/restore", { method: "POST" })
        .then((r) => r.json())
        .then((data) => {
            if (data.code === 200) {
                alert(data.message);
                bootstrap.Modal.getInstance(
                    document.getElementById("settingsConsoleModal"),
                ).hide();
            } else {
                alert("恢复阻断: " + data.message);
            }
        })
        .catch((err) => alert("网络异常: " + err));
};
