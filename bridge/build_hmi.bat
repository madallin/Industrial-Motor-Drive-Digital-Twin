@echo off
setlocal
cd /d "%~dp0"
set "COMPILATOR_HMI=C:\msys64\mingw32\bin\gcc.exe"
set "PATH=C:\msys64\mingw32\bin;%PATH%"
if not exist "%COMPILATOR_HMI%" (
  echo Lipseste compilatorul MSYS2 MINGW32 x86: %COMPILATOR_HMI%
  exit /b 1
)
"%COMPILATOR_HMI%" -shared -O2 -Wall -Wextra -Werror -static-libgcc -Wl,--kill-at -o psim_drive_control_plc.dll psim_hmi.c -lws2_32
exit /b %errorlevel%
