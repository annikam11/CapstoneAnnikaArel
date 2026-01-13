import tkinter as tk
from tkinter import Canvas

def start_ui():
    root = tk.Tk()
    root.title("ArelGuard Cybersecurity Tool")
    root.geometry("600x400")
    root.configure(bg="black")

    canvas = Canvas(root, width=500, height=400, bg="black", highlightthickness=0)
    canvas.pack(pady=20)

    canvas.create_text(
        250, 50, 
        text="Welcome to ArelGuard !", fill="Purple",
        font=("Bebas Neue", 16, "bold"))

    #Defense Mode
    canvas.create_rectangle(
        325, 150, 475, 230, fill="white", outline="blue", width=2)
    
    canvas.create_text(
        400, 190, text="Defense Mode", fill="blue", font=("Bebas Neue", 15, "bold"))
    
    #Attack Mode
    canvas.create_rectangle(
        25, 150, 175, 230, fill="white", outline="red", width=2)
    
    canvas.create_text(
        103, 190, text="Attack Mode", fill="red", font=("Bebas Neue", 15, "bold"))

    root.mainloop()
