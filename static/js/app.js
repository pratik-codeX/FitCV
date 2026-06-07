const UI = {
    states: {
        idle: document.getElementById('state-idle'),
        loading: document.getElementById('state-loading'),
        result: document.getElementById('state-result'),
        error: document.getElementById('state-error')
    },
    form: document.getElementById('gen-form'),
    jdInput: document.getElementById('f-jd'),
    jdCount: document.getElementById('jd-count'),
    btnGen: document.getElementById('btn-gen'),
    toggleKey: document.getElementById('toggle-key'),
    fKey: document.getElementById('f-key'),
    fRelocation: document.getElementById('f-relocation'),
    statusDot: document.getElementById('status-dot'),
    statusText: document.getElementById('status-text'),
    healthBadge: document.getElementById('health-badge'),

    // Loading
    ps1: document.getElementById('ps-1'),
    ps2: document.getElementById('ps-2'),
    ps3: document.getElementById('ps-3'),
    ps4: document.getElementById('ps-4'),
    loadMsg: document.getElementById('loading-msg'),

    // Result
    atsScore: document.getElementById('ats-score'),
    atsBar: document.getElementById('ats-bar'),
    metaRole: document.getElementById('meta-role'),
    metaSeniority: document.getElementById('meta-seniority'),
    metaKwCount: document.getElementById('meta-kw-count'),
    metaProjects: document.getElementById('meta-projects'),
    kwContainer: document.getElementById('kw-container'),
    atsBreakdown: document.getElementById('ats-breakdown'),
    resumeOutput: document.getElementById('resume-output'),
    pdfNotice: document.getElementById('pdf-notice'),
    btnTxt: document.getElementById('btn-txt'),
    btnTex: document.getElementById('btn-tex'),
    btnPdf: document.getElementById('btn-pdf'),
    btnCopy: document.getElementById('btn-copy'),
    btnImprove: document.getElementById('btn-improve'),
    improvePanel: document.getElementById('improve-panel'),
    improveLoading: document.getElementById('improve-loading'),
    improveContent: document.getElementById('improve-content'),
    improveScore: document.getElementById('improve-score'),

    // Error
    errorTitle: document.getElementById('error-title'),
    errorMsg: document.getElementById('error-msg')
};

let rawResumeText = "";
let _lastData = null;  // stored so improve button can send full context

function showState(name) {
    Object.values(UI.states).forEach(el => el.classList.remove('active'));
    UI.states[name].classList.add('active');
}

function updatePipe(step, state) {
    const el = document.getElementById(`ps-${step}`);
    if (state === 'active') {
        el.classList.add('active');
        el.classList.remove('done');
        el.querySelector('.step-icon').innerHTML = '<div class="loader"></div>';
    } else if (state === 'done') {
        el.classList.add('active', 'done');
        el.querySelector('.step-icon').innerHTML = '✓';
    } else {
        el.classList.remove('active', 'done');
        el.querySelector('.step-icon').innerHTML = step;
    }
}

// Check health
fetch('/api/health').then(r => r.json()).then(data => {
    if (data.pdflatex) {
        UI.healthBadge.textContent = 'pdflatex available';
        UI.healthBadge.className = 'badge green';
    } else {
        UI.healthBadge.textContent = 'pdflatex missing';
        UI.healthBadge.className = 'badge amber';
    }
}).catch(() => {
    UI.healthBadge.textContent = 'Offline';
});

// JD Char count
UI.jdInput.addEventListener('input', () => {
    UI.jdCount.textContent = UI.jdInput.value.length;
});

// Toggle API key
UI.toggleKey.addEventListener('click', () => {
    UI.fKey.type = UI.fKey.type === 'password' ? 'text' : 'password';
});

