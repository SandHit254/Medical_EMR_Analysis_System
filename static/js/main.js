/**
 * 模块名称：前端状态机与交互流转控制模块
 * 功能描述：负责前端 DOM 动态渲染、自适应坐标重组、微服务异步调度，
 * 以及基于 GUI 与 JSON 双向同步的全局参数控制中心。
 */

/**
 * 唤起全局防阻断加载遮罩。
 *
 * Args:
 * text (string): 遮罩层中显示的提示文案。
 */
function showLoading(text="神经引擎介入中...") { 
    document.getElementById('loading-text').innerText = text; 
    document.getElementById('loading-overlay').style.display = 'flex'; 
}

/**
 * 隐藏全局加载遮罩。
 */
function hideLoading() { 
    document.getElementById('loading-overlay').style.display = 'none'; 
}

/**
 * HTML 字符转义过滤。
 * 防御 XSS 注入，确保文本在渲染到 DOM 时标签闭合安全。
 *
 * Args:
 * text (string): 原始文本字符串。
 *
 * Returns:
 * string: 经过安全转义的纯文本。
 */
function escapeHtml(text) { 
    if (!text) return ""; 
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;"); 
}

/**
 * 核心渲染引擎：投影实体视图。
 *
 * 遍历全局状态机中的 EMR 文本数据与实体数据，通过绝对坐标进行文本切割，
 * 动态拼接出带有实体高亮标签、极性状态（删除线）的 HTML 字符串，并挂载至视图层。
 */
function renderEntityHighlights() {
    const context = window.SYSTEM_CONTEXT;
    if (!context || !context.emrData) return;
    const renderTarget = document.getElementById('highlight-render-target');
    if (!renderTarget) return;
    renderTarget.innerHTML = ''; 

    Object.keys(context.emrData).forEach(sectionName => {
        const rawText = context.emrData[sectionName];
        if (!rawText || rawText.trim() === '') return;
        
        // 过滤出当前段落的实体，并按起始坐标排序
        const sectionEntities = context.entitiesData.filter(ent => ent.section === sectionName || ent['所属段落'] === sectionName).sort((a, b) => a.start - b.start);
        let htmlStream = "";
        let cursor = 0;

        sectionEntities.forEach(ent => {
            if (ent.start >= cursor) {
                // 拼接实体前方的普通文本
                htmlStream += escapeHtml(rawText.substring(cursor, ent.start));
                const safeClass = ent.type.replace(/\//g, '_');
                
                // 处理极性逻辑样式
                const isNegative = ent.polarity === '阴性';
                const polarityStyle = isNegative ? 'opacity: 0.5; text-decoration: line-through;' : '';
                const polarityBadge = isNegative ? '<span style="color:#ef4444;font-size:0.6rem;margin-left:4px;">(排除)</span>' : '';

                htmlStream += `<span class="entity-box type-${safeClass}" style="${polarityStyle} cursor: pointer; border-radius: 4px; padding: 2px 4px; transition: 0.2s;" onclick="openEntityEditor('${escapeHtml(ent.text)}', ${ent.start}, '${sectionName}', '${ent.type}', '${ent.polarity}')"><span class="entity-text fw-bold">${escapeHtml(ent.text)}</span><span class="entity-label">${escapeHtml(ent.type)}${polarityBadge}</span></span>`;
                cursor = ent.end;
            }
        });
        
        // 拼接剩余普通文本
        htmlStream += escapeHtml(rawText.substring(cursor));

        const sectionWrapper = document.createElement('div');
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
}

/**
 * 触发微服务流转：临床决策支持系统 (CDSS) 动态校验。
 * 将当前文本库与实体树异步发送至后端，拦截命中用药禁忌的操作并触发高危红色预警。
 */
function triggerDynamicCDSS() {
    const fullText = Object.values(window.SYSTEM_CONTEXT.emrData).join(" ");
    fetch('/api/dynamic_cdss', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emr_text: fullText, entities: window.SYSTEM_CONTEXT.entitiesData })
    }).then(r => r.json()).then(data => {
        const container = document.getElementById('cdss-alert-container');
        if (data.code === 200 && data.warnings && data.warnings.length > 0) {
            let listHtml = data.warnings.map(w => `<li class="mb-1">${w}</li>`).join('');
            container.innerHTML = `<div class="alert shadow-sm border-0 mb-3 rounded" style="background-color: #fef2f2; border-left: 6px solid #ef4444 !important; animation: pulse-red 2s infinite;"><div class="d-flex align-items-center mb-2"><i class="bi bi-shield-fill-x text-danger fs-4 me-2"></i><h6 class="fw-bold text-danger m-0">临床决策支持系统 (CDSS) 实时预警</h6></div><ul class="mb-0 small text-danger fw-bold" style="list-style-type: square;">${listHtml}</ul></div>`;
        } else { container.innerHTML = ""; }
    });
}

