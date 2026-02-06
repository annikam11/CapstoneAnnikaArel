import time
import random
import threading
import json

class attackDoSMode:
    def __init__(self):
        self.request_count = 0
        self.lock = threading.Lock()
        self.running = True
        self.attack_goal = 2200
        self.confirm_threshold = 3
        self.last_state = {}
        self.log_file = "attack_dos_mode_log.jsonl"
        self.attacker_id = "Attacker_DoS"
        self.ip_request_counts = {}
        self.min_dominance_dos = 0.70
        self.dos_streak = 0
        self.blocked = False
        self.burst_chance = 0.03
        self.exit_burst_chance = 0.05
        self.burst_sleep_range = (0.001, 0.004)
        self.normal_sleep_range = (0.003, 0.01)
    
    def simulate_dos_attack(self):
        in_burst = False
        while self.running:
            if self.blocked == False:
                if in_burst:
                    time.sleep(random.uniform(*self.burst_sleep_range))
                    if random.random() < self.exit_burst_chance:
                        in_burst = False
                else:
                    time.sleep(random.uniform(*self.normal_sleep_range))
                    if random.random() < self.burst_chance:
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
                impact_goal = rps > self.attack_goal
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
                print(f"Impact has not occurred. Requests per second: {rps}, Dominance: {dominance}")

            with self.lock:
                self.last_state = {
                    "rps": rps,
                    "impact_achieved": sustained_goal,
                    "unique_ips": unique_ips,
                    "top_ip": top_ips,
                    "dominance": dominance
                }
            with open(self.log_file, "a") as f:
                json.dump(self.last_state, f)
                f.write("\n")
            
    def start(self, num_threads=10, duration=15):
        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=self.simulate_dos_attack, daemon=True)
            t.start()
            threads.append(t)

        monitor = threading.Thread(target=self.simulate_dosattack_success, daemon=True)
        monitor.start()

        time.sleep(duration)
        self.running = False

        for t in threads:
            t.join()
        monitor.join()

class attackDDoSMode:
    def __init__(self):
        self.request_count = 0
        self.lock = threading.Lock()
        self.running = True
        self.attack_ddos_goal = 3100
        self.confirm_threshold = 3
        self.ip_request_counts = {}
        self.last_state = {}
        self.log_file= "ddosattack_log.jsonl"
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
        self.active_attackers = []
        k0 = random.randint(5, 20)
        self.active_attackers = random.sample(self.attacker_pool, k0)
        self.goal_dominance_ddos = 0.35
        self.ddos_streak = 0
        self.adaptive_override = False
    
    def simulate_ddos_attack(self):
        in_burst = False
        while self.running:
            if in_burst:
                time.sleep(random.uniform(0.001, 0.004))
                if random.random() < 0.03:
                    in_burst = False
            else:
                time.sleep(random.uniform(0.003, 0.01))
                if random.random() < 0.05:
                    in_burst = True
            with self.lock:
                attackers = list(self.active_attackers)
            if not attackers:
                time.sleep(0.01)
                continue
            attacker = random.choice(attackers)
            ip = attacker
            behavior = self.behavior[attacker]
            if behavior == "heavy":
                with self.lock:
                    self.request_count += 3
                    self.ip_request_counts[ip] = self.ip_request_counts.get(ip, 0) + 3
            elif behavior == "medium":
                with self.lock:
                    self.request_count += 2
                    self.ip_request_counts[ip] = self.ip_request_counts.get(ip, 0) + 2
            else:
                with self.lock:
                    self.request_count += 1
                    self.ip_request_counts[ip] = self.ip_request_counts.get(ip, 0) + 1
    
    def display_attack_success(self):
        while self.running:
            time.sleep(1)
            with self.lock:
                rps = self.request_count
                ip_snapshot = dict(self.ip_request_counts)
                if not self.adaptive_override:
                    k = random.randint(5, 45)
                    self.active_attackers = random.sample(self.attacker_pool, k)
                self.request_count = 0
                self.ip_request_counts.clear()
            unique_ips = len(ip_snapshot)
            top_ips = max(ip_snapshot.values()) if ip_snapshot else 0
            dominance = (top_ips / rps) if rps > 0 else 0.0
            over_limit = rps > self.attack_ddos_goal
            ddos_footprint = over_limit and ( dominance <= self.goal_dominance_ddos and unique_ips >=4)
            if ddos_footprint:
                self.ddos_streak +=1
            else:
                self.ddos_streak = 0
            succesful_ddos= self.ddos_streak >= self.confirm_threshold and over_limit
            if succesful_ddos:
                print(f"Impact achieved! DDoS successful, Requests per second: {rps}, Unique IPs: {unique_ips}, Top IP requests: {top_ips}, Dominance: {dominance:.2f}")
            elif over_limit:
                print(f"Adding pressure but no success. Current requests: {rps}, Unique IPs: {unique_ips}, Top IP requests: {top_ips}, Dominance: {dominance:.2f}")
            else:
                print(f" Pressure insufficient this second, Requests per second: {rps}, Unique IPs: {unique_ips}, Top IP requests: {top_ips}, Dominance: {dominance:.2f}")
            with self.lock:
                self.last_state = {
                    "rps": rps,
                    "impact_achieved": succesful_ddos,
                    "unique_ips": unique_ips,
                    "top_ip": top_ips,
                    "dominance": dominance
                }
            with open(self.log_file, "a") as f:
                json.dump(self.last_state, f)
                f.write("\n")
    def start(self, num_threads=10, duration=15):
        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=self.simulate_ddos_attack, daemon=True)
            t.start()
            threads.append(t)

        monitor = threading.Thread(target=self.display_attack_success, daemon=True)
        monitor.start()

        time.sleep(duration)
        self.running = False

        for t in threads:
            t.join()
        monitor.join()

