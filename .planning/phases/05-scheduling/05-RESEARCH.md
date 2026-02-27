# Phase 5: Scheduling - Research

**Researched:** 2026-02-27
**Domain:** Windows Task Scheduler, APScheduler 3.x, Python process scheduling on Windows
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCHED-01 | El sistema ejecuta el ETL completo al inicio de cada trimestre de forma programada vía Windows Task Scheduler o APScheduler (<4.0), actualizando los datos de todas las empresas cargadas | Windows Task Scheduler XML with ScheduleByMonth on months Jan/Apr/Jul/Oct day=1, OR APScheduler 3.11.2 BlockingScheduler with CronTrigger(month='1,4,7,10', day=1). Wrapper .bat calls `python agent.py` which runs run_batch() → FinancialAgent.run() → needs_update() short-circuits if already current. |
</phase_requirements>

---

## Summary

Phase 5 adds a quarterly ETL trigger so `python agent.py` fires automatically on the first day of January, April, July, and October — no human involvement. The entire entry point already exists: `agent.py __main__` calls `run_batch()` over `BASE_TICKERS`, which in turn calls `FinancialAgent.run()` per ticker; `needs_update()` already handles the case where data is already current, making re-runs cheap. This phase is purely an infrastructure task: wire the existing entry point to an OS or in-process scheduler.

There are two viable approaches. **Windows Task Scheduler** (recommended for this project) is the OS-native solution for Windows 11 — a `.bat` wrapper script handles conda path resolution, and a Task Scheduler XML registers the quarterly monthly trigger. It runs whether the user is logged in or not, produces log files, and survives reboots. **APScheduler 3.11.2** is a Python-native alternative that adds a `scheduler.py` process to keep running; it is simpler to configure but requires the process to stay alive (problematic for a workstation that reboots). Given the project is local-only on Windows 11, Windows Task Scheduler is the correct choice.

The critical implementation risk is conda PATH isolation: Task Scheduler runs in a sterile environment where `python` is not on PATH. The solution is a `.bat` wrapper that uses the full absolute path to `C:\Users\Seb\miniconda3\python.exe` and sets the working directory to the project root, ensuring `load_dotenv()` and all relative paths in the code resolve correctly.

**Primary recommendation:** Use Windows Task Scheduler with a `.bat` wrapper that hard-codes the miniconda3 Python path and project directory. Register via `schtasks /create /XML`. Test immediately with `schtasks /run /TN "AI2026_QuarterlyETL"`.

---

## Standard Stack

### Core
| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| Windows Task Scheduler | OS-native (Windows 11) | Quarterly trigger, runs without user login | OS-native, no extra dependencies, survives reboots, GUI management available |
| `schtasks.exe` | OS-native | CLI to create/run/delete tasks | Scriptable task registration without GUI |
| `.bat` wrapper script | N/A | Resolves conda PATH, sets working directory, redirects logs | Only reliable way to run conda Python from Task Scheduler |

### Supporting (APScheduler path, not recommended for this project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| APScheduler | 3.11.2 | In-process Python scheduler with CronTrigger | Use if process can stay alive 24/7 (server, not workstation) |
| pytz | >=2021.1 | Timezone support for APScheduler | Required when passing timezone to BlockingScheduler |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Windows Task Scheduler | APScheduler 3.11.2 BlockingScheduler | APScheduler requires a Python process running permanently — breaks on reboot/logout without a service wrapper. Task Scheduler handles restarts natively. |
| Windows Task Scheduler | APScheduler with BackgroundScheduler inside `app.py` | Would couple scheduling to Streamlit process. If dashboard is not running on Jan 1, batch never fires. Incorrect architecture. |
| .bat wrapper | Direct schtasks /TR pointing at python.exe | Schtasks /TR can reference python.exe directly, but log redirection requires the bat wrapper pattern. Also bat wrapper allows conda activate if an env is needed. |

**Installation (APScheduler, only if chosen):**
```bash
pip install "apscheduler==3.11.2"
```

---

## Architecture Patterns

### Recommended Project Structure
```
AI 2026/
├── agent.py              # existing — run_batch() + __main__ entry point
├── scheduler.bat         # NEW — wrapper that Task Scheduler calls
├── logs/                 # NEW — scheduler run logs (stdout+stderr)
│   └── etl_YYYYMMDD.log  # created by scheduler.bat on each run
└── .planning/
    └── phases/
        └── 05-scheduling/
            ├── quarterly_etl_task.xml  # NEW — Task Scheduler XML definition
            └── register_task.bat       # NEW — one-time registration script
```

### Pattern 1: .bat Wrapper Script (scheduler.bat)

