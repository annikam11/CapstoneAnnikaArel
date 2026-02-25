import time
import random
import threading
import json


def sleep_with_stop(stop_event, seconds: float, step: float = 0.05):
    """Sleep in small chunks so the mode can stop immediately."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_event is not None and stop_event.is_set():
            return
        time.sleep(min(step, end - time.time()))


class DefenseDosMode:
    def __init__(self):
        self.request_count = 0
        self.lock = threading.Lock()
        self.running = True
        self.dos_limit = 2200
        self.confirm_threshold = 3
        self.last_state = {}
        self.log_file = "dos_mode_log.jsonl"
        self.attacker_id = "Attacker_DoS"
        self.ip_request_counts = {}
        self.min_dominance_dos = 0.70
        self.dos_streak = 0
        self.blocked = False

    def simulate_incoming_requests(self):
        in_burst = False
        while self.running:
            stop_event = getattr(self, "stop_event", None)
            if stop_event is not None and stop_event.is_set():
                self.running = False
                break

            if not self.blocked:
                if in_burst:
                    sleep_with_stop(stop_event, random.uniform(0.001, 0.004), step=0.01)
                    if random.random() < 0.03:
                        in_burst = False
                else:
                    sleep_with_stop(stop_event, random.uniform(0.003, 0.01), step=0.01)
                    if random.random() < 0.05:
                        in_burst = True

                with self.lock:
                    self.request_count += 1
                    self.ip_request_counts[self.attacker_id] = self.ip_request_counts.get(self.attacker_id, 0) + 1
            else:
                sleep_with_stop(stop_event, 0.01, step=0.01)

    def display_request_count(self):
        while self.running:
            stop_event = getattr(self, "stop_event", None)
            if stop_event is not None and stop_event.is_set():
                self.running = False
                break

            sleep_with_stop(stop_event, 1)

            with self.lock:
                rps = self.request_count
                ip_snapshot = dict(self.ip_request_counts)
                self.request_count = 0
                self.ip_request_counts.clear()

            unique_ips = len(ip_snapshot)
            top_ips = max(ip_snapshot.values()) if ip_snapshot else 0
            dominance = (top_ips / rps) if rps > 0 else 0.0
            dos_like = dominance >= self.min_dominance_dos
            over_limit = rps > self.dos_limit

            if over_limit and dos_like:
                self.dos_streak += 1
            else:
                self.dos_streak = 0

            confirmed_dos = self.dos_streak >= self.confirm_threshold and over_limit

            if confirmed_dos:
                print(f"Confirmed DoS attack detected! Requests per second: {rps}, Dominance: {dominance:.2f}")
            elif over_limit:
                print(f"Spike was detected but not confirmed. Current requests: {rps}, Dominance: {dominance:.2f}")
            else:
                print(f"Normal traffic has occurred. Requests per second: {rps}, Dominance: {dominance:.2f}")

            self.last_state = {
                "rps": rps,
                "confirmed_DoS": confirmed_dos,
                "unique_ips": unique_ips,
                "top_ip": top_ips,
                "dominance": dominance,
            }

            with open(self.log_file, "a") as f:
                json.dump(self.last_state, f)
                f.write("\n")

    def start(self, num_threads=5, duration=10):
        self.running = True

        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=self.simulate_incoming_requests, daemon=True)
            t.start()
            threads.append(t)

        display_thread = threading.Thread(target=self.display_request_count, daemon=True)
        display_thread.start()

        stop_event = getattr(self, "stop_event", None)
        sleep_with_stop(stop_event, duration)
        self.running = False

        for t in threads:
            t.join()
        display_thread.join()


class DefenseDDoSMode:
    def __init__(self):
        self.request_count = 0
        self.lock = threading.Lock()
        self.running = True

        self.ddos_limit = 3100
        self.confirm_threshold = 3
        self.ip_request_counts = {}
        self.last_state = {}
        self.log_file = "ddos_log.jsonl"

        self.attacker_pool = [f"Attacker {i}" for i in range(1, 101)]
        self.heavy_ratio = 0.10
        self.medium_ratio = 0.20

        self.behavior = {}
        for a in self.attacker_pool:
            roll = random.random()
            if roll < self.heavy_ratio:
                self.behavior[a] = "heavy"
            elif roll < self.heavy_ratio + self.medium_ratio:
                self.behavior[a] = "medium"
            else:
                self.behavior[a] = "light"

        k0 = random.randint(5, 20)
        self.active_attackers = random.sample(self.attacker_pool, k0)

        self.max_dominance_ddos = 0.35
        self.min_dominance_dos = 0.70
        self.ddos_streak = 0
        self.dos_streak = 0

        self.drop_rate = 0.0

    def simulate_incoming_requests(self):
        in_burst = False
        while self.running:
            stop_event = getattr(self, "stop_event", None)
            if stop_event is not None and stop_event.is_set():
                self.running = False
                break

            if in_burst:
                sleep_with_stop(stop_event, random.uniform(0.0015, 0.0045), step=0.01)
                if random.random() < 0.03:
                    in_burst = False
            else:
                sleep_with_stop(stop_event, random.uniform(0.0006, 0.0018), step=0.01)
                if random.random() < 0.05:
                    in_burst = True

            with self.lock:
                attackers = list(self.active_attackers)
            if not attackers:
                sleep_with_stop(stop_event, 0.01, step=0.01)
                continue

            attacker = random.choice(attackers)
            ip = attacker

            if self.drop_rate > 0.0 and random.random() < self.drop_rate:
                continue

            behavior = self.behavior[attacker]
            inc = 3 if behavior == "heavy" else 2 if behavior == "medium" else 1

            with self.lock:
                self.request_count += inc
                self.ip_request_counts[ip] = self.ip_request_counts.get(ip, 0) + inc

    def display_request_count(self):
        while self.running:
            stop_event = getattr(self, "stop_event", None)
            if stop_event is not None and stop_event.is_set():
                self.running = False
                break

            sleep_with_stop(stop_event, 1)

            with self.lock:
                rps = self.request_count
                ip_snapshot = dict(self.ip_request_counts)

                # rotate attackers unless adaptive overrides by changing drop_rate/limits
                k = random.randint(5, 45)
                self.active_attackers = random.sample(self.attacker_pool, k)

                self.request_count = 0
                self.ip_request_counts.clear()

            unique_ips = len(ip_snapshot)
            top_ips = max(ip_snapshot.values()) if ip_snapshot else 0
            dominance = (top_ips / rps) if rps > 0 else 0.0
            over_limit = rps > self.ddos_limit

            dos_evidence = over_limit and (dominance >= self.min_dominance_dos or unique_ips <= 3)
            ddos_evidence = over_limit and (dominance <= self.max_dominance_ddos and unique_ips >= 4)

            if dos_evidence:
                self.dos_streak += 1
            else:
                self.dos_streak = 0

            if ddos_evidence:
                self.ddos_streak += 1
            else:
                self.ddos_streak = 0

            confirmed_dos = self.dos_streak >= self.confirm_threshold and over_limit
            confirmed_ddos = self.ddos_streak >= self.confirm_threshold and over_limit

            if confirmed_dos:
                print(
                    f"Confirmed DoS attack detected! Requests per second: {rps}, "
                    f"Unique IPs: {unique_ips}, Top IP requests: {top_ips}, Dominance: {dominance:.2f}"
                )
            elif confirmed_ddos:
                print(
                    f"Confirmed DDoS attack detected! Requests per second: {rps}, "
                    f"Unique IPs: {unique_ips}, Top IP requests: {top_ips}, Dominance: {dominance:.2f}"
                )
            elif over_limit:
                print(
                    f"Spike was detected but not confirmed. Current requests: {rps}, "
                    f"Unique IPs: {unique_ips}, Top IP requests: {top_ips}, Dominance: {dominance:.2f}"
                )
            else:
                print(
                    f"Normal traffic has occurred. Requests per second: {rps}, "
                    f"Unique IPs: {unique_ips}, Top IP requests: {top_ips}, Dominance: {dominance:.2f}"
                )

            self.last_state = {
                "rps": rps,
                "confirmed_DoS": confirmed_dos,
                "confirmed_DDoS": confirmed_ddos,
                "unique_ips": unique_ips,
                "top_ip": top_ips,
                "dominance": dominance,
            }

            with open(self.log_file, "a") as f:
                json.dump(self.last_state, f)
                f.write("\n")

    def start(self, num_threads=10, duration=8):
        self.running = True

        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=self.simulate_incoming_requests, daemon=True)
            t.start()
            threads.append(t)

        display_thread = threading.Thread(target=self.display_request_count, daemon=True)
        display_thread.start()

        stop_event = getattr(self, "stop_event", None)
        sleep_with_stop(stop_event, duration)
        self.running = False

        for t in threads:
            t.join()
        display_thread.join()


class DefenseAdaptiveMode:
    def __init__(self, dos_mode, ddos_mode):
        self.dos_mode = dos_mode
        self.ddos_mode = ddos_mode
        self.running = True
        self.level = "Normal"
        self.history = []
        self.state_streak = 0
        self.required_streak = 1
        self.current_state = None

    def start(self):
        self.running = True
        while self.running:
            stop_event = getattr(self, "stop_event", None)
            if stop_event is not None and stop_event.is_set():
                self.running = False
                break
            sleep_with_stop(stop_event, 1)
            self.evaluate()

    def evaluate(self):
        dos = self.dos_mode.last_state
        ddos = self.ddos_mode.last_state
        if not dos or not ddos:
            return

        rps = max(dos.get("rps", 0), ddos.get("rps", 0))
        dominance = max(dos.get("dominance", 0), ddos.get("dominance", 0))
        unique_ips = ddos.get("unique_ips", 0)

        self.history.append((rps, dominance, unique_ips))
        self.history = self.history[-10:]

        # Keep compatibility with your original keys if you still use them elsewhere
        ddos_confirmed = bool(ddos.get("confirmed_DDoS") or ddos.get("confirmed DDoS"))
        dos_confirmed = bool(dos.get("confirmed_DoS") or dos.get("confirmed DoS"))

        if ddos_confirmed:
            new_state = "DDoS"
        elif dos_confirmed:
            new_state = "DoS"
        else:
            new_state = "Normal"

        if new_state != self.current_state:
            self.current_state = new_state
            self.state_streak = 1 if new_state != "Normal" else 0
        else:
            self.state_streak = self.state_streak + 1 if new_state != "Normal" else 0

        if new_state == "DDoS":
            if self.state_streak >= self.required_streak:
                self.enable_aggressive_ddos()
        elif new_state == "DoS":
            if self.state_streak >= self.required_streak:
                self.enable_tight_dos()
        else:
            self.relax()

    def enable_tight_dos(self):
        if self.level != "TIGHT":
            print("Adaptive: Tightening DoS defense, blocking attacker...")
            self.level = "TIGHT"
            self.dos_mode.blocked = True
            self.dos_mode.dos_limit = 1800

    def enable_aggressive_ddos(self):
        if self.level != "AGGRESSIVE":
            self.level = "AGGRESSIVE"
            self.ddos_mode.drop_rate = 0.25
            self.ddos_mode.ddos_limit = 2500
            print(f"Adaptive: Tightening DDoS defense (drop rate={self.ddos_mode.drop_rate})")

    def relax(self):
        if self.level != "Normal":
            print("Adaptive: Relaxing to Normal limits")
            self.level = "Normal"
            self.dos_mode.blocked = False
            self.ddos_mode.drop_rate = 0.0
            self.dos_mode.dos_limit = 2200
            self.ddos_mode.ddos_limit = 3100