/**
 * 开启原始文本复核模态框。
 *
 * Args:
 * sectionName (string): 触发段落名称。
 */
window.openOcrEditor = function(sectionName) {
    document.getElementById('edit-ocr-section').value = sectionName;
    document.getElementById('edit-ocr-content').value = window.SYSTEM_CONTEXT.emrData[sectionName] || "";
    new bootstrap.Modal(document.getElementById('editOcrTextModal')).show();
};

/**
 * 保存修改后的段落文本，并触发重组引擎。
 *
 * Args:
 * triggerNerReload (boolean): 若为 false，仅在前端内存中强行修正坐标漂移；
 * 若为 true，异步调用微服务进行大模型局部重推断。
 */
window.saveOcrText = function(triggerNerReload) {
    const section = document.getElementById('edit-ocr-section').value;
    const newText = document.getElementById('edit-ocr-content').value.trim();
    if (!newText) return alert("文本不能为空！");
    
    window.SYSTEM_CONTEXT.emrData[section] = newText;
    const formTextarea = document.querySelector(`textarea[name="${section}"]`);
    if (formTextarea) formTextarea.value = newText;

    if (!triggerNerReload) {
        let updatedEntities = [];
        window.SYSTEM_CONTEXT.entitiesData.forEach(ent => {
            if (ent.section === section || ent['所属段落'] === section) {
                const newStartIdx = newText.indexOf(ent.text);
                if (newStartIdx !== -1) { 
                    ent.start = newStartIdx; 
                    ent.end = newStartIdx + ent.text.length; 
                    updatedEntities.push(ent); 
                }
            } else { updatedEntities.push(ent); }
        });
        window.SYSTEM_CONTEXT.entitiesData = updatedEntities;
        renderEntityHighlights(); triggerDynamicCDSS();
        bootstrap.Modal.getInstance(document.getElementById('editOcrTextModal')).hide();
    } else {
        bootstrap.Modal.getInstance(document.getElementById('editOcrTextModal')).hide();
        showLoading("微服务流转中：局部 NER 推理重载...");
        fetch('/api/dynamic_ner', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ section: section, text: newText })})
        .then(r => r.json()).then(data => {
            hideLoading();
            if(data.code === 200) {
                window.SYSTEM_CONTEXT.entitiesData = window.SYSTEM_CONTEXT.entitiesData.filter(e => e.section !== section && e['所属段落'] !== section);
                window.SYSTEM_CONTEXT.entitiesData = window.SYSTEM_CONTEXT.entitiesData.concat(data.entities);
                renderEntityHighlights(); triggerDynamicCDSS();
            } else { alert("神经推理失败: " + data.message); }
        }).catch(err => { hideLoading(); alert("网络异常"); });
    }
};

/**
 * 唤醒实体属性编辑面板。
 */
window.openEntityEditor = function(text, start, section, type, polarity) {
    document.getElementById('edit-ent-text').value = text; document.getElementById('edit-ent-start').value = start; document.getElementById('edit-ent-section').value = section;
    document.getElementById('edit-display-text').innerText = text; document.getElementById('edit-ent-type').value = type; document.getElementById('edit-ent-polarity').value = polarity || '阳性';
    new bootstrap.Modal(document.getElementById('editEntityModal')).show();
};

/**
 * 执行实体的属性（类别/极性）修改并更新视图。
 */
window.updateEntity = function() {
    const text = document.getElementById('edit-ent-text').value; const start = parseInt(document.getElementById('edit-ent-start').value); const section = document.getElementById('edit-ent-section').value;
    const ent = window.SYSTEM_CONTEXT.entitiesData.find(e => e.text === text && e.start === start && (e.section === section || e['所属段落'] === section));
    if (ent) { 
        ent.type = document.getElementById('edit-ent-type').value; 
        ent.polarity = document.getElementById('edit-ent-polarity').value; 
        renderEntityHighlights(); triggerDynamicCDSS(); 
    }
    bootstrap.Modal.getInstance(document.getElementById('editEntityModal')).hide();
};

