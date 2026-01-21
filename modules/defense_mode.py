import time
import random
import threading

class DefenseDosMode:
    def __init__(self):
        self.request_count = 0
        self.lock = threading.Lock()
        self.running = True
        self.dos_limit = 2200
        self.overload_limit = 0
        self.confirm_threshold = 3
        self.last_state = {}

    # Simulate incoming requests with random intervals:
    def simulate_incoming_requests(self):
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
                self.request_count += 1

    # Every second, it will display how many requests occured in that second
    def display_request_count(self):
        while self.running:
            time.sleep(1)
            with self.lock:
                rps = self.request_count
                self.request_count = 0
            if rps > self.dos_limit:
                self.overload_limit += 1
                if self.overload_limit >= self.confirm_threshold:
                    print(f"Confirmed DoS attack detected! Requests per second: {rps}")
                else:
                    print(f"Spike was detected but not confirmed. Current requests: {rps}")
            else:
                self.overload_limit = 0
                print(f" Normal traffic has occurred. Requests per second: {rps}")

            self.last_state = {
                "rps": rps,
                "confirmed": self.overload_limit >= self.confirm_threshold,
                "unique_ips": 1,
                "top_ip": rps
            }

    def start(self, num_threads=5, duration=10):
        threads = []

    # Start threads to simulate incoming requests
        for _ in range(num_threads):
            t = threading.Thread(target=self.simulate_incoming_requests)
            t.start()
            threads.append(t)
        
        display_thread = threading.Thread(target=self.display_request_count)
        display_thread.start()

        time.sleep(duration)
        self.running = False

        for t in threads:
            t.join()
        display_thread.join()

if __name__ == "__main__":
    dos_mode = DefenseDosMode()
    dos_mode.start(num_threads=10, duration=8)

class DefenseDDoS_Mode:
    def __init__(self):
        self.request_count = 0
        self.lock = threading.Lock()
        self.running = True

        self.ddos_limit = 2200
        self.overload_limit = 0
        self.confirm_threshold = 3
        self.ip_request_counts = {}
        self.last_state = {}
    
    def simulate_incoming_requests(self):
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
            ip = f"192.168.1.{random.randint(1, 255)}"
            with self.lock:
                self.request_count += 1
                self.ip_request_counts[ip] = self.ip_request_counts.get(ip, 0) + 1
    
    def display_request_count(self):
        while self.running:
            time.sleep(1)
            with self.lock:
                rps = self.request_count
                ip_snapshot = dict(self.ip_request_counts)
                self.request_count = 0
                self.ip_request_counts.clear()
            unique_ips = len(ip_snapshot)
            top_ips = max(ip_snapshot.values()) if ip_snapshot else 0
            if rps > self.ddos_limit:
                self.overload_limit += 1
                if self.overload_limit >= self.confirm_threshold:
                    if top_ips > rps * 0.7:
                        print(f" Confirmed DoS attack detected! Requests per second: {rps}")
                    else:
                        print(f" Confirmed DDoS attack detected! Requests per second: {rps}, Unique IPs: {unique_ips}, Top IP requests: {top_ips}")
                else:
                    print(f" Spike was detected but not confirmed. Current requests: {rps}, Unique IPs: {unique_ips}")
            else:
                self.overload_limit = 0
                print(f" Normal traffic has occurred. Requests per second: {rps}, Unique IPs: {unique_ips}")
            self.last_state = {
                "rps": rps,
                "confirmed": self.overload_limit >= self.confirm_threshold,
                "unique_ips": unique_ips,
                "top_ip": top_ips
            }

    def start(self, num_threads=10, duration=8):
        threads = []

        for _ in range(num_threads):
            t = threading.Thread(target=self.simulate_incoming_requests)
            t.start()
            threads.append(t)

        display_thread = threading.Thread(target=self.display_request_count)
        display_thread.start()

        time.sleep(duration)
        self.running = False
        for t in threads:
            t.join()
        display_thread.join()

if __name__ == "__main__":
    ddos_mode = DefenseDDoS_Mode()
    ddos_mode.start(num_threads=10, duration=8)

# class DefenseAdaptive_Mode:
#     def __init__(self):
#         self.request_count = 0

# # if __name__ == "__main__":
#     adaptive_mode = DefenseAdaptive_Mode()
#     adaptive_mode.start(num_threads=10, duration=8)