**What:** A batch file that hard-codes the Python executable path, sets the working directory, and redirects stdout/stderr to a timestamped log file.
**When to use:** Always when invoking conda Python from Windows Task Scheduler.

```batch
@echo off
REM scheduler.bat — Quarterly ETL runner for AI 2026 project
REM Called by Windows Task Scheduler. Uses absolute paths to avoid PATH issues.

SET PYTHON=C:\Users\Seb\miniconda3\python.exe
SET PROJECT=C:\Users\Seb\AI 2026
SET LOGDIR=%PROJECT%\logs

REM Create logs directory if it doesn't exist
IF NOT EXIST "%LOGDIR%" MKDIR "%LOGDIR%"

REM Timestamped log file (YYYYMMDD format)
FOR /F "tokens=2 delims==" %%I IN ('wmic os get localdatetime /format:list') DO SET DATETIME=%%I
SET LOGFILE=%LOGDIR%\etl_%DATETIME:~0,8%.log

REM Change to project directory so relative paths in code work
CD /D "%PROJECT%"

REM Run ETL — log stdout and stderr to file
ECHO [%DATETIME%] Starting quarterly ETL >> "%LOGFILE%"
"%PYTHON%" "%PROJECT%\agent.py" >> "%LOGFILE%" 2>&1
SET EXITCODE=%ERRORLEVEL%
ECHO [%DATETIME%] ETL complete. Exit code: %EXITCODE% >> "%LOGFILE%"

EXIT /B %EXITCODE%
```

**Key points:**
- `%PYTHON%` uses full absolute path — no dependency on PATH
- `CD /D "%PROJECT%"` — ensures `Path(__file__).parent` resolves correctly for `scraper.py`'s `load_dotenv()` call
- `>> "%LOGFILE%" 2>&1` — captures both stdout (loguru) and stderr
- `EXIT /B %EXITCODE%` — propagates exit code so Task Scheduler knows if it succeeded or failed

### Pattern 2: Task Scheduler XML Definition (quarterly_etl_task.xml)

**What:** An XML file that defines the complete task with a ScheduleByMonth trigger restricted to January, April, July, October — the only way to get a true quarterly trigger from schtasks.
**When to use:** Quarterly schedules that `schtasks /create /SC MONTHLY /M` cannot express with a single command.

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Quarterly ETL run for AI 2026 S&amp;P 500 financial data</Description>
    <Author>Seb</Author>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-04-01T06:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByMonth>
        <DaysOfMonth>
          <Day>1</Day>
        </DaysOfMonth>
        <Months>
          <January/>
          <April/>
          <July/>
          <October/>
        </Months>
      </ScheduleByMonth>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <AllowStartOnDemand>true</AllowStartOnDemand>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>C:\Users\Seb\AI 2026\scheduler.bat</Command>
    </Exec>
  </Actions>
</Task>
```

**Key settings explained:**
- `<StartWhenAvailable>true</StartWhenAvailable>` — if the machine was off on Jan 1, Task Scheduler runs the task on next startup. Critical for a workstation.
- `<LogonType>InteractiveToken</LogonType>` — runs as the logged-in user (Seb), which has access to `.env`, data files, and conda installation
- `<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>` — prevents overlapping runs if ETL is slow
- `<ExecutionTimeLimit>PT2H</ExecutionTimeLimit>` — 2-hour timeout; ETL for 20 tickers takes ~10 min normally
- `StartBoundary>2026-04-01T06:00:00` — first fire at 6 AM Apr 1, 2026 (set to 6 AM to avoid midnight edge cases)

### Pattern 3: Registration Command (register_task.bat)

**What:** One-time script to register the task with Task Scheduler.
**When to use:** During setup / deployment.

```batch
@echo off
REM register_task.bat — Run once as Administrator to register the quarterly ETL task

SET TASK_NAME=AI2026_QuarterlyETL
SET XML_FILE=C:\Users\Seb\AI 2026\.planning\phases\05-scheduling\quarterly_etl_task.xml

schtasks /create /XML "%XML_FILE%" /TN "%TASK_NAME%" /F

IF %ERRORLEVEL% EQU 0 (
    ECHO Task registered successfully: %TASK_NAME%
    ECHO Test with: schtasks /run /TN "%TASK_NAME%"
) ELSE (
    ECHO ERROR: Task registration failed. Exit code: %ERRORLEVEL%
)
```

### Pattern 4: Immediate Test Run

**What:** Trigger the registered task right now to verify it works, without waiting 3 months.
**Command:**
```batch
schtasks /run /TN "AI2026_QuarterlyETL"
```

Then verify output:
```batch
REM Check Task Scheduler last run result
schtasks /query /TN "AI2026_QuarterlyETL" /FO LIST /V

