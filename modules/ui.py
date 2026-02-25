from __future__ import annotations

import sys
import json
import queue
import threading
import time
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
COL_GOOD = COL_GREEN
COL_AMBER = "#f59e0b"


# =========================
# Non-technical helpers
# =========================
def traffic_level_label(rps: int, limit: Optional[int] = None, impact: bool = False) -> tuple[str, str]:
    """
    Traffic level:
    - If impact is true, always "Overwhelmed".
    - If we have a limit, use percent-of-limit (best).
    - If we DON'T have a limit, use conservative defaults so we don't scream "High" too early.
    """
    if impact:
        return ("Overwhelmed", COL_RED)

    rps = int(rps or 0)

    # Best case: we know the mode's limit/threshold
    if limit and limit > 0:
        ratio = rps / float(limit)

        # Conservative: "High" only when you're truly close
        if ratio < 0.40:
            return ("Low", COL_GREEN)
        if ratio < 0.85:
            return ("Moderate", COL_AMBER)
        return ("High", COL_RED)

    # Fallback (no limit detected):
    # Make this conservative so "High" doesn't show up unless it's *really* high.
    if rps < 1200:
        return ("Low", COL_GREEN)
    if rps < 3000:
        return ("Moderate", COL_AMBER)
    return ("High", COL_RED)


def explain_for_nontechnical(family: str, kind: str, state: dict, limit: Optional[int] = None) -> tuple[str, str]:
    """
    CLEAN version (no duplicates/unreachable code).
    """
    rps = int(state.get("rps", 0) or 0)
    dominance = float(state.get("dominance", 0.0) or 0.0)
    unique_ips = int(state.get("unique_ips", 0) or 0)

    impact = bool(state.get("impact_achieved", False) or state.get("impact achieved", False) or state.get("impact", False))
    confirmed_dos = bool(state.get("confirmed_DoS", False) or state.get("confirmed DoS", False))
    confirmed_ddos = bool(state.get("confirmed_DDoS", False) or state.get("confirmed DDoS", False))

    lvl, _ = traffic_level_label(rps, limit=limit, impact=impact)

    # Attack wording
    if family == "Attack":
        if impact:
            return ("✅ Disruption achieved", "The service is now overwhelmed by traffic.")
        if lvl == "High":
            return ("⚠️ Heavy pressure", "Traffic is close to the disruption threshold. Keep it steady to trigger disruption.")
        if lvl == "Moderate":
            return ("⏳ Building pressure", "Traffic is increasing, but it may not be enough yet.")
        return ("✅ Light traffic", "Traffic is low. Increase threads to apply more pressure.")

    # Defense wording
    if confirmed_dos:
        return ("🚨 Confirmed DoS attack", "Most traffic appears to come from one main source. Defenses would rate-limit or block it.")
    if confirmed_ddos:
        return ("🚨 Confirmed DDoS attack", "Traffic comes from many sources at once. Defenses would filter and mitigate broadly.")

    # Suspicion hints (only when traffic is meaningfully high)
    if lvl in ("Moderate", "High"):
        if unique_ips >= 15 and dominance <= 0.35:
            return ("⚠️ Suspicious: many-source flooding", "Many sources appear active at once. Waiting for confirmation.")
        if dominance >= 0.75 and (unique_ips == 0 or unique_ips <= 3):
            return ("⚠️ Suspicious: one-source flooding", "One main source appears to dominate the traffic. Waiting for confirmation.")

    if lvl == "High":
        return ("⚠️ Unusual spike", "Traffic is very high, but not confirmed as an attack yet.")
    return ("✅ Normal traffic", "Traffic looks typical and doesn’t match common attack patterns right now.")


def _extract_limit_from_mode(mode_obj) -> Optional[int]:
    """
    Tries common attribute names across your modes.
    If your modes use a different attribute name, add it here.
    """
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
    labs_completed: list[str] = None           # ["A1","D1",...]
    quizzes_completed: list[str] = None        # ["A1:quiz","D1:quiz",...]
    points: int = 0

    # saved per-user settings
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
    instruction: str
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
    recommended_mode: str  # "DoS" / "DDoS" / "Adaptive"
    steps: list[LabStep]
    quiz: Optional[LabQuiz] = None


def _get_bool(state: dict, *keys: str) -> bool:
    for k in keys:
        if bool(state.get(k, False)):
            return True
    return False


