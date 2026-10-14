import os
import re
import json
import time
import hashlib
import subprocess
import shutil
import math
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import requests
import json_repair

# ─────────────────────────────────────────────────────────────────────────────
# TAXONOMY ENGINE & SEMANTIC MATCHING
# ─────────────────────────────────────────────────────────────────────────────
SKILL_CATEGORIES = {
    "frontend": ["react", "angular", "vue", "javascript", "typescript", "html", "css", "frontend", "ui", "responsive design", "bootstrap"],
    "backend": ["java", "spring", "node", "python", "api", "microservices", "hibernate", "rest", "backend"],
    "database": ["mysql", "postgresql", "mongodb", "redis", "sql", "nosql", "database", "oracle"],
    "cloud": ["aws", "azure", "gcp", "cloud", "docker", "kubernetes", "ci/cd", "jenkins", "terraform"],
    "ai": ["openai", "gemini", "langchain", "rag", "llm", "ai", "automation", "prompt engineering", "machine learning"]
}

COMMON_SYNONYMS = {
    "java programming": "java",
    "java developer": "java",
    "problem solving skills": "problem solving",
    "problem solving": "problem solving",
    "analytical problem solving": "problem solving",
    "software development lifecycle": "sdlc",
    "software development life cycle": "sdlc",
    "sdlc": "sdlc",
    "object oriented programming": "oop",
    "object-oriented programming": "oop",
    "oop": "oop",
    "data structures": "dsa",
    "data structures & algorithms": "dsa",
    "data structures and algorithms": "dsa",
    "dsa": "dsa",
    "restful api": "rest api",
    "restful apis": "rest api",
    "rest api": "rest api",
    "rest apis": "rest api",
    "web api": "api",
    "web apis": "api",
    "relational database": "database",
    "sql database": "database",
    "nosql database": "database",
    "version control": "git",
    "git version control": "git",
    "github": "git",
    "ci/cd": "ci/cd",
    "continuous integration": "ci/cd",
    "continuous deployment": "ci/cd",
    "c++ programming": "cpp",
    "c++": "cpp",
    "c programming": "c",
    "c language": "c",
    "docker containers": "docker",
    "docker": "docker",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "agile methodologies": "agile",
    "agile cycle": "agile",
    "agile sprint": "agile",
    "multithreaded programming": "multithreading",
    "multithreading": "multithreading",
    "concurrent programming": "concurrency",
    "concurrency": "concurrency",
}

def get_category(skill: str) -> str:
    s = skill.lower()
    for cat, keywords in SKILL_CATEGORIES.items():
        if any(kw in s for kw in keywords):
            return cat
    return "other"

def cosine_similarity(v1, v2):
    if not v1 or not v2: return 0.0
    dot = sum(a*b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a*a for a in v1))
    norm2 = math.sqrt(sum(b*b for b in v2))
    if norm1 == 0 or norm2 == 0: return 0.0
    return dot / (norm1 * norm2)

def get_embedding(text: str, api_key: str) -> list:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key}"
    try:
        resp = requests.post(url, headers={'Content-Type': 'application/json'}, json={"model": "models/text-embedding-004", "content": {"parts": [{"text": text}]}}, timeout=5)
        if resp.status_code == 200:
            return resp.json().get('embedding', {}).get('values', [])
    except:
        pass
    return []

_EMBEDDINGS_CACHE = {}

def get_cached_embedding(text: str, api_key: str) -> list:
    text = text.lower().strip()
    if text not in _EMBEDDINGS_CACHE:
        emb = get_embedding(text, api_key)
        if emb:
            _EMBEDDINGS_CACHE[text] = emb
        else:
            _EMBEDDINGS_CACHE[text] = []
    return _EMBEDDINGS_CACHE[text]

def normalize_keyword(kw: str) -> str:
    if not isinstance(kw, str):
        return ""
    kw = kw.lower().strip()
    kw = re.sub(r'\b(programming|skills|development|lifecycle|life cycle|technologies|framework|systems|tools|architecture|developer|methodologies|sprint|cycle|concepts)\b', '', kw)
    kw = re.sub(r'[^a-z0-9+#\-\s]', '', kw)
    kw = re.sub(r'\s+', ' ', kw).strip()
    if kw in COMMON_SYNONYMS:
        return COMMON_SYNONYMS[kw]
    return kw

def compile_project_reasons(p, target_tags, jd_categories):
    reasons = []
    p_tags = [t.lower() for t in p.get('tags', [])]
    
    # 1. Check tag matches
    for tag in p_tags:
        for tgt in target_tags:
            tgt_norm = normalize_keyword(tgt)
            tag_norm = normalize_keyword(tag)
            if tag_norm and tgt_norm and (tag_norm == tgt_norm or tag_norm in tgt_norm or tgt_norm in tag_norm):
                # Capitalize tech name nicely
                tech_display = tag.title()
                if tag.lower() == 'cpp' or tag.lower() == 'c++':
                    tech_display = 'C++'
                elif tag.lower() == 'c':
                    tech_display = 'C'
                elif tag.lower() == 'jwt':
                    tech_display = 'JWT'
                elif tag.lower() in ['api', 'apis', 'rest-api']:
                    tech_display = 'REST API'
                elif tag.lower() == 'sql':
                    tech_display = 'SQL'
                elif tag.lower() == 'nosql':
                    tech_display = 'NoSQL'
                elif tag.lower() == 'dbms':
                    tech_display = 'DBMS'
                elif tag.lower() == 'os':
                    tech_display = 'Operating Systems'
                elif tag.lower() == 'dsa':
                    tech_display = 'Data Structures & Algorithms'
                elif tag.lower() == 'rbac':
                    tech_display = 'RBAC Authentication'
                
                reason_str = f"✓ {tech_display} Match"
                if reason_str not in reasons:
                    reasons.append(reason_str)
                    
    # 2. Check category matches
    p_cats = set(get_category(t) for t in p_tags) - {"other"}
    for cat in p_cats.intersection(jd_categories):
        cat_display = cat.title()
        if cat == 'db' or cat == 'database':
            cat_display = 'Database'
        reason_str = f"✓ {cat_display} Architecture Match" if cat != 'database' else "✓ Database Match"
        if reason_str not in reasons:
            reasons.append(reason_str)
            
    # 3. Full stack check
    if 'frontend' in p_cats and 'backend' in p_cats:
        reasons.append("✓ Full Stack Match")
        
    return reasons

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


