"""Task functions for TimeoutPool tests (must be importable by worker processes)."""
import os
import time


def echo(x):
    return {"x": x}


def sleepy(x):
    time.sleep(x)
    return {"slept": x}


def crash(_x):
    os._exit(3)


def boom(_x):
    raise ValueError("bad file")
