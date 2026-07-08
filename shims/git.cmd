@echo off
setlocal
set "MICA_PROXY_DIR=%~dp0..\proxy"
set "PYTHONPATH=%MICA_PROXY_DIR%;%PYTHONPATH%"
python -m mica_proxy --tool git -- %*
exit /b %ERRORLEVEL%
