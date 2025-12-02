import os
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageFilter, ImageTk
import tkinter.font as tkFont
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import subprocess
import platform

# Para habilitar el Drag & Drop
from tkinterdnd2 import TkinterDnD, DND_FILES

# ==========MECANISMOS DE SINCRONIZACIÓN ==========
class SharedCounter:
    """Contador compartido con protección por Lock (Mutex)"""
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()
    
    def increment(self):
        with self._lock:
            self._value += 1
            return self._value
    
    def get_value(self):
        with self._lock:
            return self._value

class ProcessingSemaphore: #Semaforos
    """Semáforo para limitar procesamiento concurrente"""
    def __init__(self, max_concurrent):
        self.semaphore = threading.Semaphore(max_concurrent)
        self.active_processes = 0
        self._lock = threading.Lock()
    
    def acquire(self):
        self.semaphore.acquire()
        with self._lock:
            self.active_processes += 1
    
    def release(self):
        with self._lock:
            self.active_processes -= 1
        self.semaphore.release()
    
    def get_active(self):
        with self._lock:
            return self.active_processes

# ========== MODELO ACTOR (PATRÓN ACTOR) ==========
class ProcessingActor:
    """Actor simple para procesamiento de tareas"""
    def __init__(self, result_queue):
        self.task_queue = queue.Queue()
        self.result_queue = result_queue
        self._running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def _run(self):
        while self._running:
            try:
                task = self.task_queue.get(timeout=1)
                result = process_image(task)
                self.result_queue.put(result)
            except queue.Empty:
                continue
    
    def submit(self, task):
        self.task_queue.put(task)
    
    def stop(self):
        self._running = False

# ========== VERSIÓN SECUENCIAL ==========
def process_image_sequential(image_paths, selected_filter, output_folder):
    """Procesamiento secuencial para comparación"""
    results = []
    start_time = time.time()
    
    for image_path in image_paths:
        result = process_image((image_path, selected_filter, output_folder, "secuencial"))
        results.append(result)
    
    elapsed_time = time.time() - start_time
    return results, elapsed_time

# ========== VERSIÓN CON MODELO ACTOR ==========
def process_image_actor(image_paths, selected_filter, output_folder, num_actors=4):
    """Procesamiento usando modelo Actor"""
    results = []
    result_queue = queue.Queue()
    actors = []
    
    # Crear actores
    for _ in range(num_actors):
        actor = ProcessingActor(result_queue)
        actors.append(actor)
    
    start_time = time.time()
    
    # Distribuir tareas entre actores (round-robin)
    for i, image_path in enumerate(image_paths):
        task = (image_path, selected_filter, output_folder, "actor")
        actors[i % num_actors].submit(task)
    
    # Recoger resultados
    for _ in range(len(image_paths)):
        result = result_queue.get()
        results.append(result)
    
    # Detener actores
    for actor in actors:
        actor.stop()
    
    elapsed_time = time.time() - start_time
    return results, elapsed_time

##==============================APLICACIÓN PRINCIPAL==============================##
def process_image(args):
    """
    Procesa una imagen aplicándole el filtro seleccionado.
    Recibe:
       args: tupla (ruta_imagen, filtro_seleccionado, carpeta_salida, metodo)
    """
    image_path, selected_filter, output_folder, method = args
    try:
        # Simular tiempo de procesamiento variable
        time.sleep(0.1)  # Simula carga de trabajo
        
        img = Image.open(image_path).convert("RGB")
        if selected_filter == "Desenfoque":
            img = img.filter(ImageFilter.BLUR)
        elif selected_filter == "Grises":
            img = img.convert('L')
        elif selected_filter == "Contorno":
            img = img.filter(ImageFilter.CONTOUR)
        elif selected_filter == "Emboss":
            img = img.filter(ImageFilter.EMBOSS)
        elif selected_filter == "Sharpen":
            img = img.filter(ImageFilter.SHARPEN)
        elif selected_filter == "Detalles":
            img = img.filter(ImageFilter.DETAIL)
        elif selected_filter == "Bordes":
            img = img.filter(ImageFilter.FIND_EDGES)
        
        base = os.path.basename(image_path)
        name, ext = os.path.splitext(base)
        # Formato: nombre_original_metodo.extension
        output_filename = f"{name}_{method}{ext}"
        output_path = os.path.join(output_folder, output_filename)
        img.save(output_path)
        
        return {
            "status": "OK", 
            "original": image_path, 
            "output": output_path, 
            "message": f"Procesado: {base} ({method})", 
            "filter": selected_filter,
            "method": method
        }
    except Exception as e:
        return {
            "status": "ERROR", 
            "original": image_path, 
            "message": f"Error en {os.path.basename(image_path)}: {str(e)}",
            "method": method
        }