REM Check log output
TYPE "C:\Users\Seb\AI 2026\logs\etl_*.log"
```

Expected: exit code 0, log shows "Batch complete — success: N, skipped: N, failed: 0".

### Anti-Patterns to Avoid

- **No `schtasks /create /SC MONTHLY /M` for quarterly:** The `/M` flag for monthly schedules cannot express "only January, April, July, October" in a single schtasks command. It would require 4 separate tasks. Use the XML approach instead.
- **Do not use relative paths in .bat:** Task Scheduler's working directory is unpredictable. Always use absolute paths.
- **Do not use `conda activate` in the bat:** `conda activate` requires conda shell integration which may not be initialized in a Task Scheduler session. Use the full path to `python.exe` directly: `C:\Users\Seb\miniconda3\python.exe`.
- **Do not run as SYSTEM account:** The SYSTEM account cannot access the user's `.env` file, conda installation, or `data/` directory. Run as the user (InteractiveToken).
- **Do not omit `<StartWhenAvailable>true`:** Without it, if the machine is off on Jan 1, the quarterly run is permanently skipped until next quarter.
- **Do not schedule at midnight (00:00):** Windows midnight edge cases and date rollover can cause issues. Use 06:00 AM.
- **Do not couple scheduling to Streamlit:** The dashboard and ETL are independent. `app.py` reads Parquet; it never calls `run_batch()` for scheduling purposes.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Quarterly trigger | Custom date-check loop in Python | Windows Task Scheduler ScheduleByMonth XML | OS handles missed runs, reboots, logging, retry — your loop needs all of this |
| Log rotation | Custom log file management | Timestamped log filename per run in bat | Simple, zero dependencies, files are self-archiving |
| Python path resolution | Conda PATH detection script | Hard-coded absolute `C:\Users\Seb\miniconda3\python.exe` | Reliable; conda PATH varies by shell session type |
| "Is data current?" logic | Custom freshness check in scheduler | `needs_update()` in FinancialAgent (already implemented) | Already handles quarter-boundary logic correctly |

**Key insight:** The entire ETL entry point already exists and handles idempotency. This phase is 90% infrastructure wiring, not code.

---

## Common Pitfalls

### Pitfall 1: Conda Python Not Found
**What goes wrong:** Task Scheduler runs `python agent.py` and gets "python is not recognized as an internal or external command". The ETL never starts. No error in the dashboard.
**Why it happens:** Task Scheduler launches a new session without inheriting the user's conda-activated PATH. `python` is not in the sterile session PATH.
**How to avoid:** Hard-code the full path in scheduler.bat: `SET PYTHON=C:\Users\Seb\miniconda3\python.exe`. Verify the path exists before testing: `dir C:\Users\Seb\miniconda3\python.exe`.
**Warning signs:** Task Scheduler shows "Last Run Result: 0x1" and log file is empty or absent.

### Pitfall 2: Working Directory Wrong → .env Not Found
**What goes wrong:** `scraper.py` calls `load_dotenv(Path(__file__).parent / ".env")`. If the working directory is wrong, the path still works because it uses `__file__` (absolute). BUT if Task Scheduler sets a different working directory, other relative paths break.
**Why it happens:** Task Scheduler's default working directory is `C:\Windows\System32`, not the project root.
**How to avoid:** Include `CD /D "C:\Users\Seb\AI 2026"` in scheduler.bat before calling Python. The `load_dotenv` call in scraper.py already uses `Path(__file__).parent` so it finds `.env` regardless, but `CD` ensures any other relative path usage works.
**Warning signs:** `EnvironmentError: EDGAR_IDENTITY not set` in the log.

### Pitfall 3: Missed Run on Machine Off → Skipped Forever
**What goes wrong:** Machine is powered off on January 1st. Task Scheduler does not run the ETL. Data stays stale for the entire Q1.
**Why it happens:** Default Task Scheduler behavior is to skip missed runs.
**How to avoid:** Set `<StartWhenAvailable>true</StartWhenAvailable>` in the XML. With this flag, the task runs on the next machine startup after the missed trigger time.
**Warning signs:** Parquet files have `last_downloaded` timestamps from the previous quarter but it's now mid-January.

### Pitfall 4: schtasks /M Flag Cannot Express Quarterly
**What goes wrong:** Developer tries `schtasks /create /SC MONTHLY /MO 1 /D 1 /M JAN,APR,JUL,OCT` and gets an error or unexpected behavior.
**Why it happens:** The `/M` parameter and `/MO` modifier for MONTHLY do not cleanly combine to express "only these 4 months" in all Windows versions.
**How to avoid:** Use the XML approach with `ScheduleByMonth` → `<Months><January/><April/><July/><October/></Months>`. Register with `schtasks /create /XML <file> /TN <name>`.
**Warning signs:** Task fires monthly instead of quarterly, or registration fails.

### Pitfall 5: InteractiveToken vs "Run Whether User Logged On or Not"
**What goes wrong:** Task is set to "Run whether user is logged on or not" (non-interactive). The task cannot access the user's conda installation at `C:\Users\Seb\miniconda3\` because the session is non-interactive and may use different permissions.
**Why it happens:** Non-interactive tasks use service-like contexts; user home directory resources may not be accessible.
**How to avoid:** For this local workstation project, use `<LogonType>InteractiveToken</LogonType>`. This means the task only runs when Seb is logged in — acceptable for a quarterly batch that uses `<StartWhenAvailable>true` to catch missed runs on next login.
**Warning signs:** Task shows "0x8007010B" (directory not found) or conda not found errors with non-interactive mode.

### Pitfall 6: APScheduler 4.x Does Not Exist Yet
**What goes wrong:** `pip install apscheduler` gets 3.11.2 — the latest stable. There is no APScheduler 4.x on PyPI as of 2026-02-27 (4.x was in alpha during 2024-2025 and never released stable).
**Why it happens:** REQUIREMENTS.md noted "APScheduler (<4.0)" — the constraint is already met by the latest stable release.
**How to avoid:** Use `apscheduler==3.11.2` (pinned). No risk of accidentally getting 4.x.
**Warning signs:** N/A — this is a non-issue, but the constraint in the requirements caused concern.

---

## Code Examples

Verified patterns from official sources:

### APScheduler 3.x — Quarterly CronTrigger (alternative approach)
```python
# Source: https://apscheduler.readthedocs.io/en/3.x/userguide.html
# Use only if Windows Task Scheduler approach is not viable.

