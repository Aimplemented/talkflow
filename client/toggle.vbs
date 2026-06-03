' TalkFlow Stream Deck launcher — runs the dictation toggle with no console window.
' Point a Stream Deck "System > Open" action at this file.
'
' It finds streamdeck_daemon.py next to itself and runs it via pythonw.exe.
' Optional argument: control port (defaults to 9878).

Dim fso, shell, here, script, port, cmd
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here   = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "streamdeck_daemon.py")

port = "9878"
If WScript.Arguments.Count > 0 Then port = WScript.Arguments(0)

cmd = "pythonw """ & script & """ toggle --port " & port

' 0 = hidden window, False = don't wait for it to finish (return instantly)
shell.Run cmd, 0, False
