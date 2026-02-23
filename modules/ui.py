from __future__ import annotations

import sys
import time
import queue
import threading
import atexit
from dataclasses import dataclass
from typing import Any, Optional, Literal

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from modules.defense_mode import DefenseDosMode, DefenseDDoSMode, DefenseAdaptiveMode
from modules.attack_mode import attackDoSMode, attackDDoSMode, attackAdaptiveMode
from modules.controller import SimulationController


# ---------------- Logging capture (prints -> UI) ----------------
class QueueWriter:
    """
    File-like object that pushes complete lines into a queue.
    Captures print() output from the sim (including threads) WITHOUT touching
    st.session_state from worker threads.
    """
    def __init__(self, q: "queue.Queue[str]"):
        self.q = q
        self._buf = ""

    def write(self, s: str):
        if not s:
            return
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip()
            if line:
                self.q.put(line)

    def flush(self):
        if self._buf.strip():
            self.q.put(self._buf.strip())
        self._buf = ""


# ---------------- Data / Helpers ----------------
@dataclass
class ModeRefs:
    dos: Any
    ddos: Any
    adaptive: Any


def safe_state(mode) -> dict:
    lock = getattr(mode, "lock", None)
    if lock:
        with lock:
            return dict(getattr(mode, "last_state", {}) or {})
    return dict(getattr(mode, "last_state", {}) or {})


def is_running() -> bool:
    t: Optional[threading.Thread] = st.session_state.get("controller_thread")
    return bool(t and t.is_alive())


def fmt_num(x, digits=3) -> str:
    if isinstance(x, (int, float)):
        return f"{x:.{digits}f}"
    return str(x)


def push_log(level: str, msg: str):
    st.session_state.log_lines.append(f"[{time.strftime('%H:%M:%S')}] {level} {msg}")


def stop_simulation():
    controller: Optional[SimulationController] = st.session_state.get("controller")
    if controller:
        controller.stop()


Severity = Literal["ERROR", "WARN", "INFO"]


def classify_line(line: str) -> Severity:
    s = line.lower()

    strong_bad = [
        "impact achieved",
        "attack detected",
        "detected attack",
        "intrusion",
        "breach",
        "compromised",
        "ddos detected",
        "dos detected",
        "under attack",
        "flood detected",
        "mitigation failed",
        "failed to block",
    ]
    if any(k in s for k in strong_bad):
        return "ERROR"

    if ("dos" in s or "ddos" in s) and any(k in s for k in ["detect", "attack", "malicious", "threat", "impact"]):
        return "ERROR"

    warn = [
        "boosting",
        "ramping up",
        "pressure insufficient",
        "suspicious",
        "rate limit",
        "throttle",
        "blocked",
        "mitigat",
        "quarantine",
        "alert",
        "threshold",
        "anomal",
        "adaptive"
    ]
    if any(k in s for k in warn):
        return "WARN"

    return "INFO"


def severity_prefix(sev: Severity) -> str:
    return {"INFO": "🟦", "WARN": "🟨", "ERROR": "🟥"}[sev]


# ---------------- Simulation Starters ----------------
def start_attack_simulation(duration: int, dos_threads: int, ddos_threads: int):
    if is_running():
        return

    dos = attackDoSMode()
    ddos = attackDDoSMode()
    adaptive = attackAdaptiveMode(dos, ddos)

    controller = SimulationController(duration=duration)

    st.session_state.controller = controller
    st.session_state.attack_modes = ModeRefs(dos=dos, ddos=ddos, adaptive=adaptive)
    st.session_state.started_at = time.time()
    st.session_state.duration = duration
    st.session_state.run_kind = "Attack"

    log_q: "queue.Queue[str]" = st.session_state.log_queue

    def runner():
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = QueueWriter(log_q)
        sys.stderr = QueueWriter(log_q)
        try:
            controller.reset()
            controller.run_many([
                (dos, {"num_threads": dos_threads, "duration": duration}),
                (ddos, {"num_threads": ddos_threads, "duration": duration}),
                (adaptive, {}),
            ])
            controller.start_for(duration)
        finally:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            sys.stdout, sys.stderr = old_out, old_err

    t = threading.Thread(target=runner, daemon=True)
    st.session_state.controller_thread = t
    t.start()


