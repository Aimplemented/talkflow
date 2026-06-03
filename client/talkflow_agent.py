"""TalkFlow Agent launcher — run this on each remote DeskFlow screen.

Catches your hotkey locally (since DeskFlow delivers it here when this screen
has the keyboard), asks the Host PC to record + transcribe, and types the
result into the focused app on this machine.

    python talkflow_agent.py --host 192.168.1.50:9877
    python talkflow_agent.py --host 100.x.y.z:9877 --hotkey f9   # Tailscale IP
"""

from network_client import main

if __name__ == "__main__":
    main()
