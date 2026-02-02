import time
import random
import threading
import json

class attackDoSMode:
    def __init__(self):
        self.request_count = 0
        self.lock = threading.Lock()
        self.running = True
        self.dos_limit = 2200
        self.confirm_threshold = 3
        self.last_state = {}
        self.log_file = "attack_dos_mode_log.json"
        self.attacker_id = "Attacker_DoS"
        self.ip_request_counts = {}
        self.min_dominance_dos = 0.70
        self.dos_streak = 0
        self.blocked = False
    
    def simulate_dos_attack(self):
        in_burst = False
        while self.running:
            if self.blocked == False:
                if in_burst:
                    time.sleep(random.uniform(0.001, 0.004))
                    if random.random() < 0.03:
                        in_burst = False
                else:
                    time.sleep(random.uniform(0.003, 0.01))
                    if random.random() < 0.05:
                        in_burst = True
                with self.lock:
                    self.request_count += 1
                    self.ip_request_counts[self.attacker_id] = self.ip_request_counts.get(self.attacker_id, 0) + 1
            else:
                time.sleep(0.01)

    def simulate_dosattack_success(self):
        while self.running:
            time.sleep(1)
            with self.lock:
                rps = self.request_count 
                ip_snapshot = dict(self.ip_request_counts)
                self.request_count = 0
                self.ip_request_counts.clear()
                unique_ips = len(ip_snapshot)
                top_ips = max(ip_snapshot.values()) if ip_snapshot else 0
                dominance = (top_ips / rps) if rps > 0 else 0.0
                dos_like = dominance >= self.min_dominance_dos
                impact_goal = rps > self.dos_limit
            if impact_goal and dos_like:
                self.dos_streak +=1
            else:
                self.dos_streak = 0
            sustained_goal = self.dos_streak >= self.confirm_threshold and impact_goal
            if sustained_goal:
                print(f"Impact achieved! Requests per second: {rps}, Dominance: {dominance}")
            elif impact_goal:
                    print(f"Ramping up, Current requests: {rps}, Dominance: {dominance}")
            else:
                print(f"A block has occurred. Requests per second: {rps}, Dominance: {dominance}")

            self.last_state = {
                "rps": rps,
                "confirmed DoS": sustained_goal,
                "unique_ips": unique_ips,
                "top_ip": top_ips,
                "dominance": dominance
            }
            with open(self.log_file, "a") as f:
                json.dump(self.last_state, f)
                f.write("\n")

class attackDDoSMode:
    def __init__(self):
        pass

class attackAdaptiveMode:
    def __init__(self):
        pass
    