@echo off
REM register_task.bat — Run ONCE to register the quarterly ETL task with Windows Task Scheduler.
REM
REM IMPORTANT: Run this script as Administrator (right-click -> Run as administrator)
REM if schtasks /create requires elevation on this machine. On Windows 11 with UAC,
REM InteractiveToken tasks typically register without admin, but elevation avoids errors.
REM
REM After registration, test immediately with:
REM   schtasks /run /TN "AI2026_QuarterlyETL"
REM Then check the log:
REM   type "C:\Users\Seb\AI 2026\logs\etl_*.log"

SET TASK_NAME=AI2026_QuarterlyETL
SET XML_FILE=C:\Users\Seb\AI 2026\.planning\phases\05-scheduling\quarterly_etl_task.xml

ECHO Registering task: %TASK_NAME%
ECHO XML source: %XML_FILE%
ECHO.

schtasks /create /XML "%XML_FILE%" /TN "%TASK_NAME%" /F

IF %ERRORLEVEL% EQU 0 (
    ECHO.
    ECHO Task registered successfully: %TASK_NAME%
    ECHO.
    ECHO To test immediately (does not affect quarterly schedule):
    ECHO   schtasks /run /TN "%TASK_NAME%"
    ECHO.
    ECHO To verify task status:
    ECHO   schtasks /query /TN "%TASK_NAME%" /FO LIST /V
    ECHO.
    ECHO To view the log after test run:
    ECHO   type "C:\Users\Seb\AI 2026\logs\etl_*.log"
) ELSE (
    ECHO.
    ECHO ERROR: Task registration failed. Exit code: %ERRORLEVEL%
    ECHO.
    ECHO Common fixes:
    ECHO   - Run as Administrator
    ECHO   - Verify XML path exists: %XML_FILE%
    ECHO   - Check XML encoding (must be UTF-16 or UTF-8 with BOM on some Windows versions)
)

PAUSE
