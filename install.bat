@echo off
chcp 65001 >nul
echo ============================================
echo  Εγκατασταση - Εξασκηση Αναγνωσης
echo ============================================
echo.

set PYTHON=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe

if not exist "%PYTHON%" (
    echo ΣΦΑΛΜΑ: Δεν βρεθηκε Python στο %PYTHON%
    echo Αλλαξε τη μεταβλητη PYTHON στο install.bat
    pause
    exit /b 1
)

echo Αναβαθμιση pip...
"%PYTHON%" -m pip install --upgrade pip setuptools >nul 2>&1

echo Εγκατασταση βιβλιοθηκων...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ΣΦΑΛΜΑ: Αποτυχια εγκαταστασης
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Εξαγωγη κειμενων απο PDF (μια φορα)
echo ============================================
set PYTHONIOENCODING=utf-8
"%PYTHON%" extract_pdfs.py --publish

echo.
echo ============================================
echo  Ετοιμο! Εκτελεσε run.bat για να ξεκινησεις
echo ============================================
pause
