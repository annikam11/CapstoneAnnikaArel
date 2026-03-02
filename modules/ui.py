from __future__ import annotations

import sys
import json
import queue
import threading
import time
import random
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Callable, Optional

from PIL import Image, ImageTk

from modules.controller import SimulationController
from modules.attack_mode import attackDoSMode, attackDDoSMode, attackAdaptiveMode
from modules.defense_mode import DefenseDosMode, DefenseDDoSMode, DefenseAdaptiveMode


# =========================
# Color theme (KEEP THESE)
# =========================
COL_BG = "#000000"
COL_SIDEBAR = "#0b0b0b"
COL_PANEL = "#111111"
COL_PANEL2 = "#1a1a1a"
COL_BORDER = "#2a2a2a"

COL_TEXT = "#ffffff"
COL_MUTED = "#c9c9c9"

COL_ATTACK_PANEL = "#b00020"
COL_ATTACK_BORDER = "#5c1f2a"

COL_DEFENSE_PANEL = "#0557ad"
COL_DEFENSE_BORDER = "#1f3c5c"

COL_PURPLE = "#9d8ea5"
COL_CYAN = "#fefefe"
COL_GREEN = "#10b981"
COL_BLUE = "#3b82f6"
COL_RED = "#ff3b3b"

COL_SECTION = "#888888"
COL_NAV_ACTIVE = COL_GREEN
COL_NAV_TEXT = "#ffffff"
COL_ACCENT = COL_CYAN
COL_AMBER = "#f59e0b"


# =========================
# Non-technical helpers
# =========================
def traffic_level_label(rps: int, limit: Optional[int] = None, impact: bool = False) -> tuple[str, str]:
    if impact:
        return ("Overwhelmed", COL_RED)

    rps = int(rps or 0)

    if limit and limit > 0:
        ratio = rps / float(limit)
        if ratio < 0.40:
            return ("Low", COL_GREEN)
        if ratio < 0.85:
            return ("Moderate", COL_AMBER)
        return ("High", COL_RED)

    if rps < 1200:
        return ("Low", COL_GREEN)
    if rps < 3000:
        return ("Moderate", COL_AMBER)
    return ("High", COL_RED)


def explain_for_nontechnical(family: str, kind: str, state: dict, limit: Optional[int] = None) -> tuple[str, str]:
    rps = int(state.get("rps", 0) or 0)
    dominance = float(state.get("dominance", 0.0) or 0.0)
    unique_ips = int(state.get("unique_ips", 0) or 0)

    impact = bool(state.get("impact_achieved", False) or state.get("impact achieved", False) or state.get("impact", False))
    confirmed_dos = bool(state.get("confirmed_DoS", False) or state.get("confirmed DoS", False))
    confirmed_ddos = bool(state.get("confirmed_DDoS", False) or state.get("confirmed DDoS", False))

    lvl, _ = traffic_level_label(rps, limit=limit, impact=impact)

    if family == "Attack":
        if impact:
            return ("✅ Disruption achieved", "The service is now overwhelmed by traffic.")
        if lvl == "High":
            return ("⚠️ Heavy pressure", "Traffic is close to the disruption threshold. Keep it steady to trigger disruption.")
        if lvl == "Moderate":
            return ("⏳ Building pressure", "Traffic is increasing, but it may not be enough yet.")
        return ("✅ Light traffic", "Traffic is low. Increase pressure to see impact.")

    # Defense
    if confirmed_dos:
        return ("🚨 Confirmed DoS attack", "Most traffic appears to come from one main source. Defenses would rate-limit or block it.")
    if confirmed_ddos:
        return ("🚨 Confirmed DDoS attack", "Traffic comes from many sources at once. Defenses would filter and mitigate broadly.")

    if lvl in ("Moderate", "High"):
        if unique_ips >= 15 and dominance <= 0.35:
            return ("⚠️ Suspicious: many-source flooding", "Many sources appear active at once. Waiting for confirmation.")
        if dominance >= 0.75 and (unique_ips == 0 or unique_ips <= 3):
            return ("⚠️ Suspicious: one-source flooding", "One main source appears to dominate the traffic. Waiting for confirmation.")

    if lvl == "High":
        return ("⚠️ Unusual spike", "Traffic is very high, but not confirmed as an attack yet.")
    return ("✅ Normal traffic", "Traffic looks typical and doesn’t match common attack patterns right now.")

def wizard_glossary_text(lab):
    lines = []
    lines.append("Quick definitions:")
    lines.append("")

    lines.append("• RPS (Requests Per Second):")
    lines.append("  How many requests hit the service every second.")
    lines.append("  Higher RPS = more pressure on the system.")
    lines.append("")

    lines.append("• Dominance:")
    lines.append("  How much of the traffic comes from the top sender (the #1 source).")
    lines.append("  Example: Dominance 0.80 means the top sender caused ~80% of traffic.")
    lines.append("  High dominance usually = one main attacker (DoS-style).")
    lines.append("  Lower dominance usually = traffic spread out (DDoS-style).")
    lines.append("")

    # Build searchable lab text safely
    step_blob = " ".join(
        [f"{s.title} {s.objective} {s.watch}" for s in (lab.steps or [])]
    )
    quiz_blob = ""
    if lab.quiz:
        quiz_blob = " ".join([lab.quiz.question] + (lab.quiz.choices or []))

    lab_text = f"{lab.title} {lab.summary} {step_blob} {quiz_blob}".lower()

    if "unique ip" in lab_text or "unique ips" in lab_text:
        lines.append("• Unique IPs:")
        lines.append("  How many different senders are active at the same time.")
        lines.append("  More unique IPs usually means a distributed attack (DDoS).")
        lines.append("")

    lines.append("Rule of thumb:")
    lines.append("  One bully = DoS.")
    lines.append("  Crowd attack = DDoS.")

    return "\n".join(lines)

def _extract_limit_from_mode(mode_obj) -> Optional[int]:
    if not mode_obj:
        return None
    for attr in ("dos_limit", "ddos_limit", "limit", "rps_limit", "threshold", "impact_threshold"):
        try:
            val = getattr(mode_obj, attr, None)
            if isinstance(val, (int, float)) and val > 0:
                return int(val)
        except Exception:
            pass
    return None


# =========================
# User profiles + Points + Settings
# =========================
@dataclass
class UserProfile:
    username: str = "Guest"
    role: str = "Learner"  # Learner / Instructor
    labs_completed: list[str] = None
    quizzes_completed: list[str] = None
    points: int = 0

    default_duration: int = 15
    default_threads: int = 10
    quiz_points: int = 10

    def __post_init__(self):
        if self.labs_completed is None:
            self.labs_completed = []
        if self.quizzes_completed is None:
            self.quizzes_completed = []


def _profiles_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    p = root / "profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _profile_path(username: str) -> Path:
    safe = "".join(ch for ch in username.strip() if ch.isalnum() or ch in ("_", "-", " ")).strip()
    if not safe:
        safe = "Guest"
    return _profiles_dir() / f"{safe}.json"


# =========================
# Guided Labs
# =========================
@dataclass
class LabStep:
    title: str
    objective: str
    do_this_now: str
    watch: str
    stuck_tip: str
    done_when: Callable[[dict], bool]


@dataclass
class LabQuiz:
    question: str
    choices: list[str]
    correct_index: int
    explain_correct: str
    points: int = 10


@dataclass
class GuidedLab:
    lab_id: str
    title: str
    summary: str
    recommended_mode: str  # DoS / DDoS / Adaptive
    steps: list[LabStep]
    quiz: Optional[LabQuiz] = None


def _get_bool(state: dict, *keys: str) -> bool:
    return any(bool(state.get(k, False)) for k in keys)


