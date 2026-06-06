#!/bin/bash
set -e
echo "=== resume.app ==="
if ! python3 -c "import flask, requests" &>/dev/null 2>&1; then
  echo "Installing dependencies..."
  pip3 install -r requirements.txt --break-system-packages -q
fi
if command -v pdflatex &>/dev/null; then
  echo "pdflatex: found — PDF output enabled"
else
  echo "pdflatex: NOT found — LaTeX/TXT output only"
  echo "Enable PDF: sudo apt install texlive-latex-extra texlive-fonts-recommended -y"
fi
echo "Starting at http://localhost:5000"
python3 app.py