def get_primary_education(profile: dict) -> str:
    """Read education directly from profile data and determine highest current qualification."""
    education_list = profile.get('education', [])
    if not education_list:
        return ""
    
    for edu in education_list:
        deg = edu.get('degree', '').upper()
        status = edu.get('status', '').strip().lower()
        
        deg_label = ""
        if 'MASTER OF COMPUTER APPLICATIONS' in deg or 'MCA' in deg:
            deg_label = "MCA"
        elif 'BACHELOR OF COMPUTER APPLICATIONS' in deg or 'BCA' in deg:
            deg_label = "BCA"
        elif 'BACHELOR OF TECHNOLOGY' in deg or 'BTECH' in deg:
            deg_label = "BTech"
        elif 'BACHELOR OF ENGINEERING' in deg or 'BE' in deg:
            deg_label = "BE"
        elif 'HIGHER SECONDARY' in deg or 'HSC' in deg or '12TH' in deg:
            deg_label = "HSC"
        else:
            match = re.search(r'\b[A-Za-z]+\b', edu.get('degree', ''))
            if match:
                deg_label = match.group(0)
            else:
                deg_label = edu.get('degree', '')
        
        if not deg_label:
            continue
            
        if status == 'pursuing' or 'pursuing' in edu.get('year', '').lower():
            return f"{deg_label} Candidate"
        else:
            return f"{deg_label} Graduate"
            
    return ""


def validate_education(summary: str, primary_edu: str) -> bool:
    """Compare generated education in summary against profile education. Returns True if valid."""
    if not primary_edu:
        return True
    
    summary_lower = summary.lower()
    edu_lower = primary_edu.lower()
    
    all_degrees = ["btech", "b.tech", "mca", "bca", "bsc", "b.sc", "msc", "m.sc", "be", "b.e", "mtech", "m.tech"]
    
    mentioned = []
    for d in all_degrees:
        if re.search(r'\b' + re.escape(d) + r'\b', summary_lower):
            mentioned.append(d)
            
    if "master of computer applications" in summary_lower:
        mentioned.append("mca")
    if "bachelor of computer applications" in summary_lower:
        mentioned.append("bca")
    if "bachelor of technology" in summary_lower:
        mentioned.append("btech")
    if "bachelor of engineering" in summary_lower:
        mentioned.append("be")
        
    mentioned = list(set(mentioned))
    
    primary_degree_type = ""
    for d in all_degrees:
        if d in edu_lower:
            primary_degree_type = d
            break
            
    if primary_degree_type:
        for m in mentioned:
            if m != primary_degree_type:
                return False
        if primary_degree_type not in summary_lower:
            return False
            
    return True


def extract_ai_evidence(profile: dict, selected_projects: list) -> list:
    """Extract AI tools only if explicitly present in projects_master.json (selected), resume_ready.json, experience, or certifications."""
    ai_keywords = [
        "gemini api", "openai api", "langchain", "rag", 
        "prompt engineering", "workflow automation", "ai applications",
        "gemini", "openai", "llm", "large language model", 
        "artificial intelligence", "machine learning"
    ]
    
    found_tools = set()
    
    def scan_text(text: str):
        if not text: return
        t_low = text.lower()
        for kw in ai_keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', t_low):
                if kw in ["gemini api", "gemini"]:
                    found_tools.add("Gemini API")
                elif kw in ["openai api", "openai"]:
                    found_tools.add("OpenAI API")
                elif kw == "langchain":
                    found_tools.add("LangChain")
                elif kw == "rag":
                    found_tools.add("RAG")
                elif kw == "prompt engineering":
                    found_tools.add("Prompt Engineering")
                elif kw == "workflow automation":
                    found_tools.add("Workflow Automation")
                elif kw in ["ai applications", "artificial intelligence", "ai", "llm", "large language model", "machine learning"]:
                    found_tools.add("AI Applications")
                    
    for cat, items in profile.get('skills_pool', {}).items():
        for item in items:
            scan_text(item)
            
    for exp in profile.get('experience', []):
        scan_text(exp.get('role', ''))
        scan_text(exp.get('company', ''))
        for bullet in exp.get('bullets', []):
            scan_text(bullet)
            
    for cert in profile.get('certifications', []):
        if isinstance(cert, str):
            scan_text(cert)
        elif isinstance(cert, dict):
            scan_text(cert.get('name', ''))
            scan_text(cert.get('authority', ''))
            
    for p in selected_projects:
        scan_text(p.get('name', ''))
        scan_text(p.get('subtitle', ''))
        scan_text(p.get('tech', ''))
        for tag in p.get('tags', []):
            scan_text(tag)
        for b in p.get('bullets', []):
            scan_text(b)
            
    return sorted(list(found_tools))