class attackAdaptiveMode:
    def __init__(self, dos_attack, ddos_attack):
        self.dos_attack = dos_attack
        self.ddos_attack = ddos_attack
        self.running = True
        self.level = "Normal"
        self.history = []
        self.state_streak = 0
        self.required_streak = 1
        self.current_state = None

    def start(self):
        while self.running:
            time.sleep(1)
            self.evaluate()

    def evaluate(self):
        with self.dos_attack.lock:
            dos = dict(self.dos_attack.last_state)
        with self.ddos_attack.lock:
            ddos = dict(self.ddos_attack.last_state)
        if not dos or not ddos:
            return
        
        rps = max(dos.get("rps", 0), ddos.get("rps", 0))
        dominance = max(dos.get("dominance", 0), ddos.get("dominance", 0))
        unique_ips = ddos.get("unique_ips", 0)
        self.history.append((rps, dominance, unique_ips))
        self.history = self.history[-10:]
        if ddos.get("impact_achieved"):
            new_state = "DDoS"
        elif  dos.get("impact_achieved"):
            new_state = "DoS"
        else:
            new_state = "Normal"

        if new_state != self.current_state:
            self.current_state = new_state
            self.state_streak = 1 if new_state != "Normal" else 0
        else:
            if new_state != "Normal":
                self.state_streak += 1
            else:
                self.state_streak = 0
        
        if new_state == "DDoS":
            if self.state_streak >= self.required_streak:
                self.enable_aggressive_ddos()
        elif new_state == "DoS":
            if self.state_streak >= self.required_streak:
                self.enable_aggressive_dos()
        else:
            self.relax()
    
    def enable_aggressive_dos(self):
        if self.level != "ATTACK":
            self.level = "ATTACK"
            print("Adaptive: Attacking DoS mode with more frequency...")
            self.dos_attack.burst_chance = 0.8
            self.dos_attack.exit_burst_chance = 0.2
            self.dos_attack.burst_sleep_range = (0.0001, 0.003)
            self.dos_attack.normal_sleep_range = (0.002, 0.007)
            self.dos_attack.blocked = False

    def enable_aggressive_ddos(self):
        if self.level != "AGGRESSIVE":
            self.level = "AGGRESSIVE"
            with self.ddos_attack.lock:
                self.ddos_attack.adaptive_override = True
                self.active_ddos_attackers = self.ddos_attack.attacker_pool.copy()
                self.ddos_attack.active_attackers = self.active_ddos_attackers
            print(f"Adaptive: Attacking DDoS mode with more attackers (active attackers={len(self.active_ddos_attackers)})...")

    def relax(self):
        if self.level != "Normal":
            print("Adaptive: Relaxing to Normal limits for DoS and DDoS")
            self.level = "Normal"
            self.dos_attack.blocked = False
            with self.ddos_attack.lock:
                self.ddos_attack.adaptive_override = False
                k = random.randint(5, 20)
                self.ddos_attack.active_attackers = random.sample(self.ddos_attack.attacker_pool, k)
            self.dos_attack.burst_chance = 0.03
            self.dos_attack.exit_burst_chance = 0.05
            self.dos_attack.burst_sleep_range = (0.001, 0.004)
            self.dos_attack.normal_sleep_range = (0.003, 0.01)

if __name__ == "__main__":
    dos_attack = attackDoSMode()
    ddos_attack = attackDDoSMode()
    adaptive_mode = attackAdaptiveMode(dos_attack, ddos_attack)
    
    threading.Thread(target=dos_attack.start, kwargs={"num_threads":10, "duration":15}, daemon=True).start()
    threading.Thread(target=ddos_attack.start, kwargs={"num_threads":10, "duration":15}, daemon=True).start()
    threading.Thread(target=adaptive_mode.start, daemon=True).start()
    time.sleep(15)
    adaptive_mode.running = False

