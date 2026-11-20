"""Process-lifetime advisory locks; lock files are not evidence of live workers."""

from contextlib import contextmanager

from .domain import identifier


@contextmanager
def run_lock(store, run_id):
    identifier(run_id)
    directory = store.root / "locks"
    directory.mkdir(exist_ok=True)
    handle = (directory / (run_id + ".lock")).open("a+b")
    try:
        try:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError("Another worker holds this run's execution lock") from None
        yield
    finally:
        # Closing the descriptor releases the OS lock even after exceptions.
        handle.close()
