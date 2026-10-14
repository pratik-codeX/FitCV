import re
import os

with open('templates/index.html', 'r') as f:
    html = f.read()

approval_html = """
            <!-- STATE 2.5: APPROVAL -->
            <div id="state-approval" class="state-container">
                <div class="result-header">
                    <h2>Project Selection Approval</h2>
                    <p class="subtitle" style="color:var(--muted); font-size:13px;">Review coverage and select projects.</p>
                </div>
                
                <div class="approval-dashboard" style="margin-top: 20px;">
                    <div class="intel-grid">
                        <div class="intel-card">
                            <div class="ic-label">Role Match Analysis</div>
                            <div id="approval-coverage" class="ic-value" style="display:flex; flex-direction:column; gap:4px;">
                            </div>
                        </div>
                        <div class="intel-card">
                            <div class="ic-label">Missing Requirements</div>
                            <div id="approval-missing-kws" class="ic-tags" style="margin-bottom:8px;"></div>
                            <div id="approval-missing-cats" class="ic-tags"></div>
                        </div>
                    </div>
                    
                    <div style="margin-top: 20px;">
                        <div class="ic-label" style="margin-bottom: 10px;">Recommended Projects</div>
                        <div id="approval-recommended" style="display:flex; flex-direction:column; gap:8px;"></div>
                    </div>
                    
                    <div style="margin-top: 20px;">
                        <div class="ic-label" style="margin-bottom: 10px;">Alternative Projects</div>
                        <div id="approval-alternatives" style="display:flex; flex-direction:column; gap:8px;"></div>
                    </div>
                    
                    <div style="margin-top: 30px; display:flex; gap:10px;">
                        <button id="btn-approve" class="btn-primary">
                            Confirm & Generate Resume
                        </button>
                    </div>
                </div>
            </div>
"""

html = html.replace('<!-- STATE 3: RESULT -->', approval_html + '\n            <!-- STATE 3: RESULT -->')

with open('templates/index.html', 'w') as f:
    f.write(html)


with open('static/js/app.js', 'r') as f:
    js = f.read()

# Replace the states object to include approval
js = js.replace("result: document.getElementById('state-result'),", "approval: document.getElementById('state-approval'),\n        result: document.getElementById('state-result'),")

# Add variables for new UI elements
js = js.replace("// Result", """// Approval
    btnApprove: document.getElementById('btn-approve'),
    approvalCoverage: document.getElementById('approval-coverage'),
    approvalMissingKws: document.getElementById('approval-missing-kws'),
    approvalMissingCats: document.getElementById('approval-missing-cats'),
    approvalRecommended: document.getElementById('approval-recommended'),
    approvalAlternatives: document.getElementById('approval-alternatives'),

    // Result""")

