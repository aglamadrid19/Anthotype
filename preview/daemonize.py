#!/usr/bin/env python3
"""Launch a command fully detached from the calling shell/session.

Double-forks so the child is re-parented to launchd and lives in its own
session -- it survives the terminal (and the agent's exec session) exiting.

usage: daemonize.py <pidfile> <logfile> <cmd> [args...]
"""
import os, subprocess, sys

if len(sys.argv) < 4:
    sys.exit('usage: daemonize.py <pidfile> <logfile> <cmd> [args...]')

pid_path, log_path, cmd = sys.argv[1], sys.argv[2], sys.argv[3:]

if os.fork() > 0:
    os._exit(0)
os.setsid()
if os.fork() > 0:
    os._exit(0)

log = open(log_path, 'ab', 0)
devnull = open(os.devnull, 'rb')
proc = subprocess.Popen(cmd, stdin=devnull, stdout=log, stderr=log,
                        start_new_session=True)
with open(pid_path, 'w') as fh:
    fh.write(str(proc.pid))
