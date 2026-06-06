import os
import re
import json
import time
import subprocess
import shutil
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
DATA_DIR    = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# LATEX ESCAPING
# ─────────────────────────────────────────────────────────────────────────────
def esc(text):
    """Escape LaTeX special characters in plain text."""
    if not isinstance(text, str):
        text = str(text)
    for ch, rep in [('\\','\\textbackslash{}'),('&',r'\&'),('%',r'\%'),
                    ('#',r'\#'),('$',r'\$'),('^',r'\textasciicircum{}'),
                    ('~',r'\textasciitilde{}'),('_',r'\_')]:
        text = text.replace(ch, rep)
    return text

# ─────────────────────────────────────────────────────────────────────────────
# FIX 1: generate_latex() — builds from structured JSON, not fragile text parsing
# ─────────────────────────────────────────────────────────────────────────────
def generate_latex(resume_json: dict, profile_data: dict, relocation: str = "") -> str:
    """
    Build LaTeX from structured JSON output of the LLM.
    Header and Education are injected from profile JSON — LLM never touches them.
    """
    personal = profile_data.get('personal', {})
    name     = personal.get('name', '')
    email    = personal.get('email', '')
    phone    = personal.get('phone', '')
    linkedin = personal.get('linkedin', '')
    github   = personal.get('github', '')
    location = personal.get('location', '')

    # Build contact line
    if relocation and relocation.strip():
        location_str = f"{esc(location)} $|$ Open to relocation -- {esc(relocation.strip())}"
    else:
        location_str = esc(location)

    contact_parts = [location_str]
    if phone:    contact_parts.append(esc(phone))
    if email:    contact_parts.append(f"\\href{{mailto:{email}}}{{{esc(email)}}}")
    if linkedin:
        url = linkedin if linkedin.startswith('http') else f"https://{linkedin}"
        contact_parts.append(f"\\href{{{url}}}{{{esc(linkedin)}}}")
    if github:
        url = github if github.startswith('http') else f"https://{github}"
        contact_parts.append(f"\\href{{{url}}}{{{esc(github)}}}")
    contact_line = " $|$ ".join(contact_parts)

    # Build education from JSON — never from LLM
    edu_latex_lines = []
    for edu in profile_data.get('education', []):
        degree = esc(edu.get('degree', ''))
        year   = esc(edu.get('year', ''))
        status = edu.get('status', '')
        score  = esc(edu.get('score', ''))
        uni    = esc(edu.get('university', edu.get('institution', '')))
        year_str = f"{year} $|$ {esc(status)}" if status else year
        edu_latex_lines.append(
            f"\\textbf{{{degree}}} \\hfill \\textit{{{year_str}}}\\\\\n{uni} \\hfill {score}\n\\vspace{{2pt}}"
        )

    # ── LaTeX Preamble ────────────────────────────────────────────────────────
    lines = [
        r"\documentclass[10.5pt,a4paper]{article}",
        # FIX 4: tighter margins, removed lmodern (not installed)
        r"\usepackage[top=0.38in, bottom=0.36in, left=0.44in, right=0.44in]{geometry}",
        r"\usepackage{enumitem}",
        r"\usepackage[hidelinks,unicode]{hyperref}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{titlesec}",
        r"\usepackage{array}",
        # FIX 4: microtype + DisableLigatures for clean ATS extraction
        r"\usepackage{microtype}",
        r"\DisableLigatures{encoding=*, family=*}",
        r"\pagestyle{empty}",
        r"\setlength{\parindent}{0pt}",
        r"\setlength{\parskip}{0pt}",
        # FIX 4: use \section not \section* so titlerule renders
        r"\titleformat{\section}{\normalfont\normalsize\bfseries\uppercase}{}{0em}{}[\vspace{1.5pt}\titlerule\vspace{3pt}]",
        r"\titlespacing*{\section}{0pt}{5pt}{0pt}",
        r"\setlist[itemize]{leftmargin=1.2em,itemsep=0.5pt,parsep=0pt,topsep=1.5pt,partopsep=0pt}",
        r"\begin{document}",
        # ── Header ──────────────────────────────────────────────────────────
        r"\begin{center}",
        f"{{\\Large\\bfseries {esc(name)}}}\\\\[2pt]",
        f"{contact_line}",
        r"\end{center}",
        r"\vspace{-2pt}",
    ]

    # ── Professional Summary ─────────────────────────────────────────────────
    summary = resume_json.get('summary', '')
    if summary:
        lines.append(r"\section{Professional Summary}")
        # Split into sentences, render as separate lines with small gap
        sentences = [s.strip() for s in summary.replace('\n', ' ').split('. ') if s.strip()]
        for i, sent in enumerate(sentences):
            if not sent.endswith('.'):
                sent += '.'
            if i < len(sentences) - 1:
                lines.append(f"{esc(sent)}\\\\[2pt]")
            else:
                lines.append(f"{esc(sent)}")

    # ── Technical Skills ─────────────────────────────────────────────────────
    skills = resume_json.get('skills', {})
    if skills:
        lines.append(r"\section{Technical Skills}")
        lines.append(r"\begin{tabular}{@{}p{0.155\textwidth}p{0.80\textwidth}@{}}")
        skill_items = list(skills.items())
        for i, (category, items) in enumerate(skill_items):
            sep = r"\\[1pt]" if i < len(skill_items) - 1 else r"\\"
            items_str = ', '.join(items) if isinstance(items, list) else str(items)
            lines.append(f"\\textbf{{{esc(category)}}} & {esc(items_str)} {sep}")
        lines.append(r"\end{tabular}")

    # ── Professional Experience ──────────────────────────────────────────────
    experience = resume_json.get('experience', [])
    if experience:
        lines.append(r"\section{Professional Experience}")
        for exp in experience:
            role_str   = esc(exp.get('role', ''))
            period_str = esc(exp.get('period', ''))
            company_str = esc(exp.get('company', ''))
            location_e  = esc(exp.get('location', ''))
            lines.append(f"\\textbf{{{role_str}}} \\hfill \\textit{{{period_str}}}")
            lines.append(f"\\\\\\textit{{{company_str} $|$ {location_e}}}")
            bullets = exp.get('bullets', [])
            if bullets:
                lines.append(r"\begin{itemize}")
                for b in bullets:
                    lines.append(f"  \\item {esc(b)}")
                lines.append(r"\end{itemize}")

    # ── Academic Projects ─────────────────────────────────────────────────────
    projects = resume_json.get('projects', [])
    if projects:
        lines.append(r"\section{Academic Projects}")
        for i, proj in enumerate(projects):
            pname    = esc(proj.get('name', ''))
            psub     = esc(proj.get('subtitle', ''))
            ptech    = esc(proj.get('tech', ''))
            pbullets = proj.get('bullets', [])
            lines.append(f"\\textbf{{{pname}}} -- {psub} \\hfill \\textit{{{ptech}}}")
            if pbullets:
                lines.append(r"\begin{itemize}")
                for b in pbullets:
                    lines.append(f"  \\item {esc(b)}")
                lines.append(r"\end{itemize}")
            if i < len(projects) - 1:
                lines.append(r"\vspace{2pt}")

    # ── Technical Strengths ──────────────────────────────────────────────────
    strengths = resume_json.get('strengths', [])
    if strengths:
        lines.append(r"\section{Technical Strengths}")
        lines.append(r"\begin{itemize}")
        for s in strengths:
            lines.append(f"  \\item {esc(s)}")
        lines.append(r"\end{itemize}")

    # ── Education (always from JSON, never from LLM) ─────────────────────────
    lines.append(r"\section{Education}")
    lines.extend(edu_latex_lines)

    lines.append(r"\end{document}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# FIX 3: Skills filter — only include skills Pratik actually has projects for
# ─────────────────────────────────────────────────────────────────────────────
FABRICATION_BLACKLIST = {
    'docker', 'kubernetes', 'redis', 'postgresql', 'graphql',
    'aws ec2', 'aws s3', 'gcp', 'azure', 'ci/cd', 'microservices',
    'kafka', 'rabbitmq', 'elasticsearch', 'terraform', 'jenkins',
    'android', 'ios', 'swift', 'kotlin', 'flutter', 'react native'
}

def filter_skills(skills_dict: dict) -> dict:
    """Remove fabricated skills not backed by actual projects."""
    cleaned = {}
    for category, items in skills_dict.items():
        if isinstance(items, list):
            filtered = [s for s in items
                        if s.lower() not in FABRICATION_BLACKLIST
                        and not any(b in s.lower() for b in FABRICATION_BLACKLIST)]
            if filtered:
                cleaned[category] = filtered
        else:
            cleaned[category] = items
    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# ATS SCORING — on actual PDF text, not LLM text
# ─────────────────────────────────────────────────────────────────────────────
def score_ats_from_pdf(pdf_path: str, keywords: list) -> dict:
    """Extract text from compiled PDF and score against keywords."""
    try:
        from pypdf import PdfReader
        r = PdfReader(pdf_path)
        text = "".join(page.extract_text() or "" for page in r.pages)
    except Exception:
        return {"score": 0, "hits": [], "misses": keywords, "total": len(keywords),
                "note": "pypdf not installed — run: pip install pypdf"}

    hits   = [kw for kw in keywords if kw.lower() in text.lower()]
    misses = [kw for kw in keywords if kw.lower() not in text.lower()]
    score  = round(len(hits) / len(keywords) * 100) if keywords else 100
    return {"score": score, "hits": hits, "misses": misses, "total": len(keywords)}


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/health')
def health():
    pdf_avail = shutil.which('pdflatex') is not None
    return jsonify({"status": "ok", "pdflatex": pdf_avail})

@app.route('/api/download/<slug>/<fmt>')
def download(slug, fmt):
    slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug)
    if fmt not in ['txt', 'tex', 'pdf', 'json']:
        return "Invalid format", 400
    file_path = os.path.join(OUTPUTS_DIR, f"{slug}.{fmt}")
    if not os.path.exists(file_path):
        return "File not found", 404
    return send_file(file_path, as_attachment=True)


