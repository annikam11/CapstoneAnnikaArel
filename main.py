import tkinter as tk
from tkinter import ttk, Canvas

def main():
    root = tk.Tk()
    root.title("ArelGuard Cybersecurity Tool")

    label = ttk.Label(root, text="Welcome to ArelGuard!")
    label = Canvas(root, width=300, height=100)
    label.pack(pady=20)

    root.mainloop()

if __name__ == "__main__":
    main()