/**
 * 从全局状态树中彻底剔除选中实体。
 */
window.deleteEntity = function() {
    const text = document.getElementById('edit-ent-text').value; const start = parseInt(document.getElementById('edit-ent-start').value); const section = document.getElementById('edit-ent-section').value;
    const index = window.SYSTEM_CONTEXT.entitiesData.findIndex(e => e.text === text && e.start === start && (e.section === section || e['所属段落'] === section));
    if (index > -1) { window.SYSTEM_CONTEXT.entitiesData.splice(index, 1); renderEntityHighlights(); triggerDynamicCDSS(); }
    bootstrap.Modal.getInstance(document.getElementById('editEntityModal')).hide();
};

/* ====================================================================
 * 沉浸式悬浮舱监听 (Selection Bubble Observer)
 * ==================================================================== */
let currentSelectionText = "", currentSelectionSection = "";

document.addEventListener("DOMContentLoaded", function() {
    renderEntityHighlights();
    const renderTarget = document.getElementById('highlight-render-target'); 
    const bubble = document.getElementById('selection-bubble');
    if(renderTarget) {
        renderTarget.addEventListener('mouseup', function(e) {
            setTimeout(() => {
                const selection = window.getSelection(); const selectedText = selection.toString().trim();
                // 若选中有效文本范围，动态计算弹出位置
                if (selectedText.length > 0 && selectedText.length < 30) {
                    currentSelectionText = selectedText;
                    let targetNode = selection.anchorNode;
                    let sectionBlock = targetNode.nodeType === 3 ? targetNode.parentNode.closest('.section-block') : targetNode.closest('.section-block');
                    currentSelectionSection = sectionBlock ? sectionBlock.dataset.section : "";
                    const rect = selection.getRangeAt(0).getBoundingClientRect();
                    
                    bubble.style.display = 'flex'; bubble.style.visibility = 'hidden'; 
                    bubble.style.top = (rect.top + window.scrollY - bubble.offsetHeight - 8) + 'px';
                    bubble.style.left = (rect.left + window.scrollX + rect.width / 2 - bubble.offsetWidth / 2) + 'px';
                    bubble.style.visibility = 'visible';
                } else { bubble.style.display = 'none'; }
            }, 50);
        });
        document.addEventListener('selectionchange', () => { if(window.getSelection().toString().trim() === "") bubble.style.display = 'none'; });
    }
});

/**
 * 触发“人工注入新实体”表单装载。
 */
window.triggerAddEntity = function() {
    document.getElementById('add-ent-text').value = currentSelectionText; 
    const sectionSelect = document.getElementById('add-ent-section'); sectionSelect.innerHTML = '';
    Object.keys(window.SYSTEM_CONTEXT.emrData).forEach(sec => {
        const opt = document.createElement('option'); opt.value = sec; opt.innerText = sec;
        if (sec === currentSelectionSection) opt.selected = true; sectionSelect.appendChild(opt);
    });
    new bootstrap.Modal(document.getElementById('addEntityModal')).show(); 
    document.getElementById('selection-bubble').style.display = 'none';
};

/**
 * 计算绝对坐标并将新增实体写入全局数据树。
 */
window.saveNewEntity = function() {
    const text = document.getElementById('add-ent-text').value; const section = document.getElementById('add-ent-section').value;
    const rawText = window.SYSTEM_CONTEXT.emrData[section]; const startIdx = rawText.indexOf(text);
    if (startIdx === -1) return alert("无法定位文本坐标");
    
    window.SYSTEM_CONTEXT.entitiesData.push({ text: text, type: document.getElementById('add-ent-type').value, polarity: document.getElementById('add-ent-polarity').value, start: startIdx, end: startIdx + text.length, section: section, score: 1.0 });
    renderEntityHighlights(); triggerDynamicCDSS(); bootstrap.Modal.getInstance(document.getElementById('addEntityModal')).hide();
};

/**
 * 触发主动学习/数据飞轮的纠错表单。
 */
