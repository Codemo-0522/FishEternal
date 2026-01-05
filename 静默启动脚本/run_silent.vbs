' run_silent.vbs
' Usage: wscript.exe run_silent.vbs "command_to_run"

' Check if an argument was provided
If WScript.Arguments.Count = 0 Then
    WScript.Quit
End If

' Get the command from the first argument
command = WScript.Arguments(0)

' Create a shell object
Set WshShell = CreateObject("WScript.Shell")

' Run the command in a hidden window (0), and don't wait for it to complete (false)
WshShell.Run command, 0, false

Set WshShell = Nothing
