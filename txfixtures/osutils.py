# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU General Public License version 3.


"""General os utilities useful for txfxtures."""


import errno
import os
import os.path
from signal import (
    SIGKILL,
    SIGTERM,
    )
import socket
import time


def _kill_may_race(pid, signal_number):
    """Kill a pid accepting that it may not exist."""
    try:
        os.kill(pid, signal_number)
    except OSError as e:
        if e.errno in (errno.ESRCH, errno.ECHILD):
            # Process has already been killed.
            return
        # Some other issue (e.g. different user owns it)
        raise


def get_pid_from_file(pidfile_path):
    """Retrieve the PID from the given file, if it exists, None otherwise."""
    if not os.path.exists(pidfile_path):
        return None
    # Get the pid.
    with open(pidfile_path, 'r') as fd:
        pid = fd.read().split()[0]
    try:
        pid = int(pid)
    except ValueError:
        # pidfile contains rubbish
        return None
    return pid


def two_stage_kill(pid, poll_interval=0.1, num_polls=50):
    """Kill process 'pid' with SIGTERM. If it doesn't die, SIGKILL it.

    :param pid: The pid of the process to kill.
    :param poll_interval: The polling interval used to check if the
        process is still around.
    :param num_polls: The number of polls to do before doing a SIGKILL.
    """
    # Kill the process.
    _kill_may_race(pid, SIGTERM)

    # Poll until the process has ended.
    for i in range(num_polls):
        try:
            # Reap the child process and get its return value. If it's not
            # gone yet, continue.
            new_pid, result = os.waitpid(pid, os.WNOHANG)
            if new_pid:
                return result
            time.sleep(poll_interval)
        except OSError as e:
            if e.errno in (errno.ESRCH, errno.ECHILD):
                # Raised if the process is gone by the time we try to get the
                # return value.
                return

    # The process is still around, so terminate it violently.
    _kill_may_race(pid, SIGKILL)


def kill_by_pidfile(pidfile_path, poll_interval=0.1, num_polls=50):
    """Kill a process identified by the pid stored in a file.

    The pid file is removed from disk.
    """
    try:
        pid = get_pid_from_file(pidfile_path)
        if pid is None:
            return
        two_stage_kill(pid, poll_interval, num_polls)
    finally:
        remove_if_exists(pidfile_path)


def remove_if_exists(path):
    """Remove the given file if it exists."""
    try:
        os.remove(path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


def until_no_eintr(retries, function, *args, **kwargs):
    """Run 'function' until it doesn't raise EINTR errors.

    :param retries: The maximum number of times to try running 'function'.
    :param function: The function to run.
    :param *args: Arguments passed to the function.
    :param **kwargs: Keyword arguments passed to the function.
    :return: The return value of 'function'.
    """
    if not retries:
        return
    for i in range(retries):
        try:
            return function(*args, **kwargs)
        except (IOError, OSError) as e:
            if e.errno == errno.EINTR:
                continue
            raise
        except socket.error as e:
            # In Python 2.6 we can use IOError instead.  It also has
            # reason.errno but we might be using 2.5 here so use the
            # index hack.
            if e[0] == errno.EINTR:
                continue
            raise
    else:
        raise
