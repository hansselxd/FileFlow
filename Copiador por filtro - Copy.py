import json
import os
import queue
import re
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def normalizar_palabras_clave(palabras):
    return [
        p.lower().strip()
        for p in palabras
        if p and p.strip()
    ]


def normalizar_destino_regla(destino):
    if destino is None:
        return ""
    destino_normalizado = str(destino).strip().replace("\\", "/")
    destino_normalizado = re.sub(r"/+", "/", destino_normalizado)
    return destino_normalizado.strip("/")


def normalizar_regla(regla):
    if regla is None:
        return {
            "palabras": [],
            "origen": "",
            "destino": "",
            "modo": "copy",
            "crear_subcarpetas": True,
            "eliminar_duplicados": False,
        }

    palabras = []
    for item in regla.get("palabras", []):
        palabra = str(item).strip()
        if palabra:
            palabras.extend([p.strip() for p in palabra.split(",") if p and p.strip()])

    modo = str(regla.get("modo", "copy")).strip().lower()
    if modo not in ("copy", "move"):
        modo = "copy"

    crear_subcarpetas = regla.get("crear_subcarpetas", True)
    if isinstance(crear_subcarpetas, str):
        crear_subcarpetas = crear_subcarpetas.strip().lower() in ("1", "true", "yes", "si", "on")

    eliminar_duplicados = regla.get("eliminar_duplicados", False)
    if isinstance(eliminar_duplicados, str):
        eliminar_duplicados = eliminar_duplicados.strip().lower() in ("1", "true", "yes", "si", "on")

    return {
        "palabras": normalizar_palabras_clave(palabras),
        "origen": str(regla.get("origen", "")).strip(),
        "destino": normalizar_destino_regla(regla.get("destino", "")),
        "modo": modo,
        "crear_subcarpetas": bool(crear_subcarpetas),
        "eliminar_duplicados": bool(eliminar_duplicados),
    }


def guardar_reglas(reglas):
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reglas.json")
    reglas_limpias = [normalizar_regla(regla) for regla in (reglas or [])]
    reglas_limpias = [regla for regla in reglas_limpias if regla["palabras"] and regla["origen"] and regla["destino"]]

    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump({"reglas": reglas_limpias}, archivo, ensure_ascii=False, indent=2)

    return ruta


def cargar_reglas():
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reglas.json")

    if not os.path.exists(ruta):
        return []

    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(datos, dict):
        return []

    reglas = datos.get("reglas", [])
    reglas_validas = []
    for regla in reglas:
        regla_normalizada = normalizar_regla(regla)
        if regla_normalizada["palabras"] and regla_normalizada["destino"]:
            reglas_validas.append(regla_normalizada)

    return reglas_validas


def obtener_palabra_clave_coincidente(ruta_archivo, palabras_clave):
    """
    Devuelve la primera palabra clave que aparece como palabra completa
    en el nombre del archivo, con la única variante permitida de una "s" final.
    Ejemplos:
      - "casa" en "casa de carlos" -> coincide
      - "cuchillo" en "mesa con cuchillos" -> coincide
      - "ver" en "versiones de la casa" -> no coincidea
    """

    if not os.path.isfile(ruta_archivo):
        return None

    nombre_archivo = os.path.basename(ruta_archivo).lower()
    tokens = re.findall(r"[a-záéíóúñ0-9]+", nombre_archivo)

    for palabra in palabras_clave:
        palabra_normalizada = re.sub(r"[^a-záéíóúñ0-9]+", "", palabra.lower())

        if not palabra_normalizada:
            continue

        for token in tokens:
            if token == palabra_normalizada:
                return palabra

            if token == palabra_normalizada + "s":
                return palabra

    return None


def obtener_regla_coincidente(ruta_archivo, reglas):
    if not os.path.isfile(ruta_archivo):
        return None

    for regla in reglas:
        regla_normalizada = normalizar_regla(regla)
        palabras = regla_normalizada["palabras"]
        if not palabras:
            continue

        if obtener_palabra_clave_coincidente(ruta_archivo, palabras) is not None:
            return regla_normalizada

    return None