// Copy button
UI.btnCopy.addEventListener('click', () => {
    navigator.clipboard.writeText(rawResumeText);
    UI.btnCopy.textContent = "Copied!";
    setTimeout(() => UI.btnCopy.textContent = "Copy text", 2000);
});

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
    UI.statusText.textContent = 'Running pipeline...';
    showState('loading');

    updatePipe(1, 'active');
    updatePipe(2, 'idle'); updatePipe(3, 'idle'); updatePipe(4, 'idle');
    UI.loadMsg.textContent = 'Extracting keywords from Job Description...';

    const t1 = setTimeout(() => {
        updatePipe(1, 'done');
        updatePipe(2, 'active');
        UI.loadMsg.textContent = 'Assembling resume (this takes 10-15s)...';
    }, 2500);

    try {
        const resp = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        clearTimeout(t1);
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
                UI.statusText.textContent = data.from_cache ? '⚡ Cache hit' : 'Complete';
                UI.btnGen.disabled = false;
            }, 400);
        }, 300);

    } catch (err) {
        clearTimeout(t1);
        UI.errorMsg.textContent = err.message;
        showState('error');
        UI.statusDot.className = 'status-dot error';
        UI.statusText.textContent = 'Error';
        UI.btnGen.disabled = false;
    }
});

