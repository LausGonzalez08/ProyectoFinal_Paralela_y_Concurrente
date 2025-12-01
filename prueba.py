import os
import threading
import queue
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageFilter, ImageTk
import tkinter.font as tkFont
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Para habilitar el Drag & Drop
from tkinterdnd2 import TkinterDnD, DND_FILES

# ========== NUEVOS MECANISMOS DE SINCRONIZACIÓN ==========
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

class ProcessingSemaphore:
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
        result = process_image((image_path, selected_filter, output_folder))
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
        task = (image_path, selected_filter, output_folder)
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

def process_image(args):
    """
    Procesa una imagen aplicándole el filtro seleccionado.
    Recibe:
       args: tupla (ruta_imagen, filtro_seleccionado, carpeta_salida)
    """
    image_path, selected_filter, output_folder = args
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
        output_filename = f"{name}_{selected_filter.lower()}{ext}"
        output_path = os.path.join(output_folder, output_filename)
        img.save(output_path)
        
        return {"status": "OK", "original": image_path, "output": output_path, 
                "message": f"Procesado: {base}", "filter": selected_filter}
    except Exception as e:
        return {"status": "ERROR", "original": image_path, 
                "message": f"Error en {os.path.basename(image_path)}: {str(e)}"}

class PhotoFilterApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Aplicador de Filtros a Fotos - Versión Avanzada")
        self.geometry("1200x800")
        self.configure(bg="#2C3E50")
        
        # Lista de imágenes cargadas y diccionario para imágenes procesadas
        self.image_paths = []
        self.processed_paths = {}  # Mapea ruta original --> ruta de imagen filtrada
        
        # Contadores compartidos con protección
        self.processed_counter = SharedCounter()
        self.error_counter = SharedCounter()
        
        # Semáforo para limitar procesamiento concurrente
        self.semaphore = ProcessingSemaphore(max_concurrent=4)
        
        # Carpeta de salida predeterminada
        self.output_folder = os.path.join(os.getcwd(), "output")
        os.makedirs(self.output_folder, exist_ok=True)
        
        # Executors para diferentes estrategias
        self.process_executor = ProcessPoolExecutor(max_workers=4)
        self.thread_executor = ThreadPoolExecutor(max_workers=4)
        
        # Métricas de desempeño
        self.metrics = {
            "sequential": [],
            "parallel_process": [],
            "parallel_thread": [],
            "actor_model": []
        }
        
        self.zoom_level = 300
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
        header_label = ttk.Label(header_frame, text="Aplicador de Filtros Avanzado", font=self.header_font)
        header_label.pack()
        
        # Panel superior: controles y botones
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=20, pady=10)
        
        # Botones de estrategia de procesamiento
        strategies_frame = ttk.LabelFrame(top_frame, text="Estrategia de Procesamiento")
        strategies_frame.pack(side=tk.LEFT, padx=5)
        
        self.strategy_var = tk.StringVar(value="multiprocess")
        ttk.Radiobutton(strategies_frame, text="Multiproceso", variable=self.strategy_var, 
                       value="multiprocess").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(strategies_frame, text="Multihilo", variable=self.strategy_var,
                       value="multithread").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(strategies_frame, text="Modelo Actor", variable=self.strategy_var,
                       value="actor").pack(side=tk.LEFT, padx=5)
        
        # Comparar estrategias
        compare_btn = ttk.Button(strategies_frame, text="Comparar Estrategias", 
                                command=self.compare_strategies)
        compare_btn.pack(side=tk.LEFT, padx=5)
        
        # Controles principales
        controls_frame = ttk.Frame(top_frame)
        controls_frame.pack(side=tk.LEFT, padx=20)
        
        output_btn = ttk.Button(controls_frame, text="Carpeta de salida", 
                               command=self.select_output_folder)
        output_btn.pack(side=tk.LEFT, padx=5)
        self.output_label = ttk.Label(controls_frame, text=f"Salida: {self.output_folder}")
        self.output_label.pack(side=tk.LEFT, padx=5)
        
        load_btn = ttk.Button(controls_frame, text="Cargar fotos", command=self.load_images)
        load_btn.pack(side=tk.LEFT, padx=5)
        
        clear_btn = ttk.Button(controls_frame, text="Limpiar lista", command=self.clear_list)
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        self.filter_var = tk.StringVar(value="Desenfoque")
        filter_options = ["Desenfoque", "Grises", "Contorno", "Emboss", "Sharpen", "Detalles", "Bordes"]
        filter_menu = ttk.OptionMenu(controls_frame, self.filter_var, filter_options[0], *filter_options)
        filter_menu.pack(side=tk.LEFT, padx=5)
        
        process_btn = ttk.Button(controls_frame, text="Aplicar filtro", command=self.apply_filter)
        process_btn.pack(side=tk.LEFT, padx=5)
        
        # Panel principal
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Panel izquierdo: lista y controles
        left_panel = ttk.Frame(main_frame)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,10))
        
        # Panel de métricas en tiempo real
        metrics_frame = ttk.LabelFrame(left_panel, text="Métricas en Tiempo Real")
        metrics_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.metrics_labels = {}
        metrics_grid = ttk.Frame(metrics_frame)
        metrics_grid.pack(fill=tk.X, padx=5, pady=5)
        
        metric_names = ["Procesadas", "Errores", "Activos", "Tiempo (s)"]
        for i, name in enumerate(metric_names):
            ttk.Label(metrics_grid, text=name + ":").grid(row=0, column=i*2, padx=5, sticky="w")
            label = ttk.Label(metrics_grid, text="0", foreground="#27AE60", font=("Helvetica", 11, "bold"))
            label.grid(row=0, column=i*2+1, padx=(0,10), sticky="w")
            self.metrics_labels[name.lower()] = label
        
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
        log_frame = ttk.LabelFrame(left_panel, text="Log de Procesamiento")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.log = tk.Text(log_frame, height=8, font=("Consolas", 9), 
                          bg="#34495E", fg="white", relief=tk.FLAT)
        self.log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.progress_bar = ttk.Progressbar(log_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill=tk.X, padx=5, pady=5)
        
        # Panel derecho: vista previa y gráficos
        right_panel = ttk.Frame(main_frame)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0))
        
        # Notebook con pestañas
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Pestaña de vista previa
        preview_frame = ttk.Frame(self.notebook)
        self.notebook.add(preview_frame, text="Vista Previa")
        
        # Vista original vs procesada
        preview_grid = ttk.Frame(preview_frame)
        preview_grid.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        orig_frame = ttk.LabelFrame(preview_grid, text="Original")
        orig_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.orig_preview_label = ttk.Label(orig_frame)
        self.orig_preview_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        proc_frame = ttk.LabelFrame(preview_grid, text="Procesada")
        proc_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.filtered_preview_label = ttk.Label(proc_frame)
        self.filtered_preview_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
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
        self.notebook.add(graph_frame, text="Comparación de Estrategias")
        
        self.figure, self.ax = plt.subplots(figsize=(8, 4))
        self.figure.patch.set_facecolor('#2C3E50')
        self.ax.set_facecolor('#34495E')
        self.canvas = FigureCanvasTkAgg(self.figure, graph_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    def clear_list(self):
        self.image_paths.clear()
        self.processed_paths.clear()
        self.listbox.delete(0, tk.END)
        self.log.delete("1.0", tk.END)
        self.orig_preview_label.config(image="", text="")
        self.filtered_preview_label.config(image="", text="")
        self.update_metrics()
    
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
            self.output_label.config(text=f"Salida: {self.output_folder}")
            os.makedirs(self.output_folder, exist_ok=True)
    
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
                    self.orig_preview_label.config(image=self.orig_preview_image)
                    
                    # Vista procesada
                    if image_path in self.processed_paths:
                        proc_path = self.processed_paths[image_path]
                        proc_img = Image.open(proc_path)
                        proc_img.thumbnail((self.zoom_level, self.zoom_level))
                        self.filtered_preview_image = ImageTk.PhotoImage(proc_img)
                        self.filtered_preview_label.config(image=self.filtered_preview_image)
                    else:
                        self.filtered_preview_label.config(image="", text="Imagen no procesada")
        except Exception as e:
            self.log_message(f"Error en vista previa: {str(e)}")
    
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
        self.metrics_labels["procesadas"].config(text=str(self.processed_counter.get_value()))
        self.metrics_labels["errores"].config(text=str(self.error_counter.get_value()))
        self.metrics_labels["activos"].config(text=str(self.semaphore.get_active()))
    
    def apply_filter(self):
        if not self.image_paths:
            messagebox.showwarning("Advertencia", "No hay fotos cargadas.")
            return
        
        selected_filter = self.filter_var.get()
        strategy = self.strategy_var.get()
        
        # Reiniciar contadores
        self.processed_counter = SharedCounter()
        self.error_counter = SharedCounter()
        
        if strategy == "multiprocess":
            self.apply_filter_multiprocess(selected_filter)
        elif strategy == "multithread":
            self.apply_filter_multithread(selected_filter)
        elif strategy == "actor":
            self.apply_filter_actor(selected_filter)
    
    def apply_filter_multiprocess(self, selected_filter):
        """Versión multiproceso original mejorada"""
        tasks = [(path, selected_filter, self.output_folder) for path in self.image_paths]
        self.progress_bar["value"] = 0
        self.progress_bar["maximum"] = len(tasks)
        self.log.delete("1.0", tk.END)
        self.log_message(f"Iniciando procesamiento multiproceso ({len(tasks)} imágenes)...")
        
        start_time = time.time()
        threading.Thread(target=self.run_multiprocess_processing, 
                        args=(tasks, start_time), daemon=True).start()
    
    def run_multiprocess_processing(self, tasks, start_time):
        """Ejecuta procesamiento con ProcessPoolExecutor"""
        result_queue = queue.Queue()
        futures = [self.process_executor.submit(process_image, task) for task in tasks]
        total = len(futures)
        
        def update_ui():
            try:
                while True:
                    result = result_queue.get_nowait()
                    if result["status"] == "OK":
                        self.processed_counter.increment()
                        self.processed_paths[result["original"]] = result["output"]
                        self.log_message(f"✓ {result['message']}")
                    else:
                        self.error_counter.increment()
                        self.log_message(f"✗ {result['message']}")
                    
                    self.progress_bar["value"] += 1
                    self.update_metrics()
            except queue.Empty:
                pass
            
            if self.progress_bar["value"] < total:
                self.after(100, update_ui)
            else:
                elapsed = time.time() - start_time
                self.metrics_labels["tiempo (s)"].config(text=f"{elapsed:.2f}")
                self.metrics["parallel_process"].append(elapsed)
                self.log_message(f"Procesamiento completado en {elapsed:.2f} segundos")
        
        self.after(100, update_ui)
        
        for future in as_completed(futures):
            result = future.result()
            result_queue.put(result)
    
    def apply_filter_multithread(self, selected_filter):
        """Versión multihilo con ThreadPoolExecutor"""
        tasks = [(path, selected_filter, self.output_folder) for path in self.image_paths]
        self.progress_bar["value"] = 0
        self.progress_bar["maximum"] = len(tasks)
        self.log.delete("1.0", tk.END)
        self.log_message(f"Iniciando procesamiento multihilo ({len(tasks)} imágenes)...")
        
        start_time = time.time()
        threading.Thread(target=self.run_multithread_processing, 
                        args=(tasks, start_time), daemon=True).start()
    
    def run_multithread_processing(self, tasks, start_time):
        """Ejecuta procesamiento con ThreadPoolExecutor"""
        result_queue = queue.Queue()
        
        def process_with_semaphore(task):
            """Función wrapper con semáforo"""
            self.semaphore.acquire()
            try:
                result = process_image(task)
                return result
            finally:
                self.semaphore.release()
        
        futures = [self.thread_executor.submit(process_with_semaphore, task) for task in tasks]
        total = len(futures)
        
        def update_ui():
            try:
                while True:
                    result = result_queue.get_nowait()
                    if result["status"] == "OK":
                        self.processed_counter.increment()
                        self.processed_paths[result["original"]] = result["output"]
                        self.log_message(f"✓ {result['message']}")
                    else:
                        self.error_counter.increment()
                        self.log_message(f"✗ {result['message']}")
                    
                    self.progress_bar["value"] += 1
                    self.update_metrics()
            except queue.Empty:
                pass
            
            if self.progress_bar["value"] < total:
                self.after(100, update_ui)
            else:
                elapsed = time.time() - start_time
                self.metrics_labels["tiempo (s)"].config(text=f"{elapsed:.2f}")
                self.metrics["parallel_thread"].append(elapsed)
                self.log_message(f"Procesamiento multihilo completado en {elapsed:.2f} segundos")
        
        self.after(100, update_ui)
        
        for future in as_completed(futures):
            result = future.result()
            result_queue.put(result)
    
    def apply_filter_actor(self, selected_filter):
        """Versión con modelo Actor"""
        tasks = [(path, selected_filter, self.output_folder) for path in self.image_paths]
        self.progress_bar["value"] = 0
        self.progress_bar["maximum"] = len(tasks)
        self.log.delete("1.0", tk.END)
        self.log_message(f"Iniciando procesamiento con modelo Actor ({len(tasks)} imágenes)...")
        
        start_time = time.time()
        threading.Thread(target=self.run_actor_processing, 
                        args=(tasks, start_time), daemon=True).start()
    
    def run_actor_processing(self, tasks, start_time):
        """Ejecuta procesamiento con modelo Actor"""
        result_queue = queue.Queue()
        results, elapsed = process_image_actor(
            [t[0] for t in tasks], 
            tasks[0][1], 
            tasks[0][2],
            num_actors=4
        )
        
        total = len(results)
        processed = 0
        
        def update_ui():
            nonlocal processed
            try:
                while results:
                    result = results.pop(0)
                    if result["status"] == "OK":
                        self.processed_counter.increment()
                        self.processed_paths[result["original"]] = result["output"]
                        self.log_message(f"✓ {result['message']}")
                    else:
                        self.error_counter.increment()
                        self.log_message(f"✗ {result['message']}")
                    
                    self.progress_bar["value"] += 1
                    processed += 1
                    self.update_metrics()
            except IndexError:
                pass
            
            if processed < total:
                self.after(100, update_ui)
            else:
                self.metrics_labels["tiempo (s)"].config(text=f"{elapsed:.2f}")
                self.metrics["actor_model"].append(elapsed)
                self.log_message(f"Procesamiento Actor completado en {elapsed:.2f} segundos")
        
        self.after(100, update_ui)
    
    def compare_strategies(self):
        """Compara todas las estrategias de procesamiento"""
        if not self.image_paths:
            messagebox.showwarning("Advertencia", "No hay fotos cargadas para comparar.")
            return
        
        selected_filter = self.filter_var.get()
        tasks = [(path, selected_filter, self.output_folder) for path in self.image_paths]
        
        self.log.delete("1.0", tk.END)
        self.log_message("Iniciando comparación de estrategias...")
        
        # Ejecutar secuencial
        self.log_message("Ejecutando versión secuencial...")
        _, seq_time = process_image_sequential(
            [t[0] for t in tasks], 
            tasks[0][1], 
            tasks[0][2]
        )
        self.metrics["sequential"].append(seq_time)
        
        # Ejecutar paralelo (ya se ejecutan en los métodos anteriores)
        # Aquí solo actualizamos el gráfico
        
        self.update_comparison_chart()
    
    def update_comparison_chart(self):
        """Actualiza el gráfico de comparación"""
        self.ax.clear()
        
        strategies = list(self.metrics.keys())
        avg_times = []
        
        for strategy in strategies:
            if self.metrics[strategy]:
                avg_time = sum(self.metrics[strategy]) / len(self.metrics[strategy])
                avg_times.append(avg_time)
            else:
                avg_times.append(0)
        
        bars = self.ax.bar(strategies, avg_times, color=['#E74C3C', '#3498DB', '#2ECC71', '#F39C12'])
        
        self.ax.set_title('Comparación de Estrategias de Procesamiento', color='white')
        self.ax.set_xlabel('Estrategia', color='white')
        self.ax.set_ylabel('Tiempo Promedio (segundos)', color='white')
        self.ax.tick_params(axis='x', colors='white')
        self.ax.tick_params(axis='y', colors='white')
        
        # Agregar valores encima de las barras
        for bar, avg in zip(bars, avg_times):
            if avg > 0:
                height = bar.get_height()
                self.ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{avg:.2f}s', ha='center', va='bottom', color='white')
        
        self.ax.grid(True, alpha=0.3)
        self.canvas.draw()
        
        # Mostrar speedup
        if self.metrics["sequential"] and self.metrics["parallel_process"]:
            seq_avg = sum(self.metrics["sequential"]) / len(self.metrics["sequential"])
            par_avg = sum(self.metrics["parallel_process"]) / len(self.metrics["parallel_process"])
            if par_avg > 0:
                speedup = seq_avg / par_avg
                self.log_message(f"Speedup (paralelo vs secuencial): {speedup:.2f}x")
                
                # Ley de Amdahl
                theoretical_max = len(self.image_paths)  # Para carga perfectamente paralelizable
                efficiency = (speedup / theoretical_max) * 100 if theoretical_max > 0 else 0
                self.log_message(f"Eficiencia paralela: {efficiency:.1f}%")

if __name__ == "__main__":
    app = PhotoFilterApp()
    app.mainloop()