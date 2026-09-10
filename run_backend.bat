@echo off
title Serveur Backend translate-for-pdf.com
echo =======================================================
echo Lancement du Serveur API FastAPI translate-for-pdf.com
echo Documentation Swagger interactive disponible sur : http://localhost:8000/docs
echo =======================================================
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
pause