function renderResult(data) {
    // Cache notice banner
    if (data.from_cache) {
        const existingNotice = document.getElementById('cache-notice');
        if (!existingNotice) {
            const notice = document.createElement('div');
            notice.id = 'cache-notice';
            notice.className = 'notice amber';
            notice.textContent = '⚡ Returned from cache — no API calls used. Change the JD to regenerate fresh.';
            const resultContainer = document.getElementById('state-result');
            const resultHeader = resultContainer.querySelector('.result-header');
            resultHeader.insertAdjacentElement('afterend', notice);
        }
    } else {
        const existingNotice = document.getElementById('cache-notice');
        if (existingNotice) existingNotice.remove();
    }

    // Build readable plain text for Copy button
    const rj_plain = data.resume_json;
    const text_lines = [];
    if (rj_plain.summary) {
        text_lines.push('PROFESSIONAL SUMMARY');
        text_lines.push('-'.repeat(50));
        text_lines.push(rj_plain.summary);
        text_lines.push('');
    }
    if (rj_plain.skills) {
        text_lines.push('TECHNICAL SKILLS');
        text_lines.push('-'.repeat(50));
        for (const [cat, items] of Object.entries(rj_plain.skills)) {
            text_lines.push(`${cat}: ${Array.isArray(items) ? items.join(', ') : items}`);
        }
        text_lines.push('');
    }
    if (rj_plain.experience && rj_plain.experience.length > 0) {
        text_lines.push('PROFESSIONAL EXPERIENCE');
        text_lines.push('-'.repeat(50));
        for (const exp of rj_plain.experience) {
            text_lines.push(`${exp.role} | ${exp.company} | ${exp.period}`);
            (exp.bullets || []).forEach(b => text_lines.push(`  • ${b}`));
            text_lines.push('');
        }
    }
    if (rj_plain.projects && rj_plain.projects.length > 0) {
        text_lines.push('ACADEMIC PROJECTS');
        text_lines.push('-'.repeat(50));
        for (const proj of rj_plain.projects) {
            text_lines.push(`${proj.name} — ${proj.subtitle} | ${proj.tech}`);
            (proj.bullets || []).forEach(b => text_lines.push(`  • ${b}`));
            text_lines.push('');
        }
    }
    if (rj_plain.strengths && rj_plain.strengths.length > 0) {
        text_lines.push('TECHNICAL STRENGTHS');
        text_lines.push('-'.repeat(50));
        rj_plain.strengths.forEach(s => text_lines.push(`  • ${s}`));
    }
    rawResumeText = text_lines.join('\n');

    const ats = data.ats || { score: 0, hits: [], misses: [], total: 0 };
    UI.atsScore.textContent = ats.score;
    let color = 'var(--red)';
    if (ats.score >= 90) color = 'var(--green)';
    else if (ats.score >= 70) color = 'var(--amber)';
    UI.atsScore.style.color = color;
    UI.atsBar.style.width = `${ats.score}%`;
    UI.atsBar.style.backgroundColor = color;

    UI.metaRole.textContent = data.stage1?.role_type || 'Unknown';
    UI.metaSeniority.textContent = data.stage1?.seniority || 'Unknown';
    UI.metaKwCount.textContent = `${(ats.hits || []).length}/${ats.total || 0} keywords hit`;
    UI.metaProjects.textContent = `Projects: ${(data.projects_used || []).join(', ')}`;

    UI.kwContainer.innerHTML = '';
    (ats.hits || []).forEach(kw => {
        const el = document.createElement('div');
        el.className = 'kw-pill hit';
        el.textContent = kw;
        UI.kwContainer.appendChild(el);
    });
    (ats.misses || []).forEach(kw => {
        const el = document.createElement('div');
        el.className = 'kw-pill miss';
        el.textContent = kw;
        UI.kwContainer.appendChild(el);
    });

    // ATS breakdown by category
    const bd = ats.breakdown;
    if (bd) {
        UI.atsBreakdown.style.display = 'block';
        function renderBDRow(elId, label, cat) {
            const c = bd[cat] || {};
            const s = c.score ?? 100;
            const col = s >= 80 ? 'var(--green)' : s >= 55 ? 'var(--amber)' : 'var(--red)';
            const hits = (c.hits || []).length, total = (c.hits || []).length + (c.misses || []).length;
            document.getElementById(elId).innerHTML = `
                <span class="bd-label">${label}</span>
                <div class="bd-bar-bg"><div class="bd-bar-fill" style="width:${s}%;background:${col}"></div></div>
                <span class="bd-pct" style="color:${col}">${s}%</span>
                <span class="bd-count">${hits}/${total}</span>`;
        }
        renderBDRow('bd-required',  'Required',  'required');
        renderBDRow('bd-preferred', 'Preferred', 'preferred');
        renderBDRow('bd-general',   'General',   'general');
    }

    const rj = data.resume_json;
    UI.resumeOutput.innerHTML = '';

    function addSection(title, contentHTML) {
        UI.resumeOutput.innerHTML += `
            <div class="resume-section">
                <div class="sec-tag">${title}</div>
                <div class="content">${contentHTML}</div>
            </div>`;
    }

    if (rj.summary) {
        addSection('PROFESSIONAL SUMMARY', `<p>${rj.summary}</p>`);
    }

    if (rj.skills) {
        let skillsHTML = '';
        for (const [cat, items] of Object.entries(rj.skills)) {
            const itemsStr = Array.isArray(items) ? items.join(', ') : items;
            skillsHTML += `<div style="margin-bottom: 4px;"><strong>${cat}:</strong> ${itemsStr}</div>`;
        }
        addSection('TECHNICAL SKILLS', skillsHTML);
    }

    if (rj.experience && rj.experience.length > 0) {
        let expHTML = '';
        for (const exp of rj.experience) {
            expHTML += `
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between;">
                        <strong>${exp.role}</strong>
                        <span>${exp.period}</span>
                    </div>
                    <div style="font-style: italic; margin-bottom: 4px;">${exp.company} | ${exp.location}</div>
                    <ul style="margin: 0; padding-left: 20px;">${(exp.bullets || []).map(b => `<li>${b}</li>`).join('')}</ul>
                </div>`;
        }
        addSection('PROFESSIONAL EXPERIENCE', expHTML);
    }

    if (rj.projects && rj.projects.length > 0) {
        let projHTML = '';
        for (const proj of rj.projects) {
            projHTML += `
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between;">
                        <strong>${proj.name}</strong>
                        <span style="font-style: italic;">${proj.tech}</span>
                    </div>
                    <div style="margin-bottom: 4px;">${proj.subtitle}</div>
                    <ul style="margin: 0; padding-left: 20px;">${(proj.bullets || []).map(b => `<li>${b}</li>`).join('')}</ul>
                </div>`;
        }
        addSection('ACADEMIC PROJECTS', projHTML);
    }

    if (rj.strengths && rj.strengths.length > 0) {
        const strHTML = `<ul style="margin: 0; padding-left: 20px;">${rj.strengths.map(s => `<li>${s}</li>`).join('')}</ul>`;
        addSection('TECHNICAL STRENGTHS', strHTML);
    }

    UI.btnTxt.href = `/api/download/${data.slug}/json`;
    UI.btnTex.href = `/api/download/${data.slug}/tex`;

    if (data.pdf_available) {
        UI.btnPdf.href = `/api/download/${data.slug}/pdf`;
        UI.btnPdf.style.display = 'inline-block';
        UI.pdfNotice.style.display = 'none';
    } else {
        UI.btnPdf.style.display = 'none';
        UI.pdfNotice.style.display = 'block';
        UI.pdfNotice.textContent = data.pdf_error || 'PDF unavailable — download LaTeX and compile with: pdflatex resume.tex';
    }

    // Reset improve panel for fresh result
    UI.improvePanel.style.display = 'none';
    UI.improveContent.innerHTML = '';
    UI.improveScore.textContent = '';
    _lastData = data;
}

