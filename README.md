# FitCV: ATS-Optimized Resume Generator

FitCV is an intelligent, ATS-optimized resume generator that dynamically tailors your resume to a specific Job Description (JD). It uses AI to extract key requirements from the JD and automatically selects your most relevant projects to build a targeted resume with high keyword coverage.

## Features
- **Dynamic Project Selection**: Automatically picks the best projects from your master list based on JD keywords.
- **ATS-Optimized Formatting**: Generates clean, parseable plain text and LaTeX/PDF formats.
- **Local Data Control**: Your personal information and project data are securely stored locally in JSON files.
- **AI-Powered Assembly**: Leverages AI (e.g., Claude Haiku) to assemble the final targeted bullet points and summary.

## Prerequisites
- Python 3.8+
- [pdflatex](https://www.tug.org/texlive/) (Optional, required if you want to generate PDF output directly)

## Installation & Setup

1. **Clone the repository and navigate to the project directory**

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install LaTeX (Optional but recommended for PDF generation)**
   - **Ubuntu/Debian**:
     ```bash
     sudo apt install texlive-latex-extra texlive-fonts-recommended -y
     ```
   - **Windows**: Install [MiKTeX](https://miktex.org/)
   - **macOS**: Install [MacTeX](https://tug.org/mactex/)

## 🚀 Customizing Your Resume Data (IMPORTANT)

**To generate your own personalized resume, you MUST replace the default data with your actual information.**

The application reads your profile and project data from two JSON files located in the `data/` folder. Open these files in any text editor and update them according to your specific profile:

### 1. `data/resume_ready.json`
This file contains your static, personal information. Update the following sections:
- **`personal`**: Name, email, phone, LinkedIn, GitHub, Location.
- **`education`**: Your degrees, universities, graduation years, and scores/CGPA.
- **`experience`**: Your work history, internships, roles, and bullet points.
- **`skills_pool`**: Categorized lists of your technical skills (languages, frontend, backend, databases, tools).
- **`strengths_pool`**: High-level summaries of your technical strengths.

### 2. `data/projects_master.json`
This file serves as your "Project Bank". You should list *all* your projects here. The app will automatically pick the most relevant ones.
- **`id` & `name`**: Unique identifier and display name.
- **`tags`**: Critical! Add keywords related to the project (e.g., "Java", "Spring Boot", "React", "AWS"). The app matches these tags against the JD to select the best projects for that specific job.
- **`bullets`**: The actual bullet points explaining what you did, the tech used, and the impact/quantifiable results.

## Running the Application

Once you have updated the JSON files with your data:

1. **Start the application**
   - **Linux/macOS**:
     ```bash
     chmod +x run.sh
     ./run.sh
     ```
   - **Windows**:
     ```cmd
     run.bat
     ```

2. **Open your browser**
   Navigate to [http://localhost:5000](http://localhost:5000)

3. **Generate a Resume**
   - Paste the Job Description (JD) into the web interface.
   - Enter your API Key if requested.
   - Click generate to get your tailored resume!

## Output Files
Generated resumes are saved to the `outputs/` directory:
- `*.txt` — Plain text version, great for copying into web forms or Word documents.
- `*.tex` — LaTeX source file.
- `*.pdf` — The beautifully compiled PDF document (requires `pdflatex`).

## How the AI Generation Works
1. **Extraction**: The AI extracts keywords, role types, and required skills from the provided JD.
2. **Matching**: The app scores your projects from `projects_master.json` against the extracted JD tags.
3. **Assembly**: The top projects and your personal info from `resume_ready.json` are combined. The AI tailors the summary and keywords.
4. **Export**: The tailored data is injected into a LaTeX template and compiled into a PDF.
