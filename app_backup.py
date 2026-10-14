import os
import re
import json
import time
import hashlib
import subprocess
import shutil
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import requests
import json_repair
# ─────────────────────────────────────────────────────────────────────────────
# GEMINI API KEY SETUP (FREE — no credit card required)
# 1. Go to: https://aistudio.google.com
# 2. Sign in with your Google account
# 3. Click "Get API Key" → "Create API key"
# 4. Copy the key — it starts with "AIza..."
# 5. Paste it into the app's API key field
# Model used: gemini-2.5-flash-preview (best free tier — 1M context, fast)
# Free tier limits: 15 requests/min, 1500 requests/day — more than enough
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
DATA_DIR    = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# REQUEST CACHE — avoids burning API quota on identical requests
# Cache is in-memory (cleared on server restart). Key = hash of JD+role+company.
# ─────────────────────────────────────────────────────────────────────────────
_RESUME_CACHE: dict = {}

def make_cache_key(jd: str, company: str, role: str, role_type: str) -> str:
    raw = f"{jd.strip().lower()}|{company.strip().lower()}|{role.strip().lower()}|{role_type.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

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
        score  = esc(edu.get('score', edu.get('cgpa', '')))
        uni    = esc(edu.get('university', edu.get('institution', '')))
        year_str = f"{year} $|$ {esc(status)}" if status else year
        edu_latex_lines.append(
            f"\\textbf{{{degree}}} \\hfill \\textit{{{year_str}}}\\\\\n{uni} \\hfill {score}\n\\vspace{{3pt}}"
        )

    # ── LaTeX Preamble ────────────────────────────────────────────────────────
    lines = [
        r"\documentclass[10.5pt,a4paper]{article}",
        # Updated: balanced margins to prevent overflowing to page 2
        r"\usepackage[top=0.45in, bottom=0.45in, left=0.55in, right=0.55in]{geometry}",
        r"\usepackage{enumitem}",
        r"\usepackage[hidelinks,unicode]{hyperref}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{lmodern}",
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
        r"\titlespacing*{\section}{0pt}{6pt}{3pt}",
        r"\setlist[itemize]{leftmargin=1.2em,itemsep=1.5pt,parsep=0pt,topsep=2pt,partopsep=0pt}",
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
        # Render summary as a single continuous paragraph
        lines.append(esc(summary.strip()))

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
    if not experience:
        raise ValueError(
            "generate_latex() called with empty 'experience' — LLM truncated. "
            "Schema validation should have caught this first."
        )
    if True:  # always render
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
    if not projects:
        raise ValueError(
            "generate_latex() called with empty 'projects' — LLM truncated. "
            "Schema validation should have caught this first."
        )
    if True:  # always render
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
                lines.append(r"\vspace{4pt}")

    # ── Technical Strengths ──────────────────────────────────────────────────
    strengths = resume_json.get('strengths', [])
    if not strengths:
        raise ValueError(
            "generate_latex() called with empty 'strengths' — LLM truncated. "
            "Schema validation should have caught this first."
        )
    if True:  # always render
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
# GEMINI API CALLER — auto-retry on 429, auto-skip on 404 model-not-found
# ─────────────────────────────────────────────────────────────────────────────
def gemini_post(url: str, headers: dict, payload: dict, stage: str = "API") -> dict:
    """
    Call Gemini REST API.
    200  → return JSON
    429  → 1 quick retry (5s), then raise tagged '429_RATE_LIMITED' so caller tries next model
    503  → 1 retry (10s wait for overload to clear), then raise tagged '503_OVERLOADED'
    404  → raise tagged '404_MODEL_NOT_FOUND' so caller tries next model
    else → raise with status + body
    """
    model_name = url.split('models/')[-1].split(':')[0]
    for attempt in range(2):   # max 2 tries per model (0, 1)
        resp = requests.post(url, headers=headers, json=payload, timeout=90)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            if attempt == 0:
                print(f"[{stage}] 429 on '{model_name}' — waiting 5s then trying once more...", flush=True)
                time.sleep(5)
                continue
            raise Exception(f"429_RATE_LIMITED:{model_name}")
        if resp.status_code == 503:
            if attempt == 0:
                print(f"[{stage}] 503 on '{model_name}' (overloaded) — waiting 10s then retrying...", flush=True)
                time.sleep(10)
                continue
            raise Exception(f"503_OVERLOADED:{model_name}")
        if resp.status_code == 404:
            raise Exception(f"404_MODEL_NOT_FOUND:{model_name}")
        raise Exception(f"{stage} API error ({resp.status_code}): {resp.text[:400]}")
    raise Exception(f"{stage} API call failed after all retries")


def gemini_call(models_priority: list, api_key: str,
                headers: dict, payload: dict, stage: str) -> dict:
    """
    Try each model in models_priority until one succeeds.
    Skips to the next model on both 404 (not found) and 429 (rate limited).
    Raises only if ALL models fail.
    """
    skipped = []
    last_err = None
    for model in models_priority:
        url = (f"https://generativelanguage.googleapis.com/v1beta"
               f"/models/{model}:generateContent?key={api_key}")
        print(f"[{stage}] Trying model: {model}", flush=True)
        try:
            result = gemini_post(url, headers, payload, stage=stage)
            print(f"[{stage}] ✓ Success with model: {model}", flush=True)
            return result
        except Exception as exc:
            last_err = exc
            exc_str = str(exc)
            if "404_MODEL_NOT_FOUND" in exc_str:
                print(f"[{stage}] '{model}' not found — trying next model...", flush=True)
                skipped.append(f"{model}(404)")
                continue
            if "429_RATE_LIMITED" in exc_str:
                print(f"[{stage}] '{model}' rate limited — trying next model...", flush=True)
                skipped.append(f"{model}(429)")
                continue
            if "503_OVERLOADED" in exc_str:
                print(f"[{stage}] '{model}' overloaded — trying next model...", flush=True)
                skipped.append(f"{model}(503)")
                continue
            raise  # any other error (400, 403, 500, etc.) is a hard failure
    # All models exhausted
    raise Exception(
        f"{stage}: All models exhausted. Skipped: {skipped}. Last error: {last_err}. "
        f"Check https://ai.dev/rate-limit for quota info."
    )



# ─────────────────────────────────────────────────────────────────────────────
# STAGE 0: COMPANY + ROLE INTELLIGENCE (Google Search Grounding)
# Uses Gemini's built-in Google Search tool — no extra API key needed.
# Searches for company tech stack, hiring signals, culture, and role context.
# Result is injected into Stage 2 prompt for smarter resume targeting.
# ─────────────────────────────────────────────────────────────────────────────
def run_stage0_intel(company: str, role: str, api_key: str,
                     headers: dict, models: list) -> dict:
    """
    Query Gemini with Google Search grounding to get company + role intelligence.
    Returns a structured dict with tech stack, culture signals, shortlist tips.
    Falls back to empty dict on any failure — Stage 0 is enhancement, not critical.
    """
    grounding_prompt = f"""Research the company "{company}" and the role "{role}".
Find and return ONLY valid JSON — no markdown, no explanation.

Return this exact schema:
{{
  "company_summary": "1 sentence: what {company} does and their tech focus",
  "tech_stack": ["actual technologies {company} is known to use internally"],
  "what_they_value": ["3-5 specific traits/skills {company} looks for in {role} candidates"],
  "shortlist_signals": ["3-4 specific things that make a {role} candidate stand out at {company}"],
  "role_context": "1 sentence: what {role} actually does day-to-day at {company}",
  "culture_keywords": ["3-5 culture/work-style words from {company} job postings or reviews"],
  "avoid_signals": ["2-3 things that typically get candidates rejected for this role"]
}}

If you cannot find specific information about {company}, use general industry knowledge for a {role} at a similar company."""

    # Gemini Search Grounding payload — adds googleSearch tool
    grounding_payload = {
        "contents": [{"parts": [{"text": grounding_prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "maxOutputTokens": 800,
            "temperature": 0.1
        }
    }

    try:
        resp = gemini_call(models, api_key, headers, grounding_payload, stage="Stage 0")
        raw = resp["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw).strip()
        intel = json_repair.loads(raw)
        print(f"[Stage 0] ✓ Company intel retrieved for {company}", flush=True)
        return intel
    except json.JSONDecodeError:
        print(f"[Stage 0] JSON parse failed — using empty intel", flush=True)
        return {}
    except Exception as e:
        print(f"[Stage 0] Failed: {e} — continuing without intel", flush=True)
        return {}

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

    # ── Cache check — return instantly if same request was already processed ──
    cache_key = make_cache_key(jd, company, role, role_type)
    if cache_key in _RESUME_CACHE:
        print(f"[Cache] HIT for key {cache_key} — returning cached result", flush=True)
        cached = _RESUME_CACHE[cache_key].copy()
        cached["from_cache"] = True
        return jsonify(cached)
    print(f"[Cache] MISS for key {cache_key} — running pipeline", flush=True)

    try:
        # ── Model priority: STABLE models first (high quota), preview models last ──
        # gemini-2.0-flash and gemini-1.5-flash have 1500 RPD free tier limits.
        # gemini-2.5-flash-preview has ~50 RPD — exhausted quickly, used as last resort.
        GEMINI_MODELS_PRIORITY = [
            'gemini-2.5-flash',
            'gemini-2.5-flash-lite',
            'gemini-2.5-flash-preview-05-20',
            'gemini-2.0-flash',           # retired but kept as last resort
        ]

        # Filter to models confirmed available for this API key (keeps order)
        try:
            list_resp = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=8
            )
            if list_resp.status_code == 200:
                available_names = [
                    m['name'].replace('models/', '')
                    for m in list_resp.json().get('models', [])
                    if 'generateContent' in m.get('supportedGenerationMethods', [])
                ]
                confirmed = [m for m in GEMINI_MODELS_PRIORITY if m in available_names]
                print(f"[Model discovery] Confirmed in list: {confirmed}", flush=True)
                # Only update priority if we confirmed at least 2 models
                # (keep full list as fallback so gemini_call can try all)
                if len(confirmed) >= 2:
                    GEMINI_MODELS_PRIORITY = confirmed
            else:
                print(f"[Model discovery] HTTP {list_resp.status_code} — using default list", flush=True)
        except Exception as disc_err:
            print(f"[Model discovery] Error: {disc_err} — using default list", flush=True)

        print(f"[Model] Will try in order: {GEMINI_MODELS_PRIORITY}", flush=True)
        headers = {'Content-Type': 'application/json'}

        # ── Load candidate data ───────────────────────────────────────────────
        with open(os.path.join(DATA_DIR, 'resume_ready.json'), 'r') as f:
            profile = json.load(f)
        with open(os.path.join(DATA_DIR, 'projects_master.json'), 'r') as f:
            all_projects_raw = json.load(f)
            all_projects = all_projects_raw.get('projects', all_projects_raw) \
                           if isinstance(all_projects_raw, dict) else all_projects_raw

        # ── STAGE 0: Company + Role Intelligence (Google Search Grounding) ────────
        # Non-blocking — if it fails, pipeline continues without intel
        print(f"[Stage 0] Fetching company intel for {company} / {role}...", flush=True)
        company_intel = run_stage0_intel(company, role, api_key, headers, GEMINI_MODELS_PRIORITY)

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

        resp1_json = gemini_call(GEMINI_MODELS_PRIORITY, api_key, headers, {
            "contents": [{"parts": [{"text": stage1_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 500,
                "responseMimeType": "application/json"
            }
        }, stage="Stage 1")

        try:
            raw1 = resp1_json['candidates'][0]['content']['parts'][0]['text'].strip()
            raw1 = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw1).strip()
            stage1 = json_repair.loads(raw1)
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

        # STAGE 2: Resume Assembly — structured JSON, concise technical English
        # Prompt is designed to produce Marvellous Infosystems-style punchy bullets
        # and Technical Strengths only (no soft skills)
        all_jd_keywords = list(dict.fromkeys(stage1.get('keywords', []) + stage1.get('required', [])))

        stage2_prompt = f"""You are a senior engineering resume writer who produces resumes for Pune tech companies.
Output ONLY valid JSON. No markdown. No explanation. Nothing before or after the JSON object.

═══ TONE AND STYLE RULES (CRITICAL) ═══
The reference style is: DIRECT. TECHNICAL. CONCISE. NO FLUFF.

GOOD bullet (Marvellous Infosystems style):
  "Built multi-client FTP server using POSIX threads and TCP communication."
  "Developed RESTful backend services for batch and student data management."
  "Implemented JWT-based RBAC enforcing tenant data isolation across all API endpoints."

BAD bullet (forbidden — do NOT produce these):
  "Spearheaded the development of a highly scalable multi-client FTP architecture leveraging POSIX threads to drive cross-functional RESTful communication."
  "Architected and orchestrated a robust JWT-driven RBAC framework ensuring holistic tenant data sovereignty."

RULES:
1. Output ONLY the JSON object. Nothing before or after.
2. DO NOT include name, email, phone, links, or location — auto-injected.
3. DO NOT include education — auto-injected.
4. Use ONLY skills in AVAILABLE_SKILLS. No additions. No fabrication.
5. SUMMARY: EXACTLY 2 short sentences. Format:
   Sentence 1: "[Degree] candidate with strong foundation in [keyword1], [keyword2], [keyword3] — [capability]."
   Sentence 2: "Hands-on experience [concise achievement] using [tech] through practical projects."
   FORBIDDEN openers: Highly, Results-driven, Passionate, Motivated, Eager, Dynamic, Dedicated, Innovative
6. PROJECT BULLETS — THIS IS THE MOST CRITICAL RULE:
   - Use the pre-written bullets from SELECTED_PROJECTS as your BASE. Do NOT throw them away.
   - Each bullet must be MAXIMUM 1 sentence and MAXIMUM 15 words.
   - You may inject 1 JD keyword per bullet ONLY if it fits naturally in under 15 words.
   - If the keyword makes the sentence longer than 15 words — SKIP THE KEYWORD. Keep the original bullet.
   - NEVER pad, NEVER add adjectives, NEVER add corporate language.
   - EXACTLY 3 bullets per project.
7. EXPERIENCE BULLETS: Copy VERBATIM from CANDIDATE_EXPERIENCE. Do not rewrite. 3 bullets only.
8. TECHNICAL STRENGTHS — STRICT SELECTION RULES:
   - Pick EXACTLY 4 items from STRENGTHS_POOL.
   - ONLY pick items that describe technical/engineering capabilities (architecture, systems, optimization, programming).
   - FORBIDDEN to pick: "quick learner", "adaptability", "analytical problem-solving", "collaborative", 
     "communication", "fast learner", "S9", "S16" or any strength that sounds like a soft skill.
   - MUST pick from: S1, S2, S3, S5, S6, S7, S8, S10, S11, S13, S14, S15 — based on JD match.
9. SKILLS: Reorder items within each category (JD-relevant first). Do NOT add items not in AVAILABLE_SKILLS.
10. KEYWORD COVERAGE: Every keyword in JD_KEYWORDS must appear somewhere in the resume.
    If a keyword doesn't fit naturally in bullets, add it to the Concepts or Exposure skill category.

═══ TARGET INFO ═══
Role: {role} at {company}
JD_KEYWORDS (must all appear): {', '.join(all_jd_keywords)}
Required skills: {', '.join(stage1.get('required', []))}

Company context: {company_intel.get('company_summary', 'N/A')}
What they value: {', '.join(company_intel.get('what_they_value', []))}
Shortlist signals: {', '.join(company_intel.get('shortlist_signals', []))}

═══ DATA TO USE ═══
AVAILABLE_SKILLS:
{json.dumps(skills_to_send, indent=2)}

CANDIDATE_EXPERIENCE (copy bullets VERBATIM — do not rewrite):
{json.dumps(profile.get('experience', []), indent=2)}

SELECTED_PROJECTS (use pre-written bullets as base — keep them short and direct):
{json.dumps(selected, indent=2)}

STRENGTHS_POOL (pick 4 technical ones only — see rule 8):
{json.dumps(profile.get('strengths_pool', {}), indent=2)}

═══ OUTPUT JSON SCHEMA ═══
{{
  "summary": "Sentence 1. Sentence 2.",
  "skills": {{
    "Languages": ["item1", "item2"],
    "Backend": ["item1", "item2"],
    "Databases": ["item1"],
    "Tools": ["item1", "item2"],
    "Concepts": ["item1", "item2"]
  }},
  "experience": [
    {{
      "role": "Software Developer Intern",
      "company": "SetTribe IT Solutions",
      "location": "Pune",
      "period": "Feb 2026 -- Ongoing",
      "bullets": ["verbatim bullet 1", "verbatim bullet 2", "verbatim bullet 3"]
    }}
  ],
  "projects": [
    {{
      "name": "project name",
      "subtitle": "project subtitle",
      "tech": "tech stack string",
      "bullets": ["max 15 words bullet 1", "max 15 words bullet 2", "max 15 words bullet 3"]
    }}
  ],
  "strengths": ["technical strength 1", "technical strength 2", "technical strength 3", "technical strength 4"]
}}"""

        # Wrap Stage 2 in a retry loop to automatically handle LLM truncations
        resume_json = None
        for attempt in range(1, 4):
            resp2_json = gemini_call(GEMINI_MODELS_PRIORITY, api_key, headers, {
                "contents": [{"parts": [{"text": stage2_prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 3500, 
                    "temperature": 0.3 + (attempt * 0.1), # vary temp slightly on retry
                    "responseMimeType": "application/json"
                }
            }, stage=f"Stage 2 (Attempt {attempt})")

            raw2 = resp2_json['candidates'][0]['content']['parts'][0]['text'].strip()
            raw2 = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw2).strip()

            try:
                resume_json = json_repair.loads(raw2)
            except json.JSONDecodeError as e:
                if attempt < 3:
                    print(f"[Stage 2] Attempt {attempt} JSON parse failed, retrying...", flush=True)
                    time.sleep(2)
                    continue
                raise Exception(f"Stage 2 JSON parse failed after 3 attempts: {e}. Raw: {raw2[:300]}")

            # ── FIX: Strict schema validation — catch LLM truncation before LaTeX ──
            REQUIRED_KEYS = ['summary', 'skills', 'experience', 'projects', 'strengths']
            is_valid = True
            for key in REQUIRED_KEYS:
                val = resume_json.get(key)
                if not val:
                    is_valid = False
                    raw_preview = raw2[:200] if len(raw2) < 300 else raw2[-200:]
                    err_msg = f"Validation Error: '{key}' is missing or empty. LLM likely truncated."
                    break
            
            if is_valid and len(resume_json.get('projects', [])) < 1:
                is_valid = False
                err_msg = "Validation Error: 'projects' array is empty."
            if is_valid and len(resume_json.get('strengths', [])) < 2:
                is_valid = False
                err_msg = "Validation Error: 'strengths' array has fewer than 2 items."

            if is_valid:
                print(f"[Stage 2] ✓ Schema validation passed on attempt {attempt}", flush=True)
                break
            else:
                if attempt < 3:
                    print(f"[Stage 2] Attempt {attempt} failed validation: {err_msg}. Retrying...", flush=True)
                    time.sleep(2)
                else:
                    raise Exception(f"{err_msg} Last 200 chars: {raw_preview}")

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

            # ATS: score by category (Required 60%, Preferred 25%, General 15%)
            if pdf_available:
                required_kws  = list(dict.fromkeys(stage1.get('required', [])))
                preferred_kws = [k for k in stage1.get('preferred', []) if k not in required_kws]
                general_kws   = [k for k in stage1.get('keywords', [])
                                 if k not in required_kws and k not in preferred_kws]

                def _score(path, kws):
                    if not kws:
                        return {"score": 100, "hits": [], "misses": [], "total": 0}
                    return score_ats_from_pdf(path, kws)

                req_ats  = _score(pdf_path, required_kws)
                pref_ats = _score(pdf_path, preferred_kws)
                gen_ats  = _score(pdf_path, general_kws)

                # Weighted score
                w_score = round(
                    req_ats["score"]  * 0.60 +
                    pref_ats["score"] * 0.25 +
                    gen_ats["score"]  * 0.15
                )
                all_hits   = req_ats["hits"]   + pref_ats["hits"]   + gen_ats["hits"]
                all_misses = req_ats["misses"] + pref_ats["misses"] + gen_ats["misses"]
                ats_data = {
                    "score":  w_score,
                    "hits":   all_hits,
                    "misses": all_misses,
                    "total":  len(all_hits) + len(all_misses),
                    "breakdown": {
                        "required":  req_ats,
                        "preferred": pref_ats,
                        "general":   gen_ats
                    }
                }
        else:
            pdf_error = "pdflatex not found — run: sudo apt install texlive-latex-extra -y"
            combined_text = json.dumps(resume_json).lower()
            required_kws  = list(dict.fromkeys(stage1.get('required', [])))
            preferred_kws = [k for k in stage1.get('preferred', []) if k not in required_kws]
            general_kws   = [k for k in stage1.get('keywords', [])
                             if k not in required_kws and k not in preferred_kws]

            def _score_text(kws):
                if not kws:
                    return {"score": 100, "hits": [], "misses": [], "total": 0}
                hits_   = [k for k in kws if k.lower() in combined_text]
                misses_ = [k for k in kws if k.lower() not in combined_text]
                return {"score": round(len(hits_)/len(kws)*100),
                        "hits": hits_, "misses": misses_, "total": len(kws)}

            req_ats  = _score_text(required_kws)
            pref_ats = _score_text(preferred_kws)
            gen_ats  = _score_text(general_kws)
            w_score  = round(req_ats["score"]*0.60 + pref_ats["score"]*0.25 + gen_ats["score"]*0.15)
            ats_data = {
                "score":  w_score,
                "hits":   req_ats["hits"]   + pref_ats["hits"]   + gen_ats["hits"],
                "misses": req_ats["misses"] + pref_ats["misses"] + gen_ats["misses"],
                "total":  len(required_kws) + len(preferred_kws) + len(general_kws),
                "breakdown": {
                    "required":  req_ats,
                    "preferred": pref_ats,
                    "general":   gen_ats
                }
            }

        result_payload = {
            "success":        True,
            "slug":           slug,
            "resume_json":    resume_json,
            "latex":          latex_content,
            "ats":            ats_data,
            "stage1":         stage1,
            "company_intel":  company_intel,
            "pdf_available":  pdf_available,
            "pdf_error":      pdf_error,
            "projects_used":  [p.get('name') for p in selected]
        }
        _RESUME_CACHE[cache_key] = result_payload
        print(f"[Cache] Stored result for key {cache_key}", flush=True)
        return jsonify(result_payload)

    except Exception as e:
        err_str = str(e)
        err_low = err_str.lower()
        print(f"\n!!! GENERATE ERROR (real message): {err_str}\n", flush=True)
        if '400' in err_str and 'api key' in err_low:
            return jsonify({"error": "Invalid Gemini API key. Get one at aistudio.google.com"}), 401
        if '403' in err_str:
            return jsonify({"error": "API key lacks Gemini access. Enable at aistudio.google.com"}), 403
        if '429' in err_str or 'quota exhausted' in err_low or 'too many requests' in err_low:
            # Distinguish per-minute vs daily exhaustion for better UX
            if 'exhausted for today' in err_low or 'midnight' in err_low or 'no working model' in err_low:
                return jsonify({"error": (
                    "Daily quota exhausted for this project — a new API key in the SAME project won't help. "
                    "Fix: go to aistudio.google.com → create a NEW project → generate a key from it. "
                    "Or wait until midnight PT (~12:30 PM IST tomorrow)."
                )}), 429
            return jsonify({"error": "Rate limit hit (per-minute) — wait 60 seconds and try again"}), 429
        if 'rate limit' in err_low or 'ratelimit' in err_low:
            return jsonify({"error": "Rate limit hit — wait 60 seconds and try again"}), 429
        if 'invalid api key' in err_low or 'api_key' in err_low:
            return jsonify({"error": "Invalid Gemini API key — check it starts with AIza"}), 401
        if 'stage 1 api error' in err_low or 'stage 2 api error' in err_low:
            return jsonify({"error": f"Gemini API call failed: {err_str}"}), 500
        return jsonify({"error": err_str}), 500

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3: IMPROVEMENT ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/improve', methods=['POST'])
def improve():
    data       = request.json
    api_key    = data.get('api_key')
    jd         = data.get('jd', '')
    resume_json = data.get('resume_json', {})
    stage1     = data.get('stage1', {})
    ats        = data.get('ats', {})

    if not api_key:
        return jsonify({"error": "API key required"}), 401

    breakdown  = ats.get('breakdown', {})
    miss_req   = breakdown.get('required',  {}).get('misses', ats.get('misses', []))
    miss_pref  = breakdown.get('preferred', {}).get('misses', [])
    hit_req    = breakdown.get('required',  {}).get('hits',   [])
    current_score = ats.get('score', 0)

    improve_prompt = f"""You are an expert ATS resume coach.
Analyze the resume below against this job description and provide SPECIFIC, ACTIONABLE improvements.

Current ATS Score: {current_score}%
Missing REQUIRED keywords (critical — fix these first): {miss_req}
Missing PREFERRED keywords: {miss_pref}
Already matching required keywords: {hit_req}

Job Description (first 2000 chars):
{jd[:2000]}

Current Resume JSON:
{json.dumps(resume_json, indent=2)[:3000]}

Return ONLY valid JSON in exactly this schema, no markdown:
{{
  "estimated_score_after": <integer 0-100, realistic estimate if all fixes applied>,
  "priority_fixes": [
    {{
      "section": "summary|skills|experience|projects",
      "issue": "one sentence describing the specific gap",
      "fix": "exact rewrite or addition — copy-paste ready"
    }}
  ],
  "skills_to_add": ["skill1", "skill2"],
  "bullets_to_rewrite": [
    {{
      "original": "existing bullet text (shortened)",
      "improved": "rewritten bullet that naturally includes missing keyword"
    }}
  ],
  "summary_note": "one sentence overall assessment"
}}

Focus on: (1) Required keywords not in resume — highest priority. (2) Natural keyword integration, not keyword stuffing. (3) Maximum 5 priority_fixes, 3 bullets_to_rewrite."""

    try:
        GEMINI_MODELS_PRIORITY = [
            'gemini-2.5-flash',
            'gemini-2.5-flash-lite',
            'gemini-2.5-flash-preview-05-20',
            'gemini-2.0-flash',
        ]
        headers = {'Content-Type': 'application/json'}
        resp_json = gemini_call(GEMINI_MODELS_PRIORITY, api_key, headers, {
            "contents": [{"parts": [{"text": improve_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 3500, 
                "temperature": 0.2,
                "responseMimeType": "application/json"
            }
        }, stage="Improve")

        raw = resp_json['candidates'][0]['content']['parts'][0]['text'].strip()
        raw = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw).strip()
        
        try:
            result = json_repair.loads(raw)
            return jsonify({"success": True, "improvement": result})
        except json.JSONDecodeError as e:
            print(f"\n[Improvement API] LLM returned invalid JSON:\n{raw}\n", flush=True)
            return jsonify({"error": f"LLM returned invalid JSON: {e}"}), 500
    except Exception as e:
        err_str = str(e)
        err_low = err_str.lower()
        if '429_RATE_LIMITED' in err_str or 'quota exhausted' in err_low:
            return jsonify({"error": "Rate limit — wait 60s and try again"}), 429
        return jsonify({"error": err_str}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)