// ── Improve button ────────────────────────────────────────────────────────────
UI.btnImprove.addEventListener('click', async () => {
    if (!_lastData) return;

    UI.improvePanel.style.display = 'block';
    UI.improveLoading.style.display = 'block';
    UI.improveContent.innerHTML = '';
    UI.improveScore.textContent = '';
    UI.btnImprove.disabled = true;
    UI.improvePanel.scrollIntoView({ behavior: 'smooth', block: 'start' });

    const payload = {
        api_key:     UI.fKey.value.trim(),
        jd:          UI.jdInput.value.trim(),
        resume_json: _lastData.resume_json,
        stage1:      _lastData.stage1,
        ats:         _lastData.ats
    };

    try {
        const resp = await fetch('/api/improve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        UI.improveLoading.style.display = 'none';
        UI.btnImprove.disabled = false;

        if (!resp.ok || !data.success) {
            UI.improveContent.innerHTML = `<div class="improve-error">⚠️ ${data.error}</div>`;
            return;
        }
        renderImprovement(data.improvement, _lastData.ats.score);
    } catch (err) {
        UI.improveLoading.style.display = 'none';
        UI.btnImprove.disabled = false;
        UI.improveContent.innerHTML = `<div class="improve-error">⚠️ ${err.message}</div>`;
    }
});

function renderImprovement(imp, currentScore) {
    const after = imp.estimated_score_after || 0;
    const delta = after - currentScore;
    const deltaStr = delta >= 0 ? `+${delta}` : `${delta}`;
    const deltaCol = delta >= 0 ? 'var(--green)' : 'var(--red)';

    UI.improveScore.innerHTML =
        `<span style="color:var(--text2)">Current: <strong>${currentScore}%</strong></span>
         <span style="margin:0 8px;color:var(--text3)">→</span>
         <span style="color:var(--green)">Estimated after fixes: <strong>${after}%</strong></span>
         <span style="margin-left:8px;color:${deltaCol};font-weight:700">(${deltaStr})</span>`;

    let html = '';

    // Summary note
    if (imp.summary_note) {
        html += `<div class="improve-note">${imp.summary_note}</div>`;
    }

    // Priority fixes
    if (imp.priority_fixes && imp.priority_fixes.length) {
        html += `<div class="improve-section-title">🔧 Priority Fixes</div>`;
        imp.priority_fixes.forEach((f, i) => {
            html += `
            <div class="improve-fix">
                <div class="fix-badge">${f.section.toUpperCase()}</div>
                <div class="fix-issue">${f.issue}</div>
                <div class="fix-suggestion">${f.fix}</div>
            </div>`;
        });
    }

    // Bullets to rewrite
    if (imp.bullets_to_rewrite && imp.bullets_to_rewrite.length) {
        html += `<div class="improve-section-title">✏️ Bullet Rewrites</div>`;
        imp.bullets_to_rewrite.forEach(b => {
            html += `
            <div class="improve-bullet">
                <div class="bullet-old">✖ ${b.original}</div>
                <div class="bullet-new">✔ ${b.improved}</div>
            </div>`;
        });
    }

    // Skills to add
    if (imp.skills_to_add && imp.skills_to_add.length) {
        html += `<div class="improve-section-title">📦 Skills to Add</div>`;
        html += `<div class="improve-skills">${imp.skills_to_add.map(s =>
            `<span class="kw-pill miss">${s}</span>`).join('')}</div>`;
    }

    UI.improveContent.innerHTML = html;
}