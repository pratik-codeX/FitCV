import os
import re
import ast

with open('app.py', 'r') as f:
    content = f.read()

# We will completely replace the /api/generate route with two new routes
generate_route_match = re.search(r"@app\.route\('/api/generate', methods=\['POST'\]\)\ndef generate\(\):.*?(?=@app\.route\('/api/improve'|# ─────────────────────────────────────────────────────────────────────────────\n# STAGE 3)", content, re.DOTALL)

if not generate_route_match:
    print("Could not find generate route")
    exit(1)

generate_code = generate_route_match.group(0)

# We will read app_backup.py or just use strings to craft the new routes.
# It is simpler to just write the new routes as strings and inject them.

new_routes = """@app.route('/api/analyze-job', methods=['POST'])
def analyze_job():
    data      = request.json
    api_key   = data.get('api_key')
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

        stage1_prompt = f\"\"\"You are a JD keyword extractor. Return ONLY valid JSON, no markdown, no explanation.

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
{jd[:3000]}\"\"\"

        resp1_json = gemini_call(GEMINI_MODELS_PRIORITY, api_key, headers, {
            "contents": [{"parts": [{"text": stage1_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 500,
                "responseMimeType": "application/json"
            }
        }, stage="Stage 1")

        try:
            raw1 = resp1_json['candidates'][0]['content']['parts'][0]['text'].strip()
            raw1 = re.sub(r'^```[a-z]*\\n?|\\n?```$', '', raw1).strip()
            stage1 = json_repair.loads(raw1)
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
            keyword_score = 0
            p_tags = [t.lower() for t in p.get('tags', [])]
            for tag in p_tags:
                for tgt in target_tags:
                    if tag in tgt or tgt in tag:
                        keyword_score += 1
            
            p_text = " ".join(p_tags) + " " + p.get('tech', '') + " " + p.get('subtitle', '')
            p_emb = get_embedding(p_text, api_key)
            semantic_score = cosine_similarity(jd_emb, p_emb) * 10
            
            p_cats = set(get_category(t) for t in p_tags) - {"other"}
            coverage_score = len(p_cats.intersection(jd_categories)) * 3

            base_score = (keyword_score * 2) + semantic_score + coverage_score + ((3 - p.get('priority', 3)) * 2)
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
                "reasons": [
                    f"Semantic Match: {round(p.get('_semantic_score',0), 2)}/10",
                    f"Categories: {', '.join(p.get('_cats', []))}"
                ]
            })
            
        alternative_projects = []
        for p in all_projects:
            if p not in selected:
                alternative_projects.append({
                    "id": p.get('id'),
                    "name": p.get('name'),
                    "score": round(p.get('_final_score', p.get('_base_score', 0)), 2),
                    "reasons": [f"Categories: {', '.join(p.get('_cats', []))}"]
                })

        coverage_data = {"frontend": 0, "backend": 0, "database": 0, "cloud": 0, "ai": 0}
        for cat, items in profile.get('skills_pool', {}).items():
            for item in items:
                c = get_category(item)
                if c in coverage_data: coverage_data[c] += 5
        for p in selected:
            for tech in p.get('tech', '').split(','):
                c = get_category(tech.strip())
                if c in coverage_data: coverage_data[c] += 20
        for k in coverage_data: coverage_data[k] = min(100, coverage_data[k])

        combined_evidence = json.dumps(profile).lower() + " " + json.dumps(all_projects).lower()
        missing_keywords = [kw for kw in target_tags if kw.lower() not in combined_evidence]
        missing_categories = [c for c in jd_categories if coverage_data.get(c, 0) < 30]

        return jsonify({
            "recommended_projects": recommended_projects,
            "alternative_projects": alternative_projects,
            "coverage": coverage_data,
            "missing_keywords": missing_keywords[:5],
            "missing_categories": missing_categories,
            "stage1": stage1,
            "company_intel": company_intel,
            "jd_categories": list(jd_categories)
        })

    except Exception as e:
        err_str = str(e)
        return jsonify({"error": err_str}), 500


@app.route('/api/generate-resume', methods=['POST'])
def generate_resume():
    data      = request.json
    api_key   = data.get('api_key')
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
        elif 'full' in role_lower:
            skills_to_send = {
                "Languages":  skills_pool.get('languages', []),
                "Backend":    skills_pool.get('backend', []),
                "Frontend":   skills_pool.get('frontend', []),
                "Databases":  skills_pool.get('databases', []),
                "Tools":      skills_pool.get('tools_java', skills_pool.get('tools_general', [])),
                "Concepts":   skills_pool.get('concepts_core', []) + skills_pool.get('concepts_backend', [])
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

        stage2_prompt = f\"\"\"You are a senior engineering resume writer who produces resumes for Pune tech companies.
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
{json.dumps(profile.get('strengths_pool', {{}}), indent=2)}

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
}}\"\"\"

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
            raw2 = re.sub(r'^```[a-z]*\\n?|\\n?```$', '', raw2).strip()

            try:
                resume_json = json_repair.loads(raw2)
            except json.JSONDecodeError as e:
                if attempt < 3:
                    time.sleep(2)
                    continue
                raise Exception(f"Stage 2 JSON parse failed after 3 attempts")

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

            if is_valid:
                gen_projects_str = json.dumps(resume_json.get('projects', [])).lower()
                for sel_proj in selected:
                    original_techs = [t.strip().lower() for t in sel_proj.get('tech', '').split(',')]
                    for t in original_techs:
                        if t and t not in gen_projects_str:
                            if get_category(t) in ['frontend', 'cloud', 'backend', 'database']:
                                is_valid = False
                                err_msg = f"Validation Error: Major technology '{t}' dropped from project '{sel_proj.get('name')}'"
                                break
                    if not is_valid:
                        break

            if is_valid:
                break
            else:
                if attempt < 3:
                    time.sleep(2)
                else:
                    raise Exception(f"{err_msg}")

        if 'skills' in resume_json:
            resume_json['skills'] = filter_skills(resume_json['skills'])

        ai_detected = []
        profile_str = json.dumps(profile).lower()
        for ai_tool in SKILL_CATEGORIES["ai"]:
            if ai_tool in profile_str:
                ai_detected.append(ai_tool)
        
        if ai_detected:
            if 'skills' not in resume_json: resume_json['skills'] = {}
            if 'AI Tools' not in resume_json['skills']:
                resume_json['skills']['AI Tools'] = list(set([a.title() for a in ai_detected]))

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
        missing_kws = [kw for kw in target_tags if kw not in json.dumps(resume_json).lower()]

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
"""

new_content = content[:generate_route_match.start()] + new_routes + "\n" + content[generate_route_match.end():]

with open('app.py', 'w') as f:
    f.write(new_content)
print("Refactored app.py successfully.")
