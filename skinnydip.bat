@ echo off
FOR /f %%p in ('where python') do SET PYTHONPATH=%%p
REM If you wish to set your python location manually, do it in the line below
REM You will also need to delete the "REM" from the beginning of the line.
REM SET PYTHONPATH=C:\python27\python.exe
ECHO Using python installation found at %PYTHONPATH%
SET SCRIPTPATH=%~dp0
%PYTHONPATH% %SCRIPTPATH%\skinnydip.py %1
pause