window.triggerOcrCorrection = function() {
    document.getElementById('ocr-wrong-word').value = currentSelectionText; document.getElementById('ocr-right-word').value = ''; 
    new bootstrap.Modal(document.getElementById('ocrCorrectionModal')).show(); document.getElementById('selection-bubble').style.display = 'none';
};

/**
 * 发送纠错指令至后端规则字典层。
 */
function submitOcrCorrection(event) {
    const btn = event.currentTarget; btn.disabled = true;
    fetch('/api/ocr/correct', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ wrong: document.getElementById('ocr-wrong-word').value, right: document.getElementById('ocr-right-word').value })
    }).then(r=>r.json()).then(data => {
        if(data.code===200) bootstrap.Modal.getInstance(document.getElementById('ocrCorrectionModal')).hide(); else alert("失败: "+data.message);
    }).finally(() => btn.disabled = false);
}

/**
 * 将人工复核干预后的最终数据对象封发落库。
 */
function executeArchiveProtocol() {
    fetch('/save_report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ "就诊编号": document.getElementById('meta-visit-id').innerText, "患者ID": document.getElementById('meta-patient-id').innerText, "操作行为": "基于微服务流转的最终确诊", "结构化病历": Object.fromEntries(new FormData(document.getElementById('emr-form'))), "提取实体": window.SYSTEM_CONTEXT.entitiesData })
    }).then(r=>r.json()).then(res => { document.getElementById('save-status-indicator').innerText = res.status === 'success' ? "归档成功" : "入库阻断"; });
}


/* ====================================================================
 * 双向同步配置中心与出厂设置引擎 (Global Settings Engine)
 * ==================================================================== */

let currentGlobalSettings = {};
let isDevModeActive = false;

/**
 * 侧边栏导航监听与 JSON 双向绑定拦截器。
 */
document.addEventListener('DOMContentLoaded', function() {
    const tabs = document.querySelectorAll('#settings-tabs button[data-bs-toggle="tab"]');
    const titleEl = document.getElementById('settings-title');
    
    tabs.forEach(tab => {
        tab.addEventListener('show.bs.tab', function (event) {
            const targetId = event.target.getAttribute('data-bs-target');
            const prevId = event.relatedTarget ? event.relatedTarget.getAttribute('data-bs-target') : null;

            // 拦截：从纯文本 JSON 模式切回 GUI
            if (prevId === '#set-dev') {
                try {
                    const parsedJson = JSON.parse(document.getElementById('editor-raw-json').value);
                    currentGlobalSettings = parsedJson; 
                    populateGuiFromData(currentGlobalSettings); 
                    isDevModeActive = false;
                } catch (e) {
                    alert("⚠️ 格式阻断：底层 JSON 语法有误。\n请修复后再切换视图！");
                    event.preventDefault(); return;
                }
            } 
            // 拦截：从 GUI 切入纯文本 JSON 模式
            else if (targetId === '#set-dev') {
                isDevModeActive = true;
                const guiData = buildDataFromGui();
                
                if(currentGlobalSettings.global_settings && currentGlobalSettings.global_settings.system) currentGlobalSettings.global_settings.system.device = guiData.device;
                if(currentGlobalSettings.model && currentGlobalSettings.model.ner) currentGlobalSettings.model.ner.inference_threshold = guiData.threshold;
                if(currentGlobalSettings.rules && currentGlobalSettings.rules.post_processing) currentGlobalSettings.rules.post_processing.enable_auto_correction = guiData.enable_correction;
                if(currentGlobalSettings.rules && currentGlobalSettings.rules.rules) {
                    currentGlobalSettings.rules.rules.section_patterns = guiData.section_patterns;
                    currentGlobalSettings.rules.rules.negation_words = guiData.negation_words;
                    currentGlobalSettings.rules.rules.cdss_rules = guiData.cdss_rules;
                }
                if(currentGlobalSettings.rules) currentGlobalSettings.rules.corrections = guiData.corrections;

                document.getElementById('editor-raw-json').value = JSON.stringify(currentGlobalSettings, null, 4);
                titleEl.innerText = "开发者底层核心"; return;
            }
            titleEl.innerText = event.target.innerText.trim();
        });
    });
});

/**
 * 打开设置面板并拉取最新聚合配置。
 */
