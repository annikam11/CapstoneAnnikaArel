import tkinter as tk
from tkinter import Canvas
from pathlib import Path
from PIL import Image, ImageTk

def on_button_click():
    print("button was clicked!")
Base = Path(__file__).resolve().parent.parent
Icons = Base / 'assets' / 'icons'

# Make this dynamic later with relative positioning with x,y coordinates

def start_ui():
    root = tk.Tk()
    root.title("ArelGuard Cybersecurity Tool")
    root.geometry("600x400")
    root.configure(bg="black")

    canvas = Canvas(root, width=500, height=400, bg="black", highlightthickness=0)
    canvas.pack(pady=20)

    canvas.create_text(
        250, 25, 
        text="Hi, Welcome to ArelGuard", fill="#8A2BE2",
        font=("Bebas Neue", 16, "bold"))
    
    shield_icon = ImageTk.PhotoImage(Image.open(Icons / 'shield.png').resize((100, 100)))
    radar_icon = ImageTk.PhotoImage(Image.open(Icons / 'radar.png').resize((180, 100)))
    
    canvas.create_image(400, 125, image=shield_icon)
    canvas.create_image(100, 125, image=radar_icon)

    #Defense Mode - This needs to be a button tomorrow
    #canvas.create_rectangle(
    # 325, 200, 475, 275, fill="white", outline="blue", width=2)
    defense_button = tk.Button(root, text="Defense Mode", font=("Bebas Neue", 16, "bold"), command=on_button_click, bg="#0000FF")
    defense_button.pack()
    canvas.create_window(400, 245, window=defense_button)
    # This will be use with x y coordinates to show where exactly on the screen it will go, it will be bound to whatever size screen it is. 
    # canvas.create_text(
        # 400, 240, text="Defense Mode", fill="blue", font=("Bebas Neue", 15, "bold"))
    
    #Attack Mode - This needs to be a button tomorrow, this will be xy cooridnates and will go with the screen size, buttons will be dynamic
    # canvas.create_rectangle(
    #    25, 200, 175, 275, fill="white", outline="red", width=2)
    attack_button = tk.Button(root, text="Attack Mode", font=("Bebas Neue", 16, "bold"), command=on_button_click, bg="red")
    attack_button.pack()
    canvas.create_window(103, 245, window=attack_button)
    # canvas.create_text(
    #    103, 240, text="Attack Mode", fill="red", font=("Bebas Neue", 15, "bold"))

    # Login 
    canvas.create_text(
        250, 285, text="Login", fill="#98F5FF", font=("Bebas Neue", 15, "bold"))
    # Sign Up
    canvas.create_text(
        250, 325, text="Sign Up", fill="#98F5FF", font=("Bebas Neue", 15, "bold"))
    
    # Copyright
    canvas.create_text(
        425, 355, text="© ArelGuard 2026", fill="white", font=("Bebas Neue", 10))
    root.mainloop()