# Replace form submit listener with the new two-step process
new_submit = """
let analyzeData = null;

UI.form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const payload = {
        api_key: UI.fKey.value.trim(),
        company: document.getElementById('f-company').value.trim(),
        role: document.getElementById('f-role').value.trim(),
        role_type: document.getElementById('f-type').value,
        jd: UI.jdInput.value.trim(),
        relocation: UI.fRelocation ? UI.fRelocation.value.trim() : ''
    };

    UI.btnGen.disabled = true;
    UI.statusDot.className = 'status-dot active';
    UI.statusText.textContent = 'Analyzing JD...';
    showState('loading');

    updatePipe(1, 'active');
    updatePipe(2, 'idle'); updatePipe(3, 'idle'); updatePipe(4, 'idle');
    UI.loadMsg.textContent = 'Extracting keywords & ranking projects...';

    try {
        const resp = await fetch('/api/analyze-job', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await resp.json();

        if (!resp.ok) {
            throw new Error(data.error || "Analysis failed");
        }

        analyzeData = data;
        analyzeData.payload = payload; // save for next step
        
        updatePipe(1, 'done');
        renderApproval(data);
        showState('approval');
        UI.statusDot.className = 'status-dot';
        UI.statusText.textContent = 'Awaiting Approval';
        UI.btnGen.disabled = false;

    } catch (err) {
        UI.errorMsg.textContent = err.message;
        showState('error');
        UI.statusDot.className = 'status-dot error';
        UI.statusText.textContent = 'Error';
        UI.btnGen.disabled = false;
    }
});

function createProjectCheckbox(p, isRecommended) {
    const div = document.createElement('div');
    div.style.padding = '10px';
    div.style.background = 'var(--bg2)';
    div.style.borderRadius = '6px';
    div.style.display = 'flex';
    div.style.alignItems = 'flex-start';
    div.style.gap = '10px';
    
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = p.id;
    cb.className = 'proj-cb';
    if (isRecommended) cb.checked = true;
    
    const textDiv = document.createElement('div');
    textDiv.innerHTML = `<strong style="color:var(--text); font-size:14px;">${p.name}</strong> <span style="color:var(--green); font-size:12px;">(Score: ${p.score})</span><br>
                         <span style="color:var(--muted); font-size:11px;">${p.reasons.join(' | ')}</span>`;
                         
    div.appendChild(cb);
    div.appendChild(textDiv);
    return div;
}

function renderApproval(data) {
    UI.approvalCoverage.innerHTML = '';
    for (const [cat, val] of Object.entries(data.coverage || {})) {
        UI.approvalCoverage.innerHTML += `<div><strong style="text-transform:capitalize;">${cat}:</strong> ${val}%</div>`;
    }
    
    UI.approvalMissingKws.innerHTML = '';
    (data.missing_keywords || []).forEach(kw => {
        UI.approvalMissingKws.innerHTML += `<span class="ic-tag bad" style="background:#2e1a1a; color:#eb5757;">${kw}</span>`;
    });
    
    UI.approvalMissingCats.innerHTML = '';
    (data.missing_categories || []).forEach(cat => {
        UI.approvalMissingCats.innerHTML += `<span class="ic-tag value" style="background:#2a1a3e; color:#b39ddb;">Misses ${cat}</span>`;
    });
    
    UI.approvalRecommended.innerHTML = '';
    (data.recommended_projects || []).forEach(p => {
        UI.approvalRecommended.appendChild(createProjectCheckbox(p, true));
    });
    
    UI.approvalAlternatives.innerHTML = '';
    (data.alternative_projects || []).forEach(p => {
        UI.approvalAlternatives.appendChild(createProjectCheckbox(p, false));
    });
}

UI.btnApprove.addEventListener('click', async () => {
    const checkboxes = document.querySelectorAll('.proj-cb:checked');
    const selectedIds = Array.from(checkboxes).map(cb => cb.value);
    
    if (selectedIds.length === 0) {
        alert("Please select at least 1 project.");
        return;
    }
    
    const payload = {
        ...analyzeData.payload,
        selected_projects: selectedIds,
        stage1: analyzeData.stage1,
        company_intel: analyzeData.company_intel,
        jd_categories: analyzeData.jd_categories
    };
    
    UI.btnApprove.disabled = true;
    showState('loading');
    updatePipe(2, 'active');
    UI.loadMsg.textContent = 'Assembling resume (this takes 10-15s)...';
    UI.statusDot.className = 'status-dot active';
    UI.statusText.textContent = 'Generating PDF...';
    
    try {
        const resp = await fetch('/api/generate-resume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        
        if (!resp.ok || !data.success) {
            throw new Error(data.error || "Generation failed");
        }
        
        updatePipe(2, 'done');
        updatePipe(3, 'active');
        UI.loadMsg.textContent = 'Scoring ATS keywords...';

        setTimeout(() => {
            updatePipe(3, 'done');
            updatePipe(4, 'active');
            UI.loadMsg.textContent = 'Generating files...';

            setTimeout(() => {
                renderResult(data);
                showState('result');
                UI.statusDot.className = 'status-dot done';
                UI.statusText.textContent = 'Complete';
                UI.btnApprove.disabled = false;
            }, 400);
        }, 300);
        
    } catch (err) {
        UI.errorMsg.textContent = err.message;
        showState('error');
        UI.statusDot.className = 'status-dot error';
        UI.statusText.textContent = 'Error';
        UI.btnApprove.disabled = false;
    }
});

// Original form submit removed entirely below
"""

# Regex out the old UI.form.addEventListener('submit') block
js_new = re.sub(r"UI\.form\.addEventListener\('submit', async \(e\) => \{.*?(?=\nfunction renderResult)", new_submit, js, flags=re.DOTALL)

with open('static/js/app.js', 'w') as f:
    f.write(js_new)

print("Frontend patched.")
