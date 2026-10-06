@echo off
rem 10 shorts van Cast achter de Pod - Bart Messing, in Podcast Jungle-stijl
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
  .venv\Scripts\python -m playwright install chromium
)
.venv\Scripts\python maak_shorts.py "\\Bobbie\Video 2\Bobbie\2026\INTERN\Cast achter de Pod\28-8-2026 Bart Messing\RENDERS" --aantal 10 --huisstijl podcast-jungle
pause
