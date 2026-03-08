function showLoading(text="神经引擎介入中...") {
    document.getElementById('loading-text').innerText = text;
    document.getElementById('loading-overlay').style.display = 'flex';
}
function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
}

function escapeHtml(text) {
    if (!text) return "";
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function renderEntityHighlights() {
    const context = window.SYSTEM_CONTEXT;
    if (!context || !context.emrData) return;
    const renderTarget = document.getElementById('highlight-render-target');
    if (!renderTarget) return;
    renderTarget.innerHTML = ''; 

    Object.keys(context.emrData).forEach(sectionName => {
        const rawText = context.emrData[sectionName];
        if (!rawText || rawText.trim() === '') return;
        const sectionEntities = context.entitiesData.filter(ent => ent.section === sectionName || ent['所属段落'] === sectionName).sort((a, b) => a.start - b.start);
        let htmlStream = "";
        let cursor = 0;

        sectionEntities.forEach(ent => {
            if (ent.start >= cursor) {
                htmlStream += escapeHtml(rawText.substring(cursor, ent.start));
                const safeClass = ent.type.replace(/\//g, '_');
                const isNegative = ent.polarity === '阴性';
                const polarityStyle = isNegative ? 'opacity: 0.5; text-decoration: line-through;' : '';
                const polarityBadge = isNegative ? '<span style="color:#ef4444;font-size:0.6rem;margin-left:4px;">(排除)</span>' : '';

                htmlStream += `<span class="entity-box type-${safeClass}" style="${polarityStyle} cursor: pointer; border-radius: 4px; padding: 2px 4px; transition: 0.2s;" onclick="openEntityEditor('${escapeHtml(ent.text)}', ${ent.start}, '${sectionName}', '${ent.type}', '${ent.polarity}')"><span class="entity-text fw-bold">${escapeHtml(ent.text)}</span><span class="entity-label">${escapeHtml(ent.type)}${polarityBadge}</span></span>`;
                cursor = ent.end;
            }
        });
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

// =========================================================================
// 【核心节点 1】触发 CDSS 动态校验
// =========================================================================
function triggerDynamicCDSS() {
    const fullText = Object.values(window.SYSTEM_CONTEXT.emrData).join(" ");
    fetch('/api/dynamic_cdss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emr_text: fullText, entities: window.SYSTEM_CONTEXT.entitiesData })
    })
    .then(r => r.json())
    .then(data => {
        const container = document.getElementById('cdss-alert-container');
        if (data.code === 200 && data.warnings && data.warnings.length > 0) {
            let listHtml = data.warnings.map(w => `<li class="mb-1">${w}</li>`).join('');
            container.innerHTML = `
                <div class="alert shadow-sm border-0 mb-3 rounded" style="background-color: #fef2f2; border-left: 6px solid #ef4444 !important; animation: pulse-red 2s infinite;">
                    <div class="d-flex align-items-center mb-2"><i class="bi bi-shield-fill-x text-danger fs-4 me-2"></i><h6 class="fw-bold text-danger m-0">临床决策支持系统 (CDSS) 实时预警</h6></div>
                    <ul class="mb-0 small text-danger fw-bold" style="list-style-type: square;">${listHtml}</ul>
                </div>`;
        } else {
            container.innerHTML = ""; // 无警报则清空
        }
    });
}

// =========================================================================
// 【核心节点 2】触发局部 NER 重载
// =========================================================================
window.openOcrEditor = function(sectionName) {
    document.getElementById('edit-ocr-section').value = sectionName;
    document.getElementById('edit-ocr-content').value = window.SYSTEM_CONTEXT.emrData[sectionName] || "";
    new bootstrap.Modal(document.getElementById('editOcrTextModal')).show();
};

window.saveOcrText = function(triggerNerReload) {
    const section = document.getElementById('edit-ocr-section').value;
    const newText = document.getElementById('edit-ocr-content').value.trim();
    if (!newText) return alert("文本不能为空！");

    window.SYSTEM_CONTEXT.emrData[section] = newText;
    const formTextarea = document.querySelector(`textarea[name="${section}"]`);
    if (formTextarea) formTextarea.value = newText;

    if (!triggerNerReload) {
        // 模式 A: 仅自适应坐标
        let updatedEntities = [];
        window.SYSTEM_CONTEXT.entitiesData.forEach(ent => {
            if (ent.section === section || ent['所属段落'] === section) {
                const newStartIdx = newText.indexOf(ent.text);
                if (newStartIdx !== -1) {
                    ent.start = newStartIdx; ent.end = newStartIdx + ent.text.length;
                    updatedEntities.push(ent);
                }
            } else { updatedEntities.push(ent); }
        });
        window.SYSTEM_CONTEXT.entitiesData = updatedEntities;
        renderEntityHighlights();
        triggerDynamicCDSS();
        bootstrap.Modal.getInstance(document.getElementById('editOcrTextModal')).hide();
    } else {
        // 模式 B: 调用后端局部 NER 微服务
        bootstrap.Modal.getInstance(document.getElementById('editOcrTextModal')).hide();
        showLoading("微服务流转中：局部 NER 推理重载...");
        fetch('/api/dynamic_ner', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ section: section, text: newText })
        })
        .then(r => r.json())
        .then(data => {
            hideLoading();
            if(data.code === 200) {
                // 清除该段落旧实体，注入新实体
                window.SYSTEM_CONTEXT.entitiesData = window.SYSTEM_CONTEXT.entitiesData.filter(e => e.section !== section && e['所属段落'] !== section);
                window.SYSTEM_CONTEXT.entitiesData = window.SYSTEM_CONTEXT.entitiesData.concat(data.entities);
                renderEntityHighlights();
                triggerDynamicCDSS();
            } else { alert("神经推理失败: " + data.message); }
        })
        .catch(err => { hideLoading(); alert("网络异常"); });
    }
};

// 实体干预操作（结束后自动触发 CDSS 检验）
window.openEntityEditor = function(text, start, section, type, polarity) {
    document.getElementById('edit-ent-text').value = text;
    document.getElementById('edit-ent-start').value = start;
    document.getElementById('edit-ent-section').value = section;
    document.getElementById('edit-display-text').innerText = text;
    document.getElementById('edit-ent-type').value = type;
    document.getElementById('edit-ent-polarity').value = polarity || '阳性';
    new bootstrap.Modal(document.getElementById('editEntityModal')).show();
};
window.updateEntity = function() {
    const text = document.getElementById('edit-ent-text').value;
    const start = parseInt(document.getElementById('edit-ent-start').value);
    const section = document.getElementById('edit-ent-section').value;
    const ent = window.SYSTEM_CONTEXT.entitiesData.find(e => e.text === text && e.start === start && (e.section === section || e['所属段落'] === section));
    if (ent) {
        ent.type = document.getElementById('edit-ent-type').value;
        ent.polarity = document.getElementById('edit-ent-polarity').value;
        renderEntityHighlights();
        triggerDynamicCDSS(); // 【触发流转】
    }
    bootstrap.Modal.getInstance(document.getElementById('editEntityModal')).hide();
};
window.deleteEntity = function() {
    const text = document.getElementById('edit-ent-text').value;
    const start = parseInt(document.getElementById('edit-ent-start').value);
    const section = document.getElementById('edit-ent-section').value;
    const index = window.SYSTEM_CONTEXT.entitiesData.findIndex(e => e.text === text && e.start === start && (e.section === section || e['所属段落'] === section));
    if (index > -1) {
        window.SYSTEM_CONTEXT.entitiesData.splice(index, 1);
        renderEntityHighlights();
        triggerDynamicCDSS(); // 【触发流转】
    }
    bootstrap.Modal.getInstance(document.getElementById('editEntityModal')).hide();
};

window.triggerAddEntity = function() {
    document.getElementById('add-ent-text').value = currentSelectionText;
    const sectionSelect = document.getElementById('add-ent-section');
    sectionSelect.innerHTML = '';
    Object.keys(window.SYSTEM_CONTEXT.emrData).forEach(sec => {
        const opt = document.createElement('option'); opt.value = sec; opt.innerText = sec;
        if (sec === currentSelectionSection) opt.selected = true;
        sectionSelect.appendChild(opt);
    });
    new bootstrap.Modal(document.getElementById('addEntityModal')).show();
    document.getElementById('selection-bubble').style.display = 'none';
};

window.saveNewEntity = function() {
    const text = document.getElementById('add-ent-text').value;
    const section = document.getElementById('add-ent-section').value;
    const rawText = window.SYSTEM_CONTEXT.emrData[section];
    const startIdx = rawText.indexOf(text);
    if (startIdx === -1) return alert("无法定位文本坐标");
    
    window.SYSTEM_CONTEXT.entitiesData.push({
        text: text, type: document.getElementById('add-ent-type').value, polarity: document.getElementById('add-ent-polarity').value,
        start: startIdx, end: startIdx + text.length, section: section, score: 1.0 
    });
    renderEntityHighlights();
    triggerDynamicCDSS(); // 【触发流转】
    bootstrap.Modal.getInstance(document.getElementById('addEntityModal')).hide();
};

// 悬浮舱逻辑保持不变...
let currentSelectionText = "", currentSelectionSection = "";
document.addEventListener("DOMContentLoaded", function() {
    renderEntityHighlights();
    const renderTarget = document.getElementById('highlight-render-target');
    const bubble = document.getElementById('selection-bubble');
    if(renderTarget) {
        renderTarget.addEventListener('mouseup', function(e) {
            setTimeout(() => {
                const selection = window.getSelection();
                const selectedText = selection.toString().trim();
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

window.triggerOcrCorrection = function() {
    document.getElementById('ocr-wrong-word').value = currentSelectionText;
    document.getElementById('ocr-right-word').value = ''; 
    new bootstrap.Modal(document.getElementById('ocrCorrectionModal')).show();
    document.getElementById('selection-bubble').style.display = 'none';
};

function submitOcrCorrection(event) {
    const btn = event.currentTarget; btn.disabled = true;
    fetch('/api/ocr/correct', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wrong: document.getElementById('ocr-wrong-word').value, right: document.getElementById('ocr-right-word').value })
    }).then(r=>r.json()).then(data => {
        if(data.code===200) bootstrap.Modal.getInstance(document.getElementById('ocrCorrectionModal')).hide();
        else alert("失败: "+data.message);
    }).finally(() => btn.disabled = false);
}

function executeArchiveProtocol() {
    fetch('/save_report', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            "就诊编号": document.getElementById('meta-visit-id').innerText,
            "患者ID": document.getElementById('meta-patient-id').innerText,
            "操作行为": "基于微服务流转的最终确诊",
            "结构化病历": Object.fromEntries(new FormData(document.getElementById('emr-form'))),
            "提取实体": window.SYSTEM_CONTEXT.entitiesData 
        })
    }).then(r=>r.json()).then(res => {
        document.getElementById('save-status-indicator').innerText = res.status === 'success' ? "归档成功" : "入库阻断";
    });
}