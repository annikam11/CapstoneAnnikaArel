import threading
import time

class SimulationController:
    def __init__(self, duration=15):
        self.duration = duration
        self.stop_event = threading.Event()
        self.threads = []
        self.modes = []

    def reset(self):
        self.stop_event.clear()
        self.threads.clear()
        self.modes.clear()

    def _attach_controls(self, mode):
        try:
            mode.stop_event = self.stop_event
        except Exception:
            pass
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
        time.sleep(self.duration if seconds is None else seconds)
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
