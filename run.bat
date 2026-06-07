@echo off
setlocal
echo === resume.app ===

:: Check if flask and requests are installed
python -c "import flask, requests" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install -r requirements.txt -q
)

:: Check if pdflatex is installed
where pdflatex >nul 2>nul
if %errorlevel% equ 0 (
    echo pdflatex: found — PDF output enabled
) else (
    echo pdflatex: NOT found — LaTeX/TXT output only
    echo Enable PDF: Install MiKTeX from https://miktex.org/download
    echo ^(Or run: winget install -e --id MiKTeX.MiKTeX^)
)

echo Starting at http://localhost:5000
python app.py
pause
