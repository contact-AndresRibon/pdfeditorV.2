"""
Firmador de PDF Interactivo - VERSIÓN PROFESIONAL CORREGIDA
- Edición de texto con doble clic
- Dibujo de firma con ratón (botones Aceptar/Cancelar/Borrar en ventana)
- Redimensionamiento perfecto con 8 manejadores blancos
- Selector de fecha con calendario y formatos desplegables
- Botón X para eliminar, Shift para mantener proporción
- CORRECCIÓN: Mapeo correcto de fuentes para exportación PDF
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from tkcalendar import Calendar
from PIL import Image, ImageTk, ImageDraw
import fitz
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PyPDF2 import PdfReader, PdfWriter
import io
import datetime
import uuid


class DraggableElement:
    def __init__(self, canvas, x, y, element_type, content, **kwargs):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.element_type = element_type
        self.content = content
        self.width = kwargs.get('width', 150)
        self.height = kwargs.get('height', 50)
        self.font_size = kwargs.get('font_size', 12)
        self.font_family = kwargs.get('font_family', 'Arial')
        self.color = kwargs.get('color', '#000000')
        self.selected = False
        self.dragging = False
        self.resizing = False
        self.resize_handle_id = None
        self.offset_x = 0
        self.offset_y = 0
        self.page_num = None
        self.id = str(uuid.uuid4())

        self.original_width = self.width
        self.original_height = self.height
        self.original_font_size = self.font_size

        self.editing = False
        self.entry = None

        self.create_visual()

    def create_visual(self):
        # Obtener offset de visualización si existe
        offset_x = getattr(self, 'display_offset_x', 0)
        offset_y = getattr(self, 'display_offset_y', 0)
        
        if self.element_type == 'text':
            self.canvas_id = self.canvas.create_text(
                self.x + offset_x, self.y + offset_y, text=self.content, font=(self.font_family, self.font_size),
                fill=self.color, anchor='nw', tags=('element', self.id)
            )
            bbox = self.canvas.bbox(self.canvas_id)
            if bbox:
                self.width = bbox[2] - bbox[0]
                self.height = bbox[3] - bbox[1]
        elif self.element_type in ['image', 'signature']:
            try:
                if isinstance(self.content, str):
                    img = Image.open(self.content)
                else:
                    img = self.content.copy()
                img = img.resize((int(self.width), int(self.height)), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(img)
                self.canvas_id = self.canvas.create_image(
                    self.x + offset_x, self.y + offset_y, image=self.photo, anchor='nw', tags=('element', self.id)
                )
            except Exception as e:
                print(f"Error imagen: {e}")
                return

        # Marco selección
        self.selection_rect = self.canvas.create_rectangle(0, 0, 0, 0,
            outline='#0078d7', width=2, dash=(4, 4), state='hidden', tags=('select', self.id))

        # Botón X
        self.delete_button = self.canvas.create_oval(0, 0, 0, 0, fill='red', outline='white', width=2, state='hidden', tags=('delete', self.id))
        self.delete_text = self.canvas.create_text(0, 0, text='X', fill='white', font=('Arial', 10, 'bold'), state='hidden', tags=('delete', self.id))

        # 8 manejadores con diseño mejorado
        self.resize_handles = []
        for i in range(8):
            h = self.canvas.create_oval(0, 0, 0, 0, fill='white', outline='#0078d7', width=2, state='hidden', tags=('handle', self.id))
            self.resize_handles.append(h)

        self.update_selection()

        # Eventos
        self.canvas.tag_bind(self.canvas_id, '<Button-1>', self.on_press)
        self.canvas.tag_bind(self.canvas_id, '<B1-Motion>', self.on_drag)
        self.canvas.tag_bind(self.canvas_id, '<ButtonRelease-1>', self.on_release)
        self.canvas.tag_bind(self.canvas_id, '<Double-Button-1>', self.start_edit)

        self.canvas.tag_bind(self.delete_button, '<Button-1>', self.on_delete)
        self.canvas.tag_bind(self.delete_text, '<Button-1>', self.on_delete)

        for i, h in enumerate(self.resize_handles):
            self.canvas.tag_bind(h, '<Button-1>', lambda e, idx=i: self.start_resize(e, idx))
            self.canvas.tag_bind(h, '<B1-Motion>', lambda e, idx=i: self.do_resize(e, idx))
            self.canvas.tag_bind(h, '<ButtonRelease-1>', self.stop_resize)

    def start_edit(self, event):
        if self.element_type != 'text' or self.editing:
            return
        self.editing = True
        bbox = self.canvas.bbox(self.canvas_id)
        if not bbox:
            return
        x1, y1, x2, y2 = bbox
        self.entry = tk.Entry(self.canvas, font=(self.font_family, self.font_size), fg=self.color, relief='flat', bd=0)
        self.entry.insert(0, self.content)
        self.entry.select_range(0, 'end')
        self.entry.focus()
        self.entry_window = self.canvas.create_window(x1, y1, anchor='nw', window=self.entry, width=x2-x1, height=y2-y1)

        def commit_edit(e=None):
            self.content = self.entry.get()
            self.canvas.delete(self.entry_window)
            self.entry.destroy()
            self.editing = False
            self.update_visual()
            self.update_selection()

        def cancel_edit(e=None):
            self.canvas.delete(self.entry_window)
            self.entry.destroy()
            self.editing = False
            self.update_selection()

        self.entry.bind('<Return>', commit_edit)
        self.entry.bind('<FocusOut>', commit_edit)
        self.entry.bind('<Escape>', cancel_edit)

    def on_delete(self, event):
        self.delete()
        return "break"

    def start_resize(self, event, idx):
        self.resizing = True
        self.resize_handle_id = idx
        self.resize_start_x = event.x
        self.resize_start_y = event.y
        self.start_width = self.width
        self.start_height = self.height
        self.start_x = self.x
        self.start_y = self.y
        self.start_font_size = self.font_size
        self.select()
        return "break"

    def do_resize(self, event, idx):
        if not self.resizing:
            return
        dx = event.x - self.resize_start_x
        dy = event.y - self.resize_start_y

        # Determinar qué bordes se están moviendo
        # 0: top-left, 1: top-center, 2: top-right
        # 3: middle-right, 4: bottom-right, 5: bottom-center
        # 6: bottom-left, 7: middle-left
        left = idx in [0, 6, 7]
        right = idx in [2, 3, 4]
        top = idx in [0, 1, 2]
        bottom = idx in [4, 5, 6]

        new_x, new_y = self.start_x, self.start_y
        new_w, new_h = self.start_width, self.start_height

        # Detectar si Shift está presionado para mantener proporción
        shift_pressed = (event.state & 0x0001) != 0

        if self.element_type in ['image', 'signature'] and shift_pressed:
            # Mantener proporción para imágenes/firmas con Shift
            ratio = self.original_width / self.original_height if self.original_height else 1
            
            # Calcular nuevo tamaño basado en el manejador usado
            if right or left:
                if left:
                    new_w = max(30, self.start_width - dx)
                    new_x = self.start_x + (self.start_width - new_w)
                else:
                    new_w = max(30, self.start_width + dx)
                new_h = new_w / ratio
            elif top or bottom:
                if top:
                    new_h = max(20, self.start_height - dy)
                    new_y = self.start_y + (self.start_height - new_h)
                else:
                    new_h = max(20, self.start_height + dy)
                new_w = new_h * ratio
        else:
            # Redimensionamiento libre
            if left:
                new_w = max(30, self.start_width - dx)
                new_x = self.start_x + (self.start_width - new_w)
            if right:
                new_w = max(30, self.start_width + dx)
            if top:
                new_h = max(20, self.start_height - dy)
                new_y = self.start_y + (self.start_height - new_h)
            if bottom:
                new_h = max(20, self.start_height + dy)

        self.x, self.y = new_x, new_y
        self.width, self.height = new_w, new_h

        # Escalar fuente proporcionalmente para texto
        if self.element_type == 'text':
            scale_w = new_w / self.start_width if self.start_width else 1
            scale_h = new_h / self.start_height if self.start_height else 1
            scale = min(scale_w, scale_h)
            self.font_size = max(8, int(self.start_font_size * scale))

        self.update_visual()
        self.update_selection()

    def stop_resize(self, event):
        self.resizing = False
        if self.element_type in ['image', 'signature']:
            self.original_width = self.width
            self.original_height = self.height

    def on_press(self, event):
        if self.resizing:
            return
        self.dragging = True
        self.select()
        
        # Obtener offset de visualización
        offset_x = getattr(self, 'display_offset_x', 0)
        offset_y = getattr(self, 'display_offset_y', 0)
        
        self.offset_x = event.x - (self.x + offset_x)
        self.offset_y = event.y - (self.y + offset_y)
        self.canvas.tag_raise(self.canvas_id)
        self.canvas.tag_raise(self.selection_rect)
        self.canvas.tag_raise(self.delete_button)
        self.canvas.tag_raise(self.delete_text)
        for h in self.resize_handles:
            self.canvas.tag_raise(h)
        return "break"

    def on_drag(self, event):
        if self.dragging and not self.resizing:
            offset_x = getattr(self, 'display_offset_x', 0)
            offset_y = getattr(self, 'display_offset_y', 0)
            
            # Actualizar posición real (sin offset)
            self.x = event.x - self.offset_x - offset_x
            self.y = event.y - self.offset_y - offset_y
            self.update_visual()
            self.update_selection()

    def on_release(self, event):
        self.dragging = False

    def update_visual(self):
        offset_x = getattr(self, 'display_offset_x', 0)
        offset_y = getattr(self, 'display_offset_y', 0)
        
        self.canvas.coords(self.canvas_id, self.x + offset_x, self.y + offset_y)
        if self.element_type == 'text':
            self.canvas.itemconfig(self.canvas_id, text=self.content,
                                 font=(self.font_family, self.font_size), fill=self.color)
            bbox = self.canvas.bbox(self.canvas_id)
            if bbox:
                self.width = bbox[2] - bbox[0]
                self.height = bbox[3] - bbox[1]
        elif self.element_type in ['image', 'signature']:
            try:
                if isinstance(self.content, str):
                    img = Image.open(self.content)
                else:
                    img = self.content.copy()
                img = img.resize((int(self.width), int(self.height)), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(img)
                self.canvas.itemconfig(self.canvas_id, image=self.photo)
            except Exception as e:
                print(f"Error: {e}")

    def update_selection(self):
        bbox = self.canvas.bbox(self.canvas_id)
        if not bbox:
            return
        pad = 4
        x1, y1, x2, y2 = bbox
        self.canvas.coords(self.selection_rect, x1-pad, y1-pad, x2+pad, y2+pad)

        # Botón X
        btn = 16
        self.canvas.coords(self.delete_button, x2-pad-btn, y1-pad-btn, x2-pad, y1-pad)
        self.canvas.coords(self.delete_text, x2-pad-btn//2, y1-pad-btn//2)

        # 8 manejadores (círculos blancos con borde azul)
        hs = 8  # Tamaño de los manejadores
        positions = [
            (x1-pad-hs//2, y1-pad-hs//2),           # 0: top-left
            ((x1+x2)//2-hs//2, y1-pad-hs//2),       # 1: top-center
            (x2+pad-hs//2, y1-pad-hs//2),           # 2: top-right
            (x2+pad-hs//2, (y1+y2)//2-hs//2),       # 3: middle-right
            (x2+pad-hs//2, y2+pad-hs//2),           # 4: bottom-right
            ((x1+x2)//2-hs//2, y2+pad-hs//2),       # 5: bottom-center
            (x1-pad-hs//2, y2+pad-hs//2),           # 6: bottom-left
            (x1-pad-hs//2, (y1+y2)//2-hs//2),       # 7: middle-left
        ]
        for i, (hx, hy) in enumerate(positions):
            h = self.resize_handles[i]
            self.canvas.coords(h, hx, hy, hx+hs, hy+hs)

    def select(self):
        for elem in self.canvas.elements:
            if elem != self and elem.selected:
                elem.deselect()
        self.selected = True
        self.canvas.itemconfig(self.selection_rect, state='normal')
        self.canvas.itemconfig(self.delete_button, state='normal')
        self.canvas.itemconfig(self.delete_text, state='normal')
        for h in self.resize_handles:
            self.canvas.itemconfig(h, state='normal')
        self.canvas.master_element = self

    def deselect(self):
        self.selected = False
        self.canvas.itemconfig(self.selection_rect, state='hidden')
        self.canvas.itemconfig(self.delete_button, state='hidden')
        self.canvas.itemconfig(self.delete_text, state='hidden')
        for h in self.resize_handles:
            self.canvas.itemconfig(h, state='hidden')

    def delete(self):
        items = self.canvas.find_withtag(self.id)
        for item in items:
            self.canvas.delete(item)
        if hasattr(self.canvas, 'master_element') and self.canvas.master_element == self:
            del self.canvas.master_element


class SignatureDrawer:
    def __init__(self, canvas, callback):
        self.canvas = canvas
        self.callback = callback
        self.drawing = False
        self.last_x = 0
        self.last_y = 0
        self.lines = []
        self.img = Image.new("RGBA", (440, 200), (255, 255, 255, 0))
        self.draw = ImageDraw.Draw(self.img)

        self.window = tk.Toplevel(canvas.master)
        self.window.title("Dibujar Firma")
        self.window.geometry("480x320")
        self.window.transient(canvas.master)
        self.window.grab_set()
        
        # Centrar ventana
        self.window.update_idletasks()
        x = (self.window.winfo_screenwidth() // 2) - (480 // 2)
        y = (self.window.winfo_screenheight() // 2) - (320 // 2)
        self.window.geometry(f'480x320+{x}+{y}')

        # Instrucciones
        ttk.Label(self.window, text="Dibuja tu firma con el ratón:", 
                 font=('Arial', 11)).pack(pady=8)

        # Canvas de dibujo con borde
        canvas_frame = ttk.Frame(self.window, relief='solid', borderwidth=1)
        canvas_frame.pack(padx=15, pady=8)
        
        self.draw_canvas = tk.Canvas(canvas_frame, width=440, height=200, bg='white', cursor='crosshair')
        self.draw_canvas.pack()

        # Botones
        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="✓ Aceptar", command=self.accept, width=15).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_frame, text="✗ Cancelar", command=self.cancel, width=15).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_frame, text="🗑 Borrar", command=self.clear, width=15).pack(side=tk.LEFT, padx=8)

        # Eventos de dibujo
        self.draw_canvas.bind('<Button-1>', self.start_draw)
        self.draw_canvas.bind('<B1-Motion>', self.draw_line)
        self.draw_canvas.bind('<ButtonRelease-1>', self.stop_draw)
        
        # Evento para cerrar ventana
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)

    def start_draw(self, event):
        self.drawing = True
        self.last_x, self.last_y = event.x, event.y

    def draw_line(self, event):
        if self.drawing:
            x, y = event.x, event.y
            line = self.draw_canvas.create_line(
                self.last_x, self.last_y, x, y, 
                width=3, fill='black', capstyle=tk.ROUND, 
                smooth=True, joinstyle=tk.ROUND
            )
            self.lines.append(line)
            self.draw.line([self.last_x, self.last_y, x, y], fill=(0, 0, 0, 255), width=3)
            self.last_x, self.last_y = x, y

    def stop_draw(self, event):
        self.drawing = False

    def clear(self):
        for line in self.lines:
            self.draw_canvas.delete(line)
        self.lines = []
        self.img = Image.new("RGBA", (440, 200), (255, 255, 255, 0))
        self.draw = ImageDraw.Draw(self.img)

    def accept(self):
        if not self.lines:
            messagebox.showwarning("Advertencia", "Por favor dibuja una firma antes de aceptar")
            return
        
        # Recortar imagen al contenido real
        bbox = self.img.getbbox()
        if bbox:
            cropped = self.img.crop(bbox)
            self.callback(cropped)
            self.window.destroy()
        else:
            messagebox.showwarning("Advertencia", "No se detectó ninguna firma")

    def cancel(self):
        self.window.destroy()


class PDFSignerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Firmador de PDF Profesional")
        self.root.geometry("1400x900")

        self.pdf_path = None
        self.pdf_document = None
        self.current_page = 0
        self.total_pages = 0
        self.elements = []
        self.zoom_level = 1.0
        self.current_color = '#000000'

        self.setup_ui()

    def setup_ui(self):
        # Barra superior con botones principales
        toolbar = ttk.Frame(self.root, relief=tk.RAISED, borderwidth=1)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=0, pady=0)

        # Frame izquierdo para botones de archivo
        file_frame = ttk.Frame(toolbar)
        file_frame.pack(side=tk.LEFT, padx=5, pady=5)
        
        ttk.Button(file_frame, text="📁 Abrir PDF", command=self.load_pdf).pack(side=tk.LEFT, padx=2)
        ttk.Button(file_frame, text="💾 Guardar PDF", command=self.save_pdf).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Frame central para herramientas
        tools_frame = ttk.Frame(toolbar)
        tools_frame.pack(side=tk.LEFT, padx=5, pady=5)
        
        ttk.Button(tools_frame, text="📝 Texto", command=self.add_text_element).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_frame, text="✍ Firma (Dibujar)", command=self.draw_signature).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_frame, text="🖼 Firma (Imagen)", command=self.add_signature_image).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_frame, text="🖼 Imagen", command=self.add_image_element).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_frame, text="📅 Fecha", command=self.add_date_element).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        ttk.Button(toolbar, text="🗑 Eliminar", command=self.delete_selected).pack(side=tk.LEFT, padx=5)

        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_panel = ttk.LabelFrame(main_frame, text="Propiedades", width=250)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        left_panel.pack_propagate(False)

        ttk.Label(left_panel, text="Tamaño de fuente:").pack(anchor=tk.W, padx=5, pady=(10, 0))
        self.font_size_var = tk.StringVar(value='12')
        font_sizes = ['8', '10', '12', '14', '16', '18', '20', '24', '28', '32', '36', '40', '48', '56', '64', '72']
        font_size_combo = ttk.Combobox(left_panel, textvariable=self.font_size_var,
                                      values=font_sizes, width=10, state='normal')
        font_size_combo.pack(fill=tk.X, padx=5, pady=5)
        
        def validate_font_size(*args):
            try:
                size = int(self.font_size_var.get())
                if size < 1:
                    self.font_size_var.set('12')
                elif size > 200:
                    self.font_size_var.set('72')
                self.update_font_size()
            except ValueError:
                pass
        
        self.font_size_var.trace_add('write', validate_font_size)

        ttk.Label(left_panel, text="Fuente:").pack(anchor=tk.W, padx=5, pady=(10, 0))
        self.font_family_var = tk.StringVar(value='Arial')
        ttk.Combobox(left_panel, textvariable=self.font_family_var,
                    values=['Arial', 'Helvetica', 'Times', 'Courier'], state='readonly').pack(fill=tk.X, padx=5, pady=5)
        self.font_family_var.trace_add('write', self.update_font_family)

        ttk.Label(left_panel, text="Color:").pack(anchor=tk.W, padx=5, pady=(10, 0))
        self.color_button = ttk.Button(left_panel, text="Elegir Color", command=self.choose_color)
        self.color_button.pack(fill=tk.X, padx=5, pady=5)
        
        # Indicador de color actual
        self.color_indicator = tk.Canvas(left_panel, height=30, bg=self.current_color, relief=tk.SUNKEN, borderwidth=2)
        self.color_indicator.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(left_panel, text="Zoom:").pack(anchor=tk.W, padx=5, pady=(20, 0))
        zoom_frame = ttk.Frame(left_panel)
        zoom_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(zoom_frame, text="➖", command=self.zoom_out, width=5).pack(side=tk.LEFT, padx=2)
        self.zoom_label = ttk.Label(zoom_frame, text="100%", font=('Arial', 9))
        self.zoom_label.pack(side=tk.LEFT, expand=True)
        ttk.Button(zoom_frame, text="➕", command=self.zoom_in, width=5).pack(side=tk.RIGHT, padx=2)
        ttk.Button(zoom_frame, text="⟲", command=self.zoom_reset, width=5).pack(side=tk.RIGHT, padx=2)

        # Ayuda
        help_frame = ttk.LabelFrame(left_panel, text="Ayuda")
        help_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=20)
        help_text = """
