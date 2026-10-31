@echo off
REM SlideLink Desktop – Windows installer (double-click). Needs Windows 10 1703+ / 11.
cd /d "%~dp0"
where py >nul 2>nul || (echo Installing Python... & winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements & echo Python installed. Please run this installer again. & pause & exit /b)
where vlc >nul 2>nul || if not exist "C:\Program Files\VideoLAN\VLC\vlc.exe" (echo Installing VLC... & winget install -e --id VideoLAN.VLC --accept-source-agreements --accept-package-agreements)
if not exist .venv py -3 -m venv .venv
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements.txt || (echo Install failed. Check your Internet connection for this one-time setup. & pause & exit /b)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\SlideLink.lnk');$s.TargetPath='%~dp0.venv\Scripts\pythonw.exe';$s.Arguments='run.py';$s.WorkingDirectory='%~dp0';$s.Save()"
echo.
echo Done! A "SlideLink" shortcut was added to your Desktop. Starting now...
start "" ".venv\Scripts\pythonw.exe" run.py
