from pathlib import Path
import sys

# If you keep your Tkinter UI in modules/ui.py and it defines ArelGuardApp
from modules.ui import ArelGuardApp



def run():
    app = ArelGuardApp()
    app.mainloop()


if __name__ == "__main__":
    # Ensure project root is on sys.path (helps when running from elsewhere)
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    run()