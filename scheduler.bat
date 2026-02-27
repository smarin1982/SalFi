@echo off
REM scheduler.bat — Quarterly ETL runner for AI 2026 project
REM Called by Windows Task Scheduler. Uses absolute paths to avoid conda PATH issues.
REM DO NOT use "python" or "conda activate" — Task Scheduler runs in a sterile session.

SET PYTHON=C:\Users\Seb\miniconda3\python.exe
SET PROJECT=C:\Users\Seb\AI 2026
SET LOGDIR=%PROJECT%\logs

REM Create logs directory if it doesn't exist
IF NOT EXIST "%LOGDIR%" MKDIR "%LOGDIR%"

REM Build timestamped log filename (YYYYMMDD format via wmic)
FOR /F "tokens=2 delims==" %%I IN ('wmic os get localdatetime /format:list') DO SET DATETIME=%%I
SET LOGFILE=%LOGDIR%\etl_%DATETIME:~0,8%.log

REM Change to project directory so relative paths in agent.py and scraper.py resolve correctly
CD /D "%PROJECT%"

REM Run ETL — capture both stdout (loguru) and stderr to the log file
ECHO [%DATETIME%] Starting quarterly ETL >> "%LOGFILE%" 2>&1
"%PYTHON%" "%PROJECT%\agent.py" >> "%LOGFILE%" 2>&1
SET EXITCODE=%ERRORLEVEL%
ECHO [%DATETIME%] ETL complete. Exit code: %EXITCODE% >> "%LOGFILE%" 2>&1

EXIT /B %EXITCODE%