def open_folder(path):
    """Abre la carpeta en el explorador de archivos del sistema"""
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", path])
        else:  # Linux
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print(f"Error al abrir carpeta: {e}")

class PhotoFilterApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Aplicador de Filtros - Comparación Secuencial vs Paralelo")
        self.geometry("1200x800")
        self.configure(bg="#2C3E50")
        
        # Lista de imágenes cargadas
        self.image_paths = []
        
        # Resultados de procesamiento
        self.sequential_results = []  # Resultados de la versión secuencial
        self.parallel_results = []    # Resultados de la versión paralela
        self.all_results = []         # Todos los resultados para abrir carpeta
        
        # Contadores compartidos con protección
        self.processed_counter = SharedCounter()
        self.error_counter = SharedCounter()
        
        # Semáforo para limitar procesamiento concurrente
        self.semaphore = ProcessingSemaphore(max_concurrent=4)
        
        # Carpeta de salida predeterminada
        self.output_folder = os.path.join(os.getcwd(), "output")
        os.makedirs(self.output_folder, exist_ok=True)
        
        # Executor para multihilo
        self.thread_executor = ThreadPoolExecutor(max_workers=4)
        
        # Métricas de desempeño
        self.metrics = {
            "Secuencial": [],
            "Multihilo": [],
            "Modelo Actor": []
        }
        
        # Tiempos de ejecución
        self.execution_times = {
            "Secuencial": 0,
            "Paralelo": 0
        }
        
        self.zoom_level = 300
        self.currently_processing = False
        self.init_styles()
        self.create_widgets()
        
    def init_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#2C3E50")
        style.configure("TLabel", background="#2C3E50", foreground="#ECF0F1", font=("Helvetica", 11))
        style.configure("TButton", font=("Helvetica", 11, "bold"), foreground="white")
        style.map("TButton", background=[("active", "#2980B9")])
        style.configure("TProgressbar", background="#27AE60")
        self.header_font = tkFont.Font(family="Helvetica", size=20, weight="bold")
        self.default_font = tkFont.Font(family="Helvetica", size=11)
    
    def create_widgets(self):
        # Cabecera
        header_frame = ttk.Frame(self)
        header_frame.pack(fill=tk.X, padx=20, pady=(20, 10))
        header_label = ttk.Label(header_frame, text="Comparador: Secuencial vs Paralelo", font=self.header_font)
        header_label.pack()
        
        # Panel superior: controles y botones
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=20, pady=10)
        
        # Botones de estrategia de procesamiento (solo paralelo)
        strategies_frame = ttk.LabelFrame(top_frame, text="Estrategia Paralela")
        strategies_frame.pack(side=tk.LEFT, padx=5)
        
        self.strategy_var = tk.StringVar(value="multithread")
        ttk.Radiobutton(strategies_frame, text="Multihilo", variable=self.strategy_var,
                       value="multithread").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(strategies_frame, text="Modelo Actor", variable=self.strategy_var,
                       value="actor").pack(side=tk.LEFT, padx=5)
        
        # Controles principales
        controls_frame = ttk.Frame(top_frame)
        controls_frame.pack(side=tk.LEFT, padx=20)
        
        output_btn = ttk.Button(controls_frame, text="Carpeta de salida", 
                               command=self.select_output_folder)
        output_btn.pack(side=tk.LEFT, padx=5)
        self.output_label = ttk.Label(controls_frame, text=f"Salida: {os.path.basename(self.output_folder)}")
        self.output_label.pack(side=tk.LEFT, padx=5)
        
        load_btn = ttk.Button(controls_frame, text="Cargar fotos", command=self.load_images)
        load_btn.pack(side=tk.LEFT, padx=5)
        
        clear_btn = ttk.Button(controls_frame, text="Limpiar lista", command=self.clear_list)
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        self.filter_var = tk.StringVar(value="Desenfoque")
        filter_options = ["Desenfoque", "Grises", "Contorno", "Emboss", "Sharpen", "Detalles", "Bordes"]
        filter_menu = ttk.OptionMenu(controls_frame, self.filter_var, filter_options[0], *filter_options)
        filter_menu.pack(side=tk.LEFT, padx=5)
        
        process_btn = ttk.Button(controls_frame, text="Aplicar filtro (Comparar)", 
                                command=self.start_processing)
        process_btn.pack(side=tk.LEFT, padx=5)
        
        # Botón para abrir carpeta de resultados
        open_folder_btn = ttk.Button(controls_frame, text="Abrir carpeta de resultados", 
                                    command=self.open_results_folder)
        open_folder_btn.pack(side=tk.LEFT, padx=5)
        
        # Panel principal
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Panel izquierdo: lista y controles
        left_panel = ttk.Frame(main_frame)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,10))
        
        # Panel de métricas en tiempo real
        metrics_frame = ttk.LabelFrame(left_panel, text="Métricas de Ejecución")
        metrics_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.metrics_labels = {}
        metrics_grid = ttk.Frame(metrics_frame)
        metrics_grid.pack(fill=tk.X, padx=5, pady=5)
        
        # Métricas de tiempo y comparación
        time_labels = ["Secuencial (s)", "Paralelo (s)", "Speedup", "Eficiencia"]
        for i, name in enumerate(time_labels):
            ttk.Label(metrics_grid, text=name + ":").grid(row=0, column=i*2, padx=5, sticky="w")
            label = ttk.Label(metrics_grid, text="0.00", foreground="#27AE60", font=("Helvetica", 11, "bold"))
            label.grid(row=0, column=i*2+1, padx=(0,10), sticky="w")
            self.metrics_labels[name.lower().split()[0]] = label
        
        # Estado actual
        status_frame = ttk.Frame(metrics_frame)
        status_frame.pack(fill=tk.X, padx=5, pady=(5,0))
        ttk.Label(status_frame, text="Estado:").pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(status_frame, text="Listo", foreground="#2ECC71", font=("Helvetica", 11, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=5)
        
        # Lista de imágenes
        list_frame = ttk.LabelFrame(left_panel, text="Imágenes Cargadas")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        instruction_label = ttk.Label(list_frame, text="Arrastra y suelta fotos aquí", font=self.default_font)
        instruction_label.pack(padx=5, pady=5)
        
        self.listbox = tk.Listbox(list_frame, selectmode=tk.SINGLE, font=self.default_font,
                                  bg="#34495E", fg="white", relief=tk.FLAT)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.listbox.drop_target_register(DND_FILES)
        self.listbox.dnd_bind('<<Drop>>', self.drop_event)
        self.listbox.bind("<<ListboxSelect>>", self.update_preview)
        
        # Log y progreso
        log_frame = ttk.LabelFrame(left_panel, text="Progreso del Procesamiento")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.log = tk.Text(log_frame, height=8, font=("Consolas", 9), 
                          bg="#34495E", fg="white", relief=tk.FLAT)
        self.log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Barra de progreso general
        self.progress_frame = ttk.Frame(log_frame)
        self.progress_frame.pack(fill=tk.X, padx=5, pady=(5,0))
        self.progress_label = ttk.Label(self.progress_frame, text="Progreso:")
        self.progress_label.pack(side=tk.LEFT, padx=5)
        self.progress_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Panel derecho: vista previa y gráficos
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0))
        
        # Notebook con pestañas
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Pestaña de vista previa (solo original)
        preview_frame = ttk.Frame(self.notebook)
        self.notebook.add(preview_frame, text="Vista Previa")
        
        # Solo vista original
        preview_container = ttk.Frame(preview_frame)
        preview_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        orig_frame = ttk.LabelFrame(preview_container, text="Imagen Original")
        orig_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.orig_preview_label = ttk.Label(orig_frame, text="Selecciona una imagen para previsualizar")
        self.orig_preview_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Información del archivo
        info_frame = ttk.Frame(preview_frame)
        info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.file_info_label = ttk.Label(info_frame, text="Sin imagen seleccionada", font=("Helvetica", 10))
        self.file_info_label.pack()
        
        # Controles de zoom
        zoom_frame = ttk.Frame(preview_frame)
        zoom_frame.pack(fill=tk.X, padx=5, pady=5)
        zoom_label = ttk.Label(zoom_frame, text="Zoom:")
        zoom_label.pack(side=tk.LEFT, padx=5)
        self.zoom_slider = ttk.Scale(zoom_frame, from_=100, to=600, orient="horizontal", 
                                    command=self.adjust_zoom)
        self.zoom_slider.set(self.zoom_level)
        self.zoom_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Pestaña de gráficos de comparación
        graph_frame = ttk.Frame(self.notebook)
        self.notebook.add(graph_frame, text="Comparación de Tiempos")
        
        self.figure, self.ax = plt.subplots(figsize=(8, 4))
        self.figure.patch.set_facecolor('#2C3E50')
        self.ax.set_facecolor('#34495E')
        self.canvas = FigureCanvasTkAgg(self.figure, graph_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    def clear_list(self):
        self.image_paths.clear()
        self.sequential_results.clear()
        self.parallel_results.clear()
        self.all_results.clear()
        self.listbox.delete(0, tk.END)
        self.log.delete("1.0", tk.END)
        self.orig_preview_label.config(image="", text="Selecciona una imagen para previsualizar")
        self.file_info_label.config(text="Sin imagen seleccionada")
        self.update_metrics()
        self.status_label.config(text="Listo", foreground="#2ECC71")
    
    def load_images(self):
        paths = filedialog.askopenfilenames(title="Selecciona fotos", 
                                           filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.bmp *.gif")])
        if paths:
            for path in paths:
                if path not in self.image_paths:
                    self.image_paths.append(path)
                    self.listbox.insert(tk.END, os.path.basename(path))
    
    def drop_event(self, event):
        files = self.tk.splitlist(event.data)
        for file in files:
            if file.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                if file not in self.image_paths:
                    self.image_paths.append(file)
                    self.listbox.insert(tk.END, os.path.basename(file))
    
    def select_output_folder(self):
        folder = filedialog.askdirectory(title="Selecciona la carpeta de salida")
        if folder:
            self.output_folder = folder
            os.makedirs(self.output_folder, exist_ok=True)
            self.output_label.config(text=f"Salida: {os.path.basename(self.output_folder)}")
    
    def open_results_folder(self):
        """Abre la carpeta con las imágenes procesadas"""
        if os.path.exists(self.output_folder) and self.all_results:
            open_folder(self.output_folder)
        else:
            messagebox.showinfo("Información", "No hay imágenes procesadas aún o la carpeta no existe.")
    
    def update_preview(self, event=None):
        try:
            selection = self.listbox.curselection()
            if selection:
                index = selection[0]
                if index < len(self.image_paths):
                    image_path = self.image_paths[index]
                    
                    # Vista original
                    img = Image.open(image_path)
                    img.thumbnail((self.zoom_level, self.zoom_level))
                    self.orig_preview_image = ImageTk.PhotoImage(img)
                    self.orig_preview_label.config(image=self.orig_preview_image, text="")
                    
                    # Información del archivo
                    file_size = os.path.getsize(image_path) / 1024  # KB
                    file_info = f"{os.path.basename(image_path)} | {img.size[0]}x{img.size[1]} | {file_size:.1f} KB"
                    self.file_info_label.config(text=file_info)
                    
        except Exception as e:
            self.orig_preview_label.config(image="", text="Error al cargar imagen")
            self.file_info_label.config(text=f"Error: {str(e)}")
    
    def adjust_zoom(self, event):
        try:
            self.zoom_level = int(float(event))
            self.update_preview()
        except Exception as e:
            self.log_message(f"Error ajustando zoom: {str(e)}")
    
    def log_message(self, message):
        self.log.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        self.log.see(tk.END)
    
    def update_metrics(self):
        # Actualizar tiempos de ejecución
        if self.execution_times["Secuencial"] > 0:
            self.metrics_labels["secuencial"].config(text=f"{self.execution_times['Secuencial']:.2f}")
        if self.execution_times["Paralelo"] > 0:
            self.metrics_labels["paralelo"].config(text=f"{self.execution_times['Paralelo']:.2f}")
            
            # Calcular speedup y eficiencia
            if self.execution_times["Paralelo"] > 0:
                speedup = self.execution_times["Secuencial"] / self.execution_times["Paralelo"]
                self.metrics_labels["speedup"].config(text=f"{speedup:.2f}x")
                
                # Eficiencia (speedup / número de workers * 100)
                efficiency = (speedup / 4) * 100  # 4 workers
                self.metrics_labels["eficiencia"].config(text=f"{efficiency:.1f}%")
    
    def start_processing(self):
        """Inicia el procesamiento secuencial -> paralelo"""
        if not self.image_paths:
            messagebox.showwarning("Advertencia", "No hay fotos cargadas.")
            return
        
        if self.currently_processing:
            messagebox.showwarning("Advertencia", "Ya hay un procesamiento en curso.")
            return
        
        self.currently_processing = True
        self.status_label.config(text="Procesando...", foreground="#F39C12")
        
        selected_filter = self.filter_var.get()
        parallel_strategy = self.strategy_var.get()
        
        # Reiniciar resultados
        self.sequential_results.clear()
        self.parallel_results.clear()
        self.all_results.clear()
        self.execution_times = {"Secuencial": 0, "Paralelo": 0}
        
        # Configurar barra de progreso
        total_images = len(self.image_paths)
        self.progress_bar["value"] = 0
        self.progress_bar["maximum"] = total_images * 2  # Secuencial + Paralelo
        
        self.log.delete("1.0", tk.END)
        self.log_message("Iniciando comparación: Secuencial vs Paralelo...")
        self.log_message(f"Filtro seleccionado: {selected_filter}")
        self.log_message(f"Estrategia paralela: {'Multihilo' if parallel_strategy == 'multithread' else 'Modelo Actor'}")
        
        # Iniciar procesamiento secuencial primero
        threading.Thread(target=self.run_sequential_then_parallel, 
                        args=(selected_filter, parallel_strategy), daemon=True).start()
    
    def run_sequential_then_parallel(self, selected_filter, parallel_strategy):
        """Ejecuta secuencial, luego paralelo"""
        # 1. Ejecutar versión secuencial
        self.after(0, self.log_message, "\n=== EJECUTANDO VERSIÓN SECUENCIAL ===")
        self.after(0, self.update_status, "Procesando (Secuencial)...")
        
        start_time = time.time()
        results, elapsed = process_image_sequential(
            self.image_paths, 
            selected_filter, 
            self.output_folder
        )
        
        self.sequential_results = results
        self.execution_times["Secuencial"] = elapsed
        self.all_results.extend(results)
        
        # Actualizar progreso
        for _ in results:
            self.after(0, self.update_progress)
        
        self.after(0, self.log_message, f"✓ Secuencial completado en {elapsed:.2f} segundos")
        self.after(0, self.log_message, f"   - Imágenes procesadas: {len(results)}")
        
        # Pequeña pausa entre procesos
        time.sleep(0.5)
        
        # 2. Ejecutar versión paralela
        self.after(0, self.log_message, "\n=== EJECUTANDO VERSIÓN PARALELA ===")
        self.after(0, self.update_status, "Procesando (Paralelo)...")
        
        if parallel_strategy == "multithread":
            results, elapsed = self.run_multithread_version(selected_filter)
        else:  # actor
            results, elapsed = self.run_actor_version(selected_filter)
        
        self.parallel_results = results
        self.execution_times["Paralelo"] = elapsed
        self.all_results.extend(results)
        
        # Actualizar progreso
        for _ in results:
            self.after(0, self.update_progress)
        
        self.after(0, self.log_message, f"✓ Paralelo completado en {elapsed:.2f} segundos")
        self.after(0, self.log_message, f"   - Imágenes procesadas: {len(results)}")
        
        # Finalizar
        self.after(0, self.finish_processing, parallel_strategy)
    
    def update_status(self, status):
        self.status_label.config(text=status)
    
    def update_progress(self):
        self.progress_bar["value"] += 1
    
    def run_multithread_version(self, selected_filter):
        """Ejecuta la versión multihilo"""
        tasks = [(path, selected_filter, self.output_folder, "multihilo") for path in self.image_paths]
        start_time = time.time()
        results = []
        
        def process_with_semaphore(task):
            self.semaphore.acquire()
            try:
                result = process_image(task)
                return result
            finally:
                self.semaphore.release()
        
        futures = [self.thread_executor.submit(process_with_semaphore, task) for task in tasks]
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
        
        elapsed = time.time() - start_time
        self.metrics["Multihilo"].append(elapsed)
        return results, elapsed
    
    def run_actor_version(self, selected_filter):
        """Ejecuta la versión con modelo Actor"""
        start_time = time.time()
        results, elapsed = process_image_actor(
            self.image_paths,
            selected_filter,
            self.output_folder,
            num_actors=4
        )
        self.metrics["Modelo Actor"].append(elapsed)
        return results, elapsed
    
    def finish_processing(self, parallel_strategy):
        """Finaliza el procesamiento y muestra resultados"""
        self.currently_processing = False
        self.status_label.config(text="Completado", foreground="#2ECC71")
        
        # Mostrar resumen
        self.after(0, self.log_message, "\n=== RESUMEN FINAL ===")
        self.after(0, self.log_message, f"Tiempo secuencial: {self.execution_times['Secuencial']:.2f}s")
        self.after(0, self.log_message, f"Tiempo paralelo: {self.execution_times['Paralelo']:.2f}s")
        
        if self.execution_times["Paralelo"] > 0:
            speedup = self.execution_times["Secuencial"] / self.execution_times["Paralelo"]
            self.after(0, self.log_message, f"Speedup: {speedup:.2f}x más rápido")
            
            efficiency = (speedup / 4) * 100
            self.after(0, self.log_message, f"Eficiencia paralela: {efficiency:.1f}%")
        
        self.after(0, self.log_message, f"\nImágenes procesadas: {len(self.all_results)}")
        self.after(0, self.log_message, f"Carpeta de resultados: {self.output_folder}")
        self.after(0, self.log_message, "Puedes abrir la carpeta de resultados para ver las imágenes.")
        
        # Actualizar métricas y gráfico
        self.after(0, self.update_metrics)
        self.after(0, self.update_comparison_chart, parallel_strategy)
        
        # Mostrar mensaje final
        self.after(0, lambda: messagebox.showinfo(
            "Procesamiento Completado", 
            f"Comparación finalizada.\n\n"
            f"Secuencial: {self.execution_times['Secuencial']:.2f}s\n"
            f"Paralelo ({'Multihilo' if parallel_strategy == 'multithread' else 'Modelo Actor'}): {self.execution_times['Paralelo']:.2f}s\n"
            f"Speedup: {(self.execution_times['Secuencial'] / self.execution_times['Paralelo']):.2f}x\n\n"
            f"Las imágenes procesadas están en:\n{self.output_folder}"
        ))
    
    def update_comparison_chart(self, parallel_strategy_name):
        """Actualiza el gráfico de comparación"""
        self.ax.clear()
        
        # Preparar datos para el gráfico
        strategies = ["Secuencial", "Paralelo"]
        times = [self.execution_times["Secuencial"], self.execution_times["Paralelo"]]
        
        colors = ['#E74C3C', '#3498DB']  # Rojo para secuencial, azul para paralelo
        
        bars = self.ax.bar(strategies, times, color=colors)
        
        # Personalizar etiqueta del eje X
        parallel_label = "Multihilo" if self.strategy_var.get() == "multithread" else "Modelo Actor"
        strategies[1] = parallel_label
        
        self.ax.set_xticks(range(len(strategies)))
        self.ax.set_xticklabels(strategies)
        
        self.ax.set_title('Comparación: Tiempo de Ejecución', color='white', fontsize=14)
        self.ax.set_ylabel('Tiempo (segundos)', color='white')
        self.ax.tick_params(axis='x', colors='white')
        self.ax.tick_params(axis='y', colors='white')
        
        # Agregar valores encima de las barras
        for bar, time_val in zip(bars, times):
            height = bar.get_height()
            self.ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{time_val:.2f}s', ha='center', va='bottom', color='white', fontweight='bold')
        
        # Agregar línea de speedup
        if times[1] > 0:
            speedup = times[0] / times[1]
            self.ax.text(0.5, 0.95, f'Speedup: {speedup:.2f}x', 
                       transform=self.ax.transAxes, ha='center', color='#2ECC71',
                       fontsize=12, fontweight='bold')
            
            # Agregar texto de eficiencia
            efficiency = (speedup / 4) * 100
            self.ax.text(0.5, 0.90, f'Eficiencia: {efficiency:.1f}%', 
                       transform=self.ax.transAxes, ha='center', color='#F39C12',
                       fontsize=11)
        
        self.ax.grid(True, alpha=0.3, linestyle='--')
        self.canvas.draw()

if __name__ == "__main__":
    app = PhotoFilterApp()
    app.mainloop()