def cleanup_empty_sections(resume_json: dict) -> dict:
    """Automatically remove sections with empty content, placeholder values, or single generic words."""
    if 'skills' not in resume_json:
        return resume_json
        
    skills = resume_json['skills']
    if not isinstance(skills, dict):
        return resume_json
        
    keys_to_delete = []
    for section_name, items in list(skills.items()):
        if not items:
            keys_to_delete.append(section_name)
            continue
            
        if not isinstance(items, list):
            keys_to_delete.append(section_name)
            continue
            
        cleaned_items = []
        for item in items:
            if not isinstance(item, str):
                continue
            item_strip = item.strip()
            item_lower = item_strip.lower()
            sec_lower = section_name.lower()
            
            if item_lower in ["n/a", "none", "placeholder", "null", "undefined"]:
                continue
                
            if item_lower == sec_lower:
                continue
            if sec_lower == "ai tools" and item_lower in ["ai", "ai tools"]:
                continue
            if sec_lower == "cloud" and item_lower in ["cloud", "cloud tools"]:
                continue
            if sec_lower == "skills" and item_lower in ["skills", "skill"]:
                continue
                
            cleaned_items.append(item_strip)
            
        if not cleaned_items:
            keys_to_delete.append(section_name)
        else:
            skills[section_name] = cleaned_items
            
    for key in keys_to_delete:
        del skills[key]
        
    return resume_json


def clean_project_name(name: str) -> str:
    # Lowercase, replace z with s to normalize customized/customised
    n = name.lower().replace('customised', 'customized')
    # Remove bracketed tags like [full-stack] or [backend]
    n = n.replace('[full-stack]', '').replace('[backend]', '').replace('[systems]', '')
    # Keep only alphanumeric characters and spaces
    n = re.sub(r'[^a-z0-9\s]', '', n)
    return " ".join(n.split())


def validate_resume_integrity(resume_json: dict, profile: dict, selected_projects: list, role_type: str = '') -> dict:
    """Validate resume sections for factual accuracy, AI sections, project correctness, and tech preservation."""
    primary_edu = get_primary_education(profile)
    summary = resume_json.get('summary', '')
    education_valid = validate_education(summary, primary_edu)
    
    ai_evidence = extract_ai_evidence(profile, selected_projects)
    ai_skills = resume_json.get('skills', {}).get('AI Tools', [])
    
    if not ai_evidence:
        ai_section_valid = (len(ai_skills) == 0)
    else:
        ai_section_valid = True
        for tool in ai_skills:
            if tool not in ai_evidence and tool.lower() not in [t.lower() for t in ai_evidence]:
                ai_section_valid = False
                break
                
    generated_proj_names = [clean_project_name(p.get('name', '')) for p in resume_json.get('projects', [])]
    selected_proj_names = [clean_project_name(p.get('name', '')) for p in selected_projects]
    
    projects_valid = True
    for name in selected_proj_names:
        if not name: continue
        found = False
        for gen_name in generated_proj_names:
            if not gen_name: continue
            if name in gen_name or gen_name in name:
                found = True
                break
        if not found:
            projects_valid = False
            break
            
    technology_preserved = True
    gen_projects_str = json.dumps(resume_json.get('projects', [])).lower()
    for sel_proj in selected_projects:
        original_techs = [t.strip().lower() for t in sel_proj.get('tech_display', sel_proj.get('tech', '')).split(',')]
        for t in original_techs:
            if t and t not in gen_projects_str:
                if get_category(t) in ['frontend', 'cloud', 'backend', 'database']:
                    technology_preserved = False
                    break
        if not technology_preserved:
            break
            
    role_evidence_valid = True
    rt = role_type.lower()
    resume_str = json.dumps(resume_json).lower()
    
    if 'front' in rt or 'ui' in rt:
        # Require at least one occurrence of: React, Angular, Vue, JavaScript, Frontend, UI
        frontend_kws = ["react", "angular", "vue", "javascript", "frontend", "ui"]
        if not any(kw in resume_str for kw in frontend_kws):
            role_evidence_valid = False
            
    elif 'backend' in rt or 'java' in rt:
        # Require at least one occurrence of: Java, Spring Boot, REST API, Backend
        backend_kws = ["java", "spring boot", "rest api", "restful api", "backend"]
        if not any(kw in resume_str for kw in backend_kws):
            role_evidence_valid = False
            
    elif 'system' in rt or 'c++' in rt or 'cpp' in rt:
        # Require at least one occurrence of: C, C++, Linux, Operating Systems
        systems_kws = ["c++", "cpp", "linux", "operating systems", "operating system"]
        has_c = bool(re.search(r'\bc\b', resume_str))
        if not (has_c or any(kw in resume_str for kw in systems_kws)):
            role_evidence_valid = False
            
    status = "PASS" if (education_valid and ai_section_valid and projects_valid and technology_preserved and role_evidence_valid) else "FAIL"
    return {
        "education_valid": education_valid,
        "ai_section_valid": ai_section_valid,
        "projects_valid": projects_valid,
        "technology_preserved": technology_preserved,
        "role_evidence_valid": role_evidence_valid,
        "status": status
    }


