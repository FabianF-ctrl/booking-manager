@echo off
REM start.bat — uruchamia HospesAI na Windows
REM Kliknij dwukrotnie lub uruchom z terminala

cd /d "%~dp0"

call BM-Venv\Scripts\activate

echo ============================================
echo   HospesAI
echo   http://localhost:8000
echo   Ctrl+C zeby zatrzymac
echo ============================================

uvicorn app:app --host 0.0.0.0 --port 8000 --reload