def obtener_nombre_unico(destino, nombre_archivo):
    ruta_destino = os.path.join(destino, nombre_archivo)

    if not os.path.exists(ruta_destino):
        return ruta_destino

    nombre_base, extension = os.path.splitext(nombre_archivo)
    contador = 1

    while True:
        nuevo_nombre = f"{nombre_base}{contador}{extension}"
        nueva_ruta = os.path.join(destino, nuevo_nombre)

        if not os.path.exists(nueva_ruta):
            return nueva_ruta

        contador += 1


def buscar_duplicado_en_destino(destino, nombre_archivo, tamaño, fecha_modificacion, fecha_creacion):
    if not os.path.isdir(destino):
        return None

    for nombre in os.listdir(destino):
        ruta_destino = os.path.join(destino, nombre)

        if not os.path.isfile(ruta_destino):
            continue

        if nombre.lower() != nombre_archivo.lower():
            continue

        if os.path.getsize(ruta_destino) != tamaño:
            continue

        if os.path.getmtime(ruta_destino) != fecha_modificacion:
            continue

        if os.path.getctime(ruta_destino) != fecha_creacion:
            continue

        return ruta_destino

    return None


def copiar_archivo_con_progreso(origen, destino, ui_callback=None, cancel_event=None):
    total = os.path.getsize(origen)
    bytes_copiados = 0
    ultimo_porcentaje = -1
    ultimo_envio = 0

    def enviar_progreso(porcentaje):
        nonlocal ultimo_porcentaje, ultimo_envio
        ahora = time.monotonic()
        porcentaje_entero = int(porcentaje)

        if (
            porcentaje_entero != ultimo_porcentaje
            or ahora - ultimo_envio >= 0.1
            or porcentaje >= 100
        ):
            ultimo_porcentaje = porcentaje_entero
            ultimo_envio = ahora

            if ui_callback is not None:
                ui_callback({
                    "tipo": "actual",
                    "valor": porcentaje,
                    "texto": f"{porcentaje:.0f}%"
                })

    enviar_progreso(0)

    try:
        with open(origen, "rb") as archivo_origen, open(destino, "wb") as archivo_destino:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Proceso cancelado por el usuario.")

                bloque = archivo_origen.read(1024 * 1024)
                if not bloque:
                    break

                archivo_destino.write(bloque)
                bytes_copiados += len(bloque)
                porcentaje = (bytes_copiados / total * 100) if total else 100
                enviar_progreso(porcentaje)

    except Exception:
        try:
            if os.path.exists(destino):
                os.remove(destino)
        except Exception:
            pass
        raise

    enviar_progreso(100)


