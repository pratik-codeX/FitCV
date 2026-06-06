# resume.app

ATS-optimized resume generator. Two focused API calls, zero manual fixes.

## Setup (5 minutes)

```bash
# 1. Install Python deps
pip3 install -r requirements.txt --break-system-packages

# 2. (Optional) Install pdflatex for PDF output
sudo apt install texlive-latex-extra texlive-fonts-recommended -y

# 3. Run
chmod +x run.sh && ./run.sh

# 4. Open browser
# http://localhost:5000
```

## Customize your data

Before generating, edit these two files with YOUR real info:

### `data/resume_ready.json`
Fill in: name, email, phone, LinkedIn, GitHub, CGPA, certifications.

### `data/projects_master.json`
Replace the sample projects with your actual projects.
Each project has:
- `tags` — keywords that trigger auto-selection (match these to JD terms)
- `bullets` — your real bullet points (quantified impact)

## How it works

```
JD Input
  → Stage 1: claude-haiku extracts keywords, role type, required skills (~400 tokens)
  → Project auto-selection: top 3 projects by tag-match score
  → Stage 2: claude-haiku assembles resume with targeted keywords (~950 tokens)
  → ATS validation: local keyword coverage scoring
  → LaTeX injection into frozen template
  → pdflatex compile → PDF
```

Total: ~1400 tokens per resume (Haiku pricing ≈ ₹0.07 per resume)

## Output files

Generated resumes saved to `outputs/` as:
- `.txt` — plain text (copy into any format)
- `.tex` — LaTeX source (compile with pdflatex)
- `.pdf` — compiled PDF (if pdflatex installed)

## API Key

Get your key from https://console.anthropic.com
Uses `claude-haiku-4-5-20251001` — fastest, cheapest model.
Key is sent only to Anthropic's API, never stored.
# FitCV