from apscheduler.schedulers.blocking import BlockingScheduler

def quarterly_etl():
    """Run the full ETL batch. Idempotent — needs_update() handles current-quarter data."""
    from agent import run_batch
    run_batch()

scheduler = BlockingScheduler(
    job_defaults={
        'coalesce': True,          # If missed multiple fires, run once — not N times
        'misfire_grace_time': 7 * 24 * 3600,  # Allow up to 7 days grace for missed runs
        'max_instances': 1,        # Never run two ETLs simultaneously
    },
    timezone='America/Chicago'     # Or user's local timezone
)

# Run at 6:00 AM on the 1st of Jan, Apr, Jul, Oct
scheduler.add_job(
    quarterly_etl,
    'cron',
    month='1,4,7,10',
    day=1,
    hour=6,
    minute=0,
    id='quarterly_etl',
    replace_existing=True,         # Required for persistent job stores on restart
)

if __name__ == '__main__':
    print("APScheduler started. Press Ctrl+C to stop.")
    scheduler.start()
```

### Windows Task Scheduler XML — Monthly Trigger Schema
```xml
<!-- Source: https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-schedulebymonth-calendartriggertype-element -->
<CalendarTrigger>
    <StartBoundary>2026-04-01T06:00:00</StartBoundary>
    <Enabled>true</Enabled>
    <ScheduleByMonth>
        <DaysOfMonth>
            <Day>1</Day>
        </DaysOfMonth>
        <Months>
            <January/>
            <April/>
            <July/>
            <October/>
        </Months>
    </ScheduleByMonth>
</CalendarTrigger>
```

### Test Task Immediately
```batch
REM Register task (run once, may need admin)
schtasks /create /XML "C:\Users\Seb\AI 2026\.planning\phases\05-scheduling\quarterly_etl_task.xml" /TN "AI2026_QuarterlyETL" /F

REM Test immediately — does not affect schedule
schtasks /run /TN "AI2026_QuarterlyETL"

REM Check result (0x0 = success)
schtasks /query /TN "AI2026_QuarterlyETL" /FO LIST /V | findstr /C:"Last Run Result" /C:"Last Run Time"
```

### Verify ETL Ran Correctly
```python
# Source: agent.py — _load_metadata() pattern
import pandas as pd
from pathlib import Path

