@echo off
ECHO Starting SciTech News Aggregator...

REM Navigate to your project directory
cd /D "C:\Users\Aman\Downloads\MySciTechProject"

REM Activate the virtual environment
ECHO Activating virtual environment...
CALL .venv\Scripts\activate.bat

REM Check if activation was successful (optional, but good practice)
IF "%VIRTUAL_ENV%"=="" (
    ECHO Failed to activate virtual environment. Exiting.
    pause
    exit /b
)

ECHO Virtual environment activated.
ECHO Starting Flask application...

REM Start the Flask application
REM The 'start' command can run Python in a new window, 
REM or you can run it directly in this window.

REM Option 1: Run Python directly in this window (Ctrl+C to stop)
python scitechnexus.py

REM Option 2: Run Python in a new minimized CMD window
REM This allows this batch script to continue (e.g., to open the browser)
REM However, you'll need to close that new CMD window to stop the Flask server.
REM START "SciTech Nexus Server" /MIN CMD /C "python scitechnexus.py"

REM Wait a few seconds for the server to start (adjust as needed)
REM This is only needed if you use Option 2 above and want to auto-open browser
REM TIMEOUT /T 5 /NOBREAK > NUL

REM Optionally, open the application in the default web browser
REM This will run after the 'python scitechnexus.py' command if using Option 1,
REM or after the TIMEOUT if using Option 2.
REM If using Option 1, this part won't execute until the Python script (Flask server) is stopped.
REM So, it's more useful with Option 2 or if you just want to start the server.
ECHO Opening application in browser (if server started successfully)...
REM start http://127.0.0.1:5000

ECHO.
ECHO Flask server is running (or was started). 
ECHO Press Ctrl+C in the Python server window to stop it.
REM If you used Option 1, this script will pause here until Flask is stopped.
REM If you used Option 2, this script will likely finish quickly.
REM pause