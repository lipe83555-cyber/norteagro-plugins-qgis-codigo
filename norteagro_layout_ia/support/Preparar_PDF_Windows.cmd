@echo off
chcp 65001 >nul
setlocal
rem ==== NorteAgro Layout IA - ambiente de suporte para PDF (opcional) ====
rem O plugin le PDF pelo GDAL do QGIS. Use este script so se o PDF nao abrir.
rem Cria a pasta %USERPROFILE%\.norteagro_layout_ia\venv com PyMuPDF e Pillow,
rem separada do Python do QGIS.
set "DESTINO=%USERPROFILE%\.norteagro_layout_ia\venv"
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale o Python 3.10 a 3.13 de python.org ^(marque "Add to PATH"^) e rode de novo.
    pause
    exit /b 1
  )
  set "PY=python"
) else (
  set "PY=py -3"
)
%PY% -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)"
if errorlevel 1 (
  echo [ERRO] Versao do Python incompativel. Use Python 3.10, 3.11, 3.12 ou 3.13.
  %PY% --version
  pause
  exit /b 1
)
if not exist "%DESTINO%\Scripts\python.exe" (
  echo Criando ambiente em "%DESTINO%" ...
  %PY% -m venv "%DESTINO%"
  if errorlevel 1 (
    echo [ERRO] Nao foi possivel criar o ambiente virtual.
    pause
    exit /b 1
  )
)
"%DESTINO%\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
"%DESTINO%\Scripts\python.exe" -m pip install pymupdf pillow
if errorlevel 1 (
  echo [ERRO] Falha ao baixar pacotes. Confira a internet ou o proxy da empresa ^(variaveis HTTPS_PROXY^) e rode de novo.
  pause
  exit /b 1
)
echo.
echo [OK] Ambiente pronto. No plugin, em Configuracoes ^> Python de suporte, informe:
echo   %DESTINO%\Scripts\python.exe
pause
