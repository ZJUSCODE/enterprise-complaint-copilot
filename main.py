from app.runtime import *  # noqa: F401,F403
from app import runtime as _runtime


def __getattr__(name):
    return getattr(_runtime, name)