window.openSettingsConsole = function() {
    fetch('/api/settings/all')
        .then(response => response.json())
        .then(res => {
            if (res.code === 200) {
                currentGlobalSettings = res.data;
                populateGuiFromData(currentGlobalSettings);
                
                const firstTab = new bootstrap.Tab(document.querySelector('#settings-tabs button[data-bs-target="#set-general"]'));
                firstTab.show();
                new bootstrap.Modal(document.getElementById('settingsConsoleModal')).show();
            } else { alert("拉取配置失败: " + res.message); }
        }).catch(err => alert("网络异常: " + err));
};

/**
 * 将获取到的 JSON 数据反序列化至前端各个 GUI 控制组件。
 *
 * Args:
 * data (object): 全局三文件聚合配置字典。
 */
function populateGuiFromData(data) {
    if (data.global_settings && data.global_settings.system) {
        document.getElementById('gui-device').value = data.global_settings.system.device || 'cpu';
    }
    if (data.model && data.model.ner) {
        document.getElementById('gui-threshold').value = data.model.ner.inference_threshold || 0.0;
    }
    if (data.rules) {
        if (data.rules.post_processing) {
            document.getElementById('gui-enable-correction').checked = data.rules.post_processing.enable_auto_correction !== false;
        }
        if (data.rules.rules) {
            document.getElementById('gui-sections').value = (data.rules.rules.section_patterns || []).join(', ');
            document.getElementById('gui-negation').value = (data.rules.rules.negation_words || []).join(', ');
            
            const cdssContainer = document.getElementById('cdss-gui-container');
            cdssContainer.innerHTML = '';
            (data.rules.rules.cdss_rules || []).forEach(rule => {
                cdssContainer.appendChild(createCdssCard(rule.allergy, (rule.drugs||[]).join(', '), rule.warning));
            });
        }
        
        const ocrContainer = document.getElementById('ocr-gui-container');
        ocrContainer.innerHTML = '';
        const corrections = data.rules.corrections || {};
        for (let wrong in corrections) { ocrContainer.appendChild(createOcrRow(wrong, corrections[wrong])); }
    }
}

/**
 * 遍历提取 GUI 列表数据并逆向拼装。
 *
 * Returns:
 * object: 图形视图上展现的数据切片合集。
 */
function buildDataFromGui() {
    const correctionsMap = {};
    document.querySelectorAll('#ocr-gui-container .row').forEach(row => {
        const wrong = row.querySelector('.ocr-wrong').value.trim(); const right = row.querySelector('.ocr-right').value.trim();
        if (wrong && right) correctionsMap[wrong] = right;
    });

    const cdssArr = [];
    document.querySelectorAll('#cdss-gui-container .card').forEach(card => {
        const allergy = card.querySelector('.cdss-allergy').value.trim(); const drugsStr = card.querySelector('.cdss-drugs').value; const warning = card.querySelector('.cdss-warning').value.trim();
        if (allergy && drugsStr) cdssArr.push({ allergy: allergy, drugs: drugsStr.split(',').map(s=>s.trim()).filter(s=>s), warning: warning });
    });

    return {
        device: document.getElementById('gui-device').value,
        threshold: parseFloat(document.getElementById('gui-threshold').value) || 0.0,
        enable_correction: document.getElementById('gui-enable-correction').checked,
        section_patterns: document.getElementById('gui-sections').value.split(',').map(s=>s.trim()).filter(s=>s),
        negation_words: document.getElementById('gui-negation').value.split(',').map(s=>s.trim()).filter(s=>s),
        corrections: correctionsMap,
        cdss_rules: cdssArr
    };
}

/**
 * 创建一行 OCR 字典编辑卡片。
 */
window.addOcrGuiRow = function() { document.getElementById('ocr-gui-container').prepend(createOcrRow('', '')); };
function createOcrRow(wrong, right) {
    const div = document.createElement('div'); div.className = "row mb-2 align-items-center bg-white p-2 rounded shadow-sm border mx-0";
    div.innerHTML = `<div class="col-5 px-1"><input type="text" class="form-control form-control-sm ocr-wrong" value="${escapeHtml(wrong)}" placeholder="错误片段"></div><div class="col-5 px-1"><input type="text" class="form-control form-control-sm text-primary fw-bold ocr-right" value="${escapeHtml(right)}" placeholder="覆盖为..."></div><div class="col-2 px-1 text-center"><button class="btn btn-sm btn-outline-danger border-0" onclick="this.closest('.row').remove()"><i class="bi bi-trash"></i></button></div>`; return div;
}

