from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Any, Optional

import streamlit as st

from modules.attack_mode import attackDoSMode, attackDDoSMode, attackAdaptiveMode
from modules.controller import SimulationController


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


def start_simulation(duration: int, dos_threads: int, ddos_threads: int):
    if is_running():
        return

    # build modes
    dos = attackDoSMode()
    ddos = attackDDoSMode()
    adaptive = attackAdaptiveMode(dos, ddos)

    controller = SimulationController(duration=duration)

    st.session_state.controller = controller
    st.session_state.modes = ModeRefs(dos=dos, ddos=ddos, adaptive=adaptive)
    st.session_state.log_lines = st.session_state.get("log_lines", [])
    st.session_state.started_at = time.time()
    st.session_state.duration = duration

    def runner():
        # IMPORTANT: do NOT touch st.session_state in this thread
        controller.reset()
        controller.run_many([
            (dos, {"num_threads": dos_threads, "duration": duration}),
            (ddos, {"num_threads": ddos_threads, "duration": duration}),
            (adaptive, {}),
        ])
        controller.start_for(duration)

    t = threading.Thread(target=runner, daemon=True)
    st.session_state.controller_thread = t
    t.start()


def stop_simulation():
    controller: Optional[SimulationController] = st.session_state.get("controller")
    if controller:
        controller.stop()


# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Capstone Simulator", layout="wide")
st.title("Capstone Simulator (Streamlit UI)")

# init session defaults
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []

running_now = is_running()

# sidebar controls
with st.sidebar:
    st.header("Controls")

    duration = st.number_input("Duration (seconds)", min_value=1, max_value=3600, value=15, step=1)
    dos_threads = st.number_input("DoS threads", min_value=1, max_value=200, value=10, step=1)
    ddos_threads = st.number_input("DDoS threads", min_value=1, max_value=200, value=10, step=1)

    colA, colB = st.columns(2)
    with colA:
        if st.button("Start", disabled=running_now):
            start_simulation(int(duration), int(dos_threads), int(ddos_threads))
            st.session_state.log_lines.append(f"[{time.strftime('%H:%M:%S')}] Started simulation")
            st.rerun()

    with colB:
        if st.button("Stop", disabled=not running_now):
            stop_simulation()
            st.session_state.log_lines.append(f"[{time.strftime('%H:%M:%S')}] Stop requested")
            st.rerun()

    st.caption("Run with: streamlit run ui_streamlit.py")


left, right = st.columns([2, 1], vertical_alignment="top")

with left:
    st.subheader("Status")

    modes: Optional[ModeRefs] = st.session_state.get("modes")
    if not modes:
        st.info("Press Start to run the simulation.")
    else:
        dos_state = safe_state(modes.dos)
        ddos_state = safe_state(modes.ddos)

        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("### DoS")
            st.metric("RPS", dos_state.get("rps", "-"))
            dom = dos_state.get("dominance", "-")
            st.metric("Dominance", f"{dom:.3f}" if isinstance(dom, (float, int)) else dom)
            st.metric("Impact", dos_state.get("impact_achieved", "-"))

        with c2:
            st.markdown("### DDoS")
            st.metric("RPS", ddos_state.get("rps", "-"))
            st.metric("Unique IPs", ddos_state.get("unique_ips", "-"))
            dom = ddos_state.get("dominance", "-")
            st.metric("Dominance", f"{dom:.3f}" if isinstance(dom, (float, int)) else dom)

        with c3:
            st.markdown("### Adaptive")
            a = modes.adaptive
            st.write("DoS boost:", getattr(a, "dos_boost_on", None))
            st.write("DDoS boost:", getattr(a, "ddos_boost_on", None))
            st.write("Fail streak DoS:", getattr(a, "fail_streak_dos", None))
            st.write("Fail streak DDoS:", getattr(a, "fail_streak_ddos", None))

        if running_now:
            st.caption("Auto-refreshing…")
            time.sleep(0.25)
            st.rerun()

with right:
    st.subheader("Logs")
    st.text_area("Log output", value="\n".join(st.session_state.log_lines[-300:]), height=500)

    st.subheader("Run state")
    st.write("Running:", running_now)
    if st.session_state.get("started_at"):
        elapsed = time.time() - st.session_state.started_at
        st.write("Elapsed:", f"{elapsed:.1f}s")