def build_guided_labs(points_per_quiz: int):
    attack_labs = [
        GuidedLab(
            lab_id="A1",
            title="Attack Lab 1 — DoS (single-source pressure)",
            summary="Overwhelm the service using one dominant sender until disruption occurs.",
            recommended_mode="DoS",
            steps=[
                LabStep(
                    title="Start traffic",
                    objective="Reach RPS ≥ 600",
                    do_this_now="Press “Run Lesson”. Then wait ~3 seconds.",
                    watch="Traffic level + status message",
                    stuck_tip="If it stays low, press “Use Recommended” or open Advanced and add +10 Threads.",
                    done_when=lambda s: int(s.get("rps", 0) or 0) >= 600,
                ),
                LabStep(
                    title="Build pressure",
                    objective="Reach RPS ≥ 1200",
                    do_this_now="Press “Use Recommended”, then “Run Lesson”.",
                    watch="RPS staying high (not just a spike)",
                    stuck_tip="If it bounces: set Duration to 35–45s in Advanced.",
                    done_when=lambda s: int(s.get("rps", 0) or 0) >= 1200,
                ),
                LabStep(
                    title="Achieve disruption",
                    objective="Disruption/Impact becomes TRUE",
                    do_this_now="Run lesson and keep pressure steady.",
                    watch="Status: “Disruption achieved”",
                    stuck_tip="If it doesn’t trigger: open Advanced and add +20 Threads.",
                    done_when=lambda s: _get_bool(s, "impact_achieved", "impact achieved", "impact"),
                ),
            ],
            quiz=LabQuiz(
                question="In a DoS attack, where does most traffic come from?",
                choices=["One main source", "Many different sources", "Only the victim"],
                correct_index=0,
                explain_correct="DoS generally means one dominant sender overwhelms the target.",
                points=points_per_quiz,
            ),
        ),
        GuidedLab(
            lab_id="A2",
            title="Attack Lab 2 — DDoS (many-source pressure)",
            summary="Increase unique senders and push traffic until disruption occurs.",
            recommended_mode="DDoS",
            steps=[
                LabStep(
                    title="Start distributed traffic",
                    objective="Reach Unique IPs ≥ 10",
                    do_this_now="Press “Run Lesson” and wait ~5 seconds.",
                    watch="Unique IPs (in Details if needed)",
                    stuck_tip="If Unique IPs is low: press “Use Recommended” then run again.",
                    done_when=lambda s: int(s.get("unique_ips", 0) or 0) >= 10,
                ),
                LabStep(
                    title="Increase sender diversity",
                    objective="Reach Unique IPs ≥ 25",
                    do_this_now="Press “Use Recommended”, then “Run Lesson”.",
                    watch="Unique IPs rising",
                    stuck_tip="Open Advanced and set Duration to 40–50s if it’s too short.",
                    done_when=lambda s: int(s.get("unique_ips", 0) or 0) >= 25,
                ),
                LabStep(
                    title="Achieve disruption",
                    objective="Disruption/Impact becomes TRUE",
                    do_this_now="Run lesson and keep pressure steady.",
                    watch="Status: “Disruption achieved”",
                    stuck_tip="If needed: Advanced → add +20 Threads.",
                    done_when=lambda s: _get_bool(s, "impact_achieved", "impact achieved", "impact"),
                ),
            ],
            quiz=LabQuiz(
                question="What often makes DDoS harder to stop than DoS?",
                choices=["It uses many sources at once", "It uses fewer requests", "It never spikes traffic"],
                correct_index=0,
                explain_correct="Many sources make blocking/filtering more difficult.",
                points=points_per_quiz,
            ),
        ),
        GuidedLab(
            lab_id="A3",
            title="Attack Lab 3 — Adaptive (switch tactics)",
            summary="Observe shifting behavior and still reach disruption.",
            recommended_mode="Adaptive",
            steps=[
                LabStep(
                    title="Start adaptive behavior",
                    objective="Reach RPS ≥ 600",
                    do_this_now="Press “Run Lesson” and wait ~5 seconds.",
                    watch="Traffic level + status message",
                    stuck_tip="If low: press “Use Recommended” then run again.",
                    done_when=lambda s: int(s.get("rps", 0) or 0) >= 600,
                ),
                LabStep(
                    title="See a clear pattern",
                    objective="Dominance ≥ 0.70 OR Unique IPs ≥ 15",
                    do_this_now="Turn on Details (optional) and wait ~5 seconds.",
                    watch="Dominance or Unique IPs",
                    stuck_tip="If it’s not showing: Advanced → Duration 45s.",
                    done_when=lambda s: (float(s.get("dominance", 0.0) or 0.0) >= 0.70)
                    or (int(s.get("unique_ips", 0) or 0) >= 15),
                ),
                LabStep(
                    title="Achieve disruption",
                    objective="Disruption/Impact becomes TRUE",
                    do_this_now="Run lesson and keep pressure steady.",
                    watch="Status: “Disruption achieved”",
                    stuck_tip="If needed: Advanced → add +20 Threads.",
                    done_when=lambda s: _get_bool(s, "impact_achieved", "impact achieved", "impact"),
                ),
            ],
            quiz=LabQuiz(
                question="What does 'Adaptive' mean in this simulator?",
                choices=["It changes tactics based on results", "It always uses only one IP", "It lowers traffic on purpose"],
                correct_index=0,
                explain_correct="Adaptive behavior shifts tactics to try to succeed more reliably.",
                points=points_per_quiz,
            ),
        ),
    ]

    defense_labs = [
        GuidedLab(
            lab_id="D1",
            title="Defense Lab 1 — Detect DoS",
            summary="Identify one dominant sender and wait for confirmation.",
            recommended_mode="DoS",
            steps=[
                LabStep(
                    title="Observe dominance",
                    objective="Dominance ≥ 0.70",
                    do_this_now="Press “Run Lesson”. Then turn on Details (optional).",
                    watch="Dominance",
                    stuck_tip="If it stays low: press “Use Recommended” then run again.",
                    done_when=lambda s: float(s.get("dominance", 0.0) or 0.0) >= 0.70,
                ),
                LabStep(
                    title="Wait for confirmation",
                    objective="Confirmed DoS = TRUE",
                    do_this_now="Keep monitoring (it takes time).",
                    watch="Confirmed DoS (in Details if needed)",
                    stuck_tip="Advanced → Duration 45–60s helps confirmations.",
                    done_when=lambda s: _get_bool(s, "confirmed_DoS", "confirmed DoS"),
                ),
            ],
            quiz=LabQuiz(
                question="In this simulator, what does 'dominance' mean?",
                choices=["How much traffic comes from the top sender", "How many ports are open", "How fast the CPU is"],
                correct_index=0,
                explain_correct="Dominance is the share of traffic produced by the most active sender.",
                points=points_per_quiz,
            ),
        ),
        GuidedLab(
            lab_id="D2",
            title="Defense Lab 2 — Detect DDoS",
            summary="Identify many senders and wait for confirmation.",
            recommended_mode="DDoS",
            steps=[
                LabStep(
                    title="Observe many sources",
                    objective="Unique IPs ≥ 15",
                    do_this_now="Press “Run Lesson” and wait ~5 seconds.",
                    watch="Unique IPs",
                    stuck_tip="If Unique IPs stays low: use “Recommended” then run again.",
                    done_when=lambda s: int(s.get("unique_ips", 0) or 0) >= 15,
                ),
                LabStep(
                    title="Wait for confirmation",
                    objective="Confirmed DDoS = TRUE",
                    do_this_now="Keep monitoring (it takes time).",
                    watch="Confirmed DDoS (in Details if needed)",
                    stuck_tip="Advanced → Duration 60s can help confirmations.",
                    done_when=lambda s: _get_bool(s, "confirmed_DDoS", "confirmed DDoS"),
                ),
            ],
            quiz=LabQuiz(
                question="What is a common warning sign of DDoS?",
                choices=["Many unique sources at once", "One IP dominates everything", "Traffic is always low"],
                correct_index=0,
                explain_correct="DDoS typically includes many concurrent senders.",
                points=points_per_quiz,
            ),
        ),
        GuidedLab(
            lab_id="D3",
            title="Defense Lab 3 — Monitor Adaptive",
            summary="Handle shifting patterns and still get a confirmation signal.",
            recommended_mode="Adaptive",
            steps=[
                LabStep(
                    title="Start monitoring",
                    objective="RPS ≥ 600",
                    do_this_now="Press “Run Lesson” and wait ~5 seconds.",
                    watch="Traffic level + status message",
                    stuck_tip="Use “Recommended” then run again if low.",
                    done_when=lambda s: int(s.get("rps", 0) or 0) >= 600,
                ),
                LabStep(
                    title="See an indicator",
                    objective="Dominance ≥ 0.70 OR Unique IPs ≥ 15",
                    do_this_now="Turn on Details (optional) and wait ~5 seconds.",
                    watch="Dominance or Unique IPs",
                    stuck_tip="Advanced → Duration 45–60s helps adaptive patterns emerge.",
                    done_when=lambda s: (float(s.get("dominance", 0.0) or 0.0) >= 0.70)
                    or (int(s.get("unique_ips", 0) or 0) >= 15),
                ),
                LabStep(
                    title="Wait for confirmation",
                    objective="Confirmed DoS OR Confirmed DDoS = TRUE",
                    do_this_now="Keep monitoring (confirmation is intentionally slower).",
                    watch="Confirmed DoS / Confirmed DDoS",
                    stuck_tip="Advanced → Duration 60s helps confirmations.",
                    done_when=lambda s: _get_bool(s, "confirmed_DoS", "confirmed DoS", "confirmed_DDoS", "confirmed DDoS"),
                ),
            ],
            quiz=LabQuiz(
                question="Why can Adaptive behavior be harder to detect?",
                choices=["It changes patterns over time", "It always has low traffic", "It uses only one request"],
                correct_index=0,
                explain_correct="Shifting patterns mean defenders must evaluate behavior across time.",
                points=points_per_quiz,
            ),
        ),
    ]

    return attack_labs, defense_labs


# =========================
# Thread print capture -> UI log
# =========================
class QueueWriter:
    def __init__(self, q: "queue.Queue[str]"):
        self.q = q
        self._buf = ""

    def write(self, s: str):
        if not s:
            return
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.q.put(line + "\n")

    def flush(self):
        if self._buf:
            self.q.put(self._buf)
            self._buf = ""