/**
 * 创建一张 CDSS 规则注入卡片。
 */
window.addCdssGuiCard = function() { document.getElementById('cdss-gui-container').prepend(createCdssCard('', '', '')); };
function createCdssCard(allergy, drugs, warning) {
    const div = document.createElement('div'); div.className = "card border mb-3 shadow-sm";
    div.innerHTML = `<div class="card-header bg-white d-flex justify-content-between align-items-center py-2"><span class="fw-bold text-dark small"><i class="bi bi-diagram-2"></i> 规则簇节点</span><button class="btn btn-sm text-danger border-0 py-0" onclick="this.closest('.card').remove()"><i class="bi bi-x-circle-fill"></i></button></div><div class="card-body p-3 bg-light"><div class="row g-2 mb-2"><div class="col-6"><label class="form-label small text-muted mb-1">过敏原触发词</label><input type="text" class="form-control form-control-sm cdss-allergy" value="${escapeHtml(allergy)}" placeholder="如：青霉素过敏"></div><div class="col-6"><label class="form-label small text-muted mb-1">拦截药物群 (逗号分隔)</label><input type="text" class="form-control form-control-sm text-primary cdss-drugs" value="${escapeHtml(drugs)}" placeholder="如：阿莫西林, 青霉素G"></div></div><div><label class="form-label small text-muted mb-1">红色预警文案 (用 {drug} 代指触发词)</label><input type="text" class="form-control form-control-sm text-danger cdss-warning" value="${escapeHtml(warning)}" placeholder="⚠️ 致命拦截..."></div></div>`; return div;
}

/**
 * 发送全量参数保存请求以触发底层热重载引擎。
 */
window.saveSettingsConsole = function(btn) {
    const originalHtml = btn.innerHTML; btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 烧录中...'; btn.disabled = true;

    try {
        let finalPayload = {};
        if (isDevModeActive) {
            finalPayload = JSON.parse(document.getElementById('editor-raw-json').value);
        } else {
            const guiData = buildDataFromGui();
            if(currentGlobalSettings.global_settings && currentGlobalSettings.global_settings.system) currentGlobalSettings.global_settings.system.device = guiData.device;
            if(currentGlobalSettings.model && currentGlobalSettings.model.ner) currentGlobalSettings.model.ner.inference_threshold = guiData.threshold;
            if(currentGlobalSettings.rules && currentGlobalSettings.rules.post_processing) currentGlobalSettings.rules.post_processing.enable_auto_correction = guiData.enable_correction;
            if(currentGlobalSettings.rules && currentGlobalSettings.rules.rules) {
                currentGlobalSettings.rules.rules.section_patterns = guiData.section_patterns;
                currentGlobalSettings.rules.rules.negation_words = guiData.negation_words;
                currentGlobalSettings.rules.rules.cdss_rules = guiData.cdss_rules;
            }
            if(currentGlobalSettings.rules) currentGlobalSettings.rules.corrections = guiData.corrections;
            finalPayload = currentGlobalSettings;
        }

        fetch('/api/settings/all', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(finalPayload)
        }).then(r => r.json()).then(data => {
            if (data.code === 200) {
                const msg = document.getElementById('settings-save-msg');
                msg.style.display = 'inline-block'; setTimeout(() => msg.style.display = 'none', 3000);
            } else { alert("❌ 热重载失败: " + data.message); }
        }).catch(err => alert("网络传输异常: " + err)).finally(() => { btn.innerHTML = originalHtml; btn.disabled = false; });
    } catch (e) { alert("执行终止：底层 JSON 格式解析崩溃。\n明细: " + e.message); btn.innerHTML = originalHtml; btn.disabled = false; }
};

/**
 * 唤起恢复出厂设置微服务。
 */
window.restoreFactorySettings = function() {
    if (!confirm("⚠️ 高危操作确认：\n这将会清除您在此期间配置的所有自定义数据，并完全还原至出厂默认状态。\n\n确认执行吗？")) return;
    fetch('/api/settings/restore', { method: 'POST' }).then(r => r.json()).then(data => {
        if (data.code === 200) { alert(data.message); bootstrap.Modal.getInstance(document.getElementById('settingsConsoleModal')).hide(); } 
        else { alert("恢复阻断: " + data.message); }
    }).catch(err => alert("网络异常: " + err));
};