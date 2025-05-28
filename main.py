import fitz
import tkinter as tk
from tkinter import filedialog, messagebox, Scrollbar, simpledialog, colorchooser
from PIL import Image, ImageTk
import tempfile
import shutil
import copy

class PDFReader:
    def __init__(self, filepath=None):
        # PDF state
        self.doc = None
        self.current_page = 0
        self.current_file = None

        # Undo/Redo stacks
        self.undo_stack = []
        self.redo_stack = []

        # Canvas/UI state
        self.mode = None
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None
        self.drawing = False
        self.pen_color = "#000000"
        self.last_draw_x = None
        self.last_draw_y = None
        self.image_id = None

        self.root = tk.Tk()
        self.root.title("OpenDoc PDF Reader")
        try:
            self.root.state('zoomed')
        except Exception:
            self.root.attributes('-zoomed', True)

        # --- Menubar ---
        menubar = tk.Menu(self.root)
        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New", command=self.new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="Open", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as, accelerator="Ctrl+Shift+S")
        menubar.add_cascade(label="File", menu=file_menu)
        # Edit Menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        menubar.add_cascade(label="Edit", menu=edit_menu)
        # Share & Help
        share_menu = tk.Menu(menubar, tearoff=0)
        share_menu.add_command(label="Share", command=self.share_file)
        menubar.add_cascade(label="Share", menu=share_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Help", command=self.show_help)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

        # --- Key Bindings ---
        self.root.bind("<Control-s>", lambda e: self.save_file())
        self.root.bind("<Control-S>", lambda e: self.save_as())
        self.root.bind("<Control-Shift-S>", lambda e: self.save_as())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-n>", lambda e: self.new_file())
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())

        # --- UI Layout ---
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill="both", expand=True)
        self.canvas_frame = tk.Frame(main_frame)
        self.canvas_frame.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(self.canvas_frame, bg="#1e1e1e")
        self.v_scroll = Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set)
        self.v_scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind('<Configure>', self.center_image)

        btn_frame = tk.Frame(self.root, bg="#2b2b2b")
        btn_frame.pack(fill="x")
        btn_style = {
            "font": ("Segoe UI", 12, "bold"),
            "bg": "#4a90e2",
            "fg": "white",
            "relief": "flat",
            "padx": 20,
            "pady": 10
        }
        tk.Button(btn_frame, text="⟵ Previous", command=self.prev_page, **btn_style).pack(side="left", padx=20, pady=10)
        tk.Button(btn_frame, text="Next ⟶", command=self.next_page, **btn_style).pack(side="right", padx=20, pady=10)

        self.page_label = tk.Label(self.canvas, font=("Segoe UI", 10, "bold"), bg="#000000", fg="#ffffff")
        self.page_label.place(x=10, rely=1.0, anchor='sw')
        self.page_label.configure(bg='#000000', fg='#ffffff')

        sidebar = tk.Frame(main_frame, width=150, bg="#2b2b2b")
        sidebar.pack(side="right", fill="y")
        tool_btn_style = {
            "font": ("Segoe UI", 10, "bold"),
            "bg": "#4a90e2",
            "fg": "white",
            "relief": "flat",
            "padx": 10,
            "pady": 5,
            "width": 12
        }
        tk.Label(sidebar, text="Tools", bg="#2b2b2b", fg="white", font=("Segoe UI", 12, "bold")).pack(pady=10)
        tk.Button(sidebar, text="Pen", command=self.pen_mode, **tool_btn_style).pack(pady=5)
        tk.Button(sidebar, text="Redact", command=self.redact_content, **tool_btn_style).pack(pady=5)
        tk.Button(sidebar, text="Remove", command=self.edit_content, **tool_btn_style).pack(pady=5)
        tk.Button(sidebar, text="Comment", command=self.add_comment_mode, **tool_btn_style).pack(pady=5)
        tk.Button(sidebar, text="Media", command=self.insert_media, **tool_btn_style).pack(pady=5)
        tk.Button(sidebar, text="New Page", command=self.new_page, **tool_btn_style).pack(pady=5)

        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)

        if filepath:
            self.root.update()
            self.load_pdf(filepath)

        self.root.mainloop()

    # --- Undo/Redo support ---
    def push_undo(self):
        # Save a copy of the current doc for undo
        if self.doc:
            # Save to memory as bytes for minimal memory use
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            self.doc.save(tmp.name)
            with open(tmp.name, "rb") as f:
                self.undo_stack.append(f.read())
            tmp.close()

    def restore_pdf(self, data):
        # Loads a PDF from bytes
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(data)
        tmp.close()
        self.doc = fitz.open(tmp.name)
        self.render_page()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.get_doc_bytes())
        last_state = self.undo_stack.pop()
        self.restore_pdf(last_state)

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.get_doc_bytes())
        next_state = self.redo_stack.pop()
        self.restore_pdf(next_state)

    def get_doc_bytes(self):
        # Returns the current doc as bytes
        if not self.doc:
            return b''
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        self.doc.save(tmp.name)
        with open(tmp.name, "rb") as f:
            data = f.read()
        tmp.close()
        return data

    # --- PDF Rendering & Events ---
    def center_image(self, event):
        if self.image_id:
            self.canvas.coords(self.image_id, event.width // 2, event.height // 2)
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def load_pdf(self, filepath):
        try:
            self.doc = fitz.open(filepath)
            self.current_file = filepath
            self.current_page = 0
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.render_page()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file:\n{e}")

    def render_page(self):
        if not self.doc or len(self.doc) == 0:
            return
        page = self.doc.load_page(self.current_page)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.tk_img = ImageTk.PhotoImage(img)
        self.canvas.delete("page_img")
        self.image_id = self.canvas.create_image(
            self.canvas.winfo_width() // 2,
            self.canvas.winfo_height() // 1.25,
            anchor="center",
            image=self.tk_img,
            tags="page_img"
        )
        self.canvas.tag_bind("page_img", "<Button-1>", self.on_canvas_click)
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
        self.page_label.config(text=f"Page {self.current_page + 1} of {len(self.doc)}")

    def next_page(self):
        if self.doc and self.current_page + 1 < len(self.doc):
            self.current_page += 1
            self.render_page()

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.render_page()

    def new_file(self):
        self.push_undo()
        self.doc = fitz.open()
        self.current_page = 0
        self.current_file = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.new_page()
        self.render_page()

    def new_page(self):
        if not self.doc:
            self.doc = fitz.open()
        self.push_undo()
        self.doc.new_page()
        self.current_page = len(self.doc) - 1
        self.render_page()

    def pen_mode(self):
        self.mode = 'pen'
        color = colorchooser.askcolor(title="Choose Pen Color")[1]
        if color:
            self.pen_color = color

    def open_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if filepath:
            self.load_pdf(filepath)

    def save_file(self):
        if not self.doc:
            return
        if not self.current_file:
            self.save_as()
            return
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp_path = tmp.name
            self.doc.save(tmp_path)
            self.doc.close()
            shutil.move(tmp_path, self.current_file)
            self.doc = fitz.open(self.current_file)
            messagebox.showinfo("Saved", "File saved successfully.")
        except Exception as e:
            messagebox.showerror("Save Failed", str(e))

    def save_as(self):
        if self.doc:
            save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
            if save_path:
                try:
                    self.doc.save(save_path)
                    self.current_file = save_path
                    messagebox.showinfo("Saved", "File saved successfully.")
                except Exception as e:
                    messagebox.showerror("Save Failed", str(e))

    def add_comment_mode(self):
        self.mode = 'comment'

    def redact_content(self):
        self.mode = 'redact'

    def edit_content(self):
        self.mode = 'edit'

    def write_text(self):
        self.mode = 'write'

    def insert_media(self):
        self.mode = 'media'

    def show_help(self):
        help_text = (
            " OpenDOC PDF Reader - Feature Guide\n\n"
            " File Menu:\n"
            " - New: Create a new blank PDF (Ctrl+N)\n"
            " - Open: Open an existing PDF (Ctrl+O)\n"
            " - Save/Save As: Save your edits (Ctrl+S/Ctrl+Shift+S)\n\n"
            " Tools:\n"
            " - Previous/Next: Navigate pages\n"
            " - Redact: Black out selected areas\n"
            " - Remove: White out areas\n"
            " - Comment: Add visible text comments\n"
            " - Media: Insert images into pages\n"
            " - Pen: Draw freehand with color picker\n\n"
            "Undo/Redo: Ctrl+Z / Ctrl+Y\n"
            " Share: Get instructions on sharing your PDF\n"
            " Help: View this guide\n\n"
            "Enjoy using OpenDOC PDF!"
        )
        messagebox.showinfo("Help", help_text)

    def share_file(self):
        if self.current_file:
            messagebox.showinfo("Share", f"Share '{self.current_file}' via email, cloud, or collaboration tools.")
        else:
            messagebox.showwarning("No File", "Please save the file before sharing.")

    # --- Coordinate Transforms ---
    def canvas_to_pdf_coords(self, event):
        if not self.image_id:
            return 0, 0
        # Only act if clicking inside the image area
        bbox = self.canvas.bbox(self.image_id)
        if not bbox:
            return 0, 0
        img_x0, img_y0, img_x1, img_y1 = bbox
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        # Check if click is inside image bounds
        if not (img_x0 <= canvas_x <= img_x1 and img_y0 <= canvas_y <= img_y1):
            return None, None
        # relative to image top-left
        rel_x = canvas_x - img_x0
        rel_y = canvas_y - img_y0
        zoom = 2
        pdf_x = rel_x / zoom
        pdf_y = rel_y / zoom
        return pdf_x, pdf_y

    def canvas_to_pdf_coords_simple(self, x, y):
        if not self.image_id:
            return 0, 0
        bbox = self.canvas.bbox(self.image_id)
        img_x0, img_y0 = bbox[0], bbox[1]
        canvas_x = self.canvas.canvasx(x)
        canvas_y = self.canvas.canvasy(y)
        rel_x = canvas_x - img_x0
        rel_y = canvas_y - img_y0
        zoom = 2
        pdf_x = rel_x // zoom
        pdf_y = rel_y // zoom
        return pdf_x, pdf_y

    # --- Mouse/Canvas Events ---
    def on_canvas_click(self, event):
        if not self.doc:
            return
        if self.mode == 'write':
            self.create_draggable_textbox(event)
        elif self.mode == 'comment':
            pdf_x, pdf_y = self.canvas_to_pdf_coords(event)
            if pdf_x is None:
                return  # Only act if click is inside the PDF image
            comment = simpledialog.askstring("Add Comment", "Enter your comment:")
            if comment:
                self.push_undo()
                page = self.doc.load_page(self.current_page)
                annot = page.add_text_annot((pdf_x, pdf_y), comment)
                annot.set_icon("Comment")
                self.render_page()
        elif self.mode == 'media':
            file_path = filedialog.askopenfilename(filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp")])
            if file_path:
                try:
                    img = fitz.Pixmap(file_path)
                except Exception:
                    img = fitz.Pixmap(fitz.csRGB, fitz.Pixmap(file_path))
                pdf_x, pdf_y = self.canvas_to_pdf_coords(event)
                if pdf_x is None:
                    return
                self.push_undo()
                page = self.doc.load_page(self.current_page)
                page.insert_image(
                    fitz.Rect(pdf_x, pdf_y, pdf_x + img.width // 2, pdf_y + img.height / 2),
                    pixmap=img
                )
                self.render_page()

    def create_draggable_textbox(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        textbox = tk.Text(self.canvas, height=4, width=30, font=("Segoe UI", 12))
        textbox_window = self.canvas.create_window(canvas_x, canvas_y, window=textbox, anchor="nw", tags="textbox")

        def start_drag(evt):
            textbox._drag_start_x = evt.x
            textbox._drag_start_y = evt.y

        def on_drag(evt):
            dx = evt.x - textbox._drag_start_x
            dy = evt.y - textbox._drag_start_y
            self.canvas.move(textbox_window, dx, dy)

        textbox.bind("<Button-1>", start_drag)
        textbox.bind("<B1-Motion>", on_drag)

        def confirm_text():
            text = textbox.get("1.0", "end").strip()
            if text:
                bbox = self.canvas.bbox(textbox_window)
                pdf_x, pdf_y = self.canvas_to_pdf_coords_simple(bbox[0], bbox[1])
                self.push_undo()
                page = self.doc.load_page(self.current_page)
                lines = text.split("\n")
                for i, line in enumerate(lines):
                    page.insert_text((pdf_x, pdf_y + i * 16), line, fontsize=16, color=(0, 0, 0))
                self.canvas.delete(textbox_window)
                textbox.destroy()
                self.render_page()
        confirm_btn = tk.Button(self.canvas, text="✔", command=confirm_text, bg="#4CAF50", fg="white")
        confirm_btn_window = self.canvas.create_window(canvas_x + 260, canvas_y, window=confirm_btn, anchor="nw")

    def on_mouse_press(self, event):
        if self.mode not in ['redact', 'edit', 'pen']:
            return
        pdf_x, pdf_y = self.canvas_to_pdf_coords(event)
        if pdf_x is None:
            return  # Only allow drawing on image
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=2)
        if self.mode == 'pen':
            self.drawing = True
            self.last_draw_x = self.start_x
            self.last_draw_y = self.start_y

    def on_mouse_drag(self, event):
        if self.rect_id and self.mode != 'pen':
            cur_x = self.canvas.canvasx(event.x)
            cur_y = self.canvas.canvasy(event.y)
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)
        if self.drawing and self.mode == 'pen':
            cur_x = self.canvas.canvasx(event.x)
            cur_y = self.canvas.canvasy(event.y)
            # Only draw if within image:
            bbox = self.canvas.bbox(self.image_id)
            if bbox:
                img_x0, img_y0, img_x1, img_y1 = bbox
                if img_x0 <= cur_x <= img_x1 and img_y0 <= cur_y <= img_y1:
                    self.canvas.create_line(self.last_draw_x, self.last_draw_y, cur_x, cur_y, fill=self.pen_color, width=2)
                    x0, y0 = self.canvas_to_pdf_coords_simple(self.last_draw_x, self.last_draw_y)
                    x1, y1 = self.canvas_to_pdf_coords_simple(cur_x, cur_y)
                    self.push_undo()
                    page = self.doc.load_page(self.current_page)
                    shape = page.new_shape()
                    shape.draw_line((x0, y0), (x1, y1))
                    r, g, b = self.hex_to_rgb(self.pen_color)
                    shape.finish(color=(r / 255, g / 255, b / 255), width=1.5)
                    shape.commit()
                    self.last_draw_x = cur_x
                    self.last_draw_y = cur_y

    def on_mouse_release(self, event):
        if not self.rect_id or not self.doc:
            return
        self.canvas.delete(self.rect_id)
        self.rect_id = None
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        bbox = self.canvas.bbox(self.image_id)
        if not bbox:
            return
        img_x0, img_y0 = bbox[0], bbox[1]
        x0, y0 = self.start_x - img_x0, self.start_y - img_y0
        x1, y1 = end_x - img_x0, end_y - img_y0
        zoom = 2
        rect = fitz.Rect(x0 / zoom, y0 / zoom, x1 / zoom, y1 / zoom)
        page = self.doc.load_page(self.current_page)
        if self.mode == 'redact':
            self.push_undo()
            page.add_redact_annot(rect, fill=(0, 0, 0))
            page.apply_redactions()
            self.render_page()
        elif self.mode == 'edit':
            self.push_undo()
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
            self.render_page()
        elif self.mode == 'pen':
            self.drawing = False
            self.render_page()

    def hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

PDFReader()