meta = pd.read_parquet(Path("data/cache/metadata.parquet"))
print(meta[["last_downloaded", "status"]].to_string())
# All rows should show current-quarter last_downloaded and status "success" or "skipped_scrape"
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `schtasks /create /SC MONTHLY` with flags | XML task definition with `ScheduleByMonth` | Windows Vista (v2 task schema) | XML is required for multi-month selection; command-line flag approach is inadequate for quarterly |
| APScheduler 3.x with SQLite jobstore | APScheduler 3.x default MemoryJobStore | N/A | For quarterly jobs, memory jobstore is fine — coalesce=True handles missed runs; no persistence needed |
| APScheduler 4.x (alpha) | APScheduler 3.11.2 (stable) | 4.x never released stable as of 2026-02-27 | Use 3.x; 4.x API is incompletely documented and unavailable on PyPI |

**Deprecated/outdated:**
- APScheduler 4.x alpha: Was in development during 2024-2025 but never released to stable PyPI. The requirement `<4.0` is correct and met by 3.11.2.
- `schtasks /create /SC MONTHLY /M JAN,APR,JUL,OCT` as a single command: Does not reliably produce quarterly behavior across Windows versions. Use XML.

---

## Open Questions

1. **Does the machine need to be on at 6 AM on Jan 1, Apr 1, Jul 1, Oct 1?**
   - What we know: `<StartWhenAvailable>true</StartWhenAvailable>` handles powered-off machines by running on next startup
   - What's unclear: If the machine boots on Jan 15 and runs the ETL, does it correctly trigger for Jan 1? Yes — Task Scheduler sees the missed trigger and fires if `StartWhenAvailable` is set
   - Recommendation: Use `StartWhenAvailable=true` and test by creating a task with a past `StartBoundary` — it should fire immediately on next startup

2. **Should logs be rotated / archived?**
   - What we know: Timestamped log filenames (`etl_20260101.log`) naturally accumulate without overwriting
   - What's unclear: At 4 runs/year, logs grow slowly (~20KB per run × 4 = 80KB/year). No rotation needed.
   - Recommendation: No log rotation needed for v1. Keep it simple.

3. **What if ETL fails partially (some tickers succeed, some fail)?**
   - What we know: `run_batch()` catches per-ticker exceptions and records `status=error` in metadata; batch continues; exits with `sys.exit(1)` if any failures
   - What's unclear: Task Scheduler will record exit code 1 as "failure" even if 18/20 tickers succeeded
   - Recommendation: Accept this behavior for v1. The dashboard still shows data for the 18 successful tickers. SCHED-02/03 (v2 requirements) address failure notification.

---

## Sources

### Primary (HIGH confidence)
- [Microsoft Learn — ScheduleByMonth element](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-schedulebymonth-calendartriggertype-element) — XML schema for monthly trigger with specific months
- [Microsoft Learn — Daily Trigger XML example](https://learn.microsoft.com/en-us/windows/win32/taskschd/daily-trigger-example--xml-) — Complete Task Scheduler XML structure (all required elements)
- [APScheduler 3.x User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — BlockingScheduler, job_defaults, coalesce, misfire_grace_time
- [APScheduler 3.x CronTrigger docs](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html) — month='1,4,7,10' day=1 hour=6 quarterly pattern
- `pip index versions apscheduler` — Confirmed: 3.11.2 is latest stable; no 4.x on PyPI as of 2026-02-27
- `powershell schtasks /create /?` — Confirmed: MONTHLY schedule type, /M parameter, /XML flag
- `powershell schtasks /run /?` — Confirmed: `/run /TN <name>` triggers task immediately

### Secondary (MEDIUM confidence)
- [Mike Nguyen — Task Scheduler with Anaconda](https://mikenguyen.netlify.app/post/task-scheduler-with-python-and-anaconda-environment/) — conda activate pattern in bat; full path python.exe approach
- [Microsoft Learn — schtasks create](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create) — /XML flag for task XML import
- [Microsoft Learn — schtasks run](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-run) — /run /TN for immediate test

### Tertiary (LOW confidence)
- Multiple community sources on conda PATH in Task Scheduler — consistent message: use full path to python.exe; verified by testing `sys.executable` = `C:\Users\Seb\miniconda3\python.exe`

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — schtasks and Task Scheduler XML verified against official Microsoft docs; APScheduler version verified with `pip index versions`
- Architecture: HIGH — .bat pattern verified against multiple sources; XML schema from official docs; Python paths verified by running `sys.executable`
- Pitfalls: HIGH (conda path), MEDIUM (InteractiveToken behavior) — conda path issue well-documented across many sources; InteractiveToken vs non-interactive verified with official Microsoft Q&A

**Research date:** 2026-02-27
**Valid until:** 2027-02-27 (Windows Task Scheduler schema is stable; APScheduler 3.x is stable and unlikely to change)
