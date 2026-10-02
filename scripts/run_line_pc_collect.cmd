@echo off
rem Runs the LINE PC collector in the logged-in session. Usage: run_line_pc_collect.cmd [collector args]
cd /d C:\Users\Public\slot-line
if not exist data\tmp_line_pc mkdir data\tmp_line_pc
del /q data\tmp_line_pc\done.txt 2>NUL
"C:\Users\Eita Ideguchi\AppData\Local\Programs\Python\Python312\python.exe" scripts\line_pc_collect.py --repo C:\Users\Public\slot-line --raw-root D:\slot-line\raw %* > data\tmp_line_pc\last_run.txt 2>&1
echo %ERRORLEVEL%> data\tmp_line_pc\done.txt
