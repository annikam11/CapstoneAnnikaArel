import tkinter as tk
from tkinter import Canvas

def main():
    root = tk.Tk()
    root.title("ArelGuard Cybersecurity Tool")

    canvas = Canvas(root, width=300, height=300)
    canvas.pack(pady=20)
    canvas.create_text(150, 50, text="Welcome to ArelGuard !", font=("Helvetica", 16))

    root.mainloop()

if __name__ == "__main__":
    main()
    # test - AI helped