class ArelGuardApp(tk.Tk):
    def __init__(self):
        super().__init__()

        def resource_path(relative: str) -> Path:
            if hasattr(sys, "_MEIPASS"):
                return Path(sys._MEIPASS) / relative
            return Path(__file__).resolve().parent.parent / relative

        # Icon
        icon_path = resource_path("assets/appIcon/ArelGuardLogo.ico")
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass
            try:
                ico_img = Image.open(str(icon_path))
                self._icon_imgtk = ImageTk.PhotoImage(ico_img)
                self.iconphoto(True, self._icon_imgtk)
            except Exception:
                pass

        # Logo
        logo_path = resource_path("assets/images/ArelGuardLogo.png")
        self.logo_image = None
        if logo_path.exists():
            img = Image.open(logo_path)

            max_w, max_h = 180, 120  # tweak these
            img.thumbnail((max_w, max_h), Image.LANCZOS)

            self.logo_image = ImageTk.PhotoImage(img)

        self.title("ArelGuard")
        self.geometry("1200x750")
        self.minsize(1050, 650)
        self.configure(bg=COL_BG)

        self.active_page = "Overview"

        # Controller
        self.controller = SimulationController(duration=15)
        self._stop_after_id = None
        self._run_end_ts: Optional[float] = None

        # Learned limits (fallback)
        self._learned_limit: dict[tuple[str, str], int] = {}
        self._observed_peak: dict[tuple[str, str], int] = {}

        # Mode refs
        self.current_family: str | None = None
        self.current_mode_kind: str | None = None
        self.current_modes: dict[str, object] = {}

        # Labs
        self._labs_loaded = False
        self.attack_labs: list[GuidedLab] = []
        self.defense_labs: list[GuidedLab] = []

        # User
        self.user = UserProfile()

        # stdout capture
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._orig_stdout = sys.stdout
        sys.stdout = QueueWriter(self._log_q)

        # Dynamic wrap registry
        self._wrap_registry: list[tuple[tk.Label, int, float]] = []
        self._sidebar_target_w = 250

        self._build_layout()
        self._setup_ttk_style()

        # ✅ FIX: enable scroll wheel globally (works even when cursor is on buttons/checkboxes)
        self._install_global_scroll()

        self.bind("<Configure>", self._on_window_resize)

        self.after(50, self._prompt_user_dialog)
        self.show_overview()

    # ---------- GLOBAL scrollable content root ----------
    def _build_scrollable_content_root(self):
        """
        One global scroll area for the whole app content (right side).
        Sidebar stays fixed.
        After this, self.content is the INNER frame you build pages into.
        """
        self.content_outer = tk.Frame(self, bg=COL_BG)
        self.content_outer.grid(row=0, column=1, sticky="nsew")
        self.content_outer.grid_rowconfigure(0, weight=1)
        self.content_outer.grid_columnconfigure(0, weight=1)

        self.content_canvas = tk.Canvas(self.content_outer, bg=COL_BG, highlightthickness=0, bd=0)
        self.content_vbar = tk.Scrollbar(self.content_outer, orient="vertical", command=self.content_canvas.yview)
        self.content_canvas.configure(yscrollcommand=self.content_vbar.set)

        self.content_canvas.grid(row=0, column=0, sticky="nsew")
        self.content_vbar.grid(row=0, column=1, sticky="ns")

        self.content = tk.Frame(self.content_canvas, bg=COL_BG)
        self._content_window_id = self.content_canvas.create_window((0, 0), window=self.content, anchor="nw")

        def _on_inner_configure(_e=None):
            self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))

        def _on_canvas_configure(e):
            try:
                self.content_canvas.itemconfigure(self._content_window_id, width=e.width)
            except Exception:
                pass

        self.content.bind("<Configure>", _on_inner_configure)
        self.content_canvas.bind("<Configure>", _on_canvas_configure)

        # helpful: click anywhere in the content area to "focus" it
        self.content_canvas.bind("<Button-1>", lambda _e: self.content_canvas.focus_set())

    # ✅ FIX: mousewheel works even on buttons/checkboxes/spinboxes/etc.
    def _install_global_scroll(self):
        def _scroll_canvas(delta_units: int):
            try:
                self.content_canvas.yview_scroll(delta_units, "units")
            except Exception:
                pass

        def _on_mousewheel_windows(e):
            # Windows / Mac touchpad often uses delta
            if getattr(e, "delta", 0):
                # normalize: delta is usually 120 multiples on Windows, smaller on touchpads
                step = int(-1 * (e.delta / 120)) if abs(e.delta) >= 120 else (-1 if e.delta > 0 else 1)
                _scroll_canvas(step)
                return "break"

        def _on_mousewheel_linux(e):
            # Linux wheel events
            if getattr(e, "num", None) == 4:
                _scroll_canvas(-3)
                return "break"
            if getattr(e, "num", None) == 5:
                _scroll_canvas(3)
                return "break"

        # Bind at root level so it works regardless of which widget is under the cursor
        self.bind_all("<MouseWheel>", _on_mousewheel_windows)
        self.bind_all("<Button-4>", _on_mousewheel_linux)
        self.bind_all("<Button-5>", _on_mousewheel_linux)

        # Optional: Shift+wheel scrolls horizontally (rarely needed, but harmless)
        def _on_shift_mousewheel(e):
            if getattr(e, "delta", 0):
                try:
                    self.content_canvas.xview_scroll(int(-1 * (e.delta / 120)), "units")
                    return "break"
                except Exception:
                    pass

        self.bind_all("<Shift-MouseWheel>", _on_shift_mousewheel)

    # ---------- Dynamic UI sizing ----------
    def _register_wrap(self, label: tk.Label, pad: int = 28, fraction: float = 0.92):
        self._wrap_registry.append((label, pad, fraction))
        self.after(1, self._on_window_resize)

    def _clear_wrap_registry(self):
        self._wrap_registry.clear()

    def _on_window_resize(self, event=None):
        total_w = max(900, self.winfo_width())
        target = int(total_w * 0.21)
        target = max(220, min(340, target))
        if self._sidebar_target_w != target:
            self._sidebar_target_w = target
            try:
                self.sidebar.configure(width=target)
            except Exception:
                pass

        try:
            content_w = max(320, self.content_canvas.winfo_width())
        except Exception:
            return

        for lbl, pad, frac in list(self._wrap_registry):
            try:
                wl = int((content_w - pad * 2) * frac)
                lbl.configure(wraplength=max(280, wl))
            except Exception:
                pass

    def _bind_simple_wrap(self, label: tk.Label, pad: int = 28, fraction: float = 0.92):
        self._register_wrap(label, pad=pad, fraction=fraction)

    # ---------- Profiles ----------
    def _load_user(self, username: str) -> UserProfile:
        p = _profile_path(username)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return UserProfile(
                    username=data.get("username", username),
                    role=data.get("role", "Learner"),
                    labs_completed=list(data.get("labs_completed", [])),
                    quizzes_completed=list(data.get("quizzes_completed", [])),
                    points=int(data.get("points", 0) or 0),
                    default_duration=int(data.get("default_duration", 15) or 15),
                    default_threads=int(data.get("default_threads", 10) or 10),
                    quiz_points=int(data.get("quiz_points", 10) or 10),
                )
            except Exception:
                pass
        return UserProfile(username=username)

    def _save_user(self):
        try:
            p = _profile_path(self.user.username)
            p.write_text(json.dumps(asdict(self.user), indent=2), encoding="utf-8")
        except Exception:
            pass

    def _prompt_user_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Choose User")
        dlg.configure(bg=COL_BG)
        dlg.geometry("520x320")
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="Welcome to ArelGuard", fg=COL_TEXT, bg=COL_BG, font=("Segoe UI", 16, "bold")).pack(pady=(18, 6))
        tk.Label(dlg, text="Enter a name to save your lab progress and points.", fg=COL_MUTED, bg=COL_BG, font=("Segoe UI", 11)).pack(pady=(0, 12))

        form = tk.Frame(dlg, bg=COL_BG)
        form.pack(fill="x", padx=22, pady=8)
        form.grid_columnconfigure(0, weight=1)

        tk.Label(form, text="Name", fg=COL_TEXT, bg=COL_BG, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        name_var = tk.StringVar(value=(self.user.username or "Guest"))
        name_entry = tk.Entry(form, textvariable=name_var, bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT, relief="flat")
        name_entry.grid(row=1, column=0, sticky="ew", pady=(4, 10))

        tk.Label(form, text="Role", fg=COL_TEXT, bg=COL_BG, font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w")
        role_var = tk.StringVar(value=(self.user.role or "Learner"))
        ttk.Combobox(form, textvariable=role_var, values=["Learner", "Instructor"], state="readonly").grid(row=3, column=0, sticky="ew", pady=(4, 0))

        msg = tk.Label(dlg, text="", fg=COL_AMBER, bg=COL_BG, font=("Segoe UI", 10, "bold"))
        msg.pack(pady=(10, 0))

        btns = tk.Frame(dlg, bg=COL_BG)
        btns.pack(fill="x", padx=22, pady=(16, 18))

        def choose():
            name = name_var.get().strip()
            if not name:
                msg.config(text="Please enter a name.")
                return
            self.user = self._load_user(name)
            self.user.role = (role_var.get().strip() or "Learner")
            self._save_user()
            dlg.destroy()
            self._labs_loaded = False
            self._build_sidebar()
            self.show_overview()

        tk.Button(
            btns,
            text="Continue",
            command=choose,
            bg=COL_ACCENT,
            fg="#0b1220",
            relief="flat",
            font=("Segoe UI", 11, "bold"),
            padx=14,
            pady=10,
            cursor="hand2",
        ).pack(side="right")

        name_entry.focus_set()
        dlg.wait_window(dlg)

    # ---------- Cleanup ----------
    def destroy(self):
        try:
            self.stop_simulation()
        except Exception:
            pass
        try:
            sys.stdout = self._orig_stdout
        except Exception:
            pass
        super().destroy()

    # =========================
    # Layout
    # =========================
    def _build_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)

        self.sidebar = tk.Frame(self, bg=COL_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="ns")

        self.sidebar.configure(width=self._sidebar_target_w)
        self.sidebar.grid_propagate(False)

        self._build_scrollable_content_root()
        self._build_sidebar()

    def _setup_ttk_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "TCombobox",
            fieldbackground=COL_PANEL2,
            background=COL_PANEL2,
            foreground=COL_TEXT,
            arrowcolor=COL_CYAN,
            bordercolor=COL_BORDER,
            lightcolor=COL_BORDER,
            darkcolor=COL_BORDER,
        )

    def _build_sidebar(self):
        for w in self.sidebar.winfo_children():
            w.destroy()

        user_card = tk.Frame(self.sidebar, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        user_card.pack(fill="x", padx=12, pady=(12, 8))

        tk.Label(user_card, text="User", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(user_card, text=self.user.username, fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(2, 0))
        tk.Label(user_card, text=self.user.role, fg=COL_CYAN, bg=COL_PANEL, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12)
        tk.Label(user_card, text=f"Points: {self.user.points}", fg=COL_GREEN, bg=COL_PANEL, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(6, 0))

        tk.Label(user_card, text="Labs:", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        done = ", ".join(self.user.labs_completed) if self.user.labs_completed else "None yet"
        tk.Label(user_card, text=done, fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 9), wraplength=210, justify="left").pack(anchor="w", padx=12, pady=(2, 8))

        tk.Button(
            user_card,
            text="Switch User",
            command=self._prompt_user_dialog,
            bg=COL_PANEL2,
            fg=COL_CYAN,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=8,
            cursor="hand2",
        ).pack(fill="x", padx=12, pady=(6, 8))

        tk.Button(
            user_card,
            text="Log Out",
            command=self.logout,
            bg=COL_PANEL2,
            fg=COL_CYAN,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=8,
            cursor="hand2",
        ).pack(fill="x", padx=12, pady=(0, 12))

        def section(label: str):
            tk.Label(self.sidebar, text=label, fg=COL_SECTION, bg=COL_SIDEBAR, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16, pady=(14, 6))

        def nav_button(text: str, command):
            active = (self.active_page == text)
            fg = COL_NAV_ACTIVE if active else COL_NAV_TEXT
            tk.Button(
                self.sidebar,
                text=text,
                fg=fg,
                bg=COL_SIDEBAR,
                activebackground=COL_PANEL,
                activeforeground=COL_NAV_ACTIVE,
                relief="flat",
                anchor="w",
                font=("Segoe UI", 11, "bold"),
                command=command,
                cursor="hand2",
                padx=6,
                pady=8,
            ).pack(fill="x", padx=12, pady=2)

        section("GENERAL")
        nav_button("Overview", self.show_overview)
        nav_button("Attack", lambda: self.show_attack(guided=False))
        nav_button("Defense", lambda: self.show_defense(guided=False))

        section("LEARNING (EASY)")
        nav_button("Attack Guided", lambda: self.show_attack(guided=True))
        nav_button("Defense Guided", lambda: self.show_defense(guided=True))

        section("SETTINGS")
        nav_button("Help", self.show_help)
        nav_button("Settings", self.show_settings)

    # =========================
    # UI helpers
    # =========================
    def clear_content(self):
        self._clear_wrap_registry()
        for w in self.content.winfo_children():
            w.destroy()
        try:
            self.content_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _set_active_page(self, page: str):
        self.active_page = page
        self._build_sidebar()

    def _page_header_centered(self, title: str, subtitle: str | None = None):
        header = tk.Frame(self.content, bg=COL_BG)
        header.pack(fill="x", padx=28, pady=(22, 14))

        if title.strip() == "ArelGuard":
            brand = tk.Frame(header, bg=COL_BG)
            brand.pack(anchor="center")
            tk.Label(brand, text="Arel", fg=COL_ATTACK_PANEL, bg=COL_BG, font=("Segoe UI", 26, "bold")).pack(side="left")
            tk.Label(brand, text="Guard", fg=COL_DEFENSE_PANEL, bg=COL_BG, font=("Segoe UI", 26, "bold")).pack(side="left")
        else:
            tk.Label(header, text=title, fg=COL_TEXT, bg=COL_BG, font=("Segoe UI", 26, "bold")).pack(anchor="center")

        if subtitle:
            lbl = tk.Label(header, text=subtitle, fg=COL_MUTED, bg=COL_BG, font=("Segoe UI", 12), wraplength=1, justify="center")
            lbl.pack(anchor="center", pady=(6, 0))
            self._bind_simple_wrap(lbl, pad=28, fraction=0.92)

        if self.logo_image:
            tk.Label(header, image=self.logo_image, bg=COL_BG).place(relx=1.0, x=-28, y=0, anchor="ne")

    # =========================
    # Simulation helpers
    # =========================
    def _cancel_hard_stop(self):
        if self._stop_after_id is not None:
            try:
                self.after_cancel(self._stop_after_id)
            except Exception:
                pass
            self._stop_after_id = None

    def _schedule_hard_stop(self, seconds: int):
        self._cancel_hard_stop()

        def do_stop():
            self.stop_simulation()
            self._stop_after_id = None

        self._stop_after_id = self.after(max(1, int(seconds)) * 1000, do_stop)

    def _start_timer_thread(self, seconds: int):
        try:
            t = threading.Thread(target=self.controller.start_for, kwargs={"seconds": int(seconds)}, daemon=True)
            t.start()
        except Exception:
            pass

    def stop_simulation(self):
        self._cancel_hard_stop()
        self._run_end_ts = None
        try:
            self.controller.stop()
        except Exception:
            pass
        try:
            self.controller.reset()
        except Exception:
            pass
        self.current_modes.clear()
        self.current_family = None
        self.current_mode_kind = None

    def _safe_state(self, mode) -> dict:
        try:
            lock = getattr(mode, "lock", None)
            if lock:
                with lock:
                    return dict(getattr(mode, "last_state", {}) or {})
            return dict(getattr(mode, "last_state", {}) or {})
        except Exception:
            return {}

    def _learn_limit(self, family: str, kind: str, rps: int) -> Optional[int]:
        key = (family, kind)
        rps = int(rps or 0)

        peak = max(self._observed_peak.get(key, 0), rps)
        self._observed_peak[key] = peak

        if peak >= 500:
            learned = int(max(1200, peak * 1.25))
            prev = self._learned_limit.get(key)
            self._learned_limit[key] = learned if prev is None else max(prev, learned)

        return self._learned_limit.get(key)

    def _start_simulation(self, family: str, mode_kind: str, threads: int, seconds: int):
        if family == "Attack":
            if mode_kind == "DoS":
                m = attackDoSMode()
                self.current_modes["single"] = m
                self.controller.run(m, start_kwargs={"num_threads": threads, "duration": seconds})
            elif mode_kind == "DDoS":
                m = attackDDoSMode()
                self.current_modes["single"] = m
                self.controller.run(m, start_kwargs={"num_threads": threads, "duration": seconds})
            else:
                dos = attackDoSMode()
                ddos = attackDDoSMode()
                adp = attackAdaptiveMode(dos, ddos)
                self.current_modes.update({"dos": dos, "ddos": ddos, "adaptive": adp})
                self.controller.run_many(
                    [
                        (dos, {"num_threads": threads, "duration": seconds}),
                        (ddos, {"num_threads": threads, "duration": seconds}),
                        (adp, {}),
                    ]
                )
        else:
            if mode_kind == "DoS":
                m = DefenseDosMode()
                self.current_modes["single"] = m
                self.controller.run(m, start_kwargs={"num_threads": threads, "duration": seconds})
            elif mode_kind == "DDoS":
                m = DefenseDDoSMode()
                self.current_modes["single"] = m
                self.controller.run(m, start_kwargs={"num_threads": threads, "duration": seconds})
            else:
                dos = DefenseDosMode()
                ddos = DefenseDDoSMode()
                adp = DefenseAdaptiveMode(dos, ddos)
                self.current_modes.update({"dos": dos, "ddos": ddos, "adaptive": adp})
                self.controller.run_many(
                    [
                        (dos, {"num_threads": max(5, threads // 2), "duration": seconds}),
                        (ddos, {"num_threads": threads, "duration": seconds}),
                        (adp, {}),
                    ]
                )

    # =========================
    # Celebration overlay
    # =========================
    def _celebrate(self, text: str, ms: int = 1800):
        try:
            self.update_idletasks()
            w = max(900, self.winfo_width())
            h = max(650, self.winfo_height())
        except Exception:
            return

        overlay = tk.Canvas(self, bg=COL_BG, highlightthickness=0, bd=0)
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.tk.call("raise", overlay._w)

        y1 = int(h * 0.12)
        y2 = int(h * 0.24)
        overlay.create_rectangle(0, y1, w, y2, fill=COL_PANEL2, outline=COL_GREEN, width=3)
        overlay.create_text(w // 2, (y1 + y2) // 2, text=text, fill=COL_GREEN, font=("Segoe UI", 26, "bold"))
        overlay.create_text(w // 2, y2 + 18, text="Nice work.", fill=COL_MUTED, font=("Segoe UI", 12, "bold"))

        confetti = []
        for _ in range(120):
            x = random.randint(0, w)
            y = random.randint(-h, 0)
            sz = random.randint(3, 7)
            col = random.choice([COL_GREEN, COL_BLUE, COL_PURPLE, COL_AMBER, COL_RED, COL_CYAN])
            r = overlay.create_rectangle(x, y, x + sz, y + sz, fill=col, outline="")
            confetti.append((r, random.uniform(2.5, 7.0), random.uniform(-1.8, 1.8)))

        def hard_kill():
            try:
                overlay.destroy()
            except Exception:
                pass

        self.after(max(400, int(ms)), hard_kill)

        start = time.time()
        duration = ms / 1000.0

        def tick():
            try:
                if not overlay.winfo_exists():
                    return
                t = time.time() - start
                if t >= duration:
                    hard_kill()
                    return
                for r, vy, vx in confetti:
                    overlay.move(r, vx, vy)
                self.after(16, tick)
            except Exception:
                hard_kill()

        tick()

    # =========================
    # Labs helpers
    # =========================
    def _init_labs_if_needed(self):
        if self._labs_loaded:
            return
        self.attack_labs, self.defense_labs = build_guided_labs(self.user.quiz_points)
        self._labs_loaded = True

    def _lab_list_for_family(self, family: str):
        self._init_labs_if_needed()
        return self.attack_labs if family == "Attack" else self.defense_labs

    def _current_lab_state(self) -> dict:
        kind = self.current_mode_kind or "DoS"

        if kind == "Adaptive":
            dos = self.current_modes.get("dos")
            ddos = self.current_modes.get("ddos")
            dos_s = self._safe_state(dos) if dos else {}
            ddos_s = self._safe_state(ddos) if ddos else {}

            return {
                "rps": max(int(dos_s.get("rps", 0) or 0), int(ddos_s.get("rps", 0) or 0)),
                "dominance": max(float(dos_s.get("dominance", 0.0) or 0.0), float(ddos_s.get("dominance", 0.0) or 0.0)),
                "unique_ips": int(ddos_s.get("unique_ips", 0) or 0),
                "top_ip": int(max(dos_s.get("top_ip", 0) or 0, ddos_s.get("top_ip", 0) or 0)),
                "impact_achieved": bool(
                    dos_s.get("impact_achieved", False) or dos_s.get("impact achieved", False) or dos_s.get("impact", False)
                    or ddos_s.get("impact_achieved", False) or ddos_s.get("impact achieved", False) or ddos_s.get("impact", False)
                ),
                "confirmed_DoS": bool(dos_s.get("confirmed_DoS", False) or dos_s.get("confirmed DoS", False)),
                "confirmed_DDoS": bool(ddos_s.get("confirmed_DDoS", False) or ddos_s.get("confirmed DDoS", False)),
            }

        single = self.current_modes.get("single")
        return self._safe_state(single) if single else {}

    def _award_quiz_points_once(self, lab_id: str, points: int):
        quiz_key = f"{lab_id}:quiz"
        if quiz_key in self.user.quizzes_completed:
            return
        self.user.quizzes_completed.append(quiz_key)
        self.user.points += int(points)
        self._save_user()
        self._build_sidebar()

    # =========================
    # Log styling + polling
    # =========================
    def _style_log_widget(self, w: tk.Text):
        try:
            w.configure(
                font=("Consolas", 12),
                spacing1=2,
                spacing3=2,
                padx=10,
                pady=10,
            )
            w.tag_configure("sev_red", foreground=COL_RED)
            w.tag_configure("sev_amber", foreground=COL_AMBER)
            w.tag_configure("sev_green", foreground=COL_GREEN)
            w.tag_configure("sev_normal", foreground=COL_TEXT)
        except Exception:
            pass

    def _poll_log_queue(self, text_widget: tk.Text):
        def tag_for_line(line: str) -> str:
            s = (line or "").lower().strip()

            if "impact" in s and any(neg in s for neg in ["not occurred", "has not occurred", "not achieved", "no impact"]):
                return "sev_amber"

            if "confirmed" in s and any(neg in s for neg in ["not confirmed", "no confirmed", "false"]):
                return "sev_amber"

            if any(k in s for k in [
                "impact has occurred", "impact achieved", "disruption achieved",
                "overwhelmed", "confirmed dos", "confirmed ddos",
                "attack confirmed", "mitigation failed"
            ]):
                return "sev_red"

            if any(k in s for k in [
                "pressure", "suspicious", "waiting", "insufficient",
                "spike", "boosting", "building"
            ]):
                return "sev_amber"

            if any(k in s for k in ["mitigated", "stable", "resolved", "success", "complete"]):
                return "sev_green"

            return "sev_normal"

        try:
            while True:
                line = self._log_q.get_nowait()
                t = tag_for_line(line)

                if t == "sev_red":
                    line = "🔴 " + line
                elif t == "sev_amber":
                    line = "🟡 " + line
                elif t == "sev_green":
                    line = "🟢 " + line
                else:
                    line = "⚪ " + line

                text_widget.configure(state="normal")
                text_widget.insert("end", line, (t,))
                text_widget.see("end")
                text_widget.configure(state="disabled")
        except queue.Empty:
            pass

        self.after(100, lambda: self._poll_log_queue(text_widget))

    def _poll_status_snapshot(self, family: str, mode_kind: str) -> dict:
        kind = mode_kind

        status = "Idle"
        rps = 0
        dom = 0.0
        uips = 0
        top = 0
        flags: dict = {}
        limit: Optional[int] = None

        if kind == "Adaptive":
            dos = self.current_modes.get("dos")
            ddos = self.current_modes.get("ddos")
            adaptive = self.current_modes.get("adaptive")

            dos_s = self._safe_state(dos) if dos else {}
            ddos_s = self._safe_state(ddos) if ddos else {}

            rps = max(int(dos_s.get("rps", 0) or 0), int(ddos_s.get("rps", 0) or 0))
            dom = max(float(dos_s.get("dominance", 0.0) or 0.0), float(ddos_s.get("dominance", 0.0) or 0.0))
            uips = int(ddos_s.get("unique_ips", 0) or 0)
            top = int(max(dos_s.get("top_ip", 0) or 0, ddos_s.get("top_ip", 0) or 0))

            flags["impact_achieved"] = bool(
                dos_s.get("impact_achieved", False) or dos_s.get("impact achieved", False) or dos_s.get("impact", False)
                or ddos_s.get("impact_achieved", False) or ddos_s.get("impact achieved", False) or ddos_s.get("impact", False)
            )
            flags["confirmed_DoS"] = bool(dos_s.get("confirmed_DoS", False) or dos_s.get("confirmed DoS", False))
            flags["confirmed_DDoS"] = bool(ddos_s.get("confirmed_DDoS", False) or ddos_s.get("confirmed DDoS", False))

            dos_limit = _extract_limit_from_mode(dos)
            ddos_limit = _extract_limit_from_mode(ddos)
            limit = max([v for v in (dos_limit, ddos_limit) if v], default=None)

            running = any(bool(getattr(m, "running", False)) for m in (dos, ddos, adaptive) if m)
            status = "Running" if running else "Idle"
        else:
            single = self.current_modes.get("single")
            s = self._safe_state(single) if single else {}

            rps = int(s.get("rps", 0) or 0)
            dom = float(s.get("dominance", 0.0) or 0.0)
            uips = int(s.get("unique_ips", 0) or 0)
            top = int(s.get("top_ip", 0) or 0)

            flags["impact_achieved"] = bool(s.get("impact_achieved", False) or s.get("impact achieved", False) or s.get("impact", False))
            flags["confirmed_DoS"] = bool(s.get("confirmed_DoS", False) or s.get("confirmed DoS", False))
            flags["confirmed_DDoS"] = bool(s.get("confirmed_DDoS", False) or s.get("confirmed DDoS", False))

            limit = _extract_limit_from_mode(single)
            status = "Running" if (single and getattr(single, "running", False)) else "Idle"

        if limit is None:
            limit = self._learn_limit(family, kind, rps)

        lvl_text, lvl_color = traffic_level_label(rps, limit=limit, impact=flags.get("impact_achieved", False))
        words_state = {"rps": rps, "dominance": dom, "unique_ips": uips, "top_ip": top, **flags}
        headline, explanation = explain_for_nontechnical(family, kind, words_state, limit=limit)

        remaining = None
        if status == "Running" and self._run_end_ts is not None:
            remaining = int(max(0, round(self._run_end_ts - time.time())))

        return {
            "status": status,
            "remaining": remaining,
            "rps": rps,
            "dominance": dom,
            "unique_ips": uips,
            "top_ip": top,
            "level_text": lvl_text,
            "level_color": lvl_color,
            "headline": headline,
            "explain": explanation,
            "flags": flags,
        }

    # =========================
    # Pages
    # =========================
    def show_overview(self):
        self._set_active_page("Overview")
        self.clear_content()
        self._page_header_centered("ArelGuard", "Beginner-friendly learning mode: big buttons, clear steps, optional advanced settings.")

        outer = tk.Frame(self.content, bg=COL_BG)
        outer.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)

        left = tk.Frame(outer, bg=COL_BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = tk.Frame(outer, bg=COL_BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        def card(parent, title, text, panel, border, primary_text, primary_cmd, secondary_text, secondary_cmd):
            c = tk.Frame(parent, bg=panel, highlightthickness=1, highlightbackground=border)
            c.pack(fill="x", pady=(0, 14))
            tk.Label(c, text=title, fg=COL_TEXT, bg=panel, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
            lbl = tk.Label(c, text=text, fg=COL_MUTED, bg=panel, font=("Segoe UI", 11), wraplength=1, justify="left")
            lbl.pack(anchor="w", padx=16, pady=(0, 14))
            self._bind_simple_wrap(lbl, pad=32, fraction=0.95)

            btns = tk.Frame(c, bg=panel)
            btns.pack(anchor="w", padx=16, pady=(0, 16))
            tk.Button(
                btns, text=primary_text, command=primary_cmd,
                bg=COL_ACCENT, fg="#0b1220",
                relief="flat", font=("Segoe UI", 12, "bold"),
                padx=16, pady=12, cursor="hand2"
            ).pack(side="left", padx=(0, 12))
            tk.Button(
                btns, text=secondary_text, command=secondary_cmd,
                bg=COL_PANEL, fg=COL_CYAN,
                relief="flat", font=("Segoe UI", 12, "bold"),
                padx=16, pady=12, cursor="hand2"
            ).pack(side="left")
            return lbl

        card(
            left,
            "Attack",
            "Learn how attackers overload services. The Guided tells you exactly what to do next.",
            COL_ATTACK_PANEL, COL_ATTACK_BORDER,
            "Start Guided Attack Lab",
            lambda: self.show_attack(guided=True),
            "Free Play",
            lambda: self.show_attack(guided=False),
        )

        card(
            left,
            "Defense",
            "Learn how defenders spot suspicious traffic and confirm attacks over time.",
            COL_DEFENSE_PANEL, COL_DEFENSE_BORDER,
            "Start Guided Defense Lab",
            lambda: self.show_defense(guided=True),
            "Free Play",
            lambda: self.show_defense(guided=False),
        )

        info = tk.Frame(right, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        info.pack(fill="both", expand=True)

        tk.Label(info, text="Progress", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 10))
        tk.Label(info, text=f"User: {self.user.username}", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11)).pack(anchor="w", padx=18)
        tk.Label(info, text=f"Points: {self.user.points}", fg=COL_GREEN, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(6, 10))

        tk.Label(info, text="Labs completed:", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11)).pack(anchor="w", padx=18)
        labs_done = ", ".join(self.user.labs_completed) if self.user.labs_completed else "None yet"
        labs_lbl = tk.Label(info, text=labs_done, fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 11), wraplength=1, justify="left")
        labs_lbl.pack(anchor="w", padx=18, pady=(6, 12))
        self._bind_simple_wrap(labs_lbl, pad=28, fraction=0.92)

        tk.Label(info, text="Easy Guided Lab tips:", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=18, pady=(8, 0))
        tips = tk.Label(
            info,
            text="• Press “Run Lesson” (it uses recommended settings)\n"
                 "• Only open Advanced if you want to experiment\n"
                 "• Steps lock in (no flicker)\n"
                 "• Quiz appears only after steps are complete",
            fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 11), wraplength=1, justify="left"
        )
        tips.pack(anchor="w", padx=18, pady=(6, 12))
        self._bind_simple_wrap(tips, pad=28, fraction=0.92)

    # =========================
    # Free Play
    # =========================
    def _build_freeplay_page(self, family: str):
        self._set_active_page(family)
        self.clear_content()
        self._page_header_centered(f"{family} — Free Play", "For experimenting. Guided Lab is recommended for non-technical users.")

        outer = tk.Frame(self.content, bg=COL_BG)
        outer.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        outer.grid_columnconfigure(0, weight=2)
        outer.grid_columnconfigure(1, weight=3)
        outer.grid_rowconfigure(0, weight=1)

        controls = tk.Frame(outer, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        controls.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        controls.grid_columnconfigure(0, weight=1)

        tk.Label(controls, text="Controls", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(16, 8))

        mode_kind_var = tk.StringVar(value="DoS")
        mode_row = tk.Frame(controls, bg=COL_PANEL)
        mode_row.pack(fill="x", padx=18, pady=(4, 8))
        tk.Label(mode_row, text="Mode", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).pack(side="left")
        ttk.Combobox(mode_row, textvariable=mode_kind_var, values=["DoS", "DDoS", "Adaptive"], state="readonly", width=12).pack(side="right")

        vars_row = tk.Frame(controls, bg=COL_PANEL)
        vars_row.pack(fill="x", padx=18, pady=(10, 6))
        vars_row.grid_columnconfigure(0, weight=1)

        tk.Label(vars_row, text="Threads", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w")
        threads_var = tk.IntVar(value=int(self.user.default_threads))
        tk.Spinbox(
            vars_row, from_=1, to=200, textvariable=threads_var, width=7,
            bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=0, column=1, sticky="e")

        tk.Label(vars_row, text="Duration (sec)", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(8, 0))
        dur_var = tk.IntVar(value=int(self.user.default_duration))
        tk.Spinbox(
            vars_row, from_=1, to=600, textvariable=dur_var, width=7,
            bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=1, column=1, sticky="e", pady=(8, 0))

        btns = tk.Frame(controls, bg=COL_PANEL)
        btns.pack(fill="x", padx=18, pady=(14, 8))

        def start_clicked():
            self.stop_simulation()
            self.current_family = family
            self.current_mode_kind = mode_kind_var.get()

            seconds = int(dur_var.get())
            threads = int(threads_var.get())
            self.controller.duration = seconds
            self._run_end_ts = time.time() + seconds

            self._start_simulation(family, mode_kind_var.get(), threads, seconds)
            self._schedule_hard_stop(seconds)
            self._start_timer_thread(seconds)

        tk.Button(
            btns, text="Start", command=start_clicked,
            bg=COL_ACCENT, fg="#0b1220",
            relief="flat", font=("Segoe UI", 11, "bold"),
            padx=14, pady=10, cursor="hand2",
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            btns, text="Stop", command=self.stop_simulation,
            bg=COL_PANEL2, fg=COL_CYAN,
            relief="flat", font=("Segoe UI", 11, "bold"),
            padx=14, pady=10, cursor="hand2",
        ).pack(side="left")

        right = tk.Frame(outer, bg=COL_BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        metrics = tk.Frame(right, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        metrics.grid(row=0, column=0, sticky="ew")
        metrics.grid_columnconfigure(0, weight=1)

        tk.Label(metrics, text="Live Status", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 6))

        meta_row = tk.Frame(metrics, bg=COL_PANEL)
        meta_row.pack(fill="x", padx=18, pady=(0, 8))
        lbl_run = tk.Label(meta_row, text="Status: Idle", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10, "bold"))
        lbl_run.pack(side="left")
        lbl_time = tk.Label(meta_row, text="Time left: —", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10, "bold"))
        lbl_time.pack(side="right")

        plain_box = tk.Frame(metrics, bg=COL_PANEL2, highlightthickness=1, highlightbackground=COL_BORDER)
        plain_box.pack(fill="x", padx=18, pady=(0, 12))
        lbl_headline = tk.Label(plain_box, text="Waiting…", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 12, "bold"))
        lbl_headline.pack(anchor="w", padx=12, pady=(10, 4))
        lbl_explain = tk.Label(plain_box, text="", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 10), wraplength=1, justify="left")
        lbl_explain.pack(anchor="w", padx=12, pady=(0, 10))
        self._bind_simple_wrap(lbl_explain, pad=46, fraction=0.92)

        traffic_row = tk.Frame(metrics, bg=COL_PANEL)
        traffic_row.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(traffic_row, text="Traffic level:", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10, "bold")).pack(side="left")
        lbl_level = tk.Label(traffic_row, text="Low", fg=COL_GREEN, bg=COL_PANEL, font=("Segoe UI", 11, "bold"))
        lbl_level.pack(side="left", padx=(8, 0))

        details = tk.Frame(metrics, bg=COL_PANEL2)
        details.pack(fill="x", padx=18, pady=(0, 14))
        lbl_rps = tk.Label(details, text="RPS: 0", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        lbl_dom = tk.Label(details, text="Dominance: 0.00", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        lbl_uips = tk.Label(details, text="Unique IPs: 0", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        lbl_top = tk.Label(details, text="Top IP req: 0", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        lbl_rps.pack(anchor="w", padx=12, pady=(10, 0))
        lbl_dom.pack(anchor="w", padx=12)
        lbl_uips.pack(anchor="w", padx=12)
        lbl_top.pack(anchor="w", padx=12, pady=(0, 10))

        logs = tk.Frame(right, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        logs.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        logs.grid_rowconfigure(1, weight=1)
        logs.grid_columnconfigure(0, weight=1)

        tk.Label(logs, text="Live Log", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))
        tk.Label(
            logs,
            text="Legend: 🔴 Critical  🟡 Warning/Building  🟢 Success  ⚪ Normal",
            fg=COL_MUTED,
            bg=COL_PANEL,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="e", padx=18, pady=(16, 8))

        text = tk.Text(
            logs,
            bg=COL_PANEL2,
            fg=COL_TEXT,
            insertbackground=COL_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COL_BORDER,
            wrap="word",
        )
        text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))
        text.configure(state="disabled")

        self._style_log_widget(text)
        self._poll_log_queue(text)

        def poll():
            if self.active_page != family:
                return

            snap = self._poll_status_snapshot(family, mode_kind_var.get())

            lbl_run.config(text=f"Status: {snap['status']}")
            if snap["status"] == "Running" and snap["remaining"] is not None:
                rem = snap["remaining"]
                lbl_time.config(text=f"Time left: {rem}s", fg=(COL_GREEN if rem > 3 else COL_AMBER))
            else:
                lbl_time.config(text="Time left: —", fg=COL_MUTED)

            lbl_level.config(text=snap["level_text"], fg=snap["level_color"])
            lbl_headline.config(text=snap["headline"])
            lbl_explain.config(text=snap["explain"])

            lbl_rps.config(text=f"RPS: {snap['rps']}")
            lbl_dom.config(text=f"Dominance: {snap['dominance']:.2f}")
            lbl_uips.config(text=f"Unique IPs: {snap['unique_ips']}")
            lbl_top.config(text=f"Top IP req: {snap['top_ip']}")

            self.after(250, poll)

        poll()

    # =========================
    # Wizard (Easy Mode)
    # =========================
    def _build_easy_wizard(self, family: str):
        # (UNCHANGED) — the scroll fix is global, so your wizard/details now scroll
        # even when the cursor is sitting on the "Show details" checkbox.
        # Everything below is identical to your previous UI.

        self._set_active_page(f"{family} Guided Lab")
        self.clear_content()

        self._page_header_centered(
            f"{family} Guided Lab (Easy Mode)",
            "Press “Run Lesson” → follow the big step card → quiz at the end. Advanced settings are optional."
        )

        labs = self._lab_list_for_family(family)

        state = {
            "lab_index": 0,
            "step_index": 0,
            "step_latched": False,
            "step_true_since": None,

            "quiz_open": False,
            "quiz_passed": False,
            "quiz_answer": -1,
            "quiz_correct_idx": None,

            "recommended_level": 0,
        }

        def base_recommended_for_mode(mode: str) -> tuple[int, int]:
            if mode == "DoS":
                return (10, 15)
            if mode == "DDoS":
                return (10, 20)
            return (15, 45)

        def bump_recommended(mode: str, bump_level: int) -> tuple[int, int]:
            t, d = base_recommended_for_mode(mode)
            t = min(200, t + bump_level * 15)
            d = min(120, d + bump_level * 5)
            return (t, d)

        def current_lab() -> GuidedLab:
            return labs[state["lab_index"]]

        def current_step() -> LabStep:
            return current_lab().steps[state["step_index"]]

        outer = tk.Frame(self.content, bg=COL_BG)
        outer.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        outer.grid_columnconfigure(0, weight=3)
        outer.grid_columnconfigure(1, weight=2)
        outer.grid_rowconfigure(0, weight=1)

        coach = tk.Frame(outer, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        coach.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        coach.grid_columnconfigure(0, weight=1)

        header = tk.Frame(coach, bg=COL_PANEL)
        header.pack(fill="x", padx=18, pady=(16, 10))

        lab_title = tk.Label(header, text="", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 16, "bold"))
        lab_title.pack(side="left")

        prog = tk.Label(header, text="", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11, "bold"))
        prog.pack(side="right")

        summary_lbl = tk.Label(coach, text="", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11), wraplength=1, justify="left")
        summary_lbl.pack(anchor="w", padx=18, pady=(0, 12))
        # -------- Beginner Definitions Box --------
        glossary_box = tk.Frame(coach, bg=COL_PANEL2, highlightthickness=1, highlightbackground=COL_BORDER)
        glossary_box.pack(fill="x", padx=18, pady=(0, 12))

        tk.Label(
            glossary_box,
            text="What these terms mean",
            fg=COL_TEXT,
            bg=COL_PANEL2,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 6))

        glossary_lbl = tk.Label(
            glossary_box,
            text="",
            fg=COL_MUTED,
            bg=COL_PANEL2,
            font=("Segoe UI", 11),
            wraplength=1,
            justify="left",
        )
        glossary_lbl.pack(anchor="w", padx=14, pady=(0, 12))

        self._bind_simple_wrap(glossary_lbl, pad=66, fraction=0.97)
        self._bind_simple_wrap(summary_lbl, pad=54, fraction=0.97)

        step_panel = tk.Frame(coach, bg=COL_PANEL2, highlightthickness=1, highlightbackground=COL_BORDER)
        step_panel.pack(fill="x", padx=18, pady=(0, 12))
        step_panel.grid_columnconfigure(0, weight=1)

        step_title = tk.Label(step_panel, text="", fg=COL_CYAN, bg=COL_PANEL2, font=("Segoe UI", 14, "bold"), wraplength=1, justify="left")
        step_title.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        self._bind_simple_wrap(step_title, pad=66, fraction=0.97)

        objective_lbl = tk.Label(step_panel, text="", fg=COL_GREEN, bg=COL_PANEL2, font=("Segoe UI", 12, "bold"), wraplength=1, justify="left")
        objective_lbl.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))
        self._bind_simple_wrap(objective_lbl, pad=66, fraction=0.97)

        do_lbl = tk.Label(step_panel, text="", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 12), wraplength=1, justify="left")
        do_lbl.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 10))
        self._bind_simple_wrap(do_lbl, pad=66, fraction=0.97)

        watch_lbl = tk.Label(step_panel, text="", fg=COL_AMBER, bg=COL_PANEL2, font=("Segoe UI", 11, "bold"), wraplength=1, justify="left")
        watch_lbl.grid(row=3, column=0, sticky="w", padx=14, pady=(0, 8))
        self._bind_simple_wrap(watch_lbl, pad=66, fraction=0.97)

        tip_lbl = tk.Label(step_panel, text="", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 11), wraplength=1, justify="left")
        tip_lbl.grid(row=4, column=0, sticky="w", padx=14, pady=(0, 12))
        self._bind_simple_wrap(tip_lbl, pad=66, fraction=0.97)

        step_status = tk.Label(coach, text="", fg=COL_AMBER, bg=COL_PANEL, font=("Segoe UI", 12, "bold"))
        step_status.pack(anchor="w", padx=18, pady=(0, 10))

        nav_row = tk.Frame(coach, bg=COL_PANEL)
        nav_row.pack(fill="x", padx=18, pady=(0, 16))

        back_btn = tk.Button(
            nav_row, text="Back",
            bg=COL_PANEL2, fg=COL_CYAN, relief="flat",
            font=("Segoe UI", 12, "bold"), padx=14, pady=12, cursor="hand2"
        )
        back_btn.pack(side="left")

        next_btn = tk.Button(
            nav_row, text="Next",
            bg=COL_ACCENT, fg="#0b1220", relief="flat",
            font=("Segoe UI", 12, "bold"), padx=14, pady=12, cursor="hand2", state="disabled"
        )
        next_btn.pack(side="right")

        quiz_card = tk.Frame(coach, bg=COL_PANEL2, highlightthickness=1, highlightbackground=COL_BORDER)
        quiz_card.pack(fill="x", padx=18, pady=(0, 14))
        quiz_card.pack_forget()

        quiz_title = tk.Label(quiz_card, text="Quick Check", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 14, "bold"))
        quiz_title.pack(anchor="w", padx=14, pady=(12, 6))

        quiz_q = tk.Label(quiz_card, text="", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 12), wraplength=1, justify="left")
        quiz_q.pack(anchor="w", padx=14, pady=(0, 10))
        self._bind_simple_wrap(quiz_q, pad=66, fraction=0.97)

        quiz_choices = tk.Frame(quiz_card, bg=COL_PANEL2)
        quiz_choices.pack(fill="x", padx=14)

        quiz_feedback = tk.Label(quiz_card, text="", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 11), wraplength=1, justify="left")
        quiz_feedback.pack(anchor="w", padx=14, pady=(10, 8))
        self._bind_simple_wrap(quiz_feedback, pad=66, fraction=0.97)

        quiz_btn_row = tk.Frame(quiz_card, bg=COL_PANEL2)
        quiz_btn_row.pack(fill="x", padx=14, pady=(0, 12))

        submit_btn = tk.Button(
            quiz_btn_row, text="Submit",
            bg=COL_ACCENT, fg="#0b1220", relief="flat",
            font=("Segoe UI", 12, "bold"), padx=14, pady=12, cursor="hand2", state="disabled"
        )
        submit_btn.pack(side="right")

        actions = tk.Frame(outer, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        actions.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        actions.grid_columnconfigure(0, weight=1)

        tk.Label(actions, text="Controls (Easy)", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(16, 8))

        mode_badge = tk.Label(actions, text="", fg=COL_CYAN, bg=COL_PANEL, font=("Segoe UI", 12, "bold"))
        mode_badge.pack(anchor="w", padx=18, pady=(0, 10))

        rec_line = tk.Label(actions, text="", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11))
        rec_line.pack(anchor="w", padx=18, pady=(0, 12))

        big_row = tk.Frame(actions, bg=COL_PANEL)
        big_row.pack(fill="x", padx=18, pady=(0, 10))
        big_row.grid_columnconfigure(0, weight=1)
        big_row.grid_columnconfigure(1, weight=1)

        use_rec_btn = tk.Button(
            big_row,
            text="Use Recommended",
            bg=COL_PANEL2,
            fg=COL_CYAN,
            relief="flat",
            font=("Segoe UI", 12, "bold"),
            padx=14,
            pady=12,
            cursor="hand2",
        )
        use_rec_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        run_btn = tk.Button(
            big_row,
            text="Run Lesson",
            bg=COL_ACCENT,
            fg="#0b1220",
            relief="flat",
            font=("Segoe UI", 12, "bold"),
            padx=14,
            pady=12,
            cursor="hand2",
        )
        run_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        stop_btn = tk.Button(
            actions,
            text="Stop",
            command=self.stop_simulation,
            bg=COL_PANEL2,
            fg=COL_CYAN,
            relief="flat",
            font=("Segoe UI", 12, "bold"),
            padx=14,
            pady=12,
            cursor="hand2",
        )
        stop_btn.pack(fill="x", padx=18, pady=(0, 14))

        advanced_open = tk.BooleanVar(value=False)

        adv_toggle = tk.Checkbutton(
            actions,
            text="Advanced settings (optional)",
            variable=advanced_open,
            fg=COL_CYAN,
            bg=COL_PANEL,
            activebackground=COL_PANEL,
            activeforeground=COL_CYAN,
            selectcolor=COL_PANEL2,
            font=("Segoe UI", 11, "bold"),
        )
        adv_toggle.pack(anchor="w", padx=18, pady=(0, 8))

        advanced_box = tk.Frame(actions, bg=COL_PANEL2, highlightthickness=1, highlightbackground=COL_BORDER)
        advanced_box.pack(fill="x", padx=18, pady=(0, 14))
        advanced_box.pack_forget()

        advanced_box.grid_columnconfigure(0, weight=1)
        advanced_box.grid_columnconfigure(1, weight=0)

        tk.Label(advanced_box, text="Threads", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        threads_var = tk.IntVar(value=int(self.user.default_threads))
        tk.Spinbox(
            advanced_box, from_=1, to=200, textvariable=threads_var, width=8,
            bg=COL_PANEL, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=0, column=1, sticky="e", padx=12, pady=(12, 6))

        tk.Label(advanced_box, text="Duration (sec)", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 12))
        dur_var = tk.IntVar(value=int(self.user.default_duration))
        tk.Spinbox(
            advanced_box, from_=1, to=600, textvariable=dur_var, width=8,
            bg=COL_PANEL, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=1, column=1, sticky="e", padx=12, pady=(0, 12))

        def toggle_advanced(*_):
            if advanced_open.get():
                advanced_box.pack(fill="x", padx=18, pady=(0, 14))
            else:
                advanced_box.pack_forget()

        advanced_open.trace_add("write", toggle_advanced)
        toggle_advanced()

        status_card = tk.Frame(actions, bg=COL_PANEL2, highlightthickness=1, highlightbackground=COL_BORDER)
        status_card.pack(fill="both", expand=True, padx=18, pady=(0, 0))
        status_card.grid_columnconfigure(0, weight=1)

        tk.Label(status_card, text="What’s happening", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(12, 6))

        status_top = tk.Frame(status_card, bg=COL_PANEL2)
        status_top.pack(fill="x", padx=12, pady=(0, 8))

        lbl_run = tk.Label(status_top, text="Status: Idle", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 11, "bold"))
        lbl_run.pack(side="left")

        lbl_time = tk.Label(status_top, text="Time left: —", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 11, "bold"))
        lbl_time.pack(side="right")

        traffic_row = tk.Frame(status_card, bg=COL_PANEL2)
        traffic_row.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(traffic_row, text="Traffic:", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 11, "bold")).pack(side="left")
        lbl_level = tk.Label(traffic_row, text="Low", fg=COL_GREEN, bg=COL_PANEL2, font=("Segoe UI", 12, "bold"))
        lbl_level.pack(side="left", padx=(8, 0))

        lbl_headline = tk.Label(status_card, text="Waiting…", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 12, "bold"))
        lbl_headline.pack(anchor="w", padx=12, pady=(6, 2))

        lbl_explain = tk.Label(status_card, text="", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 11), wraplength=1, justify="left")
        lbl_explain.pack(anchor="w", padx=12, pady=(0, 10))
        self._bind_simple_wrap(lbl_explain, pad=46, fraction=0.92)

        show_details = tk.BooleanVar(value=False)
        show_log = tk.BooleanVar(value=True)

        toggles = tk.Frame(status_card, bg=COL_PANEL2)
        toggles.pack(fill="x", padx=12, pady=(0, 8))

        tk.Checkbutton(
            toggles, text="Show details",
            variable=show_details,
            fg=COL_CYAN, bg=COL_PANEL2,
            activebackground=COL_PANEL2, activeforeground=COL_CYAN,
            selectcolor=COL_PANEL,
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")

        tk.Checkbutton(
            toggles, text="Show log",
            variable=show_log,
            fg=COL_CYAN, bg=COL_PANEL2,
            activebackground=COL_PANEL2, activeforeground=COL_CYAN,
            selectcolor=COL_PANEL,
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=(14, 0))

        details_box = tk.Frame(status_card, bg=COL_PANEL)
        details_box.pack(fill="x", padx=12, pady=(0, 10))
        details_box.pack_forget()

        lbl_rps = tk.Label(details_box, text="RPS: 0", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 11, "bold"))
        lbl_dom = tk.Label(details_box, text="Dominance: 0.00", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 11, "bold"))
        lbl_uips = tk.Label(details_box, text="Unique IPs: 0", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 11, "bold"))
        lbl_top = tk.Label(details_box, text="Top IP req: 0", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 11, "bold"))
        lbl_rps.pack(anchor="w", padx=12, pady=(10, 0))
        lbl_dom.pack(anchor="w", padx=12)
        lbl_uips.pack(anchor="w", padx=12)
        lbl_top.pack(anchor="w", padx=12, pady=(0, 10))

        log_box = tk.Frame(status_card, bg=COL_PANEL)
        log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        log_box.pack_forget()
        log_box.grid_rowconfigure(1, weight=1)
        log_box.grid_columnconfigure(0, weight=1)

        tk.Label(log_box, text="Live Log", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        tk.Label(
            log_box,
            text="Legend: 🔴 Critical  🟡 Warning/Building  🟢 Success  ⚪ Normal",
            fg=COL_MUTED,
            bg=COL_PANEL,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="e", padx=12, pady=(12, 6))

        log_text = tk.Text(
            log_box,
            bg=COL_PANEL2,
            fg=COL_TEXT,
            insertbackground=COL_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COL_BORDER,
            wrap="word",
            height=8,
        )
        log_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log_text.configure(state="disabled")

        self._style_log_widget(log_text)
        self._poll_log_queue(log_text)

        def _toggle_details(*_):
            if show_details.get():
                details_box.pack(fill="x", padx=12, pady=(0, 10))
            else:
                details_box.pack_forget()

        def _toggle_log(*_):
            if show_log.get():
                log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
            else:
                log_box.pack_forget()

        show_details.trace_add("write", _toggle_details)
        show_log.trace_add("write", _toggle_log)
        _toggle_details()
        _toggle_log()

        def reset_step_latch():
            state["step_latched"] = False
            state["step_true_since"] = None

        def hide_quiz():
            state["quiz_open"] = False
            state["quiz_passed"] = False
            state["quiz_answer"] = -1
            state["quiz_correct_idx"] = None
            quiz_feedback.config(text="", fg=COL_MUTED)
            for w in quiz_choices.winfo_children():
                w.destroy()
            submit_btn.config(state="disabled")
            quiz_card.pack_forget()

        def show_quiz():
            lab = current_lab()
            if not lab.quiz:
                return

            state["quiz_open"] = True
            quiz_card.pack(fill="x", padx=18, pady=(0, 14))

            q = lab.quiz
            quiz_q.config(text=q.question)

            already = f"{lab.lab_id}:quiz" in self.user.quizzes_completed
            if already:
                quiz_feedback.config(text=f"You already earned +{q.points} for this quiz.", fg=COL_GREEN)
            else:
                quiz_feedback.config(text="", fg=COL_MUTED)

            pairs = [(c, i == q.correct_index) for i, c in enumerate(q.choices)]
            random.shuffle(pairs)
            correct_idx = next(i for i, (_c, ok) in enumerate(pairs) if ok)
            state["quiz_correct_idx"] = correct_idx
            state["quiz_answer"] = -1

            ans_var = tk.IntVar(value=-1)

            def enable_submit(*_):
                state["quiz_answer"] = int(ans_var.get())
                submit_btn.config(state=("normal" if ans_var.get() >= 0 else "disabled"))

            ans_var.trace_add("write", enable_submit)

            for w in quiz_choices.winfo_children():
                w.destroy()

            for idx, (choice, _ok) in enumerate(pairs):
                rb = tk.Radiobutton(
                    quiz_choices,
                    text=choice,
                    variable=ans_var,
                    value=idx,
                    fg=COL_TEXT,
                    bg=COL_PANEL2,
                    selectcolor=COL_PANEL,
                    activebackground=COL_PANEL2,
                    activeforeground=COL_TEXT,
                    font=("Segoe UI", 12),
                    wraplength=1,
                    justify="left",
                )
                rb.pack(anchor="w", pady=2)
                self._bind_simple_wrap(rb, pad=66, fraction=0.97)  # type: ignore[arg-type]

            def do_submit():
                lab2 = current_lab()
                q2 = lab2.quiz
                if not q2:
                    return
                if state["quiz_answer"] == state["quiz_correct_idx"]:
                    if f"{lab2.lab_id}:quiz" not in self.user.quizzes_completed:
                        self._award_quiz_points_once(lab2.lab_id, q2.points)
                        extra = f" (+{q2.points} points)"
                    else:
                        extra = ""
                    state["quiz_passed"] = True
                    quiz_feedback.config(text=f"✅ Correct! {q2.explain_correct}{extra}", fg=COL_GREEN)

                    next_btn.config(state="normal")
                    next_btn.config(text=("Next Lab" if state["lab_index"] < len(labs) - 1 else "Finish"))
                    submit_btn.config(state="disabled")
                else:
                    quiz_feedback.config(text="❌ Not quite — try again.", fg=COL_AMBER)

            submit_btn.config(command=do_submit)

        def render():
            lab = current_lab()
            step = current_step()

            prog.config(text=f"Lab {state['lab_index'] + 1}/{len(labs)} • Step {state['step_index'] + 1}/{len(lab.steps)}")
            lab_title.config(text=lab.title)
            summary_lbl.config(text=lab.summary)
            glossary_lbl.config(text=wizard_glossary_text(lab))

            step_title.config(text=step.title)
            objective_lbl.config(text=f"✅ Objective: {step.objective}")
            do_lbl.config(text=f"Do this now:\n{step.do_this_now}")
            watch_lbl.config(text=f"Watch: {step.watch}")
            tip_lbl.config(text=f"If stuck: {step.stuck_tip}")

            mode_badge.config(text=f"Mode: {lab.recommended_mode}")

            reset_step_latch()
            hide_quiz()

            next_btn.config(text="Next", state="disabled")
            step_status.config(text="⏳ Do the step. It will lock when true for ~1 second.", fg=COL_AMBER)

            back_btn.config(state=("normal" if (state["step_index"] > 0 or state["lab_index"] > 0) else "disabled"))

            state["recommended_level"] = 0
            t, d = bump_recommended(lab.recommended_mode, state["recommended_level"])
            rec_line.config(text=f"Recommended settings: {t} Threads • {d}s")
            threads_var.set(t)
            dur_var.set(d)

        def apply_recommended(bump: bool):
            lab = current_lab()
            if bump:
                state["recommended_level"] = min(6, state["recommended_level"] + 1)
            t, d = bump_recommended(lab.recommended_mode, state["recommended_level"])
            rec_line.config(text=f"Recommended settings: {t} Threads • {d}s")
            threads_var.set(t)
            dur_var.set(d)

        def run_lesson():
            lab = current_lab()
            self.stop_simulation()

            self.current_family = family
            self.current_mode_kind = lab.recommended_mode

            seconds = int(dur_var.get())
            threads = int(threads_var.get())
            self.controller.duration = seconds
            self._run_end_ts = time.time() + seconds

            self._start_simulation(family, lab.recommended_mode, threads, seconds)
            self._schedule_hard_stop(seconds)
            self._start_timer_thread(seconds)

        use_rec_btn.config(command=lambda: apply_recommended(bump=True))
        run_btn.config(command=run_lesson)

        def go_back():
            if state["step_index"] > 0:
                state["step_index"] -= 1
                render()
            elif state["lab_index"] > 0:
                state["lab_index"] -= 1
                state["step_index"] = 0
                render()

        def finish_lab_and_advance():
            lab = current_lab()

            if lab.lab_id not in self.user.labs_completed:
                self.user.labs_completed.append(lab.lab_id)
                self._save_user()
                self._build_sidebar()

            back_btn.config(state="disabled")
            next_btn.config(state="disabled")
            run_btn.config(state="disabled")
            use_rec_btn.config(state="disabled")
            stop_btn.config(state="disabled")

            self._celebrate("🎉 Lab Achieved!", ms=1800)

            def after_party():
                run_btn.config(state="normal")
                use_rec_btn.config(state="normal")
                stop_btn.config(state="normal")
                back_btn.config(state=("normal" if (state["step_index"] > 0 or state["lab_index"] > 0) else "disabled"))

                if state["lab_index"] < len(labs) - 1:
                    state["lab_index"] += 1
                    state["step_index"] = 0
                    render()
                else:
                    self._celebrate("🏆 All Guided Labs Completed!", ms=1800)
                    step_status.config(text="🏆 All guided labs completed!", fg=COL_GREEN)
                    next_btn.config(state="disabled")
                    run_btn.config(state="disabled")
                    use_rec_btn.config(state="disabled")
                    stop_btn.config(state="disabled")

            self.after(1900, after_party)

        def go_next():
            lab = current_lab()
            last_step = state["step_index"] >= (len(lab.steps) - 1)

            if not last_step:
                state["step_index"] += 1
                render()
                return

            if lab.quiz and not state["quiz_passed"]:
                if not state["quiz_open"]:
                    show_quiz()
                next_btn.config(state="disabled")
                step_status.config(text="✅ Steps complete. Answer the quiz to finish the lab.", fg=COL_GREEN)
                return

            finish_lab_and_advance()

        back_btn.config(command=go_back)
        next_btn.config(command=go_next)

        def poll_step_and_status():
            if self.active_page != f"{family} Guided Lab":
                return

            lab = current_lab()
            step = current_step()

            snap = self._poll_status_snapshot(family, lab.recommended_mode)
            lbl_run.config(text=f"Status: {snap['status']}")
            if snap["status"] == "Running" and snap["remaining"] is not None:
                rem = snap["remaining"]
                lbl_time.config(text=f"Time left: {rem}s", fg=(COL_GREEN if rem > 3 else COL_AMBER))
            else:
                lbl_time.config(text="Time left: —", fg=COL_MUTED)

            lbl_level.config(text=snap["level_text"], fg=snap["level_color"])
            lbl_headline.config(text=snap["headline"])
            lbl_explain.config(text=snap["explain"])

            lbl_rps.config(text=f"RPS: {snap['rps']}")
            lbl_dom.config(text=f"Dominance: {snap['dominance']:.2f}")
            lbl_uips.config(text=f"Unique IPs: {snap['unique_ips']}")
            lbl_top.config(text=f"Top IP req: {snap['top_ip']}")

            if not state["step_latched"]:
                try:
                    raw_done = bool(step.done_when(self._current_lab_state()))
                except Exception:
                    raw_done = False

                if raw_done:
                    if state["step_true_since"] is None:
                        state["step_true_since"] = time.time()
                    else:
                        if (time.time() - state["step_true_since"]) >= 1.0:
                            state["step_latched"] = True
                            step_status.config(text="✅ Step complete (locked). Click Next.", fg=COL_GREEN)
                            next_btn.config(state="normal")
                else:
                    state["step_true_since"] = None
                    step_status.config(text="⏳ Not complete yet. Press Run Lesson, then follow the step.", fg=COL_AMBER)
                    next_btn.config(state="disabled")

            self.after(260, poll_step_and_status)

        render()
        poll_step_and_status()

    # =========================
    # Routing
    # =========================
    def show_attack(self, guided: bool = False):
        if guided:
            self._build_easy_wizard("Attack")
        else:
            self._build_freeplay_page("Attack")

    def show_defense(self, guided: bool = False):
        if guided:
            self._build_easy_wizard("Defense")
        else:
            self._build_freeplay_page("Defense")

    def show_help(self):
        self._set_active_page("Help")
        self.clear_content()
        self._page_header_centered("Help", "Simple definitions + how to use Easy Guided Lab.")

        lbl = tk.Label(
            self.content,
            text=(
                "Beginner-friendly definitions:\n\n"
                "• DoS: One source overwhelms a service with requests.\n"
                "• DDoS: Many sources overwhelm a service at the same time.\n"
                "• Adaptive: Behavior shifts tactics to try to succeed.\n\n"
                "Easy Guided Lab (recommended):\n"
                "• Press “Run Lesson” (uses recommended settings).\n"
                "• Press “Use Recommended” if you want it stronger.\n"
                "• Open Advanced only if you want to experiment.\n"
                "• Steps lock in (no flicker).\n"
                "• Quiz appears only after the final step.\n\n"
                "Optional terms:\n"
                "• RPS: requests per second\n"
                "• Dominance: share of traffic from the top sender\n"
                "• Unique IPs: number of different senders\n\n"
                "Live Log (raw traffic):\n"
                "• 🔴 Critical  🟡 Warning/Building  🟢 Success  ⚪ Normal"
            ),
            fg=COL_TEXT,
            bg=COL_BG,
            font=("Segoe UI", 12),
            wraplength=1,
            justify="left",
        )
        lbl.pack(anchor="w", padx=28, pady=(10, 10))
        self._bind_simple_wrap(lbl, pad=28, fraction=0.92)

    def show_settings(self):
        self._set_active_page("Settings")
        self.clear_content()
        self._page_header_centered("Settings", "Defaults used by Free Play and as a starting point for Easy Guided Lab.")

        card = tk.Frame(self.content, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        card.pack(fill="x", padx=28, pady=(0, 16))

        tk.Label(card, text="Defaults", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(16, 10))

        form = tk.Frame(card, bg=COL_PANEL)
        form.pack(fill="x", padx=18, pady=(0, 12))
        form.grid_columnconfigure(0, weight=1)

        tk.Label(form, text="Default duration (seconds)", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w")
        dur_var = tk.IntVar(value=int(self.user.default_duration))
        tk.Spinbox(
            form, from_=1, to=600, textvariable=dur_var, width=10,
            bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=0, column=1, sticky="e")

        tk.Label(form, text="Default threads", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", pady=(10, 0))
        thr_var = tk.IntVar(value=int(self.user.default_threads))
        tk.Spinbox(
            form, from_=1, to=200, textvariable=thr_var, width=10,
            bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=1, column=1, sticky="e", pady=(10, 0))

        tk.Label(form, text="Quiz points per lab", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 11)).grid(row=2, column=0, sticky="w", pady=(10, 0))
        pts_var = tk.IntVar(value=int(self.user.quiz_points))
        tk.Spinbox(
            form, from_=1, to=100, textvariable=pts_var, width=10,
            bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=2, column=1, sticky="e", pady=(10, 0))

        msg = tk.Label(card, text="", fg=COL_GREEN, bg=COL_PANEL, font=("Segoe UI", 11, "bold"))
        msg.pack(anchor="w", padx=18, pady=(10, 10))

        btns = tk.Frame(card, bg=COL_PANEL)
        btns.pack(fill="x", padx=18, pady=(0, 18))

        def save_settings():
            self.user.default_duration = int(dur_var.get())
            self.user.default_threads = int(thr_var.get())
            self.user.quiz_points = int(pts_var.get())
            self._save_user()
            self._labs_loaded = False
            self._build_sidebar()
            msg.config(text="Saved ✅")

        def reset_progress():
            self.user.points = 0
            self.user.labs_completed = []
            self.user.quizzes_completed = []
            self._save_user()
            self._build_sidebar()
            msg.config(text="Progress reset ✅")

        tk.Button(
            btns, text="Save",
            command=save_settings,
            bg=COL_ACCENT, fg="#0b1220",
            relief="flat", font=("Segoe UI", 12, "bold"),
            padx=14, pady=12, cursor="hand2",
        ).pack(side="left")

        tk.Button(
            btns, text="Reset Progress",
            command=reset_progress,
            bg=COL_PANEL2, fg=COL_CYAN,
            relief="flat", font=("Segoe UI", 12, "bold"),
            padx=14, pady=12, cursor="hand2",
        ).pack(side="left", padx=(12, 0))

    def logout(self):
        try:
            self.stop_simulation()
        except Exception:
            pass
        self.user = UserProfile()
        self._labs_loaded = False
        self._build_sidebar()
        self.after(50, self._prompt_user_dialog)


if __name__ == "__main__":
    app = ArelGuardApp()
    app.mainloop()