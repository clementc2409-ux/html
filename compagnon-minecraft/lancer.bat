@echo off
rem Lance le compagnon Minecraft : double-clique sur ce fichier.
rem La premiere fois, il installe tout seul les bibliotheques Python (2 minutes environ).
rem Pour le mode test : lancer.bat --test
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Premiere installation : creation de l'environnement Python...
    py -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python est introuvable. Installe Python 3.11 ou plus recent depuis https://www.python.org/downloads/
        echo en cochant "Add python.exe to PATH", puis relance ce fichier.
        pause
        exit /b 1
    )
)

fc /b requirements.txt ".venv\requirements_installees.txt" >nul 2>&1
if errorlevel 1 (
    echo Installation des bibliotheques, patiente une ou deux minutes...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo L'installation a echoue : verifie ta connexion Internet et relance ce fichier.
        pause
        exit /b 1
    )
    copy /y requirements.txt ".venv\requirements_installees.txt" >nul
)

".venv\Scripts\python.exe" compagnon.py %*
echo.
pause