def generate_quality_report(resume_json: dict, profile: dict, selected_projects: list, integrity_res: dict) -> dict:
    """Generate the final resume quality validation report."""
    primary_edu = get_primary_education(profile)
    education_source = primary_edu.split()[0] if primary_edu else "None"
    
    empty_sections_removed = True
    
    ai_evidence = extract_ai_evidence(profile, selected_projects)
    ai_section_present = 'AI Tools' in resume_json.get('skills', {})
    ai_section_removed = (not ai_evidence) and (not ai_section_present)
    
    score = 0
    if integrity_res.get('education_valid'): score += 40
    if integrity_res.get('ai_section_valid'): score += 20
    if integrity_res.get('projects_valid'): score += 20
    if integrity_res.get('technology_preserved'): score += 20
    
    return {
        "education_source": education_source,
        "summary_verified": integrity_res.get('education_valid', False),
        "empty_sections_removed": empty_sections_removed,
        "ai_section_removed": ai_section_removed,
        "resume_integrity_score": score
    }


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
        if not isinstance(intel, dict):
            raise ValueError("Intel is not a dictionary")
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


@app.route('/api/analyze-job', methods=['POST'])
def analyze_job():
    data      = request.json
    api_key   = data.get('api_key') or os.environ.get('GOOGLE_API_KEY')
    jd        = data.get('jd', '')
    company   = data.get('company', 'Unknown')
    role      = data.get('role', 'Role')
    role_type = data.get('role_type', '')

    if not api_key:
        return jsonify({"error": "API key required"}), 401
    if len(jd.strip()) < 100:
        return jsonify({"error": "JD too short — paste full job description"}), 400

    try:
        GEMINI_MODELS_PRIORITY = [
            'gemini-2.5-flash',
            'gemini-2.5-flash-lite',
            'gemini-2.5-flash-preview-05-20',
            'gemini-2.0-flash',
        ]
        headers = {'Content-Type': 'application/json'}

        with open(os.path.join(DATA_DIR, 'resume_ready.json'), 'r') as f:
            profile = json.load(f)
        with open(os.path.join(DATA_DIR, 'projects_master.json'), 'r') as f:
            all_projects_raw = json.load(f)
            all_projects = all_projects_raw.get('projects', all_projects_raw) if isinstance(all_projects_raw, dict) else all_projects_raw

        company_intel = run_stage0_intel(company, role, api_key, headers, GEMINI_MODELS_PRIORITY)

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
            if not isinstance(stage1, dict):
                raise ValueError("Stage 1 response is not a dictionary")
        except Exception:
            stage1 = {"role_type": role_type, "seniority": "fresher",
                      "keywords": [], "required": [], "preferred": [],
                      "responsibilities": [], "ai_ml_cloud_mentioned": False}

        target_tags = [kw.lower() for kw in stage1.get('keywords', []) + stage1.get('required', [])]
        target_tags.append(role_type.lower())

        jd_text = " ".join(target_tags)
        jd_emb = get_embedding(jd_text, api_key)
        jd_categories = set(get_category(t) for t in target_tags) - {"other"}

        for p in all_projects:
            # 1. Keyword Score (0 to 10)
            p_tags = [t.lower() for t in p.get('tags', [])]
            norm_p_tags = [normalize_keyword(t) for t in p_tags if t]
            norm_target_tags = [normalize_keyword(tgt) for tgt in target_tags if tgt]
            
            keyword_matches = 0
            matched_tgts = set()
            for np in norm_p_tags:
                if not np: continue
                for nt in norm_target_tags:
                    if not nt: continue
                    if np == nt or np in nt or nt in np:
                        if nt not in matched_tgts:
                            keyword_matches += 1
                            matched_tgts.add(nt)
                            break
            
            if keyword_matches == 0:
                keyword_score = 0.0
            elif keyword_matches == 1:
                keyword_score = 5.0
            elif keyword_matches == 2:
                keyword_score = 8.0
            else:
                keyword_score = 10.0

            # Collect matches display list
            matched_keywords_list = []
            for tag in p_tags:
                for tgt in target_tags:
                    tgt_norm = normalize_keyword(tgt)
                    tag_norm = normalize_keyword(tag)
                    if tag_norm and tgt_norm and (tag_norm == tgt_norm or tag_norm in tgt_norm or tgt_norm in tag_norm):
                        matched_keywords_list.append(tag.title())
            seen = set()
            unique_matches = []
            for m in matched_keywords_list:
                if m.lower() not in seen:
                    seen.add(m.lower())
                    unique_matches.append(m)
            p['_matches'] = unique_matches

            # 2. Category Score (0 to 10)
            p_cats = set(get_category(t) for t in p_tags) - {"other"}
            for tech in p.get('tech_display', p.get('tech', '')).split(','):
                tech_cat = get_category(tech.strip())
                if tech_cat != 'other':
                    p_cats.add(tech_cat)
            category_score = 10.0 * len(p_cats.intersection(jd_categories)) / max(1, len(jd_categories))

            # 3. Embedding Similarity (0 to 10)
            p_text = " ".join(p_tags) + " " + p.get('tech', '') + " " + p.get('subtitle', '')
            p_emb = get_embedding(p_text, api_key)
            if not jd_emb or not p_emb:
                embedding_score = keyword_score
            else:
                embedding_score = cosine_similarity(jd_emb, p_emb) * 10

            # 4. Final Semantic Hybrid Score (0 to 10)
            semantic_score = (keyword_score * 0.4) + (category_score * 0.3) + (embedding_score * 0.3)
            
            # Log component scores
            log_data = {
                "project": p.get('name'),
                "keyword_score": round(keyword_score, 1),
                "category_score": round(category_score, 1),
                "embedding_score": round(embedding_score, 1),
                "final_score": round(semantic_score, 1)
            }
            print("PROJECT_SCORE_DEBUG:", json.dumps(log_data), flush=True)

            # Base Score (0 to 100)
            base_score = semantic_score * 10 + ((3 - p.get('priority', 3)) * 2)
            p['_base_score'] = base_score
            p['_cats'] = list(p_cats)
            p['_is_full_stack'] = ('frontend' in p_cats and 'backend' in p_cats)
            p['_semantic_score'] = semantic_score

        all_projects.sort(key=lambda x: x['_base_score'], reverse=True)
        selected = []
        covered_cats = set()
        
        for p in all_projects:
            if len(selected) >= 3:
                break
            redundancy_penalty = 0
            if set(p['_cats']).issubset(covered_cats) and len(selected) > 0:
                redundancy_penalty = 5
            
            p['_final_score'] = p['_base_score'] - redundancy_penalty
            if len(selected) < 3:
                selected.append(p)
                covered_cats.update(set(p['_cats']))
            
        selected.sort(key=lambda x: x.get('_final_score', 0), reverse=True)
        
        recommended_projects = []
        for p in selected:
            recommended_projects.append({
                "id": p.get('id'),
                "name": p.get('name'),
                "score": round(p.get('_final_score', 0), 2),
                "categories": p.get('_cats', []),
                "matches": p.get('_matches', []),
                "reasons": compile_project_reasons(p, target_tags, jd_categories)
            })
            
        alternative_projects = []
        for p in all_projects:
            if p not in selected:
                alternative_projects.append({
                    "id": p.get('id'),
                    "name": p.get('name'),
                    "score": round(p.get('_final_score', p.get('_base_score', 0)), 2),
                    "categories": p.get('_cats', []),
                    "matches": p.get('_matches', []),
                    "reasons": compile_project_reasons(p, target_tags, jd_categories)
                })

        # Calculate coverage using ALL profile evidence
        coverage_data = {"frontend": 0, "backend": 0, "database": 0, "cloud": 0, "ai": 0}
        candidate_evidence = {cat: set() for cat in coverage_data.keys()}
        
        # 1. Skills Pool
        for cat, items in profile.get('skills_pool', {}).items():
            for item in items:
                c = get_category(item)
                if c in candidate_evidence:
                    candidate_evidence[c].add(item.lower().strip())
                    
        # 2. All Projects
        for p in all_projects:
            for tag in p.get('tags', []):
                c = get_category(tag)
                if c in candidate_evidence:
                    candidate_evidence[c].add(tag.lower().strip())
            for tech in p.get('tech_display', p.get('tech', '')).split(','):
                tech = tech.strip()
                if tech:
                    c = get_category(tech)
                    if c in candidate_evidence:
                        candidate_evidence[c].add(tech.lower().strip())
                        
        # 3. Experience
        for exp in profile.get('experience', []):
            for bullet in exp.get('bullets', []):
                for word in re.findall(r'\b\w+\b', bullet.lower()):
                    c = get_category(word)
                    if c in candidate_evidence:
                        candidate_evidence[c].add(word)

        for cat in coverage_data.keys():
            jd_reqs_in_cat = [t for t in target_tags if get_category(t) == cat]
            if not jd_reqs_in_cat:
                # Baseline coverage from candidate profile
                evidence_count = len(candidate_evidence[cat])
                coverage_data[cat] = min(20, max(5, evidence_count * 2))
                if cat == 'frontend' and evidence_count > 0:
                    coverage_data[cat] = 15
                elif cat == 'cloud' and evidence_count > 0:
                    coverage_data[cat] = 10
                elif cat == 'ai' and evidence_count > 0:
                    coverage_data[cat] = 5
            else:
                matched_reqs = 0
                for req in jd_reqs_in_cat:
                    req_norm = normalize_keyword(req)
                    matched = False
                    for ev in candidate_evidence[cat]:
                        ev_norm = normalize_keyword(ev)
                        if req_norm == ev_norm or req_norm in ev_norm or ev_norm in req_norm:
                            matched = True
                            break
                    if matched:
                        matched_reqs += 1
                        
                match_ratio = matched_reqs / len(jd_reqs_in_cat)
                pct = match_ratio * 75
                extra_skills = len([s for s in candidate_evidence[cat] if normalize_keyword(s) not in [normalize_keyword(r) for r in jd_reqs_in_cat]])
                pct += min(25, extra_skills * 3)
                coverage_data[cat] = min(100, max(30, round(pct)))

        # Build comprehensive evidence word list for missing keywords
        evidence_words = []
        for cat, items in profile.get('skills_pool', {}).items():
            evidence_words.extend(items)
        for p in all_projects:
            evidence_words.extend(p.get('tags', []))
            evidence_words.extend(p.get('tech_display', p.get('tech', '')).split(','))
            evidence_words.append(p.get('name', ''))
            evidence_words.append(p.get('subtitle', ''))
        for exp in profile.get('experience', []):
            evidence_words.extend(exp.get('bullets', []))

        matched_keywords = []
        missing_keywords = []
        for kw in target_tags:
            kw_norm = normalize_keyword(kw)
            matched = False
            for ev in evidence_words:
                ev_norm = normalize_keyword(ev)
                if not ev_norm: continue
                if kw_norm == ev_norm or kw_norm in ev_norm or ev_norm in kw_norm:
                    matched = True
                    break
            if not matched:
                kw_emb = get_cached_embedding(kw_norm, api_key)
                if kw_emb:
                    for ev in profile.get('skills_pool', {}).get('concepts_core', []) + profile.get('skills_pool', {}).get('concepts_backend', []) + profile.get('skills_pool', {}).get('concepts_systems', []):
                        ev_norm = normalize_keyword(ev)
                        ev_emb = get_cached_embedding(ev_norm, api_key)
                        if ev_emb and cosine_similarity(kw_emb, ev_emb) >= 0.80:
                            matched = True
                            break
            if matched:
                if kw not in matched_keywords:
                    matched_keywords.append(kw)
            else:
                if kw not in missing_keywords:
                    missing_keywords.append(kw)

        missing_categories = [c for c in jd_categories if coverage_data.get(c, 0) < 30]

        # Calculate Recommendation Confidence Score
        req_kws = stage1.get('required', [])
        if not req_kws:
            req_kws = target_tags
        req_matched = 0
        for rk in req_kws:
            rk_norm = normalize_keyword(rk)
            matched = False
            for ev in evidence_words:
                ev_norm = normalize_keyword(ev)
                if rk_norm == ev_norm or rk_norm in ev_norm or ev_norm in rk_norm:
                    matched = True
                    break
            if matched:
                req_matched += 1
        req_kws_match_ratio = req_matched / max(1, len(req_kws))
        
        req_cats = [c for c in jd_categories if c in coverage_data]
        if req_cats:
            avg_category_coverage = sum(coverage_data[c] for c in req_cats) / len(req_cats)
        else:
            avg_category_coverage = sum(coverage_data.values()) / len(coverage_data)
            
        recommendation_confidence = round(req_kws_match_ratio * 40 + (avg_category_coverage / 100) * 60)
        recommendation_confidence = min(100, max(10, recommendation_confidence))

        return jsonify({
            "recommended_projects": recommended_projects,
            "alternative_projects": alternative_projects,
            "coverage": coverage_data,
            "matched_keywords": matched_keywords,
            "missing_keywords": missing_keywords,
            "missing_categories": missing_categories,
            "stage1": stage1,
            "company_intel": company_intel,
            "jd_categories": list(jd_categories),
            "recommendation_confidence": recommendation_confidence
        })

    except Exception as e:
        err_str = str(e)
        return jsonify({"error": err_str}), 500


