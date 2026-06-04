' TalkFlow Stream Deck launcher — dictate to the AI5090 (remote target).
' Point a SECOND Stream Deck "System > Open" action at this file; keep your
' existing button pointed at toggle.vbs for PC (local) dictation.
'
' It finds streamdeck_daemon.py next to itself and runs `toggle-remote` via
' pythonw.exe (no console window). Optional argument: control port (default 9878).

Dim fso, shell, here, script, port, cmd
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here   = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "streamdeck_daemon.py")

port = "9878"
If WScript.Arguments.Count > 0 Then port = WScript.Arguments(0)

cmd = "pythonw """ & script & """ toggle-remote --port " & port

' 0 = hidden window, False = don't wait for it to finish (return instantly)
shell.Run cmd, 0, False