def start_defense_simulation(duration: int, dos_threads: int, ddos_threads: int):
    if is_running():
        return

    dos = DefenseDosMode()
    ddos = DefenseDDoSMode()
    adaptive = DefenseAdaptiveMode(dos, ddos)

    controller = SimulationController(duration=duration)

    st.session_state.controller = controller
    st.session_state.defense_modes = ModeRefs(dos=dos, ddos=ddos, adaptive=adaptive)
    st.session_state.started_at = time.time()
    st.session_state.duration = duration
    st.session_state.run_kind = "Defense"

    log_q: "queue.Queue[str]" = st.session_state.log_queue

    def runner():
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = QueueWriter(log_q)
        sys.stderr = QueueWriter(log_q)
        try:
            controller.reset()
            controller.run_many([
                # If your defense run() signatures differ, adjust kwargs here.
                (dos, {"num_threads": dos_threads, "duration": duration}),
                (ddos, {"num_threads": ddos_threads, "duration": duration}),
                (adaptive, {}),
            ])
            controller.start_for(duration)
        finally:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            sys.stdout, sys.stderr = old_out, old_err

    t = threading.Thread(target=runner, daemon=True)
    st.session_state.controller_thread = t
    t.start()


# ---------------- Streamlit UI ----------------
st.set_page_config(
    page_title="ArelGuard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# init session defaults
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []
if "log_queue" not in st.session_state:
    st.session_state.log_queue = queue.Queue()
if "started_at" not in st.session_state:
    st.session_state.started_at = None
if "duration" not in st.session_state:
    st.session_state.duration = None
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True
if "auto_scroll_logs" not in st.session_state:
    st.session_state.auto_scroll_logs = True
if "run_kind" not in st.session_state:
    st.session_state.run_kind = None
if "attack_modes" not in st.session_state:
    st.session_state.attack_modes = None
if "defense_modes" not in st.session_state:
    st.session_state.defense_modes = None
if "page" not in st.session_state:
    st.session_state.page = "OVERVIEW"
if "username" not in st.session_state:
    st.session_state.username = "USERNAME"
if "log_limit" not in st.session_state:
    st.session_state.log_limit = 5000

running_now = is_running()

# Drain background logs into the UI list (MAIN THREAD ONLY)
q: "queue.Queue[str]" = st.session_state.log_queue
try:
    while True:
        line = q.get_nowait()
        st.session_state.log_lines.append(f"[{time.strftime('%H:%M:%S')}] {line}")
except queue.Empty:
    pass

# Keep log history bounded (prevents session from growing forever)
if len(st.session_state.log_lines) > int(st.session_state.log_limit):
    st.session_state.log_lines = st.session_state.log_lines[-int(st.session_state.log_limit):]

# ---------------- Neon CSS Theme ----------------
st.markdown(
    """
<style>
.stApp {
  background: radial-gradient(circle at 50% 0%, #111 0%, #000 55%, #000 100%) !important;
  color: #e6e6e6;
}

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

section[data-testid="stSidebar"] {
  background: #0a0a0a !important;
  border-right: 1px solid #1f1f1f;
}

.sidebar-title {
  font-weight: 800;
  letter-spacing: .08em;
  color: #bdbdbd;
  opacity: .9;
  font-size: 0.85rem;
  margin-top: 1rem;
}

/* Hero (Overview) */
.hero-wrap { width: 100%; display: flex; justify-content: center; margin-top: 2.5rem; }
.hero-card {
  width: min(980px, 95%);
  padding: 2.0rem 2.2rem;
  border-radius: 16px;
  background: rgba(0,0,0,0.35);
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow: 0 0 40px rgba(0,0,0,0.7);
  text-align: center;
}
.brand { font-size: 64px; font-weight: 900; letter-spacing: .08em; color: #8a2be2; margin: 0; line-height: 1.0; }
.welcome {
  margin-top: 1.0rem;
  font-size: 32px;
  font-weight: 900;
  color: #ff2a7a;
  text-shadow: 0 0 10px rgba(255,42,122,0.25);
}
.choose {
  margin-top: 0.6rem;
  font-size: 30px;
  font-weight: 900;
  color: #00e7ff;
  text-shadow: 0 0 10px rgba(0,231,255,0.2);
}
.mode-row { display: flex; justify-content: center; gap: 60px; margin-top: 1.4rem; }
.mode-col { width: 320px; display: flex; flex-direction: column; align-items: center; gap: 14px; }
.mode-icon { font-size: 56px; filter: drop-shadow(0 0 10px rgba(0,255,150,0.18)); }
.mode-icon-blue { filter: drop-shadow(0 0 10px rgba(0,180,255,0.18)); }

/* Buttons */
div.stButton > button {
  border-radius: 10px;
  border: 2px solid rgba(255,255,255,0.55);
  background: rgba(255,255,255,0.06);
  padding: 0.65rem 1.0rem;
  font-weight: 900;
  letter-spacing: .06em;
  text-transform: uppercase;
}
div.stButton > button:hover {
  background: rgba(255,255,255,0.10);
  border-color: rgba(255,255,255,0.80);
}

/* Logs area */
textarea {
  background: #070707 !important;
  color: #e9e9e9 !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown('<div class="sidebar-title">GENERAL</div>', unsafe_allow_html=True)

    nav_items = ["OVERVIEW", "ATTACK", "DEFENSE", "HELP", "SETTINGS"]
    st.session_state.page = st.radio(
        "Navigation",
        nav_items,
        index=nav_items.index(st.session_state.page) if st.session_state.page in nav_items else 0,
        label_visibility="collapsed",
    )

    st.divider()

    st.markdown('<div class="sidebar-title">PROFILE</div>', unsafe_allow_html=True)
    st.session_state.username = st.text_input("Username", value=st.session_state.username)

    st.divider()

    st.markdown('<div class="sidebar-title">RUNTIME</div>', unsafe_allow_html=True)
    # IMPORTANT: when using key=..., do NOT pass value=... (avoids Streamlit warning)
    st.toggle("Auto-refresh", key="auto_refresh")
    st.toggle("Auto-scroll logs", key="auto_scroll_logs")

    if st.session_state.page in ("ATTACK", "DEFENSE"):
        st.subheader("Scenario")
        duration = st.number_input("Duration (seconds)", min_value=1, max_value=3600, value=15, step=1)
        dos_threads = st.slider("DoS threads", min_value=1, max_value=100, value=10, step=1)
        ddos_threads = st.slider("DDoS threads", min_value=1, max_value=100, value=10, step=1)

        st.subheader("Run")
        colA, colB = st.columns(2)
        with colA:
            if st.button("▶ Start", use_container_width=True, disabled=running_now):
                if st.session_state.page == "ATTACK":
                    start_attack_simulation(int(duration), int(dos_threads), int(ddos_threads))
                    push_log("INFO", "Started ATTACK simulation")
                else:
                    start_defense_simulation(int(duration), int(dos_threads), int(ddos_threads))
                    push_log("INFO", "Started DEFENSE simulation")
                st.rerun()

        with colB:
            if st.button("⏹ Stop", use_container_width=True, disabled=not running_now):
                stop_simulation()
                push_log("WARN", "Stop requested")
                st.rerun()

    if st.button("🧹 Clear Logs", use_container_width=True):
        st.session_state.log_lines = []
        st.rerun()


# ---------------- Page: OVERVIEW ----------------
if st.session_state.page == "OVERVIEW":
    # CRITICAL: no blank lines + no indentation -> prevents Streamlit from creating a code block
    hero_html = (
        f'<div class="hero-wrap">'
        f'  <div class="hero-card">'
        f'    <div class="brand">ARELGUARD</div>'
        f'    <div class="welcome">WELCOME: {st.session_state.username}!</div>'
        f'    <div class="choose">CHOOSE YOUR PATH</div>'
        f'    <div class="mode-row">'
        f'      <div class="mode-col"><div class="mode-icon">📡</div></div>'
        f'      <div class="mode-col"><div class="mode-icon mode-icon-blue">🛡️</div></div>'
        f'    </div>'
        f'  </div>'
        f'</div>'
    )
    st.markdown(hero_html, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("ATTACK MODE", use_container_width=True):
            st.session_state.page = "ATTACK"
            st.rerun()
    with c2:
        if st.button("DEFENSE MODE", use_container_width=True):
            st.session_state.page = "DEFENSE"
            st.rerun()

    st.caption("Use the left menu to switch pages anytime. Start/Stop controls appear in Attack/Defense pages.")


# ---------------- Pages: ATTACK / DEFENSE ----------------
elif st.session_state.page in ("ATTACK", "DEFENSE"):
    left, right = st.columns([2.2, 1], vertical_alignment="top")

    with left:
        active_modes: Optional[ModeRefs] = (
            st.session_state.get("attack_modes")
            if st.session_state.page == "ATTACK"
            else st.session_state.get("defense_modes")
        )

        mode_title = "📡 Attack Mode" if st.session_state.page == "ATTACK" else "🛡️ Defense Mode"
        st.markdown(f"## {mode_title}")

        tabs = st.tabs(["Live Telemetry", "Event Feed", "About"])

        with tabs[0]:
            if not active_modes:
                st.info("Press **Start** in the sidebar to run this mode.")
            else:
                dos_state = safe_state(active_modes.dos)
                ddos_state = safe_state(active_modes.ddos)
                a = active_modes.adaptive

                r1c1, r1c2, r1c3, r1c4 = st.columns(4)
                with r1c1:
                    st.metric("DoS RPS", dos_state.get("rps", "-"))
                with r1c2:
                    st.metric("DDoS RPS", ddos_state.get("rps", "-"))
                with r1c3:
                    st.metric("Unique IPs", ddos_state.get("unique_ips", "-"))
                with r1c4:
                    impact = (
                        dos_state.get("impact_achieved")
                        or dos_state.get("impact")
                        or dos_state.get("confirmed DoS")
                        or ddos_state.get("confirmed DDoS")
                    )
                    st.metric("Impact / Detection", "YES" if impact else "NO")

                st.divider()

                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown("### 🔥 DoS")
                    dom = dos_state.get("dominance", "-")
                    st.metric("Dominance", fmt_num(dom, 3) if dom != "-" else "-")
                    st.write("Top IP reqs:", dos_state.get("top_ip_requests", dos_state.get("top_ip", "-")))
                    st.write("Notes:", dos_state.get("note", "-"))

                with c2:
                    st.markdown("### 🌐 DDoS")
                    dom = ddos_state.get("dominance", "-")
                    st.metric("Dominance", fmt_num(dom, 3) if dom != "-" else "-")
                    st.write("Unique IPs:", ddos_state.get("unique_ips", "-"))
                    st.write("Notes:", ddos_state.get("note", "-"))

                with c3:
                    st.markdown("### 🧠 Adaptive")
                    a = active_modes.adaptive

                    # DefenseAdaptiveMode (your class)
                    if hasattr(a, "level") or hasattr(a, "current_state"):
                        st.write("Level:", getattr(a, "level", "—"))
                        st.write("State:", getattr(a, "current_state", "—"))
                        st.write("State streak:", getattr(a, "state_streak", "—"))
                        st.write("Required streak:", getattr(a, "required_streak", "—"))

                        hist = getattr(a, "history", None)
                        if isinstance(hist, list) and hist:
                            rps, dom, uips = hist[-1]
                            st.caption(f"Last sample → rps={rps}, dominance={dom:.3f}, unique_ips={uips}")

                    # AttackAdaptiveMode (your other class)
                    else:
                        st.write("DoS boost:", getattr(a, "dos_boost_on", None))
                        st.write("DDoS boost:", getattr(a, "ddos_boost_on", None))
                        st.write("Fail streak DoS:", getattr(a, "fail_streak_dos", None))
                        st.write("Fail streak DDoS:", getattr(a, "fail_streak_ddos", None))

        with tabs[1]:
            st.markdown("### Event Feed (full run history)")
            lines = list(reversed(st.session_state.log_lines[-int(st.session_state.log_limit):]))
            level = st.selectbox("Filter", ["ALL", "INFO", "WARN", "ERROR"], index=0, key="log_filter")

            shown = 0
            for ln in lines:
                sev = classify_line(ln)
                if level != "ALL" and sev != level:
                    continue
                st.markdown(f"{severity_prefix(sev)} `{ln}`")
                shown += 1
                if shown >= 500:
                    break
            if shown == 0:
                st.caption("No events match your filter yet.")

        with tabs[2]:
            st.markdown(
                """
## About ArelGuard

ArelGuard is an educational attack/defense simulator designed to help learners understand how high-level
network pressure events (DoS/DDoS) and defensive response strategies look over time.

### What you’re seeing
- **Live Telemetry**: real-time metrics from the active simulation mode.
- **Event Feed**: captures *every* log line during the run (including `print()` output from your modules),
  then marks entries by severity:
  - 🟥 **Red**: detection/impact/confirmed attack outcome
  - 🟨 **Yellow**: escalation, throttling, blocking, suspicious activity, threshold pressure
  - 🟦 **Blue**: general informational events

### Modes
- **Attack Mode (Radar)**: runs your attack simulations (DoS / DDoS / Adaptive).
- **Defense Mode (Shield)**: runs your defense simulations (DoS / DDoS / Adaptive defense behavior).
"""
            )

    with right:
        st.markdown("### 🧾 Logs (raw)")
        raw = "\n".join(st.session_state.log_lines[-600:])
        st.text_area("Log output", value=raw, height=520)


# ---------------- HELP / SETTINGS ----------------
elif st.session_state.page == "HELP":
    st.header("Help")
    st.markdown(
        """
### How to use this UI
1. Go to **Attack** or **Defense** from the left menu.
2. Set duration + threads.
3. Click **Start**.
4. Watch telemetry and review all output in **Event Feed** and **Logs (raw)**.
"""
    )

elif st.session_state.page == "SETTINGS":
    st.header("Settings")
    st.subheader("Logs")
    st.session_state.log_limit = st.slider(
        "Max log lines kept", min_value=500, max_value=20000, value=int(st.session_state.log_limit), step=500
    )
    st.caption("Higher values keep more history but use more memory.")


# ---------- Auto-refresh ----------
if running_now and st.session_state.get("auto_refresh", True):
    st_autorefresh(interval=250, key="refresh_250ms")

def cleanup():
    try:
        controller = st.session_state.get("controller")
        if controller:
            controller.stop()
    except Exception:
        pass

atexit.register(cleanup)