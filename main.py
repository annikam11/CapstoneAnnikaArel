from modules.ui import start_ui
from modules.defense_mode import DefenseDosMode, DefenseDDoS_Mode, DefenseAdaptive_Mode

def main():
    start_ui()
    DefenseDosMode().start(num_threads=10, duration=8)
    DefenseAdaptive_Mode()
    DefenseDDoS_Mode()


if __name__ == "__main__":
    main()