@app.route('/api/generate-resume', methods=['POST'])
def generate_resume():
    data      = request.json
    api_key   = data.get('api_key') or os.environ.get('GOOGLE_API_KEY')
    jd        = data.get('jd', '')
    company   = data.get('company', 'Unknown')
    role      = data.get('role', 'Role')
    role_type = data.get('role_type', '')
    relocation = data.get('relocation', '')
    selected_project_ids = data.get('selected_projects', [])
    stage1    = data.get('stage1', {})
    company_intel = data.get('company_intel', {})
    jd_categories = data.get('jd_categories', [])

    if not api_key:
        return jsonify({"error": "API key required"}), 401

    try:
        GEMINI_MODELS_PRIORITY = ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-flash-preview-05-20', 'gemini-2.0-flash']
        headers = {'Content-Type': 'application/json'}

        with open(os.path.join(DATA_DIR, 'resume_ready.json'), 'r') as f:
            profile = json.load(f)
        with open(os.path.join(DATA_DIR, 'projects_master.json'), 'r') as f:
            all_projects_raw = json.load(f)
            all_projects = all_projects_raw.get('projects', all_projects_raw) if isinstance(all_projects_raw, dict) else all_projects_raw

        selected = [p for p in all_projects if p.get('id') in selected_project_ids]
        if not selected:
            return jsonify({"error": "No valid projects selected"}), 400

        for p in selected:
            p_tags = [t.lower() for t in p.get('tags', [])]
            p_cats = set(get_category(t) for t in p_tags) - {"other"}
            p['_is_full_stack'] = ('frontend' in p_cats and 'backend' in p_cats)

        skills_pool = profile.get('skills_pool', {})
        role_lower = role_type.lower()
        if 'c++' in role_lower or 'system' in role_lower or 'embedded' in role_lower:
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Systems":    skills_pool.get('cpp_stack', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_cpp', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', []) + skills_pool.get('concepts_systems', [])
            }
        elif 'full' in role_lower or 'general' in role_lower or 'intern' in role_lower:
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Backend":    skills_pool.get('backend', []),
                "Frontend":   skills_pool.get('frontend', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_java', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', []) + skills_pool.get('concepts_backend', [])
            }
        elif 'front' in role_lower or 'ui' in role_lower or 'react' in role_lower or 'angular' in role_lower:
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Frontend":   skills_pool.get('frontend', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_java', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', [])
            }
        elif 'cloud' in role_lower or 'devops' in role_lower:
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Backend":    skills_pool.get('backend', []),
                "Cloud":      skills_pool.get('exposure', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_java', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', [])
            }
        else:
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Backend":    skills_pool.get('backend', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_java', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', []) + skills_pool.get('concepts_backend', [])
            }
            if stage1.get('ai_ml_cloud_mentioned'):
                skills_to_send["Exposure"] = skills_pool.get('exposure', [])

        all_jd_keywords = list(dict.fromkeys(stage1.get('keywords', []) + stage1.get('required', [])))
        primary_edu = get_primary_education(profile)

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
5. SUMMARY: EXACTLY 2 short sentences.
   - You MUST use the candidate's actual education: "{primary_edu}". Do not mention any other degrees.
   - The summary MUST be strictly evidence-driven using ONLY verified education, internship experience, selected projects, and verified technologies.
   - Do NOT generate BTech Candidate, Cloud Infrastructure Expert, or AI Engineer unless supported by verified profile evidence.
   - Format:
     Sentence 1: "[Degree] candidate with strong foundation in [keyword1], [keyword2], [keyword3] — [capability]."
     Sentence 2: "Experience building [full-stack/backend/systems] applications using [frontend_tech], [backend_tech], and [database_tech]." (Choose "full-stack" if frontend tech is present).
     FORBIDDEN openers: Highly, Results-driven, Passionate, Motivated, Eager, Dynamic, Dedicated, Innovative
