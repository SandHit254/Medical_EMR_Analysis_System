/* * 文件名称：main.js
 * 功能描述：医疗工作站前端业务逻辑控制模块
 * 包含 DOM 动态渲染、表单序列化及异步持久化请求下发
 */

function showLoading() {
    document.getElementById('loading-overlay').style.display = 'flex';
}

function escapeHtml(text) {
    return text.replace(/&/g, "&amp;")
               .replace(/</g, "&lt;")
               .replace(/>/g, "&gt;")
               .replace(/"/g, "&quot;")
               .replace(/'/g, "&#039;");
}

function renderEntityHighlights() {
    const context = window.SYSTEM_CONTEXT;
    if (!context || !context.emrData) return;

    const emrData = context.emrData;
    const entitiesData = context.entitiesData;
    const renderTarget = document.getElementById('highlight-render-target');
    
    if (!renderTarget) return;

    Object.keys(emrData).forEach(sectionName => {
        const rawText = emrData[sectionName];
        if (!rawText || rawText.trim() === '') return;

        const sectionEntities = entitiesData
            .filter(ent => ent['所属段落'] === sectionName)
            .sort((a, b) => a.start - b.start);

        let htmlStream = "";
        let cursor = 0;

        sectionEntities.forEach(ent => {
            if (ent.start >= cursor) {
                htmlStream += escapeHtml(rawText.substring(cursor, ent.start));
                const safeClass = ent.type.replace(/\//g, '_');
                const scoreDisplay = ent.score ? ent.score.toFixed(3) : 'N/A';
                
                htmlStream += `
                    <span class="entity-box type-${safeClass}" title="置信度: ${scoreDisplay}">
                        <span class="entity-text">${escapeHtml(ent.text)}</span>
                        <span class="entity-label">${escapeHtml(ent.type)}</span>
                    </span>`;
                cursor = ent.end;
            }
        });
        htmlStream += escapeHtml(rawText.substring(cursor));

        const sectionWrapper = document.createElement('div');
        sectionWrapper.className = "mb-4";
        sectionWrapper.innerHTML = `
            <div class="fw-bold text-muted mb-1 small text-uppercase tracking-wide">
                <i class="bi bi-record-circle-fill text-primary" style="font-size: 0.6rem; vertical-align: middle; margin-right: 4px;"></i> ${sectionName}
            </div>
            <div class="text-dark bg-light p-3 rounded" style="border: 1px solid #f0f0f5;">${htmlStream}</div>
        `;
        renderTarget.appendChild(sectionWrapper);
    });
}

function injectNewDiagnosisRow() {
    const tbody = document.querySelector('#diagnosis-table tbody');
    const newRow = document.createElement('tr');
    newRow.innerHTML = `
        <td><input type="text" class="form-control form-control-sm border-0 bg-transparent" placeholder="录入结论参数"></td>
        <td><input type="text" class="form-control form-control-sm border-0 bg-transparent" placeholder="关联关系"></td>
        <td><input type="text" class="form-control form-control-sm border-0 bg-transparent" placeholder="锚点段落"></td>
        <td class="text-center">
            <button type="button" class="btn btn-sm text-danger border-0" onclick="removeDiagnosisRow(this)"><i class="bi bi-trash"></i></button>
        </td>
    `;
    tbody.appendChild(newRow);
    newRow.style.opacity = 0;
    setTimeout(() => newRow.style.opacity = 1, 50);
    newRow.style.transition = "opacity 0.3s ease";
}

function removeDiagnosisRow(btn) {
    const row = btn.closest('tr');
    row.style.opacity = 0;
    setTimeout(() => row.remove(), 300);
}

function executeArchiveProtocol() {
    const statusIndicator = document.getElementById('save-status-indicator');
    const spinner = document.getElementById('save-spinner');
    
    statusIndicator.innerText = "数据封装与同步中...";
    statusIndicator.className = "text-primary small fw-bold";
    spinner.style.display = "inline-block";

    const visitId = document.getElementById('meta-visit-id').innerText;
    const patientId = document.getElementById('meta-patient-id').innerText;

    const emrPayload = {};
    const formElements = new FormData(document.getElementById('emr-form'));
    for (let [key, val] of formElements.entries()) {
        emrPayload[key] = val;
    }

    const diagnosisPayload = [];
    const tableRows = document.querySelectorAll('#diagnosis-table tbody tr');
    tableRows.forEach(row => {
        const inputs = row.querySelectorAll('input');
        if (inputs[0].value.trim() !== '') {
            diagnosisPayload.push({
                "临床结论": inputs[0].value.trim(),
                "逻辑类型": inputs[1].value.trim(),
                "来源段落": inputs[2].value.trim()
            });
        }
    });

    const finalDataPackage = {
        "就诊编号": visitId,
        "患者ID": patientId,
        "操作行为": "基于 05 文件的人工覆盖更新",
        "归档状态": "人工复核认证通过",
        "结构化病历": emrPayload,
        "智能诊断核心问题": diagnosisPayload,
        "提取实体": window.SYSTEM_CONTEXT.entitiesData 
    };

    fetch('/save_report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(finalDataPackage)
    })
    .then(response => response.json())
    .then(res => {
        spinner.style.display = "none";
        if (res.status === 'success') {
            statusIndicator.innerHTML = '<i class="bi bi-check-circle-fill text-success"></i> 归档成功：已生成 06_human_verified 最终确诊文件';
            statusIndicator.className = "text-success small fw-bold";
        } else {
            statusIndicator.innerText = "入库阻断: " + res.message;
            statusIndicator.className = "text-danger small fw-bold";
        }
    })
    .catch(err => {
        spinner.style.display = "none";
        statusIndicator.innerText = "网络链路异常";
        statusIndicator.className = "text-danger small fw-bold";
    });
}

// =========================================================================
// 主动学习模块 (Active Learning & Data Flywheel)
// =========================================================================

/**
 * 序列化纠错参数，向下发网络请求并触发底层系统热重载
 */
function submitOcrCorrection(event) {
    const wrongWord = document.getElementById('ocr-wrong-word').value.trim();
    const rightWord = document.getElementById('ocr-right-word').value.trim();

    if (!wrongWord || !rightWord) {
        alert("系统拦截：错词与正词对照不能为空。");
        return;
    }

    const btn = event.currentTarget;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> 底层库同步中...';
    btn.disabled = true;

    fetch('/api/ocr/correct', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wrong: wrongWord, right: rightWord })
    })
    .then(response => response.json())
    .then(data => {
        if (data.code === 200) {
            alert('✅ 规则反哺成功！\n系统级提醒：底层 ConfigManager 已完成内存热重载，该规则将在下一次任务中立刻生效。');
            
            document.getElementById('ocr-wrong-word').value = '';
            document.getElementById('ocr-right-word').value = '';
            
            // 安全关闭模态框
            const modalElement = document.getElementById('ocrCorrectionModal');
            const modalInstance = bootstrap.Modal.getInstance(modalElement);
            if(modalInstance) {
                modalInstance.hide();
            }
        } else {
            alert('❌ 知识库同步失败: ' + data.message);
        }
    })
    .catch(err => {
        alert('网络传输层错误: ' + err);
    })
    .finally(() => {
        btn.innerHTML = originalText;
        btn.disabled = false;
    });
}

// 初始化
document.addEventListener("DOMContentLoaded", function() {
    renderEntityHighlights();
});