def procesar_archivos(reglas, ui_callback=None, cancel_event=None):
    reglas = [normalizar_regla(regla) for regla in (reglas or [])]
    reglas = [regla for regla in reglas if regla["palabras"] and regla["origen"] and regla["destino"]]

    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Proceso cancelado por el usuario.")

    if not reglas:
        raise ValueError("Debes crear al menos una regla de clasificación con origen y destino.")

    def enviar(dato):
        if ui_callback is not None:
            ui_callback(dato)

    def registrar_log(mensaje):
        enviar({"tipo": "log", "mensaje": mensaje})

    def actualizar_estado(mensaje):
        enviar({"tipo": "estado", "estado": mensaje})

    def actualizar_actual(valor, texto, estado=None):
        dato = {"tipo": "actual", "valor": valor, "texto": texto}
        if estado is not None:
            dato["estado"] = estado
        enviar(dato)

    def actualizar_analisis(valor, texto):
        enviar({"tipo": "analisis", "valor": valor, "texto": texto})

    almacenamiento_total = 0
    archivos_procesados_total = 0

    actualizar_estado("Analizando reglas y archivos...")
    registrar_log(f"Reglas activas: {len(reglas)}")
    for index, regla in enumerate(reglas, start=1):
        registrar_log(f"{index}. {', '.join(regla['palabras'])} -> {regla['origen']} -> {regla['destino']}")

    for regla in reglas:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Proceso cancelado por el usuario.")

        origen = regla["origen"]
        destino = regla["destino"]
        modo = regla["modo"]
        crear_subcarpetas = bool(regla.get("crear_subcarpetas", True))
        eliminar_duplicados = bool(regla.get("eliminar_duplicados", False))

        if not os.path.isdir(origen):
            registrar_log(f"La carpeta origen no existe y se omite: {origen}")
            continue

        os.makedirs(destino, exist_ok=True)

        archivos = []
        for raiz, _, lista_archivos in os.walk(origen):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Proceso cancelado por el usuario.")

            for nombre in lista_archivos:
                archivos.append(os.path.join(raiz, nombre))

        total_archivos = len(archivos)
        almacenamiento_total += total_archivos
        enviar({"tipo": "total_archivos", "valor": almacenamiento_total})

        registros_coincidentes = []
        for ruta_archivo in archivos:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Proceso cancelado por el usuario.")

            palabra_coincidente = obtener_palabra_clave_coincidente(ruta_archivo, regla["palabras"])
            if palabra_coincidente is not None:
                registros_coincidentes.append((ruta_archivo, palabra_coincidente))

        total_coincidencias = len(registros_coincidentes)
        enviar({"tipo": "total", "valor": total_coincidencias})
        registrar_log(f"Carpeta origen: {origen} | archivos encontrados: {total_archivos} | coincidencias: {total_coincidencias}")

        if total_coincidencias == 0:
            actualizar_estado(f"Sin coincidencias en: {origen}")
            continue

        for ruta_archivo, palabra_coincidente in registros_coincidentes:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Proceso cancelado por el usuario.")

            archivo = os.path.basename(ruta_archivo)
            carpeta_destino = os.path.normpath(destino)

            if crear_subcarpetas:
                carpeta_destino = os.path.normpath(os.path.join(destino, palabra_coincidente))
                os.makedirs(carpeta_destino, exist_ok=True)

            registrar_log("Coincidencia encontrada:")
            registrar_log(f"Archivo: {archivo}")
            registrar_log(f"Palabra: {palabra_coincidente}")
            registrar_log(f"Destino: {carpeta_destino}")

            try:
                tamaño_archivo = os.path.getsize(ruta_archivo)
                fecha_modificacion = os.path.getmtime(ruta_archivo)
                fecha_creacion = os.path.getctime(ruta_archivo)
            except OSError as e:
                registrar_log(f"No se pudo leer {archivo}: {e}")
                archivos_procesados_total += 1
                continue

            ruta_duplicada = buscar_duplicado_en_destino(
                carpeta_destino,
                archivo,
                tamaño_archivo,
                fecha_modificacion,
                fecha_creacion,
            )

            if ruta_duplicada is not None:
                if eliminar_duplicados:
                    try:
                        os.remove(ruta_archivo)
                        registrar_log(f"Archivo duplicado eliminado del origen: {archivo}")
                        actualizar_estado(f"Archivo duplicado eliminado del origen: {archivo}")
                    except Exception as e:
                        registrar_log(f"Error al eliminar duplicado {archivo}: {e}")
                        actualizar_estado(f"Error al eliminar duplicado: {e}")
                else:
                    registrar_log(f"Se mantiene archivo original porque ya existe exactamente igual en destino: {archivo}")
                    actualizar_estado(f"Se mantiene archivo original porque ya existe exactamente igual en destino: {archivo}")

                archivos_procesados_total += 1
                continue

            destino_final = obtener_nombre_unico(carpeta_destino, archivo)

            try:
                tamaño_formateado = os.path.getsize(ruta_archivo)
                registrar_log("Procesando:")
                registrar_log(f"{archivo}")

                if modo == "copy":
                    actualizar_actual(0, "0%", f"Copiando: {archivo}")
                    registrar_log(f"Copiando - {archivo} - {tamaño_formateado} bytes")
                    copiar_archivo_con_progreso(ruta_archivo, destino_final, ui_callback=ui_callback, cancel_event=cancel_event)
                    actualizar_actual(100, "100%", f"Copiado: {archivo}")
                    registrar_log("Archivo copiado correctamente.")

                elif modo == "move":
                    actualizar_actual(0, "0%", f"Moviendo: {archivo}")
                    registrar_log(f"Moviendo - {archivo} - {tamaño_formateado} bytes")
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Proceso cancelado por el usuario.")
                    shutil.move(ruta_archivo, destino_final)
                    actualizar_actual(100, "100%", f"Movido: {archivo}")
                    registrar_log("Archivo movido correctamente.")

            except Exception as e:
                registrar_log(f"Error al procesar {archivo}: {e}")
                actualizar_actual(0, "0%", f"Error: {e}")
                if cancel_event is not None and cancel_event.is_set():
                    raise

            archivos_procesados_total += 1
            porcentaje = (archivos_procesados_total / max(1, almacenamiento_total) * 100)
            actualizar_analisis(porcentaje, f"{porcentaje:.0f}% procesado")

    if cancel_event is not None and cancel_event.is_set():
        actualizar_estado("Proceso cancelado por el usuario.")
        registrar_log("Proceso cancelado por el usuario.")
        return archivos_procesados_total

    actualizar_actual(100, "100%", "Proceso finalizado.")
    actualizar_analisis(100, "100% procesado")
    actualizar_estado("Proceso finalizado.")
    registrar_log(f"Proceso terminado. Archivos procesados: {archivos_procesados_total}")
    return archivos_procesados_total


