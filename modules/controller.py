import threading
import time


def sleep_with_stop(stop_event, seconds: float, step: float = 0.05):
    """Sleep in small chunks so Stop works instantly."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_event is not None and stop_event.is_set():
            return
        time.sleep(min(step, end - time.time()))


class SimulationController:
    def __init__(self, duration: int = 15):
        self.duration = duration
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.modes: list[object] = []

    def reset(self):
        self.stop_event.clear()
        self.threads.clear()
        self.modes.clear()

    def _attach_controls(self, mode):
        # Attach the shared stop_event so modes can exit immediately
        mode.stop_event = self.stop_event
        if hasattr(mode, "running"):
            mode.running = True

    def run(self, mode, start_kwargs=None, daemon=True):
        start_kwargs = start_kwargs or {}
        self._attach_controls(mode)
        self.modes.append(mode)

        t = threading.Thread(target=mode.start, kwargs=start_kwargs, daemon=daemon)
        t.start()
        self.threads.append(t)
        return t

    def run_many(self, items, daemon=True):
        for mode, kwargs in items:
            self.run(mode, kwargs, daemon=daemon)

    def start_for(self, seconds=None):
        # Stop-event friendly timer thread
        sleep_with_stop(self.stop_event, self.duration if seconds is None else seconds)
        self.stop()

    def stop(self):
        self.stop_event.set()

        for m in self.modes:
            if hasattr(m, "running"):
                m.running = False

        for t in self.threads:
            t.join(timeout=2.0)

        self.threads.clear()
        self.modes.clear()