def build_guided_labs(points_per_quiz: int):
    """
    Awareness-friendly labs; completion uses last_state keys only.
    """
    attack_labs = [
        GuidedLab(
            lab_id="A1",
            title="Attack Lab 1 — Build Pressure (DoS)",
            summary="See what it looks like when one strong source sends a lot of traffic.",
            recommended_mode="DoS",
            steps=[
                LabStep(
                    title="Start the simulation",
                    instruction="Select Mode: DoS, then press Start. Watch traffic rise.",
                    done_when=lambda s: int(s.get("rps", 0) or 0) > 600,
                ),
                LabStep(
                    title="Increase pressure",
                    instruction="Increase Threads if needed until traffic stays high.",
                    done_when=lambda s: int(s.get("rps", 0) or 0) > 1200,
                ),
                LabStep(
                    title="Cause disruption",
                    instruction="Keep traffic high until disruption is achieved.",
                    done_when=lambda s: _get_bool(s, "impact_achieved", "impact achieved", "impact"),
                ),
            ],
            quiz=LabQuiz(
                question="In a DoS attack, where does most traffic come from?",
                choices=["One main source", "Many different sources", "Only the victim"],
                correct_index=0,
                explain_correct="DoS usually means one dominant source overwhelms the target.",
                points=points_per_quiz,
            ),
        ),
        GuidedLab(
            lab_id="A2",
            title="Attack Lab 2 — Spread Out (DDoS)",
            summary="See what it looks like when many sources send traffic together.",
            recommended_mode="DDoS",
            steps=[
                LabStep(
                    title="Start the simulation",
                    instruction="Select Mode: DDoS, then press Start. Watch the number of sources increase.",
                    done_when=lambda s: int(s.get("unique_ips", 0) or 0) >= 10,
                ),
                LabStep(
                    title="Increase source diversity",
                    instruction="Increase Threads until many sources are active.",
                    done_when=lambda s: int(s.get("unique_ips", 0) or 0) >= 25,
                ),
                LabStep(
                    title="Cause disruption",
                    instruction="Keep traffic high until disruption is achieved.",
                    done_when=lambda s: _get_bool(s, "impact_achieved", "impact achieved", "impact"),
                ),
            ],
            quiz=LabQuiz(
                question="What often makes DDoS harder to stop than DoS?",
                choices=["It uses many sources at once", "It uses fewer requests", "It never spikes traffic"],
                correct_index=0,
                explain_correct="Many sources make filtering/blocking more difficult.",
                points=points_per_quiz,
            ),
        ),
    ]

    defense_labs = [
        GuidedLab(
            lab_id="D1",
            title="Defense Lab 1 — Spot DoS",
            summary="Learn how defenders recognize one dominant source and confirm DoS.",
            recommended_mode="DoS",
            steps=[
                LabStep(
                    title="Start monitoring",
                    instruction="Select Mode: DoS, press Start. Watch for one source dominating traffic.",
                    done_when=lambda s: float(s.get("dominance", 0.0) or 0.0) >= 0.70,
                ),
                LabStep(
                    title="Wait for confirmation",
                    instruction="Let the defense confirm DoS (it needs repeated evidence).",
                    done_when=lambda s: _get_bool(s, "confirmed_DoS", "confirmed DoS"),
                ),
            ],
            quiz=LabQuiz(
                question="In this simulator, what does 'dominance' mean?",
                choices=["How much traffic comes from the top sender", "How many ports are open", "How fast the CPU is"],
                correct_index=0,
                explain_correct="Dominance is the share of traffic coming from the most active sender.",
                points=points_per_quiz,
            ),
        ),
        GuidedLab(
            lab_id="D2",
            title="Defense Lab 2 — Spot DDoS",
            summary="Learn how defenders recognize many sources and confirm DDoS.",
            recommended_mode="DDoS",
            steps=[
                LabStep(
                    title="Start monitoring",
                    instruction="Select Mode: DDoS, press Start. Watch the number of sources rise.",
                    done_when=lambda s: int(s.get("unique_ips", 0) or 0) >= 15,
                ),
                LabStep(
                    title="Wait for confirmation",
                    instruction="Let the defense confirm DDoS (it needs repeated evidence).",
                    done_when=lambda s: _get_bool(s, "confirmed_DDoS", "confirmed DDoS"),
                ),
            ],
            quiz=LabQuiz(
                question="What is a common warning sign of DDoS?",
                choices=["Many unique sources at once", "One IP dominates everything", "Traffic is always low"],
                correct_index=0,
                explain_correct="DDoS typically involves many sources participating simultaneously.",
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

        # Logo
        def resource_path(relative: str) -> Path:
            # PyInstaller onefile temp folder
            if hasattr(sys, "_MEIPASS"):
                return Path(sys._MEIPASS) / relative

            # Dev: modules/ui.py -> project root
            return Path(__file__).resolve().parent.parent / relative


        logo_path = resource_path("assets/images/ArelGuardLogo.png")

        self.logo_image = None
        if logo_path.exists():
            img = Image.open(logo_path)
            img = img.resize((140, 140), Image.LANCZOS)
            self.logo_image = ImageTk.PhotoImage(img)
        
        self.title("ArelGuard")
        self.geometry("1200x750")
        self.minsize(1050, 650)
        self.configure(bg=COL_BG)

        self.active_page = "Overview"

        # Controller
        self.controller = SimulationController(duration=15)
        self._stop_after_id = None  # UI hard-stop timer id

        # Countdown state
        self._run_end_ts: Optional[float] = None

        # Learned limits (only used when modes don't expose a limit)
        self._learned_limit: dict[tuple[str, str], int] = {}   # (family, kind) -> limit
        self._observed_peak: dict[tuple[str, str], int] = {}   # (family, kind) -> peak

        # Mode refs
        self.current_family: str | None = None
        self.current_mode_kind: str | None = None
        self.current_modes: dict[str, object] = {}

        # Labs
        self._labs_loaded = False
        self._lab_index = 0
        self._step_index = 0
        self._quiz_done = False

        # User
        self.user = UserProfile()

        # stdout capture
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._orig_stdout = sys.stdout
        sys.stdout = QueueWriter(self._log_q)

        # --- Dynamic wrap registry (NEW) ---
        self._wrap_registry: list[tuple[tk.Label, int, float]] = []
        self._sidebar_target_w = 240

        self._build_layout()
        self._setup_ttk_style()

        # Global resize handler (NEW)
        self.bind("<Configure>", self._on_window_resize)

        # Prompt user on startup
        self.after(50, self._prompt_user_dialog)
        self.show_overview()

    # ---------- Dynamic UI sizing (NEW) ----------
    def _register_wrap(self, label: tk.Label, pad: int = 28, fraction: float = 0.92):
        """Register a label whose wraplength should follow window width."""
        self._wrap_registry.append((label, pad, fraction))
        self.after(1, self._on_window_resize)

    def _clear_wrap_registry(self):
        self._wrap_registry.clear()

    def _on_window_resize(self, event=None):
        # dynamic sidebar width (clamped)
        total_w = max(800, self.winfo_width())
        target = int(total_w * 0.20)
        target = max(210, min(300, target))
        if self._sidebar_target_w != target:
            self._sidebar_target_w = target
            try:
                self.sidebar.configure(width=target)
            except Exception:
                pass

        # update wraplengths
        try:
            content_w = max(300, self.content.winfo_width())
        except Exception:
            return

        for lbl, pad, frac in list(self._wrap_registry):
            try:
                wl = int((content_w - pad * 2) * frac)
                lbl.configure(wraplength=max(260, wl))
            except Exception:
                pass

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
        role_box = ttk.Combobox(form, textvariable=role_var, values=["Learner", "Instructor"], state="readonly")
        role_box.grid(row=3, column=0, sticky="ew", pady=(4, 0))

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

    # ---------- Tk cleanup ----------
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
    # Layout  (UPDATED: ROOT uses grid so everything resizes)
    # =========================
    def _build_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0)  # sidebar
        self.grid_columnconfigure(1, weight=1)  # content

        self.sidebar = tk.Frame(self, bg=COL_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="ns")

        self.content = tk.Frame(self, bg=COL_BG)
        self.content.grid(row=0, column=1, sticky="nsew")

        self.sidebar.configure(width=self._sidebar_target_w)
        self.sidebar.grid_propagate(False)

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

        # User card
        user_card = tk.Frame(self.sidebar, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        user_card.pack(fill="x", padx=12, pady=(12, 8))

        tk.Label(user_card, text="User", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(user_card, text=self.user.username, fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=12, pady=(2, 0))
        tk.Label(user_card, text=self.user.role, fg=COL_CYAN, bg=COL_PANEL, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(0, 0))
        tk.Label(user_card, text=f"Points: {self.user.points}", fg=COL_GREEN, bg=COL_PANEL, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(6, 0))

        # show completed labs in sidebar too (easy/non-technical)
        tk.Label(user_card, text="Labs:", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        done = ", ".join(self.user.labs_completed) if self.user.labs_completed else "None yet"
        tk.Label(user_card, text=done, fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 9), wraplength=180, justify="left").pack(anchor="w", padx=12, pady=(2, 8))

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
            tk.Label(
                self.sidebar,
                text=label,
                fg=COL_SECTION,
                bg=COL_SIDEBAR,
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", padx=16, pady=(14, 6))

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

        section("GUIDED")
        nav_button("Attack (Guided)", lambda: self.show_attack(guided=True))
        nav_button("Defense (Guided)", lambda: self.show_defense(guided=True))

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

    def _set_active_page(self, page: str):
        self.active_page = page
        self._build_sidebar()

    # UPDATED: keep your function name, but make it truly dynamic (no unbinds)
    def _bind_simple_wrap(self, label: tk.Label, pad: int = 28, fraction: float = 0.90):
        self._register_wrap(label, pad=pad, fraction=fraction)

    def _page_header_centered(self, title: str, subtitle: str | None = None):
        header = tk.Frame(self.content, bg=COL_BG)
        header.pack(fill="x", padx=28, pady=(22, 14))

        # Brand title: Arel (red) + Guard (blue) when the title is exactly "ArelGuard"
        if title.strip() == "ArelGuard":
            brand = tk.Frame(header, bg=COL_BG)
            brand.pack(anchor="center")

            arel = tk.Label(
                brand,
                text="Arel",
                fg=COL_ATTACK_PANEL,
                bg=COL_BG,
                font=("Segoe UI", 26, "bold"),
                padx=0,
                pady=0,
                borderwidth=0,
                highlightthickness=0
            )
            arel.pack(side="left")

            guard = tk.Label(
                brand,
                text="Guard",
            fg=COL_DEFENSE_PANEL,
            bg=COL_BG,
            font=("Segoe UI", 26, "bold"),
            padx=0,
            pady=0,
            borderwidth=0,
            highlightthickness=0
            )
            guard.pack(side="left")
        else:
            tk.Label(header, text=title, fg=COL_TEXT, bg=COL_BG,
                font=("Segoe UI", 26, "bold")).pack(anchor="center")
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
        """
        HARD stop regardless of what controller/modes do.
        Ensures traffic stops after duration ends.
        """
        self._cancel_hard_stop()

        def do_stop():
            self.stop_simulation()
            self._stop_after_id = None

        self._stop_after_id = self.after(max(1, int(seconds)) * 1000, do_stop)

    def _start_timer_thread(self, seconds: int):
        # Optional controller-side timer (UI hard-stop is the real guarantee)
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
        """
        If a mode doesn't expose a fixed limit, learn one from observed peaks
        so Low/Moderate/High matches YOUR simulator scale.
        """
        key = (family, kind)
        rps = int(rps or 0)

        peak = max(self._observed_peak.get(key, 0), rps)
        self._observed_peak[key] = peak

        if peak >= 500:
            learned = int(max(1200, peak * 1.25))
            prev = self._learned_limit.get(key)
            self._learned_limit[key] = learned if prev is None else max(prev, learned)

        return self._learned_limit.get(key)

    # =========================
    # Guided lab helpers
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

    def _build_guided_lab_panel(self, parent: tk.Frame, family: str, mode_kind_var: tk.StringVar):
        labs = self._lab_list_for_family(family)

        panel = tk.Frame(parent, bg=COL_PANEL2, highlightthickness=1, highlightbackground=COL_BORDER)
        panel.pack(fill="x", padx=18, pady=(10, 10))

        header = tk.Frame(panel, bg=COL_PANEL2)
        header.pack(fill="x", padx=12, pady=(10, 6))

        tk.Label(header, text="Guided Lab", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 12, "bold")).pack(side="left")
        prog_lbl = tk.Label(header, text="", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        prog_lbl.pack(side="right")

        lab_title_lbl = tk.Label(panel, text="", fg=COL_CYAN, bg=COL_PANEL2, font=("Segoe UI", 11, "bold"), wraplength=1, justify="left")
        lab_title_lbl.pack(anchor="w", padx=12, pady=(6, 2))
        self._bind_simple_wrap(lab_title_lbl, pad=46, fraction=0.92)

        lab_summary_lbl = tk.Label(panel, text="", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 10), wraplength=1, justify="left")
        lab_summary_lbl.pack(anchor="w", padx=12, pady=(0, 6))
        self._bind_simple_wrap(lab_summary_lbl, pad=46, fraction=0.92)

        lab_done_badge = tk.Label(panel, text="", fg=COL_AMBER, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        lab_done_badge.pack(anchor="w", padx=12, pady=(0, 10))

        step_title_lbl = tk.Label(panel, text="", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 11, "bold"), wraplength=1, justify="left")
        step_title_lbl.pack(anchor="w", padx=12)
        self._bind_simple_wrap(step_title_lbl, pad=46, fraction=0.92)

        step_instr_lbl = tk.Label(panel, text="", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10), wraplength=1, justify="left")
        step_instr_lbl.pack(anchor="w", padx=12, pady=(2, 0))
        self._bind_simple_wrap(step_instr_lbl, pad=46, fraction=0.92)

        status_lbl = tk.Label(panel, text="", fg=COL_AMBER, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        status_lbl.pack(anchor="w", padx=12, pady=(8, 8))

        btn_row = tk.Frame(panel, bg=COL_PANEL2)
        btn_row.pack(fill="x", padx=12, pady=(0, 12))

        next_btn = tk.Button(
            btn_row,
            text="Next",
            bg=COL_ACCENT,
            fg="#0b1220",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=8,
            cursor="hand2",
            state="disabled",
        )
        next_btn.pack(side="right")

        points_lbl = tk.Label(panel, text="", fg=COL_GREEN, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        points_lbl.pack(anchor="w", padx=12, pady=(0, 10))

        def load_lab(idx: int):
            idx = max(0, min(idx, len(labs) - 1))
            self._lab_index = idx
            self._step_index = 0
            self._quiz_done = False

            lab = labs[self._lab_index]
            mode_kind_var.set(lab.recommended_mode)

            prog_lbl.config(text=f"{self._lab_index + 1}/{len(labs)}")
            lab_title_lbl.config(text=lab.title)
            lab_summary_lbl.config(text=lab.summary)

            completed = (lab.lab_id in self.user.labs_completed)
            lab_done_badge.config(text=("Lab Completed ✅" if completed else "Not completed yet"),
                                  fg=(COL_GREEN if completed else COL_AMBER))

            step = lab.steps[self._step_index]
            step_title_lbl.config(text=f"Step {self._step_index + 1}: {step.title}")
            step_instr_lbl.config(text=step.instruction)

            status_lbl.config(text="Waiting for completion…", fg=COL_AMBER)
            next_btn.config(state="disabled")

            if lab.quiz:
                earned = (f"{lab.lab_id}:quiz" in self.user.quizzes_completed)
                points_lbl.config(
                    text=(f"Quiz points: earned (+{lab.quiz.points}) ✅" if earned else f"Quiz points available: +{lab.quiz.points}"),
                    fg=COL_GREEN
                )
            else:
                points_lbl.config(text="", fg=COL_GREEN)

        def show_quiz_if_needed() -> bool:
            lab = labs[self._lab_index]
            if not lab.quiz or self._quiz_done:
                return True

            quiz_key = f"{lab.lab_id}:quiz"
            already_earned = quiz_key in self.user.quizzes_completed

            quiz = tk.Toplevel(self)
            quiz.title("Quick Check")
            quiz.configure(bg=COL_BG)
            quiz.geometry("580x360")
            quiz.resizable(False, False)
            quiz.grab_set()

            tk.Label(quiz, text="Quick Check", fg=COL_TEXT, bg=COL_BG, font=("Segoe UI", 16, "bold")).pack(pady=(16, 6))
            tk.Label(
                quiz,
                text=lab.quiz.question,
                fg=COL_TEXT,
                bg=COL_BG,
                font=("Segoe UI", 11),
                wraplength=540,
                justify="left",
            ).pack(padx=18, pady=(0, 10))

            if already_earned:
                tk.Label(
                    quiz,
                    text=f"You already earned these points (+{lab.quiz.points}) for this quiz.",
                    fg=COL_GREEN,
                    bg=COL_BG,
                    font=("Segoe UI", 10, "bold"),
                ).pack(padx=18, pady=(0, 10))

            ans = tk.IntVar(value=-1)
            for i, c in enumerate(lab.quiz.choices):
                tk.Radiobutton(
                    quiz,
                    text=c,
                    variable=ans,
                    value=i,
                    fg=COL_TEXT,
                    bg=COL_BG,
                    selectcolor=COL_PANEL2,
                    activebackground=COL_BG,
                    activeforeground=COL_TEXT,
                    font=("Segoe UI", 11),
                    wraplength=540,
                    justify="left",
                ).pack(anchor="w", padx=24, pady=2)

            feedback = tk.Label(quiz, text="", fg=COL_MUTED, bg=COL_BG, font=("Segoe UI", 10), wraplength=540, justify="left")
            feedback.pack(padx=18, pady=(10, 6))

            def submit():
                if ans.get() == lab.quiz.correct_index:
                    gained_text = ""
                    if not already_earned:
                        self._award_quiz_points_once(lab.lab_id, lab.quiz.points)
                        gained_text = f" (+{lab.quiz.points} points)"
                    feedback.config(text=f"✅ Correct! {lab.quiz.explain_correct}{gained_text}", fg=COL_GREEN)
                    self._quiz_done = True
                    quiz.after(700, quiz.destroy)
                else:
                    feedback.config(text="❌ Not quite — try again.", fg=COL_AMBER)

            tk.Button(
                quiz,
                text="Submit",
                command=submit,
                bg=COL_ACCENT,
                fg="#0b1220",
                relief="flat",
                font=("Segoe UI", 11, "bold"),
                padx=12,
                pady=8,
                cursor="hand2",
            ).pack(pady=(6, 16))

            return False

        def mark_lab_completed(lab_id: str):
            if lab_id not in self.user.labs_completed:
                self.user.labs_completed.append(lab_id)
                self._save_user()
                self._build_sidebar()
            lab_done_badge.config(text="Lab Completed ✅", fg=COL_GREEN)

        def advance_step_or_lab():
            lab = labs[self._lab_index]
            last_step = (self._step_index >= len(lab.steps) - 1)

            if last_step:
                if not show_quiz_if_needed():
                    return

                mark_lab_completed(lab.lab_id)

                if self._lab_index < len(labs) - 1:
                    load_lab(self._lab_index + 1)
                else:
                    status_lbl.config(text="🎉 All guided labs completed!", fg=COL_GREEN)
                    next_btn.config(state="disabled")
                return

            self._step_index += 1
            step = lab.steps[self._step_index]
            step_title_lbl.config(text=f"Step {self._step_index + 1}: {step.title}")
            step_instr_lbl.config(text=step.instruction)
            status_lbl.config(text="Waiting for completion…", fg=COL_AMBER)
            next_btn.config(state="disabled")

        next_btn.config(command=advance_step_or_lab)

        def poll_lab_progress():
            if self.active_page != f"{family} (Guided)":
                return

            step = labs[self._lab_index].steps[self._step_index]
            state = self._current_lab_state()

            try:
                done = bool(step.done_when(state))
            except Exception:
                done = False

            if done:
                status_lbl.config(text="✅ Step complete! Click Next.", fg=COL_GREEN)
                next_btn.config(state="normal")
            else:
                status_lbl.config(
                    text=("⏳ Keep increasing pressure…" if family == "Attack" else "⏳ Keep observing… confirmation may take a moment."),
                    fg=COL_AMBER,
                )
                next_btn.config(state="disabled")

            self.after(350, poll_lab_progress)

        load_lab(self._lab_index)
        poll_lab_progress()

    # =========================
    # Polling + live log
    # =========================
    def _poll_log_queue(self, text_widget: tk.Text):
        try:
            while True:
                line = self._log_q.get_nowait()
                text_widget.configure(state="normal")
                text_widget.insert("end", line)
                text_widget.see("end")
                text_widget.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(120, lambda: self._poll_log_queue(text_widget))

    def _poll_metrics(
        self,
        family: str,
        mode_kind_var: tk.StringVar,
        lbl_run: tk.Label,
        lbl_time: tk.Label,
        lbl_headline: tk.Label,
        lbl_explain: tk.Label,
        lbl_level: tk.Label,
        lbl_rps: tk.Label,
        lbl_dom: tk.Label,
        lbl_uips: tk.Label,
        lbl_top: tk.Label,
    ):
        if self.active_page not in (family, f"{family} (Guided)"):
            return

        kind = mode_kind_var.get()

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

        # if no fixed limit exists, learn one (so labels match your simulator scale)
        if limit is None:
            limit = self._learn_limit(family, kind, rps)

        lbl_run.configure(text=f"Status: {status}")

        # Countdown label
        if status == "Running" and self._run_end_ts is not None:
            remaining = int(max(0, round(self._run_end_ts - time.time())))
            lbl_time.configure(text=f"Time left: {remaining}s", fg=(COL_GREEN if remaining > 3 else COL_AMBER))
        else:
            lbl_time.configure(text="Time left: —", fg=COL_MUTED)

        lvl_text, lvl_color = traffic_level_label(rps, limit=limit, impact=flags.get("impact_achieved", False))
        lbl_level.configure(text=lvl_text, fg=lvl_color)

        state_for_words = {"rps": rps, "dominance": dom, "unique_ips": uips, "top_ip": top, **flags}
        headline, explanation = explain_for_nontechnical(family, kind, state_for_words, limit=limit)
        lbl_headline.configure(text=headline)
        lbl_explain.configure(text=explanation)

        lbl_rps.configure(text=f"RPS: {rps}")
        lbl_dom.configure(text=f"Dominance: {dom:.2f}")
        lbl_uips.configure(text=f"Unique IPs: {uips}")
        lbl_top.configure(text=f"Top IP req: {top}")

        self.after(
            250,
            lambda: self._poll_metrics(
                family,
                mode_kind_var,
                lbl_run,
                lbl_time,
                lbl_headline,
                lbl_explain,
                lbl_level,
                lbl_rps,
                lbl_dom,
                lbl_uips,
                lbl_top,
            ),
        )

    # =========================
    # Pages
    # =========================
    def show_overview(self):
        self._set_active_page("Overview")
        self.clear_content()

        self._page_header_centered("ArelGuard", "Learn DoS/DDoS through guided labs and interactive simulations.")

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
            tk.Label(c, text=title, fg=COL_TEXT, bg=panel, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=14, pady=(14, 6))
            lbl = tk.Label(c, text=text, fg=COL_MUTED, bg=panel, font=("Segoe UI", 10), wraplength=1, justify="left")
            lbl.pack(anchor="w", padx=14, pady=(0, 12))
            self._bind_simple_wrap(lbl, pad=28, fraction=0.95)

            btns = tk.Frame(c, bg=panel)
            btns.pack(anchor="w", padx=14, pady=(0, 14))
            tk.Button(
                btns, text=primary_text, command=primary_cmd,
                bg=COL_ACCENT, fg="#0b1220",
                relief="flat", font=("Segoe UI", 10, "bold"),
                padx=12, pady=8, cursor="hand2"
            ).pack(side="left", padx=(0, 10))
            tk.Button(
                btns, text=secondary_text, command=secondary_cmd,
                bg=COL_PANEL, fg=COL_CYAN,
                relief="flat", font=("Segoe UI", 10, "bold"),
                padx=12, pady=8, cursor="hand2"
            ).pack(side="left")
            return lbl

        a_lbl = card(
            left,
            "Attack",
            "See how attackers try to overwhelm services with traffic (DoS/DDoS).",
            COL_ATTACK_PANEL,
            COL_ATTACK_BORDER,
            "Guided",
            lambda: self.show_attack(guided=True),
            "Free Play",
            lambda: self.show_attack(guided=False),
        )

        d_lbl = card(
            left,
            "Defense",
            "See how defenders detect suspicious traffic and confirm attacks over time.",
            COL_DEFENSE_PANEL,
            COL_DEFENSE_BORDER,
            "Guided",
            lambda: self.show_defense(guided=True),
            "Free Play",
            lambda: self.show_defense(guided=False),
        )

        info = tk.Frame(right, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        info.pack(fill="both", expand=True)

        tk.Label(info, text="Your Progress", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(16, 10))
        tk.Label(info, text=f"User: {self.user.username}", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).pack(anchor="w", padx=18)
        tk.Label(info, text=f"Points: {self.user.points}", fg=COL_GREEN, bg=COL_PANEL, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18, pady=(6, 10))

        tk.Label(info, text="Labs completed:", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).pack(anchor="w", padx=18)
        labs_done = ", ".join(self.user.labs_completed) if self.user.labs_completed else "None yet"
        labs_lbl = tk.Label(info, text=labs_done, fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 10), wraplength=1, justify="left")
        labs_lbl.pack(anchor="w", padx=18, pady=(4, 12))
        self._bind_simple_wrap(labs_lbl, pad=28, fraction=0.92)

        tk.Label(info, text="How to earn points:", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).pack(anchor="w", padx=18)
        earn_lbl = tk.Label(
            info,
            text="• Complete guided labs and answer the quick quiz correctly.",
            fg=COL_TEXT, bg=COL_PANEL,
            font=("Segoe UI", 10),
            wraplength=1, justify="left"
        )
        earn_lbl.pack(anchor="w", padx=18, pady=(4, 0))
        self._bind_simple_wrap(earn_lbl, pad=28, fraction=0.92)

        self._bind_simple_wrap(a_lbl, pad=28, fraction=0.95)
        self._bind_simple_wrap(d_lbl, pad=28, fraction=0.95)

    def _build_mode_page(self, family: str, guided: bool):
        self._set_active_page(f"{family} (Guided)" if guided else family)
        self.clear_content()

        title = f"{family} — Guided Labs" if guided else f"{family} — Free Play"
        subtitle = "Follow the steps and earn points from the quick quiz. Technical details are optional."

        self._page_header_centered(title, subtitle)

        outer = tk.Frame(self.content, bg=COL_BG)
        outer.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        outer.grid_columnconfigure(0, weight=2)  # UPDATED: nicer proportional split
        outer.grid_columnconfigure(1, weight=3)  # UPDATED
        outer.grid_rowconfigure(0, weight=1)

        # LEFT: Controls
        controls = tk.Frame(outer, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        controls.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        controls.grid_columnconfigure(0, weight=1)

        tk.Label(controls, text="Controls", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(16, 8))

        mode_kind_var = tk.StringVar(value="DoS")
        mode_row = tk.Frame(controls, bg=COL_PANEL)
        mode_row.pack(fill="x", padx=18, pady=(4, 8))
        tk.Label(mode_row, text="Mode", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).pack(side="left")
        ttk.Combobox(mode_row, textvariable=mode_kind_var, values=["DoS", "DDoS", "Adaptive"], state="readonly", width=12).pack(side="right")

        if guided:
            self._build_guided_lab_panel(controls, family, mode_kind_var)

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

            # start countdown
            self._run_end_ts = time.time() + seconds

            if family == "Attack":
                if mode_kind_var.get() == "DoS":
                    m = attackDoSMode()
                    self.current_modes["single"] = m
                    self.controller.run(m, start_kwargs={"num_threads": threads, "duration": seconds})
                elif mode_kind_var.get() == "DDoS":
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
                if mode_kind_var.get() == "DoS":
                    m = DefenseDosMode()
                    self.current_modes["single"] = m
                    self.controller.run(m, start_kwargs={"num_threads": threads, "duration": seconds})
                elif mode_kind_var.get() == "DDoS":
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

            # HARD stop ✅ + optional controller timer
            self._schedule_hard_stop(seconds)
            self._start_timer_thread(seconds)

        def stop_clicked():
            self.stop_simulation()

        tk.Button(
            btns, text="Start", command=start_clicked,
            bg=COL_ACCENT, fg="#0b1220",
            relief="flat", font=("Segoe UI", 11, "bold"),
            padx=14, pady=10, cursor="hand2",
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            btns, text="Stop", command=stop_clicked,
            bg=COL_PANEL2, fg=COL_CYAN,
            relief="flat", font=("Segoe UI", 11, "bold"),
            padx=14, pady=10, cursor="hand2",
        ).pack(side="left")

        hint = tk.Label(
            controls,
            text=("Guided: Follow steps → quick quiz → earn points." if guided else "Free play: Experiment with threads/duration."),
            fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10), wraplength=1, justify="left",
        )
        hint.pack(anchor="w", padx=18, pady=(10, 14))
        self._bind_simple_wrap(hint, pad=46, fraction=0.92)

        # RIGHT: Status + logs
        right = tk.Frame(outer, bg=COL_BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        metrics = tk.Frame(right, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        metrics.grid(row=0, column=0, sticky="ew")
        metrics.grid_columnconfigure(0, weight=1)

        tk.Label(metrics, text="Live Status", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 6))

        # status + countdown row
        meta_row = tk.Frame(metrics, bg=COL_PANEL)
        meta_row.pack(fill="x", padx=18, pady=(0, 8))

        lbl_run = tk.Label(meta_row, text="Status: Idle", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10, "bold"))
        lbl_run.pack(side="left")

        lbl_time = tk.Label(meta_row, text="Time left: —", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10, "bold"))
        lbl_time.pack(side="right")

        # Plain-language status box (always visible)
        plain_box = tk.Frame(metrics, bg=COL_PANEL2, highlightthickness=1, highlightbackground=COL_BORDER)
        plain_box.pack(fill="x", padx=18, pady=(0, 12))

        lbl_headline = tk.Label(plain_box, text="Waiting…", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 12, "bold"))
        lbl_headline.pack(anchor="w", padx=12, pady=(10, 4))

        lbl_explain = tk.Label(plain_box, text="", fg=COL_MUTED, bg=COL_PANEL2, font=("Segoe UI", 10), wraplength=1, justify="left")
        lbl_explain.pack(anchor="w", padx=12, pady=(0, 10))
        self._bind_simple_wrap(lbl_explain, pad=46, fraction=0.92)

        # Traffic level row
        traffic_row = tk.Frame(metrics, bg=COL_PANEL)
        traffic_row.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(traffic_row, text="Traffic level:", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10, "bold")).pack(side="left")
        lbl_level = tk.Label(traffic_row, text="Low", fg=COL_GREEN, bg=COL_PANEL, font=("Segoe UI", 11, "bold"))
        lbl_level.pack(side="left", padx=(8, 0))

        # Toggle technical details (hidden by default)
        show_tech = tk.BooleanVar(value=False)

        toggle_row = tk.Frame(metrics, bg=COL_PANEL)
        toggle_row.pack(fill="x", padx=18, pady=(0, 10))

        tech_details = tk.Frame(metrics, bg=COL_PANEL2)
        tech_details.pack_forget()

        def _toggle_tech():
            if show_tech.get():
                tech_details.pack(fill="x", padx=18, pady=(0, 14))
            else:
                tech_details.pack_forget()

        tk.Checkbutton(
            toggle_row,
            text="Show technical details",
            variable=show_tech,
            command=_toggle_tech,
            fg=COL_CYAN,
            bg=COL_PANEL,
            activebackground=COL_PANEL,
            activeforeground=COL_CYAN,
            selectcolor=COL_PANEL2,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        lbl_rps = tk.Label(tech_details, text="RPS: 0", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        lbl_dom = tk.Label(tech_details, text="Dominance: 0.00", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        lbl_uips = tk.Label(tech_details, text="Unique IPs: 0", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))
        lbl_top = tk.Label(tech_details, text="Top IP req: 0", fg=COL_TEXT, bg=COL_PANEL2, font=("Segoe UI", 10, "bold"))

        lbl_rps.pack(anchor="w", padx=12, pady=(10, 0))
        lbl_dom.pack(anchor="w", padx=12)
        lbl_uips.pack(anchor="w", padx=12)
        lbl_top.pack(anchor="w", padx=12, pady=(0, 10))

        logs = tk.Frame(right, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        logs.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        logs.grid_rowconfigure(1, weight=1)
        logs.grid_columnconfigure(0, weight=1)

        tk.Label(logs, text="Live Log", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))

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

        self._poll_log_queue(text)
        self._poll_metrics(
            family,
            mode_kind_var,
            lbl_run,
            lbl_time,
            lbl_headline,
            lbl_explain,
            lbl_level,
            lbl_rps,
            lbl_dom,
            lbl_uips,
            lbl_top,
        )

    def show_attack(self, guided: bool = False):
        if guided:
            self._lab_index = 0
            self._step_index = 0
            self._quiz_done = False
        self._build_mode_page("Attack", guided)

    def show_defense(self, guided: bool = False):
        if guided:
            self._lab_index = 0
            self._step_index = 0
            self._quiz_done = False
        self._build_mode_page("Defense", guided)

    def show_help(self):
        self._set_active_page("Help")
        self.clear_content()
        self._page_header_centered("Help", "Simple definitions and how to read the simulator.")

        lbl = tk.Label(
            self.content,
            text=(
                "Beginner-friendly definitions:\n\n"
                "• DoS: One source overwhelms a service with requests.\n"
                "• DDoS: Many sources overwhelm a service at the same time.\n"
                "• Traffic level: Low / Moderate / High (how busy the service is).\n\n"
                "Optional technical terms:\n"
                "• RPS: Requests per second (traffic speed)\n"
                "• Dominance: How much traffic comes from the top sender\n"
                "• Unique IPs: How many different senders are active\n\n"
                "Points:\n"
                "• Earn points by answering the quick quiz correctly.\n"
                "• Each quiz awards points only once per user."
            ),
            fg=COL_TEXT,
            bg=COL_BG,
            font=("Segoe UI", 11),
            wraplength=1,
            justify="left",
        )
        lbl.pack(anchor="w", padx=28, pady=(10, 10))
        self._bind_simple_wrap(lbl, pad=28, fraction=0.92)

    # =========================
    # Settings page
    # =========================
    def show_settings(self):
        self._set_active_page("Settings")
        self.clear_content()
        self._page_header_centered("Settings", "Customize defaults for your simulations and quizzes.")

        card = tk.Frame(self.content, bg=COL_PANEL, highlightthickness=1, highlightbackground=COL_BORDER)
        card.pack(fill="x", padx=28, pady=(0, 16))

        tk.Label(card, text="Simulation Defaults", fg=COL_TEXT, bg=COL_PANEL, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(16, 10))

        form = tk.Frame(card, bg=COL_PANEL)
        form.pack(fill="x", padx=18, pady=(0, 12))
        form.grid_columnconfigure(0, weight=1)
        form.grid_columnconfigure(1, weight=0)

        tk.Label(form, text="Default duration (seconds)", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w")
        dur_var = tk.IntVar(value=int(self.user.default_duration))
        tk.Spinbox(
            form, from_=1, to=600, textvariable=dur_var, width=8,
            bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=0, column=1, sticky="e")

        tk.Label(form, text="Default threads", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(8, 0))
        thr_var = tk.IntVar(value=int(self.user.default_threads))
        tk.Spinbox(
            form, from_=1, to=200, textvariable=thr_var, width=8,
            bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=1, column=1, sticky="e", pady=(8, 0))

        tk.Label(form, text="Quiz points per lab", fg=COL_MUTED, bg=COL_PANEL, font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=(8, 0))
        pts_var = tk.IntVar(value=int(self.user.quiz_points))
        tk.Spinbox(
            form, from_=1, to=100, textvariable=pts_var, width=8,
            bg=COL_PANEL2, fg=COL_TEXT, insertbackground=COL_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COL_BORDER,
        ).grid(row=2, column=1, sticky="e", pady=(8, 0))

        msg = tk.Label(card, text="", fg=COL_GREEN, bg=COL_PANEL, font=("Segoe UI", 10, "bold"))
        msg.pack(anchor="w", padx=18, pady=(0, 10))

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
            relief="flat", font=("Segoe UI", 11, "bold"),
            padx=14, pady=10, cursor="hand2",
        ).pack(side="left")

        tk.Button(
            btns, text="Reset Progress",
            command=reset_progress,
            bg=COL_PANEL2, fg=COL_CYAN,
            relief="flat", font=("Segoe UI", 11, "bold"),
            padx=14, pady=10, cursor="hand2",
        ).pack(side="left", padx=(10, 0))

    # =========================
    # Logout -> back to login prompt
    # =========================
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