@app.route('/api/generate', methods=['POST'])
def generate():
    data      = request.json
    api_key   = data.get('api_key')
    jd        = data.get('jd', '')
    company   = data.get('company', 'Unknown')
    role      = data.get('role', 'Role')
    role_type = data.get('role_type', '')
    relocation = data.get('relocation', '')   # NEW: optional relocation city

    if not api_key:
        return jsonify({"error": "API key required"}), 401
    if len(jd.strip()) < 100:
        return jsonify({"error": "JD too short — paste full job description"}), 400

    try:
        # ── Model discovery ───────────────────────────────────────────────────
        target_model = 'models/gemini-1.5-flash'
        try:
            list_resp = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}")
            if list_resp.status_code == 200:
                available = [m['name'] for m in list_resp.json().get('models', [])
                             if 'generateContent' in m.get('supportedGenerationMethods', [])]
                for pref in ['models/gemini-2.5-flash','models/gemini-2.0-flash',
                             'models/gemini-1.5-flash-latest','models/gemini-1.5-flash']:
                    if pref in available:
                        target_model = pref
                        break
        except Exception as e:
            print("Model discovery failed:", e)

        url     = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}

        # ── Load candidate data ───────────────────────────────────────────────
        with open(os.path.join(DATA_DIR, 'resume_ready.json'), 'r') as f:
            profile = json.load(f)
        with open(os.path.join(DATA_DIR, 'projects_master.json'), 'r') as f:
            all_projects_raw = json.load(f)
            all_projects = all_projects_raw.get('projects', all_projects_raw) \
                           if isinstance(all_projects_raw, dict) else all_projects_raw

        # ── STAGE 1: JD Keyword Extraction ───────────────────────────────────
        stage1_prompt = f"""You are a JD keyword extractor. Return ONLY valid JSON, no markdown, no explanation.

Schema:
{{
  "role_type": "string",
  "seniority": "fresher|junior|mid",
  "keywords": ["12-15 exact skill/tool strings verbatim from JD"],
  "required": ["top 8 must-have skills"],
  "preferred": ["top 5 nice-to-have"],
  "responsibilities": ["3 key responsibilities as short phrases"],
  "ai_ml_cloud_mentioned": true or false
}}

Job: {role} at {company}
Category: {role_type}

JD:
{jd[:3000]}"""

        resp1 = requests.post(url, headers=headers, json={
            "contents": [{"parts": [{"text": stage1_prompt}]}],
            "generationConfig": {"maxOutputTokens": 500}
        })
        if resp1.status_code != 200:
            raise Exception(f"Stage 1 API error ({resp1.status_code}): {resp1.text[:300]}")

        try:
            raw1 = resp1.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            raw1 = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw1).strip()
            stage1 = json.loads(raw1)
        except Exception:
            stage1 = {"role_type": role_type, "seniority": "fresher",
                      "keywords": [], "required": [], "preferred": [],
                      "responsibilities": [], "ai_ml_cloud_mentioned": False}

        # ── Project auto-selection (pure Python) ──────────────────────────────
        target_tags = [kw.lower() for kw in
                       stage1.get('keywords', []) + stage1.get('required', [])]
        target_tags.append(role_type.lower())

        for p in all_projects:
            score = 0
            for tag in [t.lower() for t in p.get('tags', [])]:
                for tgt in target_tags:
                    if tag in tgt or tgt in tag:
                        score += 1
            # Boost by priority field
            score += (3 - p.get('priority', 3)) * 2
            p['_score'] = score

        selected = sorted(all_projects, key=lambda x: x['_score'], reverse=True)[:3]

        # ── Build skills pool for this role ───────────────────────────────────
        skills_pool = profile.get('skills_pool', {})

        # FIX 3: determine which skill tracks to send based on role_type
        role_lower = role_type.lower()
        if 'c++' in role_lower or 'system' in role_lower or 'embedded' in role_lower:
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Systems":    skills_pool.get('cpp_stack', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_cpp', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', []) + skills_pool.get('concepts_systems', [])
            }
        elif 'full' in role_lower:
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Backend":    skills_pool.get('backend', []),
                "Frontend":   skills_pool.get('frontend', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_java', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', []) + skills_pool.get('concepts_backend', [])
            }
        else:  # java-backend, general, internship
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Backend":    skills_pool.get('backend', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_java', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', []) + skills_pool.get('concepts_backend', [])
            }
            if stage1.get('ai_ml_cloud_mentioned'):
                skills_to_send["Exposure"] = skills_pool.get('exposure', [])

        # ── STAGE 2: Resume Assembly → structured JSON output ─────────────────
        time.sleep(2)

        # FIX 2: LLM outputs structured JSON, not plain text
        stage2_prompt = f"""You are an expert resume writer. Output ONLY valid JSON, no markdown, no explanation.

STRICT RULES:
1. Output structured JSON only — schema shown below
2. DO NOT include name, email, phone, links, location in ANY field — header is injected separately
3. DO NOT include education in ANY field — it is injected separately from JSON
4. Use ONLY the skills provided in AVAILABLE_SKILLS — no additions, no fabrication
5. Use strong action verbs: Engineered, Architected, Designed, Optimized, Implemented, Developed
6. Every project bullet must include a measurable metric or outcome
7. Summary: exactly 2 sentences. No "passionate/motivated/eager/excited". Engineer-profile tone only.
8. Each project must have exactly 3 bullets
9. Experience bullets: exactly 3 bullets, use verbatim from CANDIDATE_EXPERIENCE
10. Strengths: exactly 4 items, engineering capabilities only, no soft skills
11. Weave JD keywords naturally into bullets and summary — never list them separately
12. Skills: reorder items within each category to put JD-relevant ones first. Do NOT add new items.

TARGET ROLE: {role} at {company}
ROLE TYPE: {stage1.get('role_type', role_type)}
JD KEYWORDS TO INCLUDE: {', '.join(stage1.get('keywords', []))}
REQUIRED SKILLS: {', '.join(stage1.get('required', []))}
KEY RESPONSIBILITIES: {'; '.join(stage1.get('responsibilities', []))}

AVAILABLE_SKILLS (use ONLY these, reorder within categories as needed):
{json.dumps(skills_to_send, indent=2)}

CANDIDATE_EXPERIENCE:
{json.dumps(profile.get('experience', []), indent=2)}

SELECTED_PROJECTS (use these 3, bullets are pre-written — reuse and enhance with JD keywords):
{json.dumps(selected, indent=2)}

STRENGTHS_POOL (pick 4 most relevant to this JD):
{json.dumps(profile.get('strengths_pool', {}), indent=2)}

OUTPUT JSON SCHEMA:
{{
  "summary": "2-sentence engineer-profile summary with JD keywords woven in",
  "skills": {{
    "Category Name": ["skill1", "skill2"],
    ...
  }},
  "experience": [
    {{
      "role": "exact role title",
      "company": "company name",
      "location": "city",
      "period": "Month YYYY -- Ongoing",
      "bullets": ["bullet 1", "bullet 2", "bullet 3"]
    }}
  ],
  "projects": [
    {{
      "name": "Project Name",
      "subtitle": "Project Subtitle",
      "tech": "Tech1, Tech2, Tech3",
      "bullets": ["bullet 1", "bullet 2", "bullet 3"]
    }}
  ],
  "strengths": ["strength 1", "strength 2", "strength 3", "strength 4"]
}}"""

        resp2 = requests.post(url, headers=headers, json={
            "contents": [{"parts": [{"text": stage2_prompt}]}],
            "generationConfig": {"maxOutputTokens": 3000}
        })
        if resp2.status_code != 200:
            raise Exception(f"Stage 2 API error ({resp2.status_code}): {resp2.text[:300]}")

        raw2 = resp2.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        raw2 = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw2).strip()

        try:
            resume_json = json.loads(raw2)
        except json.JSONDecodeError as e:
            raise Exception(f"Stage 2 JSON parse failed: {e}. Raw: {raw2[:300]}")

        # FIX 3: Filter fabricated skills from LLM output
        if 'skills' in resume_json:
            resume_json['skills'] = filter_skills(resume_json['skills'])

        # ── Generate LaTeX ─────────────────────────────────────────────────────
        latex_content = generate_latex(resume_json, profile, relocation)

        # ── Save files ─────────────────────────────────────────────────────────
        timestamp = int(time.time())
        slug = re.sub(r'[^a-z0-9_]', '',
                      f"{company}_{role}_{timestamp}".replace(' ', '_').lower())

        tex_path = os.path.join(OUTPUTS_DIR, f"{slug}.tex")
        pdf_path = os.path.join(OUTPUTS_DIR, f"{slug}.pdf")
        json_path = os.path.join(OUTPUTS_DIR, f"{slug}.json")

        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(latex_content)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(resume_json, f, indent=2)

        # ── Compile PDF with auto-retry ────────────────────────────────────────
        pdf_available = False
        pdf_error     = None
        ats_data      = {"score": 0, "hits": [], "misses": [], "total": 0}

        if shutil.which('pdflatex'):
            for attempt in range(1, 4):
                try:
                    result = subprocess.run(
                        ['pdflatex', '-interaction=nonstopmode',
                         f'-output-directory={OUTPUTS_DIR}', tex_path],
                        capture_output=True, text=True
                    )
                    if os.path.exists(pdf_path):
                        pdf_available = True
                        break
                    else:
                        # Extract first error line from log
                        err_lines = [l for l in result.stdout.splitlines() if l.startswith('!')]
                        pdf_error = err_lines[0] if err_lines else "pdflatex failed silently"

                        # AUTO-FIX: if lmodern missing, patch and retry
                        if 'lmodern' in pdf_error.lower():
                            latex_content = latex_content.replace(r'\usepackage{lmodern}', '')
                            with open(tex_path, 'w') as f:
                                f.write(latex_content)
                            continue

                        # AUTO-FIX: if overflow (2 pages), tighten margins
                        if attempt == 2:
                            latex_content = re.sub(r'top=[\d.]+in', 'top=0.34in', latex_content)
                            latex_content = re.sub(r'bottom=[\d.]+in', 'bottom=0.32in', latex_content)
                            latex_content = re.sub(r'\\documentclass\[[\d.]+pt',
                                                   r'\\documentclass[10pt', latex_content)
                            with open(tex_path, 'w') as f:
                                f.write(latex_content)
                        break
                except Exception as e:
                    pdf_error = str(e)
                    break

            # FIX 5: ATS score from actual PDF text, not LLM text
            if pdf_available:
                all_kws = list(set(stage1.get('keywords', []) + stage1.get('required', [])))
                ats_data = score_ats_from_pdf(pdf_path, all_kws)
        else:
            pdf_error = "pdflatex not found — run: sudo apt install texlive-latex-extra -y"
            # Fallback ATS scoring from resume_json text
            combined_text = json.dumps(resume_json).lower()
            all_kws = list(set(stage1.get('keywords', []) + stage1.get('required', [])))
            hits   = [kw for kw in all_kws if kw.lower() in combined_text]
            misses = [kw for kw in all_kws if kw.lower() not in combined_text]
            ats_data = {"score": round(len(hits)/len(all_kws)*100) if all_kws else 100,
                        "hits": hits, "misses": misses, "total": len(all_kws)}

        return jsonify({
            "success":       True,
            "slug":          slug,
            "resume_json":   resume_json,
            "latex":         latex_content,
            "ats":           ats_data,
            "stage1":        stage1,
            "pdf_available": pdf_available,
            "pdf_error":     pdf_error,
            "projects_used": [p.get('name') for p in selected]
        })

    except Exception as e:
        err = str(e).lower()
        if 'api_key' in err or 'authentication' in err or '400' in err:
            return jsonify({"error": "Invalid API key"}), 401
        elif 'quota' in err or 'rate' in err or '429' in err:
            return jsonify({"error": f"Rate limit — wait 60s and retry: {str(e)}"}), 429
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)