@echo off
SET PYTHONPATH=C:\python27\python.exe
SET SCRIPTPATH=%~dp0
%PYTHONPATH% %SCRIPTPATH%\skinnydip.py %1
pause