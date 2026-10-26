@echo off
rem AgentParcel launcher - double-click to open, or drag a .zip onto this file.
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0AgentParcel.ps1" %*
