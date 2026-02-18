# main.py
from modules.controller import SimulationController
from modules.attack_mode import attackDoSMode, attackDDoSMode, attackAdaptiveMode
from modules.ui import MainWindow, ModeRefs

def run():
    controller = SimulationController(duration=15)

    dos = attackDoSMode()
    ddos = attackDDoSMode()
    adaptive = attackAdaptiveMode(dos, ddos)

    modes = ModeRefs(dos=dos, ddos=ddos, adaptive=adaptive)
    main(controller, modes)

if __name__ == "__main__":
    run()