6. PROJECT BULLETS — THIS IS THE MOST CRITICAL RULE:
   - Use the pre-written bullets from SELECTED_PROJECTS as your BASE. Do NOT throw them away.
   - Each bullet must be MAXIMUM 1 sentence and MAXIMUM 15 words.
   - You may inject 1 JD keyword per bullet ONLY if it fits naturally in under 15 words.
   - If the keyword makes the sentence longer than 15 words — SKIP THE KEYWORD. Keep the original bullet.
   - NEVER pad, NEVER add adjectives, NEVER add corporate language.
   - EXACTLY 3 bullets per project.
   - For any project labeled [FULL-STACK], EXACTLY ONE bullet MUST explicitly mention the frontend framework, and EXACTLY ONE bullet MUST explicitly mention the backend framework.
7. EXPERIENCE BULLETS: Copy VERBATIM from CANDIDATE_EXPERIENCE. Do not rewrite. 3 bullets only.
8. TECHNICAL STRENGTHS — STRICT SELECTION RULES:
   - Pick EXACTLY 4 items from STRENGTHS_POOL.
   - ONLY pick items that describe technical/engineering capabilities (architecture, systems, optimization, programming).
   - FORBIDDEN to pick: "quick learner", "adaptability", "analytical problem-solving", "collaborative", 
     "communication", "fast learner", "S9", "S16" or any strength that sounds like a soft skill.
   - MUST pick from: S1, S2, S3, S5, S6, S7, S8, S10, S11, S13, S14, S15 — based on JD match.
