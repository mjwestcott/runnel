from contextlib import contextmanager
from subprocess import Popen


@contextmanager
def subprocess(app: str, graceful=True):
    try:
        p = Popen(["runnel", "worker", app])
        yield p
    finally:
        if graceful:
            p.terminate()
        else:
            p.kill()
