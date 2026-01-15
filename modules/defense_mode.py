import time
import random
import threading

class DefenseMode:
    def __init__(self):
        self.request_count = 0
        self.lock = threading.Lock()
        self.running = True

    # Simulate incoming requests with random intervals:
    def simulate_incoming_requests(self):
        while self.running:
            time.sleep(random.uniform(0.01, 0.02))
            with self.lock:
                self.request_count += 1

    # Every second, it will display how many requests occured in that second
    def display_request_count(self):
        while self.running:
            time.sleep(1)
            with self.lock:
                rps = self.request_count
                self.request_count = 0
            print(f"Requests per second: {rps}")
    
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
    defense_mode = DefenseMode()
    defense_mode.start(num_threads=10, duration=8)