• Doble clic: Editar texto
• Arrastrar: Mover elemento
• Círculos blancos: Redimensionar
• Shift + arrastrar: Mantener proporción
• Botón X rojo: Eliminar
• Scroll: Desplazar PDF vertical
        """
        ttk.Label(help_frame, text=help_text, justify=tk.LEFT, font=('Arial', 8)).pack(padx=5, pady=5)

        center_panel = ttk.Frame(main_frame)
        center_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        canvas_frame = ttk.Frame(center_panel, relief=tk.SUNKEN, borderwidth=1)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(canvas_frame, bg='#2b2b2b',
                               xscrollcommand=self.h_scroll.set, 
                               yscrollcommand=self.v_scroll.set,
                               highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.elements = []

        self.h_scroll.config(command=self.canvas.xview)
        self.v_scroll.config(command=self.canvas.yview)
        
        # Soporte para scroll con rueda del ratón
        self.canvas.bind('<MouseWheel>', self.on_mousewheel)
        self.canvas.bind('<Button-4>', self.on_mousewheel)  # Linux scroll up
        self.canvas.bind('<Button-5>', self.on_mousewheel)  # Linux scroll down

        nav_frame = ttk.Frame(center_panel)
        nav_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(nav_frame, text="⏮ Primera", command=self.first_page, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav_frame, text="⬅ Anterior", command=self.prev_page, width=12).pack(side=tk.LEFT, padx=2)
        
        self.page_label = ttk.Label(nav_frame, text="Sin PDF cargado", font=('Arial', 10, 'bold'))
        self.page_label.pack(side=tk.LEFT, expand=True)
        
        ttk.Button(nav_frame, text="Siguiente ➡", command=self.next_page, width=12).pack(side=tk.RIGHT, padx=2)
        ttk.Button(nav_frame, text="Última ⏭", command=self.last_page, width=12).pack(side=tk.RIGHT, padx=2)

        self.canvas.bind('<Button-1>', self.on_canvas_click)

    def on_canvas_click(self, event):
        hit = self.canvas.find_withtag("current")
        if not hit or not any(tag in self.canvas.gettags(hit[0]) for tag in ['element']):
            for elem in self.canvas.elements:
                elem.deselect()
    
    def on_mousewheel(self, event):
        """Soporte para scroll con rueda del ratón"""
        if event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, "units")
        elif event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, "units")

    def load_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if path:
            try:
                self.pdf_path = path
                self.pdf_document = fitz.open(path)
                self.total_pages = len(self.pdf_document)
                self.current_page = 0
                self.elements = []
                self.zoom_level = 1.0
                self.render_page()
                messagebox.showinfo("Éxito", f"PDF cargado correctamente\n{self.total_pages} páginas")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo cargar el PDF:\n{str(e)}")

    def render_page(self):
        self.canvas.delete("all")
        if not self.pdf_document:
            return
        
        page = self.pdf_document[self.current_page]
        mat = fitz.Matrix(self.zoom_level, self.zoom_level)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Convertir a imagen con mejor calidad
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # Crear fondo gris para simular sombra del documento
        self.shadow_offset = 10
        bg_width = pix.width + self.shadow_offset * 2
        bg_height = pix.height + self.shadow_offset * 2
        background = Image.new('RGB', (bg_width, bg_height), '#2b2b2b')
        
        # Crear sombra
        shadow = Image.new('RGBA', (pix.width + 10, pix.height + 10), (0, 0, 0, 80))
        background.paste(shadow, (self.shadow_offset + 5, self.shadow_offset + 5))
        
        # Pegar PDF sobre el fondo
        background.paste(img, (self.shadow_offset, self.shadow_offset))
        
        self.pdf_img = ImageTk.PhotoImage(background)
        self.canvas.create_image(self.shadow_offset, self.shadow_offset, image=self.pdf_img, anchor='nw', tags='pdf_bg')
        
        # Configurar región de scroll para mostrar todo el contenido
        self.canvas.config(scrollregion=(0, 0, bg_width, bg_height))
        
        # Actualizar etiquetas
        self.page_label.config(text=f"Página {self.current_page + 1} de {self.total_pages}")
        self.zoom_label.config(text=f"{int(self.zoom_level * 100)}%")

        # Re-crear elementos visuales de la página actual
        self.canvas.elements = [e for e in self.elements if getattr(e, 'page_num', -1) == self.current_page]
        for elem in self.canvas.elements:
            # Temporalmente ajustar posición para visualización
            elem.display_offset_x = self.shadow_offset
            elem.display_offset_y = self.shadow_offset
            elem.create_visual()

    def add_text_element(self):
        if not self.pdf_document:
            messagebox.showwarning("Advertencia", "Por favor carga un PDF primero")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Agregar Texto")
        dialog.geometry("500x180")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Centrar
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (dialog.winfo_screenheight() // 2) - (180 // 2)
        dialog.geometry(f'500x180+{x}+{y}')
        
        ttk.Label(dialog, text="Ingresa el texto:", font=('Arial', 11)).pack(pady=15)
        entry = ttk.Entry(dialog, width=50, font=('Arial', 12))
        entry.pack(pady=15, padx=25)
        entry.focus()
        
        def create():
            text = entry.get().strip()
            if text:
                try:
                    font_size = int(self.font_size_var.get())
                except ValueError:
                    font_size = 12
                    
                elem = DraggableElement(self.canvas, 100, 100, 'text', text,
                                      font_size=font_size,
                                      font_family=self.font_family_var.get(),
                                      color=self.current_color)
                elem.page_num = self.current_page
                self.elements.append(elem)
                self.canvas.elements.append(elem)
                dialog.destroy()
            else:
                messagebox.showwarning("Advertencia", "El texto no puede estar vacío")
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="✓ Aceptar", command=create, width=15).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_frame, text="✗ Cancelar", command=dialog.destroy, width=15).pack(side=tk.LEFT, padx=8)
        
        entry.bind('<Return>', lambda e: create())

    def draw_signature(self):
        if not self.pdf_document:
            messagebox.showwarning("Advertencia", "Por favor carga un PDF primero")
            return
        SignatureDrawer(self.canvas, self.add_signature_from_image)

    def add_signature_image(self):
        if not self.pdf_document:
            messagebox.showwarning("Advertencia", "Por favor carga un PDF primero")
            return
        path = filedialog.askopenfilename(
            title="Seleccionar imagen de firma",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.gif *.bmp")]
        )
        if path:
            try:
                img = Image.open(path)
                self.add_signature_from_image(img)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo cargar la imagen:\n{str(e)}")

    def add_signature_from_image(self, img):
        elem = DraggableElement(self.canvas, 100, 100, 'signature', img, width=200, height=80)
        elem.page_num = self.current_page
        self.elements.append(elem)
        self.canvas.elements.append(elem)
        elem.select()
        messagebox.showinfo("Firma agregada", 
                          "Usa los círculos blancos para redimensionar la firma.\n" +
                          "Mantén presionado Shift para conservar la proporción.")

    def add_image_element(self):
        if not self.pdf_document:
            messagebox.showwarning("Advertencia", "Por favor carga un PDF primero")
            return
        path = filedialog.askopenfilename(
            title="Seleccionar imagen",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.gif *.bmp")]
        )
        if path:
            try:
                elem = DraggableElement(self.canvas, 100, 100, 'image', path, width=150, height=150)
                elem.page_num = self.current_page
                self.elements.append(elem)
                self.canvas.elements.append(elem)
                elem.select()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo cargar la imagen:\n{str(e)}")

    def add_date_element(self):
        if not self.pdf_document:
            messagebox.showwarning("Advertencia", "Por favor carga un PDF primero")
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Agregar Fecha")
        dialog.geometry("500x520")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Centrar
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (dialog.winfo_screenheight() // 2) - (520 // 2)
        dialog.geometry(f'500x520+{x}+{y}')
        
        # Título
        ttk.Label(dialog, text="Selecciona la fecha:", font=('Arial', 12, 'bold')).pack(pady=12)
        
        # Frame para el calendario
        cal_frame = ttk.Frame(dialog)
        cal_frame.pack(padx=25, pady=8)
        
        # Calendario
        cal = Calendar(cal_frame, selectmode='day', date_pattern='yyyy-mm-dd',
                      font=('Arial', 10), selectbackground='#0078d7',
                      background='white', foreground='black',
                      borderwidth=2, showweeknumbers=False)
        cal.pack()
        
        # Separador
        ttk.Separator(dialog, orient='horizontal').pack(fill='x', padx=25, pady=18)
        
        # Frame para formato
        format_frame = ttk.Frame(dialog)
        format_frame.pack(padx=25, pady=8, fill='x')
        
        ttk.Label(format_frame, text="Formato:", font=('Arial', 11)).pack(anchor='w', pady=(0, 8))
        
        # Formatos disponibles
        date_formats = {
            "dd/mm/yyyy": "%d/%m/%Y",
            "mm/dd/yyyy": "%m/%d/%Y",
            "yyyy-mm-dd": "%Y-%m-%d",
            "dd-mm-yyyy": "%d-%m-%Y",
            "dd de Mes de yyyy": "%d de %B de %Y",
            "Día, dd de Mes de yyyy": "%A, %d de %B de %Y",
            "dd/mm/yy": "%d/%m/%y",
            "Mes dd, yyyy": "%B %d, %Y",
            "dd.mm.yyyy": "%d.%m.%Y",
            "yyyy/mm/dd": "%Y/%m/%d"
        }
        
        format_var = tk.StringVar(value="dd/mm/yyyy")
        format_combo = ttk.Combobox(format_frame, textvariable=format_var, 
                                   values=list(date_formats.keys()), 
                                   state='readonly', width=35, font=('Arial', 10))
        format_combo.pack(fill='x')
        
        # Vista previa
        preview_frame = ttk.LabelFrame(dialog, text="Vista previa")
        preview_frame.pack(padx=25, pady=18, fill='x')
        
        preview_label = ttk.Label(preview_frame, text="", font=('Arial', 12, 'bold'), foreground='#0078d7')
        preview_label.pack(pady=12, padx=12)
        
        def update_preview(event=None):
            try:
                selected_date = cal.get_date()
                date_obj = datetime.datetime.strptime(selected_date, '%Y-%m-%d')
                format_key = format_var.get()
                format_string = date_formats[format_key]
                formatted_date = date_obj.strftime(format_string)
                preview_label.config(text=formatted_date)
            except:
                preview_label.config(text="Error en formato")
        
        # Actualizar vista previa al cambiar fecha o formato
        cal.bind("<<CalendarSelected>>", update_preview)
        format_combo.bind("<<ComboboxSelected>>", update_preview)
        
        # Mostrar vista previa inicial
        update_preview()
        
        def create():
            try:
                selected_date = cal.get_date()
                date_obj = datetime.datetime.strptime(selected_date, '%Y-%m-%d')
                format_key = format_var.get()
                format_string = date_formats[format_key]
                date_text = date_obj.strftime(format_string)
                
                try:
                    font_size = int(self.font_size_var.get())
                except ValueError:
                    font_size = 12
                
                elem = DraggableElement(self.canvas, 100, 100, 'text', date_text,
                                      font_size=font_size,
                                      font_family=self.font_family_var.get(),
                                      color=self.current_color)
                elem.page_num = self.current_page
                self.elements.append(elem)
                self.canvas.elements.append(elem)
                elem.select()
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Error al crear fecha: {str(e)}")
        
        # Botones
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="✓ Aceptar", command=create, width=15).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_frame, text="✗ Cancelar", command=dialog.destroy, width=15).pack(side=tk.LEFT, padx=8)

    def choose_color(self):
        color = colorchooser.askcolor(initialcolor=self.current_color, title="Elegir color de texto")
        if color[1]:
            self.current_color = color[1]
            self.color_indicator.config(bg=self.current_color)
            if hasattr(self.canvas, 'master_element') and self.canvas.master_element.element_type == 'text':
                elem = self.canvas.master_element
                elem.color = color[1]
                elem.update_visual()

    def update_font_size(self, val=None):
        if hasattr(self.canvas, 'master_element') and self.canvas.master_element.element_type == 'text':
            try:
                elem = self.canvas.master_element
                elem.font_size = int(self.font_size_var.get())
                elem.original_font_size = int(self.font_size_var.get())
                elem.update_visual()
                elem.update_selection()
            except ValueError:
                pass

    def update_font_family(self, *args):
        if hasattr(self.canvas, 'master_element') and self.canvas.master_element.element_type == 'text':
            elem = self.canvas.master_element
            elem.font_family = self.font_family_var.get()
            elem.update_visual()
            elem.update_selection()

    def delete_selected(self):
        to_remove = [e for e in self.elements if e.selected]
        if not to_remove:
            messagebox.showinfo("Info", "No hay elementos seleccionados para eliminar")
            return
        for e in to_remove:
            e.delete()
            self.elements.remove(e)
            if e in self.canvas.elements:
                self.canvas.elements.remove(e)

    def zoom_in(self): 
        self.zoom_level = min(3.0, self.zoom_level + 0.2)
        self.render_page()
        
    def zoom_out(self): 
        self.zoom_level = max(0.5, self.zoom_level - 0.2)
        self.render_page()
    
    def zoom_reset(self):
        self.zoom_level = 1.0
        self.render_page()
    
    def first_page(self):
        if not self.pdf_document:
            return
        if self.current_page > 0:
            self.current_page = 0
            self.render_page()
    
    def last_page(self):
        if not self.pdf_document:
            return
        if self.current_page < self.total_pages - 1:
            self.current_page = self.total_pages - 1
            self.render_page()
        
    def prev_page(self):
        if not self.pdf_document:
            return
        if self.current_page > 0:
            self.current_page -= 1
            self.render_page()

    def next_page(self):
        if not self.pdf_document:
            return
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.render_page()

    def save_pdf(self):
        if not self.pdf_document:
            messagebox.showwarning("Advertencia", "No hay ningún PDF cargado")
            return
        if not self.elements:
            result = messagebox.askyesno("Confirmar", 
                "No hay elementos añadidos al PDF.\n¿Desea guardar el PDF original sin cambios?")
            if not result:
                return
            
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            title="Guardar PDF firmado"
        )
        if not path:
            return
            
        try:
            reader = PdfReader(self.pdf_path)
            writer = PdfWriter()
            
            for i in range(len(reader.pages)):
                page = reader.pages[i]
                pw = float(page.mediabox.width)
                ph = float(page.mediabox.height)
                
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=(pw, ph))
                
                # Procesar elementos de esta página
                page_elements = [e for e in self.elements if getattr(e, 'page_num', -1) == i]
                
                for elem in page_elements:
                    # Usar las coordenadas reales del elemento (sin el offset de visualización)
                    # Convertir coordenadas del canvas al sistema de coordenadas del PDF
                    x = elem.x / self.zoom_level
                    y = ph - (elem.y / self.zoom_level)
                    
                    if elem.element_type == 'text':
                        # Mapear nombres de fuentes a los nombres válidos de ReportLab
                        font_mapping = {
                            'Arial': 'Helvetica',
                            'Helvetica': 'Helvetica',
                            'Times': 'Times-Roman',
                            'Courier': 'Courier'
                        }
                        font_name = font_mapping.get(elem.font_family, 'Helvetica')
                        
                        try:
                            can.setFont(font_name, elem.font_size / self.zoom_level)
                            r, g, b = [int(elem.color[j:j+2], 16)/255 for j in (1, 3, 5)]
                            can.setFillColorRGB(r, g, b)
                            can.drawString(x, y, elem.content)
                        except Exception as e:
                            print(f"Error al agregar texto: {e}")
                            # Usar fuente por defecto si falla
                            can.setFont('Helvetica', 12)
                            can.drawString(x, y, elem.content)
                    else:
                        try:
                            if isinstance(elem.content, str):
                                img = ImageReader(elem.content)
                            else:
                                buf = io.BytesIO()
                                elem.content.save(buf, format='PNG')
                                buf.seek(0)
                                img = ImageReader(buf)
                            w = elem.width / self.zoom_level
                            h = elem.height / self.zoom_level
                            can.drawImage(img, x, y - h, width=w, height=h, preserveAspectRatio=True)
                        except Exception as e:
                            print(f"Error al agregar imagen: {e}")
                
                can.save()
                packet.seek(0)
                overlay = PdfReader(packet)
                if overlay.pages:
                    page.merge_page(overlay.pages[0])
                writer.add_page(page)
            
            with open(path, 'wb') as f:
                writer.write(f)
            
            messagebox.showinfo("Éxito", f"PDF guardado correctamente en:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar el PDF:\n{str(e)}")


def main():
    root = tk.Tk()
    app = PDFSignerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()