class Aplicacion(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FileFlow")
        self.geometry("980x920")
        self.minsize(980, 920)
        self.configure(bg="#edf3fb")

        self._procesando = False
        self._cola = queue.Queue()
        self.cancel_event = None
        self._hilo_proceso = None

        reglas_guardadas = cargar_reglas()
        self.reglas = reglas_guardadas if reglas_guardadas is not None else []
        if reglas_guardadas is None:
            messagebox.showwarning(
                "Reglas",
                "El archivo de reglas está corrupto o no se pudo leer. Se inició con una lista vacía."
            )

        self.var_progreso_actual = tk.DoubleVar(value=0)
        self.var_progreso_analisis = tk.DoubleVar(value=0)
        self.var_texto_actual = tk.StringVar(value="0%")
        self.var_texto_analisis = tk.StringVar(value="0% analizado")
        self.var_estado = tk.StringVar(value="Listo para iniciar.")
        self.var_total_archivos = tk.StringVar(value="Total encontrados: 0")
        self.var_reglas_count = tk.StringVar(value="Reglas configuradas: 0")
        self.var_reglas_activas = tk.StringVar(value="REGLAS ACTIVAS: 0")

        self._crear_interfaz()
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_reglas()

    def _crear_interfaz(self):
        contenedor = ttk.Frame(self, padding=20)
        contenedor.pack(fill="both", expand=True)

        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame", background="#edf3fb")
        style.configure("TLabelframe", background="#f8fbff", foreground="#1f2937")
        style.configure("TLabelframe.Label", background="#f8fbff", foreground="#1f2937", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background="#edf3fb", foreground="#1f2937")
        style.configure("TEntry", padding=8, fieldbackground="#ffffff", foreground="#111827")
        style.configure("TProgressbar", background="#2563eb", troughcolor="#dfe7f1")
        style.configure("Treeview", background="#ffffff", foreground="#111827", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", background="#dfeafc", foreground="#0f172a", font=("Segoe UI", 9, "bold"))
        style.configure("Primary.TButton", padding=(14, 10), font=("Segoe UI", 10, "bold"), foreground="#ffffff", background="#2563eb")
        style.configure("Secondary.TButton", padding=(14, 10), font=("Segoe UI", 10, "bold"), foreground="#0f172a", background="#e5edf8")
        style.map("Primary.TButton", background=[("active", "#1d4ed8"), ("pressed", "#1e40af"), ("disabled", "#93c5fd")], foreground=[("disabled", "#eff6ff")])
        style.map("Secondary.TButton", background=[("active", "#d7e3f5"), ("pressed", "#cfe0f7"), ("disabled", "#e5e7eb")], foreground=[("disabled", "#6b7280")])

        header = tk.Frame(contenedor, bg="#edf3fb")
        header.pack(fill="x", pady=(0, 14))

        tk.Label(
            header,
            text="FileFlow",
            font=("Segoe UI", 22, "bold"),
            fg="#0f172a",
            bg="#edf3fb",
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Organizador de archivos mediante reglas automáticas.",
            font=("Segoe UI", 10),
            fg="#475569",
            bg="#edf3fb",
        ).pack(anchor="w", pady=(4, 0))

        reglas_frame = ttk.LabelFrame(contenedor, text="Reglas de clasificación", padding=12)
        reglas_frame.pack(fill="both", pady=(0, 12))

        self.tree_reglas = ttk.Treeview(reglas_frame, columns=("prioridad", "palabras", "destino"), show="headings", height=7)
        self.tree_reglas.heading("prioridad", text="Prioridad")
        self.tree_reglas.heading("palabras", text="Palabras clave")
        self.tree_reglas.heading("destino", text="Destino")
        self.tree_reglas.column("prioridad", width=70, anchor="center")
        self.tree_reglas.column("palabras", width=220, anchor="w")
        self.tree_reglas.column("destino", width=360, anchor="w")
        self.tree_reglas.pack(fill="both", expand=True, pady=(0, 8))

        btns_reglas = ttk.Frame(reglas_frame, style="TFrame")
        btns_reglas.pack(fill="x")

        ttk.Button(btns_reglas, text="+ Agregar regla", command=self._agregar_regla, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns_reglas, text="Editar regla", command=self._editar_regla, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns_reglas, text="Eliminar regla", command=self._eliminar_regla, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns_reglas, text="↑ Subir", command=self._subir_regla, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns_reglas, text="↓ Bajar", command=self._bajar_regla, style="Secondary.TButton").pack(side="left")

        self.var_reglas_count.set("Reglas configuradas: 0")
        self.var_reglas_activas.set("REGLAS ACTIVAS: 0")
        ttk.Label(contenedor, textvariable=self.var_reglas_count, anchor="w").pack(anchor="w", pady=(0, 4))
        ttk.Label(contenedor, textvariable=self.var_reglas_activas, anchor="w").pack(anchor="w", pady=(0, 8))
        ttk.Label(contenedor, text="Las reglas se aplican de arriba hacia abajo.", foreground="#475569").pack(anchor="w", pady=(0, 8))

        progreso_frame = ttk.LabelFrame(contenedor, text="Progreso", padding=14)
        progreso_frame.pack(fill="x", pady=(0, 12))

        ttk.Label(progreso_frame, text="Archivo actual:").pack(anchor="w")
        self.barra_actual = ttk.Progressbar(progreso_frame, variable=self.var_progreso_actual, maximum=100, length=500)
        self.barra_actual.pack(fill="x", pady=(2, 2))
        ttk.Label(progreso_frame, textvariable=self.var_texto_actual, anchor="e").pack(anchor="e")

        ttk.Label(progreso_frame, text="Carpeta de origen analizada:").pack(anchor="w", pady=(8, 0))
        self.barra_analisis = ttk.Progressbar(progreso_frame, variable=self.var_progreso_analisis, maximum=100, length=500)
        self.barra_analisis.pack(fill="x", pady=(2, 2))
        ttk.Label(progreso_frame, textvariable=self.var_texto_analisis, anchor="e").pack(anchor="e")
        ttk.Label(progreso_frame, textvariable=self.var_total_archivos, anchor="w").pack(anchor="w", pady=(8, 0))

        self.log_text = tk.Text(contenedor, height=8, wrap="word", bg="#ffffff", fg="#1f2937", relief="flat", borderwidth=1, highlightthickness=1, highlightbackground="#dfe7f1", highlightcolor="#dfe7f1", state="disabled", cursor="arrow", padx=10, pady=8)
        self.log_text.pack(fill="both", pady=(0, 10))

        ttk.Label(contenedor, textvariable=self.var_estado, wraplength=650, justify="left").pack(anchor="w", pady=(0, 8))

        botones = ttk.Frame(contenedor, style="TFrame")
        botones.pack(fill="x")

        self.boton_iniciar = ttk.Button(botones, text="Iniciar", command=self._iniciar_proceso, style="Primary.TButton")
        self.boton_iniciar.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.boton_cancelar = ttk.Button(botones, text="Cancelar", command=self._cancelar_proceso, state="disabled", style="Secondary.TButton")
        self.boton_cancelar.pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _guardar_reglas_estado(self):
        guardar_reglas(self.reglas)
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_reglas()

    def _actualizar_tabla_reglas(self):
        for item in self.tree_reglas.get_children():
            self.tree_reglas.delete(item)

        for indice, regla in enumerate(self.reglas, start=1):
            palabras = ", ".join(regla.get("palabras", []))
            destino = regla.get("destino", "")
            self.tree_reglas.insert("", "end", values=(indice, palabras, destino))

        self.var_reglas_count.set(f"Reglas configuradas: {len(self.reglas)}")

    def _actualizar_resumen_reglas(self):
        self.var_reglas_activas.set(f"REGLAS ACTIVAS: {len(self.reglas)}")

        if not self.reglas:
            self.var_estado.set("Debes crear al menos una regla de clasificación.")

    def _validar_regla(self, regla, indice_actual=None):
        regla = normalizar_regla(regla)
        palabras = regla.get("palabras", [])
        origen = regla.get("origen", "")
        destino = regla.get("destino", "")

        if not palabras:
            raise ValueError("Debes indicar al menos una palabra clave.")
        if not origen:
            raise ValueError("Debes indicar una carpeta de origen.")
        if not destino:
            raise ValueError("Debes indicar una carpeta de destino.")

        for palabra in palabras:
            if not palabra.strip():
                raise ValueError("Las palabras clave no pueden estar vacías.")

        for indice, item in enumerate(self.reglas):
            if indice == indice_actual:
                continue
            regla_actual = normalizar_regla(item)
            if regla_actual == regla:
                raise ValueError("Esta regla ya existe.")

        return regla

    def _mostrar_ventana_regla(self, regla=None):
        editar = regla is not None
        ventana = tk.Toplevel(self)
        ventana.title("Editar regla" if editar else "Agregar regla")
        ventana.geometry("650x520")
        ventana.minsize(650, 520)
        ventana.maxsize(1000, 800)
        ventana.transient(self)
        ventana.grab_set()

        contenido = ttk.Frame(ventana, padding=18)
        contenido.pack(fill="both", expand=True)

        tk.Label(contenido, text="Palabras clave:").pack(anchor="w", pady=(0, 4))
        entrada_palabras = tk.Entry(contenido, width=80)
        entrada_palabras.pack(fill="x", pady=(0, 12))

        origen_default = (regla or {}).get("origen", "")
        destino_default = (regla or {}).get("destino", "")
        modo_default = (regla or {}).get("modo", "copy")
        eliminar_default = bool((regla or {}).get("eliminar_duplicados", False))
        crear_default = bool((regla or {}).get("crear_subcarpetas", True))

        frame_origen = ttk.Frame(contenido)
        frame_origen.pack(fill="x", pady=(0, 12))
        tk.Label(frame_origen, text="Carpeta de origen:").pack(anchor="w", pady=(0, 4))
        var_origen = tk.StringVar(value=origen_default)
        entrada_origen = tk.Entry(frame_origen, textvariable=var_origen)
        entrada_origen.pack(side="left", fill="x", expand=True)
        ttk.Button(frame_origen, text="Buscar", command=lambda: self._seleccionar_origen_regla(var_origen)).pack(side="left", padx=(8, 0))

        frame_destino = ttk.Frame(contenido)
        frame_destino.pack(fill="x", pady=(0, 12))
        tk.Label(frame_destino, text="Carpeta de destino:").pack(anchor="w", pady=(0, 4))
        var_destino = tk.StringVar(value=destino_default)
        entrada_destino = tk.Entry(frame_destino, textvariable=var_destino)
        entrada_destino.pack(side="left", fill="x", expand=True)
        ttk.Button(frame_destino, text="Buscar", command=lambda: self._seleccionar_destino_regla(var_destino)).pack(side="left", padx=(8, 0))

        tk.Label(contenido, text="Acción:").pack(anchor="w", pady=(0, 6))
        var_modo = tk.StringVar(value=modo_default)
        frame_modo = ttk.Frame(contenido)
        frame_modo.pack(anchor="w", pady=(0, 12))
        ttk.Radiobutton(frame_modo, text="Copiar archivos", variable=var_modo, value="copy").pack(side="left", padx=(0, 18))
        ttk.Radiobutton(frame_modo, text="Mover archivos", variable=var_modo, value="move").pack(side="left")

        var_crear_subcarpetas = tk.BooleanVar(value=crear_default)
        ttk.Checkbutton(contenido, text="Crear carpetas automáticamente según la regla", variable=var_crear_subcarpetas).pack(anchor="w", pady=(0, 12))

        var_eliminar_duplicados = tk.BooleanVar(value=eliminar_default)
        ttk.Checkbutton(
            contenido,
            text="Eliminar archivos del origen si ya existen exactamente iguales en el destino",
            variable=var_eliminar_duplicados,
        ).pack(anchor="w", pady=(0, 12))

        if editar and regla:
            entrada_palabras.insert(0, ", ".join(regla.get("palabras", [])))
        else:
            entrada_palabras.insert(0, "")

        def guardar():
            try:
                palabras_texto = entrada_palabras.get().strip()
                palabras = [p.strip() for p in palabras_texto.split(",") if p.strip()]
                nueva_regla = {
                    "palabras": palabras,
                    "origen": var_origen.get().strip(),
                    "destino": normalizar_destino_regla(var_destino.get().strip()),
                    "modo": var_modo.get(),
                    "crear_subcarpetas": bool(var_crear_subcarpetas.get()),
                    "eliminar_duplicados": bool(var_eliminar_duplicados.get()),
                }
                indice_actual = self.reglas.index(regla) if editar else None
                regla_validada = self._validar_regla(nueva_regla, indice_actual=indice_actual)

                if editar:
                    self.reglas[indice_actual] = regla_validada
                else:
                    self.reglas.append(regla_validada)

                guardar_reglas(self.reglas)
                self._actualizar_tabla_reglas()
                self._actualizar_resumen_reglas()
                ventana.destroy()
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))

        botones = ttk.Frame(contenido)
        botones.pack(fill="x", pady=(8, 0))
        ttk.Button(botones, text="Cancelar", command=ventana.destroy).pack(side="right")
        ttk.Button(botones, text="Guardar regla", command=guardar).pack(side="right", padx=(0, 8))

    def _seleccionar_origen_regla(self, var_origen):
        carpeta = filedialog.askdirectory(title="Selecciona la carpeta de origen de la regla")
        if carpeta:
            var_origen.set(carpeta)

    def _seleccionar_destino_regla(self, var_destino_regla):
        destino_rel = filedialog.askdirectory(title="Selecciona la carpeta destino de la regla")
        if destino_rel:
            var_destino_regla.set(normalizar_destino_regla(destino_rel))

    def _agregar_regla(self):
        self._mostrar_ventana_regla()

    def _editar_regla(self):
        seleccion = self.tree_reglas.selection()
        if not seleccion:
            messagebox.showinfo("Reglas", "Selecciona una regla para editar.")
            return

        indice = int(self.tree_reglas.index(seleccion[0]))
        regla = self.reglas[indice]
        self._mostrar_ventana_regla(regla)

    def _eliminar_regla(self):
        seleccion = self.tree_reglas.selection()
        if not seleccion:
            messagebox.showinfo("Reglas", "Selecciona una regla para eliminar.")
            return

        indice = int(self.tree_reglas.index(seleccion[0]))
        regla = self.reglas[indice]
        texto = f"{', '.join(regla.get('palabras', []))} → {regla.get('destino', '')}"

        respuesta = messagebox.askyesno("Eliminar regla", f"¿Quieres eliminar la regla \"{texto}\"?")
        if not respuesta:
            return

        del self.reglas[indice]
        guardar_reglas(self.reglas)
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_reglas()

    def _subir_regla(self):
        seleccion = self.tree_reglas.selection()
        if not seleccion:
            return

        indice = int(self.tree_reglas.index(seleccion[0]))
        if indice == 0:
            return

        self.reglas[indice - 1], self.reglas[indice] = self.reglas[indice], self.reglas[indice - 1]
        guardar_reglas(self.reglas)
        self._actualizar_tabla_reglas()

    def _bajar_regla(self):
        seleccion = self.tree_reglas.selection()
        if not seleccion:
            return

        indice = int(self.tree_reglas.index(seleccion[0]))
        if indice >= len(self.reglas) - 1:
            return

        self.reglas[indice], self.reglas[indice + 1] = self.reglas[indice + 1], self.reglas[indice]
        guardar_reglas(self.reglas)
        self._actualizar_tabla_reglas()

    def _registrar_log(self, mensaje):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, mensaje + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _ui_callback(self, dato):
        self._cola.put(dato)

    def _procesar_cola(self):
        while True:
            try:
                dato = self._cola.get_nowait()
            except queue.Empty:
                break

            tipo = dato.get("tipo")

            if tipo == "actual":
                self.var_progreso_actual.set(dato.get("valor", 0))
                self.var_texto_actual.set(dato.get("texto", "0%"))
                if dato.get("estado"):
                    self.var_estado.set(dato["estado"])

            elif tipo == "analisis":
                self.var_progreso_analisis.set(dato.get("valor", 0))
                self.var_texto_analisis.set(dato.get("texto", "0% analizado"))

            elif tipo == "estado":
                self.var_estado.set(dato.get("estado", "Listo para iniciar."))

            elif tipo == "log":
                self._registrar_log(dato.get("mensaje", ""))

            elif tipo == "total":
                self.var_total_archivos.set(f"Total encontrados: {dato.get('valor', 0)}")

            elif tipo == "total_archivos":
                self.var_total_archivos.set(f"Total encontrados: {dato.get('valor', 0)}")

            elif tipo == "error":
                mensaje = dato.get("mensaje", "Error desconocido.")
                self.var_estado.set(f"Error: {mensaje}")
                self._registrar_log(f"ERROR: {mensaje}")
                messagebox.showerror("Error", mensaje)

            elif tipo == "terminado":
                cancelado = dato.get("cancelado", False)
                error = dato.get("error")
                self._procesando = False
                self.boton_iniciar.config(state="normal")
                self.boton_cancelar.config(state="disabled")

                if error is not None:
                    self.var_estado.set(f"Error: {error}")
                elif cancelado:
                    self.var_estado.set("Proceso cancelado por el usuario.")
                else:
                    self.var_estado.set("Proceso finalizado.")
                    self.var_progreso_actual.set(100)
                    self.var_progreso_analisis.set(100)
                    self.var_texto_actual.set("100%")
                    self.var_texto_analisis.set("100% procesado")

                self._registrar_log("Proceso finalizado.")
                self.cancel_event = None

        if self._procesando or not self._cola.empty():
            self.after(50, self._procesar_cola)

    def _cancelar_proceso(self):
        if not self._procesando:
            return

        evento = self.cancel_event
        if evento is not None:
            evento.set()

        self.var_estado.set("Cancelando proceso...")
        self.boton_cancelar.config(state="disabled")

    def _iniciar_proceso(self):
        if self._procesando:
            return

        if not self.reglas:
            messagebox.showerror("Error", "Debes crear al menos una regla de clasificación.")
            return

        reglas_para_proceso = [normalizar_regla(regla) for regla in self.reglas]
        reglas_para_proceso = [regla for regla in reglas_para_proceso if regla["palabras"] and regla["origen"] and regla["destino"]]

        if not reglas_para_proceso:
            messagebox.showerror("Error", "Cada regla debe incluir una carpeta de origen y una de destino.")
            return

        self.var_estado.set("Iniciando proceso...")
        self.var_progreso_actual.set(0)
        self.var_progreso_analisis.set(0)
        self.var_texto_actual.set("0%")
        self.var_texto_analisis.set("0% analizado")
        self.var_total_archivos.set("Total encontrados: 0")

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

        self._registrar_log("Inicio del proceso con reglas independientes por regla.")
        for idx, regla in enumerate(reglas_para_proceso, start=1):
            self._registrar_log(f"{idx}. {', '.join(regla['palabras'])} | Origen: {regla['origen']} | Destino: {regla['destino']} | Modo: {regla['modo']}")
        self._registrar_log("Procesando...")

        self.update_idletasks()

        self._cola = queue.Queue()
        self._procesando = True
        self.cancel_event = threading.Event()

        self.boton_iniciar.config(state="disabled")
        self.boton_cancelar.config(state="normal")

        self.after(50, self._procesar_cola)

        def ejecutar():
            error = None
            cancelado = False

            try:
                procesar_archivos(
                    reglas=reglas_para_proceso,
                    ui_callback=self._ui_callback,
                    cancel_event=self.cancel_event,
                )
                cancelado = self.cancel_event.is_set()
            except Exception as e:
                if self.cancel_event.is_set():
                    cancelado = True
                    self._ui_callback({"tipo": "log", "mensaje": "Proceso cancelado por el usuario."})
                else:
                    error = str(e)
                    self._ui_callback({"tipo": "error", "mensaje": error})
            finally:
                self._ui_callback({"tipo": "terminado", "cancelado": cancelado, "error": error})

        self._hilo_proceso = threading.Thread(target=ejecutar, daemon=True, name="HiloProcesamiento")
        self._hilo_proceso.start()


def main():
    app = Aplicacion()
    app.mainloop()


if __name__ == "__main__":
    main()
