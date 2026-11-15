"""Process-group helpers that work on POSIX and Windows."""
import os
import signal
import subprocess
import sys

WINDOWS = sys.platform == 'win32'


def group_kwargs():
    """Popen arguments that put the child in its own process group/session."""
    if WINDOWS:
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {'start_new_session': True}


def stop_group(process, force=False):
    """Ask the child and its descendants to stop; force=True kills them."""
    try:
        if WINDOWS:
            # taskkill /T also ends descendants; without /F it asks politely.
            args = ['taskkill', '/PID', str(process.pid), '/T']
            if force:
                args.append('/F')
            subprocess.run(args, capture_output=True, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass
