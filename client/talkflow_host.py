"""TalkFlow Host launcher — run this on the PC (the machine with the mic).

Reads client/config.json for the transcription backend, key, and mic, then
listens for TalkFlow Agents running on your remote DeskFlow screens.

    python talkflow_host.py            # default port 9877
    python talkflow_host.py --port 9900
"""

from network_server import main

if __name__ == "__main__":
    main()