9. SKILLS: Reorder items within each category (JD-relevant first). Do NOT add items not in AVAILABLE_SKILLS.
10. CATEGORY BALANCE: The JD requires: {', '.join(jd_categories)}. You MUST highlight these categories in the summary, projects, and skills. Do NOT over-optimize only backend keywords if Frontend/Cloud/AI are requested.
11. KEYWORD COVERAGE: Every keyword in JD_KEYWORDS must appear somewhere in the resume.
    If a keyword doesn't fit naturally in bullets, add it to the Concepts or Exposure skill category.
12. TECHNOLOGY PRESERVATION: You MUST retain ALL original technologies mentioned in the project tech stack. Do NOT drop React, frontend frameworks, or cloud tools.

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
{json.dumps([{**p, 'name': f"[FULL-STACK] {{p['name']}}" if p.get('_is_full_stack') else p['name']} for p in selected], indent=2)}

STRENGTHS_POOL (pick 4 technical ones only — see rule 8):
{json.dumps(profile.get('strengths_pool', dict()), indent=2)}

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

        resume_json = None
        for attempt in range(1, 4):
            resp2_json = gemini_call(GEMINI_MODELS_PRIORITY, api_key, headers, {
                "contents": [{"parts": [{"text": stage2_prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 3500, 
                    "temperature": 0.3 + (attempt * 0.1),
                    "responseMimeType": "application/json"
                }
            }, stage=f"Stage 2 (Attempt {attempt})")

            raw2 = resp2_json['candidates'][0]['content']['parts'][0]['text'].strip()
            raw2 = re.sub(r'^```[a-z]*\n?|\n?```$', '', raw2).strip()

            try:
                resume_json = json_repair.loads(raw2)
                if not isinstance(resume_json, dict):
                    raise ValueError("Stage 2 response is not a dictionary")
            except Exception as e:
                if attempt < 3:
                    time.sleep(2)
                    continue
                raise Exception(f"Stage 2 JSON parse failed after 3 attempts")

            if 'skills' in resume_json:
                resume_json['skills'] = filter_skills(resume_json['skills'])
            else:
                resume_json['skills'] = {}

            ai_detected = extract_ai_evidence(profile, selected)
            if ai_detected:
                resume_json['skills']['AI Tools'] = ai_detected
            elif 'AI Tools' in resume_json['skills']:
                del resume_json['skills']['AI Tools']

            resume_json = cleanup_empty_sections(resume_json)

            integrity_res = validate_resume_integrity(resume_json, profile, selected, role_type)

            REQUIRED_KEYS = ['summary', 'skills', 'experience', 'projects', 'strengths']
            is_valid = True
            for key in REQUIRED_KEYS:
                if not resume_json.get(key):
                    is_valid = False
                    err_msg = f"Validation Error: '{key}' is missing or empty."
                    break

            if is_valid and len(resume_json.get('projects', [])) < 1:
                is_valid = False
                err_msg = "Validation Error: 'projects' array is empty."
            if is_valid and len(resume_json.get('strengths', [])) < 2:
                is_valid = False
                err_msg = "Validation Error: 'strengths' array has fewer than 2 items."

            if is_valid and integrity_res['status'] != "PASS":
                is_valid = False
                if not integrity_res['education_valid']:
                    err_msg = "Education Hallucination Detected"
                elif not integrity_res.get('role_evidence_valid', True):
                    err_msg = "Role Evidence Missing"
                else:
                    failed_checks = [k for k, v in integrity_res.items() if v is False]
                    err_msg = f"Validation Failed: {', '.join(failed_checks)}"

            if is_valid:
                quality_report = generate_quality_report(resume_json, profile, selected, integrity_res)
                print("\n=== RESUME_QUALITY_REPORT ===", flush=True)
                print(json.dumps(quality_report, indent=2), flush=True)
                print("=============================\n", flush=True)
                break
            else:
                if attempt < 3:
                    time.sleep(2)
                else:
                    return jsonify({
                        "error": err_msg,
                        "validation": integrity_res,
                        "status": "FAIL"
                    }), 400

        coverage_data = {"frontend": 0, "backend": 0, "database": 0, "cloud": 0, "ai": 0}
        for cat, items in resume_json.get('skills', {}).items():
            for item in items:
                c = get_category(item)
                if c in coverage_data: coverage_data[c] += 10
        for p in resume_json.get('projects', []):
            for tech in p.get('tech', '').split(','):
                c = get_category(tech.strip())
                if c in coverage_data: coverage_data[c] += 20
        for k in coverage_data: coverage_data[k] = min(100, coverage_data[k])
        
        target_tags = [kw.lower() for kw in stage1.get('keywords', []) + stage1.get('required', [])]
        target_tags.append(role_type.lower())
        
        gen_resume_text = json.dumps(resume_json).lower()
        
        missing_kws = []
        for kw in target_tags:
            kw_norm = normalize_keyword(kw)
            matched = False
            if kw_norm in gen_resume_text or kw.lower() in gen_resume_text:
                matched = True
            else:
                # check individual words or phrases in resume
                for w in re.findall(r'\b[a-zA-Z0-9+#\-]+\b', gen_resume_text):
                    w_norm = normalize_keyword(w)
                    if w_norm and (kw_norm == w_norm or kw_norm in w_norm or w_norm in kw_norm):
                        matched = True
                        break
            if not matched:
                missing_kws.append(kw)

        latex_content = generate_latex(resume_json, profile, relocation)
        slug = re.sub(r'[^a-z0-9]', '_', f"{company}_{role}".lower()) + f"_{int(time.time())}"
        
        tex_path = os.path.join(OUTPUTS_DIR, f"{slug}.tex")
        pdf_path = os.path.join(OUTPUTS_DIR, f"{slug}.pdf")
        json_path = os.path.join(OUTPUTS_DIR, f"{slug}.json")
        
        with open(tex_path, 'w') as f:
            f.write(latex_content)
        with open(json_path, 'w') as f:
            json.dump(resume_json, f, indent=2)

        pdf_available = False
        pdf_error = None
        if shutil.which('pdflatex'):
            try:
                subprocess.run(['pdflatex', '-interaction=nonstopmode', f"{slug}.tex"], cwd=OUTPUTS_DIR, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
                pdf_available = True
            except Exception as e:
                pdf_error = str(e)
        else:
            pdf_error = "pdflatex not found"

        ats_data = {}
        if pdf_available:
            required_kws  = list(dict.fromkeys(stage1.get('required', [])))
            preferred_kws = [k for k in stage1.get('preferred', []) if k not in required_kws]
            general_kws   = [k for k in stage1.get('keywords', []) if k not in required_kws and k not in preferred_kws]

            def _score(path, kws):
                if not kws: return {"score": 100, "hits": [], "misses": [], "total": 0}
                res = score_ats_from_pdf(path, kws)
                source_tech_str = " ".join([p.get('tech', '') for p in selected]).lower()
                for kw in list(res["misses"]):
                    if kw.lower() in source_tech_str:
                        res["misses"].remove(kw)
                        res["hits"].append(kw)
                res["score"] = round(len(res["hits"]) / len(kws) * 100) if kws else 100
                return res

            req_ats  = _score(pdf_path, required_kws)
            pref_ats = _score(pdf_path, preferred_kws)
            gen_ats  = _score(pdf_path, general_kws)
            avg_cov = sum(coverage_data.values()) / max(1, len([c for c in jd_categories if c in coverage_data])) if jd_categories else 100
            
            w_score = round(req_ats["score"]*0.4 + avg_cov*0.25 + pref_ats["score"]*0.15 + gen_ats["score"]*0.1 + 10)
            w_score = min(100, w_score)
            
            ats_data = {
                "score":  w_score,
                "hits":   req_ats["hits"] + pref_ats["hits"] + gen_ats["hits"],
                "misses": req_ats["misses"] + pref_ats["misses"] + gen_ats["misses"],
                "total":  len(required_kws) + len(preferred_kws) + len(general_kws),
                "breakdown": {"required": req_ats, "preferred": pref_ats, "general": gen_ats}
            }

        result_payload = {
            "success": True,
            "slug": slug,
            "resume_json": resume_json,
            "latex": latex_content,
            "ats": ats_data,
            "pdf_available": pdf_available,
            "pdf_error": pdf_error,
            "generation_report": {
                "selected_projects": [p.get('name') for p in selected],
                "coverage": coverage_data,
                "missing_keywords": missing_kws[:5]
            }
        }
        return jsonify(result_payload)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
            if not isinstance(result, dict):
                raise ValueError("Improvement response is not a dictionary")
            return jsonify({"success": True, "improvement": result})
        except Exception as e:
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