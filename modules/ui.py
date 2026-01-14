import tkinter as tk
from tkinter import Canvas
from pathlib import Path
from PIL import Image, ImageTk

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
        250, 50, 
        text="Welcome to ArelGuard !", fill="#8A2BE2",
        font=("Bebas Neue", 16, "bold"))
    
    shield_icon = ImageTk.PhotoImage(Image.open(Icons / 'shield.png').resize((64, 64)))
    radar_icon = ImageTk.PhotoImage(Image.open(Icons / 'radar.png').resize((100, 80)))
    
    canvas.create_image(400, 100, image=shield_icon)
    canvas.create_image(100, 100, image=radar_icon)

    #Defense Mode - This needs to be a button tomorrow
    canvas.create_rectangle(
        325, 200, 475, 275, fill="white", outline="blue", width=2)
    
    canvas.create_text(
        400, 240, text="Defense Mode", fill="blue", font=("Bebas Neue", 15, "bold"))
    
    #Attack Mode - This needs to be a button tomorrow
    canvas.create_rectangle(
        25, 200, 175, 275, fill="white", outline="red", width=2)
    
    canvas.create_text(
        103, 240, text="Attack Mode", fill="red", font=("Bebas Neue", 15, "bold"))

    # Login 
    canvas.create_text(
        250, 300, text="Login", fill="#98F5FF", font=("Bebas Neue", 15, "bold"))
    # Sign Up
    canvas.create_text(
        250, 325, text="Sign Up", fill="#98F5FF", font=("Bebas Neue", 15, "bold"))
    root.mainloop()
