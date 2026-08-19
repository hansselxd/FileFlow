import hashlib
import json
import os
import queue
import re
import shutil
import threading
import time
import uuid
from datetime import date, datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def normalizar_palabras_clave(palabras):
    return [
        p.lower().strip()
        for p in palabras
        if p and p.strip()
    ]


def normalizar_destino_regla(destino):
    if destino is None:
        return ""

    destino = str(destino).strip()
    if not destino:
        return ""

    destino = destino.replace("\\", os.sep).replace("/", os.sep)
    return os.path.normpath(destino)


def normalizar_extensiones(extensiones):
    if extensiones is None:
        return []

    if isinstance(extensiones, str):
        valores = [extensiones]
    else:
        valores = extensiones

    normalizadas = []
    for item in valores:
        for parte in str(item).split(","):
            texto = parte.strip().lower().replace(".", "")
            if not texto:
                continue
            if texto not in normalizadas:
                normalizadas.append(texto)

    return normalizadas


def obtener_extension_archivo(ruta_archivo):
    if not ruta_archivo:
        return ""

    _, extension = os.path.splitext(str(ruta_archivo).strip())
    if not extension:
        return ""

    return extension.lstrip(".").lower()


def extension_permitida(ruta_archivo, extensiones):
    if not ruta_archivo:
        return False

    extensiones_normalizadas = normalizar_extensiones(extensiones)
    if not extensiones_normalizadas:
        return False

    extension = obtener_extension_archivo(ruta_archivo)
    return extension in extensiones_normalizadas


MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def normalizar_parte_fecha(valor):
    if valor in (None, "", "cualquiera", "any"):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def normalizar_condicion_fecha(condicion):
    condicion = condicion if isinstance(condicion, dict) else {}
    activo = condicion.get("activo", False)
    if isinstance(activo, str):
        activo = activo.strip().lower() in ("1", "true", "si", "yes", "on")

    campo = str(condicion.get("campo", "modificacion")).strip().lower()
    if campo not in ("creacion", "modificacion", "acceso"):
        campo = "modificacion"

    tipo = str(condicion.get("tipo", "parcial")).strip().lower()
    if tipo not in ("especifica", "parcial", "rango"):
        tipo = "parcial"

    def normalizar_extremo(extremo):
        extremo = extremo if isinstance(extremo, dict) else {}
        return {
            "dia": normalizar_parte_fecha(extremo.get("dia")),
            "mes": normalizar_parte_fecha(extremo.get("mes")),
            "año": normalizar_parte_fecha(extremo.get("año", extremo.get("ano"))),
        }

    resultado = {
        "activo": bool(activo),
        "campo": campo,
        "tipo": tipo,
        "rango": tipo == "rango",
    }
    if tipo == "rango":
        resultado["desde"] = normalizar_extremo(condicion.get("desde"))
        resultado["hasta"] = normalizar_extremo(condicion.get("hasta"))
    else:
        resultado.update(normalizar_extremo(condicion))
    return resultado


def obtener_fecha_archivo(ruta_archivo, campo):
    try:
        estadisticas = os.stat(ruta_archivo)
        timestamp = {
            "creacion": estadisticas.st_ctime,
            "modificacion": estadisticas.st_mtime,
            "acceso": estadisticas.st_atime,
        }.get(campo, estadisticas.st_mtime)
        return datetime.fromtimestamp(timestamp).date()
    except (OSError, OverflowError, ValueError):
        return None


def fecha_cumple_condicion(fecha, condicion):
    condicion = normalizar_condicion_fecha(condicion)
    if not condicion["activo"]:
        return True
    if fecha is None:
        return False

    def coincide_componentes(valor, extremo):
        return all(
            parte is None or getattr(valor, nombre) == parte
            for nombre, parte in (("day", extremo["dia"]), ("month", extremo["mes"]), ("year", extremo["año"]))
        )

    if condicion["tipo"] != "rango":
        return coincide_componentes(fecha, condicion)

    def limite(extremo, inferior):
        año = extremo["año"] if extremo["año"] is not None else (1 if inferior else 9999)
        mes = extremo["mes"] if extremo["mes"] is not None else (1 if inferior else 12)
        if extremo["dia"] is not None:
            dia = extremo["dia"]
        elif inferior:
            dia = 1
        else:
            dia = 31
        while dia > 28:
            try:
                return date(año, mes, dia)
            except ValueError:
                dia -= 1
        return date(año, mes, dia)

    try:
        return limite(condicion["desde"], True) <= fecha <= limite(condicion["hasta"], False)
    except (ValueError, OverflowError):
        return False


def archivo_cumple_fecha(ruta_archivo, condicion):
    condicion = normalizar_condicion_fecha(condicion)
    if not condicion["activo"]:
        return True
    return fecha_cumple_condicion(
        obtener_fecha_archivo(ruta_archivo, condicion["campo"]),
        condicion,
    )


def archivo_cumple_regla(ruta_archivo, regla):
    regla = normalizar_regla(regla)
    if obtener_palabra_clave_coincidente(ruta_archivo, regla["palabras"]) is None:
        return False

    if bool(regla.get("filtrar_extensiones", False)):
        if not extension_permitida(ruta_archivo, regla.get("extensiones", [])):
            return False

    if not archivo_cumple_fecha(ruta_archivo, regla.get("fecha_archivo")):
        return False

    return True


def normalizar_regla(regla):
    if regla is None:
        return {
            "palabras": [],
            "origen": "",
            "destino": "",
            "modo": "copy",
            "crear_subcarpetas": True,
            "eliminar_duplicados": False,
            "filtrar_extensiones": False,
            "extensiones": [],
            "fecha_archivo": normalizar_condicion_fecha({}),
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

    filtrar_extensiones = regla.get("filtrar_extensiones", False)
    if isinstance(filtrar_extensiones, str):
        filtrar_extensiones = filtrar_extensiones.strip().lower() in ("1", "true", "yes", "si", "on")

    extensiones = normalizar_extensiones(regla.get("extensiones", []))
    fecha_archivo = normalizar_condicion_fecha(regla.get("fecha_archivo"))

    return {
        "palabras": normalizar_palabras_clave(palabras),
        "origen": str(regla.get("origen", "")).strip(),
        "destino": normalizar_destino_regla(regla.get("destino", "")),
        "modo": modo,
        "crear_subcarpetas": bool(crear_subcarpetas),
        "eliminar_duplicados": bool(eliminar_duplicados),
        "filtrar_extensiones": bool(filtrar_extensiones),
        "extensiones": extensiones,
        "fecha_archivo": fecha_archivo,
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
        if (
            regla_normalizada["palabras"]
            and regla_normalizada["origen"]
            and regla_normalizada["destino"]
        ):
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
        if not regla_normalizada["palabras"]:
            continue

        if archivo_cumple_regla(ruta_archivo, regla_normalizada):
            return regla_normalizada

    return None


def obtener_nombre_unico(destino, nombre_archivo, crear_directorio=True):
    if crear_directorio and not os.path.isdir(destino):
        os.makedirs(destino, exist_ok=True)

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


def calcular_hash_archivo(ruta_archivo, chunk_size=1024 * 1024):
    if not os.path.isfile(ruta_archivo):
        raise FileNotFoundError(f"El archivo no existe: {ruta_archivo}")

    sha256 = hashlib.sha256()
    with open(ruta_archivo, "rb") as archivo:
        while True:
            bloque = archivo.read(chunk_size)
            if not bloque:
                break
            sha256.update(bloque)
    return sha256.hexdigest()


def buscar_duplicado_en_destino(destino, nombre_archivo, ruta_origen=None, tamaño=None):
    if not os.path.isdir(destino):
        return None

    ruta_destino = os.path.join(destino, nombre_archivo)
    if not os.path.isfile(ruta_destino):
        return None

    if ruta_origen is not None and os.path.abspath(ruta_origen) == os.path.abspath(ruta_destino):
        return None

    if tamaño is not None and os.path.getsize(ruta_destino) != tamaño:
        return None

    if ruta_origen is None:
        return ruta_destino

    try:
        tamaño_origen = os.path.getsize(ruta_origen)
        tamaño_destino = os.path.getsize(ruta_destino)
        if tamaño_origen != tamaño_destino:
            return None

        hash_origen = calcular_hash_archivo(ruta_origen)
        hash_destino = calcular_hash_archivo(ruta_destino)
        if hash_origen == hash_destino:
            return ruta_destino
    except (OSError, ValueError, TypeError):
        return None

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


def crear_operacion_analisis(ruta_archivo, regla, indice_regla):
    if not os.path.isfile(ruta_archivo):
        return None

    palabra_coincidente = obtener_palabra_clave_coincidente(ruta_archivo, regla["palabras"])
    if palabra_coincidente is None:
        return None

    if bool(regla.get("filtrar_extensiones", False)) and not extension_permitida(ruta_archivo, regla.get("extensiones", [])):
        return None

    nombre_archivo = os.path.basename(ruta_archivo)
    destino_directorio = os.path.normpath(regla["destino"])
    if regla.get("crear_subcarpetas", True):
        destino_directorio = os.path.normpath(os.path.join(regla["destino"], palabra_coincidente))

    destino_base = os.path.join(destino_directorio, nombre_archivo)
    duplicado = buscar_duplicado_en_destino(destino_directorio, nombre_archivo, ruta_origen=ruta_archivo)

    if duplicado is not None:
        destino_final = destino_base
        estado = "Duplicado"
        if bool(regla.get("eliminar_duplicados", False)):
            estado = "Duplicado - se eliminaría del origen al ejecutar"
    elif os.path.exists(destino_base):
        destino_final = obtener_nombre_unico(destino_directorio, nombre_archivo, crear_directorio=False)
        estado = "Listo"
    else:
        destino_final = destino_base
        estado = "Listo"

    return {
        "id": uuid.uuid4().hex,
        "seleccionado": True,
        "archivo": nombre_archivo,
        "origen": ruta_archivo,
        "regla": indice_regla,
        "palabra": palabra_coincidente,
        "modo": regla.get("modo", "copy"),
        "accion": "Mover" if regla.get("modo", "copy") == "move" else "Copiar",
        "destino": destino_directorio,
        "destino_final": destino_final,
        "estado": estado,
        "duplicado": duplicado is not None,
        "eliminar_duplicados": bool(regla.get("eliminar_duplicados", False)),
    }


def generar_operaciones_analisis(reglas, ui_callback=None, cancel_event=None):
    reglas = [normalizar_regla(regla) for regla in (reglas or [])]
    reglas = [regla for regla in reglas if regla["palabras"] and regla["origen"] and regla["destino"]]

    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Proceso cancelado por el usuario.")

    if not reglas:
        return []

    operaciones = []
    archivos_vistos = set()
    total_archivos = 0

    for regla in reglas:
        origen = regla["origen"]
        if not os.path.isdir(origen):
            continue
        for _, _, lista_archivos in os.walk(origen):
            total_archivos += len(lista_archivos)

    if ui_callback is not None:
        ui_callback({"tipo": "analisis", "valor": 0, "texto": "0 archivos analizados"})

    archivos_analizados = 0
    for indice_regla, regla in enumerate(reglas, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Proceso cancelado por el usuario.")

        origen = regla["origen"]
        if not os.path.isdir(origen):
            continue

        for raiz, _, lista_archivos in os.walk(origen):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Proceso cancelado por el usuario.")

            for nombre in sorted(lista_archivos):
                ruta_archivo = os.path.join(raiz, nombre)
                archivos_analizados += 1
                if total_archivos:
                    porcentaje = min(100, int((archivos_analizados / total_archivos) * 100))
                else:
                    porcentaje = 100

                if ui_callback is not None:
                    ui_callback({
                        "tipo": "analisis",
                        "valor": porcentaje,
                        "texto": f"{archivos_analizados} archivos analizados"
                    })

                if ruta_archivo in archivos_vistos:
                    continue

                if not archivo_cumple_regla(ruta_archivo, regla):
                    continue

                operacion = crear_operacion_analisis(ruta_archivo, regla, indice_regla)
                if operacion is None:
                    continue

                operaciones.append(operacion)
                archivos_vistos.add(ruta_archivo)

    if ui_callback is not None:
        ui_callback({"tipo": "preview_total", "valor": len(operaciones)})

    return operaciones


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

    actualizar_estado("Analizando reglas y archivos...")
    registrar_log(f"Reglas activas: {len(reglas)}")
    for index, regla in enumerate(reglas, start=1):
        registrar_log(f"{index}. {', '.join(regla['palabras'])} -> {regla['origen']} -> {regla['destino']}")

    operaciones = generar_operaciones_analisis(reglas, ui_callback=ui_callback, cancel_event=cancel_event)
    total = len(operaciones)
    registrar_log(f"Operaciones preparadas: {total}")
    enviar({"tipo": "total", "valor": total})
    enviar({"tipo": "total_archivos", "valor": total})

    if total == 0:
        actualizar_estado("Sin coincidencias por procesar.")
        registrar_log("No se encontraron coincidencias con ninguna regla activa.")
        return 0

    for operacion in operaciones:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Proceso cancelado por el usuario.")
        registrar_log(f"Archivo: {operacion['archivo']} | Regla: {operacion['regla']} | Destino: {operacion['destino_final']} | Estado: {operacion['estado']}")

    return ejecutar_operaciones(operaciones, ui_callback=ui_callback, cancel_event=cancel_event)


def generar_vista_previa(reglas, ui_callback=None, cancel_event=None):
    return generar_operaciones_analisis(reglas, ui_callback=ui_callback, cancel_event=cancel_event)


def ejecutar_operaciones(operaciones, ui_callback=None, cancel_event=None):
    seleccionadas = []
    for operacion in operaciones or []:
        if not bool(operacion.get("seleccionado", False)):
            continue

        origen = operacion.get("origen")
        if not origen or not os.path.isfile(origen):
            if ui_callback is not None:
                ui_callback({"tipo": "log", "mensaje": f"Archivo ya no existe y se omite: {origen}"})
            continue

        seleccionadas.append(dict(operacion))

    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Proceso cancelado por el usuario.")

    if not seleccionadas:
        if ui_callback is not None:
            ui_callback({"tipo": "estado", "estado": "No hay archivos seleccionados para ejecutar."})
        return 0

    total = len(seleccionadas)
    procesados = 0

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

    actualizar_estado("Procesando archivos seleccionados...")
    registrar_log(f"Archivos seleccionados para ejecutar: {total}")

    for operacion in seleccionadas:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Proceso cancelado por el usuario.")

        origen = operacion.get("origen")
        archivo = operacion.get("archivo", os.path.basename(origen))
        destino_final = operacion.get("destino_final") or os.path.join(operacion.get("destino", ""), archivo)
        destino_directorio = os.path.dirname(destino_final)
        modo = operacion.get("modo", "copy")
        eliminar_duplicados = bool(operacion.get("eliminar_duplicados", False))
        duplicado = bool(operacion.get("duplicado", False))

        if not os.path.isfile(origen):
            registrar_log(f"Archivo ya no existe y se omite: {origen}")
            continue

        os.makedirs(destino_directorio, exist_ok=True)

        if duplicado:
            if eliminar_duplicados:
                try:
                    os.remove(origen)
                    registrar_log(f"Archivo duplicado detectado. Archivo original eliminado del origen: {archivo}")
                    actualizar_estado(f"Archivo duplicado detectado. Archivo original eliminado del origen: {archivo}")
                except Exception as exc:
                    registrar_log(f"Error al eliminar duplicado {archivo}: {exc}")
            else:
                registrar_log(f"Archivo duplicado detectado. Se mantiene el original en el origen: {archivo}")
            procesados += 1
            porcentaje = (procesados / total * 100) if total else 100
            actualizar_analisis(porcentaje, f"{porcentaje:.0f}% procesado")
            continue

        try:
            destino_base = os.path.join(destino_directorio, archivo)
            if os.path.exists(destino_base):
                duplicado_real = buscar_duplicado_en_destino(destino_directorio, archivo, ruta_origen=origen)
                if duplicado_real is not None:
                    if eliminar_duplicados:
                        os.remove(origen)
                        registrar_log(f"Archivo duplicado detectado. Archivo original eliminado del origen: {archivo}")
                        actualizar_estado(f"Archivo duplicado detectado. Archivo original eliminado del origen: {archivo}")
                    else:
                        registrar_log(f"Archivo duplicado detectado. Se mantiene el original en el origen: {archivo}")
                    procesados += 1
                    porcentaje = (procesados / total * 100) if total else 100
                    actualizar_analisis(porcentaje, f"{porcentaje:.0f}% procesado")
                    continue
                destino_final = obtener_nombre_unico(destino_directorio, archivo)
            else:
                destino_final = destino_base

            if os.path.exists(destino_final):
                duplicado_real = buscar_duplicado_en_destino(destino_directorio, os.path.basename(destino_final), ruta_origen=origen)
                if duplicado_real is not None:
                    if eliminar_duplicados:
                        os.remove(origen)
                        registrar_log(f"Archivo duplicado detectado. Archivo original eliminado del origen: {archivo}")
                        actualizar_estado(f"Archivo duplicado detectado. Archivo original eliminado del origen: {archivo}")
                    else:
                        registrar_log(f"Archivo duplicado detectado. Se mantiene el original en el origen: {archivo}")
                    procesados += 1
                    porcentaje = (procesados / total * 100) if total else 100
                    actualizar_analisis(porcentaje, f"{porcentaje:.0f}% procesado")
                    continue

            if modo == "copy":
                actualizar_actual(0, "0%", f"Copiando: {archivo}")
                if os.path.exists(destino_final):
                    destino_final = obtener_nombre_unico(destino_directorio, archivo)
                copiar_archivo_con_progreso(origen, destino_final, ui_callback=ui_callback, cancel_event=cancel_event)
                actualizar_actual(100, "100%", f"Copiado: {archivo}")
                registrar_log(f"Archivo copiado correctamente: {archivo}")
            elif modo == "move":
                actualizar_actual(0, "0%", f"Moviendo: {archivo}")
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Proceso cancelado por el usuario.")
                if os.path.exists(destino_final):
                    destino_final = obtener_nombre_unico(destino_directorio, archivo)
                shutil.move(origen, destino_final)
                actualizar_actual(100, "100%", f"Movido: {archivo}")
                registrar_log(f"Archivo movido correctamente: {archivo}")
        except Exception as exc:
            registrar_log(f"Error al procesar {archivo}: {exc}")
            actualizar_actual(0, "0%", f"Error: {exc}")
            if cancel_event is not None and cancel_event.is_set():
                raise

        procesados += 1
        porcentaje = (procesados / total * 100) if total else 100
        actualizar_analisis(porcentaje, f"{porcentaje:.0f}% procesado")

    if cancel_event is not None and cancel_event.is_set():
        actualizar_estado("Proceso cancelado por el usuario.")
        registrar_log("Proceso cancelado por el usuario.")
        return procesados

    actualizar_actual(100, "100%", "Proceso finalizado.")
    actualizar_analisis(100, "100% procesado")
    actualizar_estado("Proceso finalizado.")
    registrar_log(f"Proceso terminado. Archivos procesados: {procesados}")
    return procesados


class ConstructorFecha(QFrame):
    def __init__(self, condicion=None, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._años = list(range(1900, datetime.now().year + 11))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.activado = QCheckBox("Fecha del archivo")
        layout.addWidget(self.activado)

        self.contenido = QWidget()
        contenido_layout = QVBoxLayout(self.contenido)
        contenido_layout.setContentsMargins(0, 0, 0, 0)
        contenido_layout.setSpacing(8)

        fila_opciones = QHBoxLayout()
        fila_opciones.addWidget(QLabel("Evaluar:"))
        self.campo = QComboBox()
        self.campo.addItem("Fecha de creación", "creacion")
        self.campo.addItem("Fecha de modificación", "modificacion")
        self.campo.addItem("Fecha de acceso", "acceso")
        fila_opciones.addWidget(self.campo)
        fila_opciones.addSpacing(12)
        fila_opciones.addWidget(QLabel("Modo:"))
        self.tipo = QComboBox()
        self.tipo.addItem("Fecha específica", "especifica")
        self.tipo.addItem("Coincidencia parcial", "parcial")
        self.tipo.addItem("Rango", "rango")
        fila_opciones.addWidget(self.tipo)
        fila_opciones.addStretch()
        contenido_layout.addLayout(fila_opciones)

        self.extremo_simple = self._crear_extremo()
        self.desde = self._crear_extremo("Desde")
        self.hasta = self._crear_extremo("Hasta")
        self.rango = QWidget()
        rango_layout = QVBoxLayout(self.rango)
        rango_layout.setContentsMargins(0, 0, 0, 0)
        rango_layout.addWidget(self.desde)
        rango_layout.addWidget(self.hasta)
        contenido_layout.addWidget(self.extremo_simple)
        contenido_layout.addWidget(self.rango)
        layout.addWidget(self.contenido)

        self.activado.toggled.connect(self._actualizar_estado)
        self.tipo.currentIndexChanged.connect(self._actualizar_tipo)
        self._establecer_condicion(condicion or {})

    def _crear_extremo(self, titulo=None):
        extremo = QFrame()
        extremo_layout = QGridLayout(extremo)
        extremo_layout.setContentsMargins(0, 0, 0, 0)
        if titulo:
            extremo_layout.addWidget(QLabel(titulo.upper()), 0, 0, 1, 3)
            fila = 1
        else:
            fila = 0
        extremo.selectores = {}
        for columna, (nombre, etiqueta) in enumerate((("dia", "Día"), ("mes", "Mes"), ("año", "Año"))):
            extremo_layout.addWidget(QLabel(etiqueta), fila, columna)
            selector = QComboBox()
            selector.addItem("Cualquiera", None)
            if nombre == "dia":
                valores = range(1, 32)
            elif nombre == "mes":
                valores = enumerate(MESES, start=1)
            else:
                valores = ((año, str(año)) for año in self._años)
            for valor in valores:
                if nombre == "mes":
                    numero, texto = valor
                    selector.addItem(texto, numero)
                elif nombre == "año":
                    numero, texto = valor
                    selector.addItem(texto, numero)
                else:
                    selector.addItem(f"{valor:02d}", valor)
            extremo_layout.addWidget(selector, fila + 1, columna)
            extremo.selectores[nombre] = selector
        return extremo

    def _establecer_extremo(self, extremo, datos):
        datos = datos if isinstance(datos, dict) else {}
        for nombre, selector in extremo.selectores.items():
            valor = normalizar_parte_fecha(datos.get(nombre))
            indice = selector.findData(valor)
            selector.setCurrentIndex(indice if indice >= 0 else 0)

    def _leer_extremo(self, extremo):
        return {nombre: selector.currentData() for nombre, selector in extremo.selectores.items()}

    def _establecer_condicion(self, condicion):
        condicion = normalizar_condicion_fecha(condicion)
        self.activado.setChecked(condicion["activo"])
        self.campo.setCurrentIndex(max(0, self.campo.findData(condicion["campo"])))
        self.tipo.setCurrentIndex(max(0, self.tipo.findData(condicion["tipo"])))
        if condicion["tipo"] == "rango":
            self._establecer_extremo(self.desde, condicion["desde"])
            self._establecer_extremo(self.hasta, condicion["hasta"])
        else:
            self._establecer_extremo(self.extremo_simple, condicion)
        self._actualizar_estado()
        self._actualizar_tipo()

    def _actualizar_estado(self):
        self.contenido.setVisible(self.activado.isChecked())

    def _actualizar_tipo(self):
        es_rango = self.tipo.currentData() == "rango"
        self.extremo_simple.setVisible(not es_rango)
        self.rango.setVisible(es_rango)
        self.contenido.updateGeometry()

    def obtener_condicion(self):
        condicion = {
            "activo": self.activado.isChecked(),
            "campo": self.campo.currentData(),
            "tipo": self.tipo.currentData(),
        }
        if condicion["tipo"] == "rango":
            condicion["desde"] = self._leer_extremo(self.desde)
            condicion["hasta"] = self._leer_extremo(self.hasta)
        else:
            condicion.update(self._leer_extremo(self.extremo_simple))
        return normalizar_condicion_fecha(condicion)


class Aplicacion(QMainWindow):
    def __init__(self):
        super().__init__()
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feather.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle("FileFlow")
        self.resize(1100, 900)
        self.setMinimumSize(860, 620)
        self.setStyleSheet(
            """
            QWidget { background: #edf3fb; color: #1f2937; }
            QFrame#panel { background: #f8fbff; border: 1px solid #dfe7f1; border-radius: 12px; }
            QLabel { background: transparent; }
            QLabel#title { font-size: 28px; font-weight: 700; color: #0f172a; }
            QLabel#subtitle { font-size: 11px; color: #475569; }
            QLabel#status { font-size: 11px; color: #0f172a; }
            QTableWidget { background: #ffffff; border: 1px solid #dfe7f1; border-radius: 10px; gridline-color: #e5edf8; }
            QHeaderView::section { background: #dfeafc; color: #0f172a; padding: 8px; border: none; font-weight: 700; }
            QProgressBar { border: 1px solid #dfe7f1; border-radius: 8px; text-align: center; background: #edf3fb; }
            QProgressBar::chunk { background: #2563eb; border-radius: 7px; }
            QPushButton { background: #e5edf8; border: none; border-radius: 10px; padding: 10px 14px; font-weight: 700; color: #0f172a; }
            QPushButton:hover { background: #d7e3f5; }
            QPushButton:pressed { background: #cfe0f7; }
            QPushButton#primary { background: #2563eb; color: white; }
            QPushButton#primary:hover { background: #1d4ed8; }
            QPushButton#primary:pressed { background: #1e40af; }
            QPushButton:disabled { background: #cbd5e1; color: #64748b; }
            QLineEdit, QPlainTextEdit, QComboBox, QCheckBox { background: #ffffff; color: #111827; border: 1px solid #dfe7f1; border-radius: 8px; padding: 8px 10px; }
            QPlainTextEdit { padding: 10px; }
            QDialog { background: #edf3fb; }
            QDialog QPushButton { min-width: 120px; }
            """
        )

        self._procesando = False
        self._cola = queue.Queue()
        self.cancel_event = None
        self._hilo_proceso = None
        self._seleccion_preview_vigente = None

        reglas_guardadas = cargar_reglas()
        self.reglas = reglas_guardadas if reglas_guardadas is not None else []
        if reglas_guardadas is None:
            QMessageBox.warning(
                self,
                "Reglas",
                "El archivo de reglas está corrupto o no se pudo leer. Se inició con una lista vacía."
            )

        self.var_progreso_actual = 0
        self.var_progreso_analisis = 0
        self.var_texto_actual = QLabel("0%")
        self.var_texto_analisis = QLabel("0% analizado")
        self.var_estado = QLabel("Listo para iniciar.")
        self.var_estado.setObjectName("status")
        self.var_total_archivos = QLabel("Total encontrados: 0")
        self.var_reglas_count = QLabel("Reglas configuradas: 0")
        self.var_reglas_activas = QLabel("REGLAS ACTIVAS: 0")

        self._crear_interfaz()
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_reglas()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._procesar_cola)
        self._timer.start(50)

    def _crear_interfaz(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.setContentsMargins(0, 0, 0, 0)

        title = QLabel("FileFlow")
        title.setObjectName("title")
        title_row.addWidget(title)

        icon_label = QLabel()
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feather.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pixmap)
            icon_label.setFixedSize(28, 28)
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setStyleSheet("background: transparent;")
        title_row.addWidget(icon_label)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        subtitle = QLabel("Organizador de archivos mediante reglas automáticas.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        reglas_frame = QFrame()
        reglas_frame.setObjectName("panel")
        reglas_layout = QVBoxLayout(reglas_frame)
        reglas_layout.setContentsMargins(14, 12, 14, 12)
        reglas_layout.setSpacing(10)

        titulo_reglas = QLabel("Reglas de clasificación")
        titulo_reglas.setStyleSheet("font-weight: 700;")
        reglas_layout.addWidget(titulo_reglas)

        self.tree_reglas = QTableWidget(0, 3)
        self.tree_reglas.setHorizontalHeaderLabels(["Prioridad", "Palabras clave", "Destino"])
        self.tree_reglas.setAlternatingRowColors(True)
        self.tree_reglas.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree_reglas.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree_reglas.verticalHeader().setVisible(False)
        self.tree_reglas.horizontalHeader().setStretchLastSection(True)
        self.tree_reglas.setColumnWidth(0, 90)
        self.tree_reglas.setColumnWidth(1, 260)
        self.tree_reglas.setColumnWidth(2, 420)
        self.tree_reglas.setEditTriggers(QAbstractItemView.NoEditTriggers)
        reglas_layout.addWidget(self.tree_reglas)

        btns_reglas = QHBoxLayout()
        btns_reglas.addWidget(self._crear_boton("+ Agregar regla", self._agregar_regla))
        btns_reglas.addWidget(self._crear_boton("Editar regla", self._editar_regla))
        btns_reglas.addWidget(self._crear_boton("Eliminar regla", self._eliminar_regla))
        btns_reglas.addWidget(self._crear_boton("↑ Subir", self._subir_regla))
        btns_reglas.addWidget(self._crear_boton("↓ Bajar", self._bajar_regla))
        reglas_layout.addLayout(btns_reglas)
        layout.addWidget(reglas_frame)

        layout.addWidget(self.var_reglas_count)
        layout.addWidget(self.var_reglas_activas)
        label_info = QLabel("Las reglas se aplican de arriba hacia abajo.")
        label_info.setStyleSheet("color: #475569;")
        layout.addWidget(label_info)

        progreso_frame = QFrame()
        progreso_frame.setObjectName("panel")
        progreso_layout = QVBoxLayout(progreso_frame)
        progreso_layout.setContentsMargins(14, 12, 14, 12)

        progreso_layout.addWidget(QLabel("Archivo actual:"))
        self.barra_actual = QProgressBar()
        self.barra_actual.setRange(0, 100)
        progreso_layout.addWidget(self.barra_actual)
        self.var_texto_actual.setAlignment(Qt.AlignRight)
        progreso_layout.addWidget(self.var_texto_actual)

        progreso_layout.addWidget(QLabel("Carpeta de origen analizada:"))
        self.barra_analisis = QProgressBar()
        self.barra_analisis.setRange(0, 100)
        progreso_layout.addWidget(self.barra_analisis)
        self.var_texto_analisis.setAlignment(Qt.AlignRight)
        progreso_layout.addWidget(self.var_texto_analisis)
        progreso_layout.addWidget(self.var_total_archivos)

        layout.addWidget(progreso_frame)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(120)
        layout.addWidget(self.log_text)
        layout.addWidget(self.var_estado)

        botones = QHBoxLayout()
        self.boton_vista_previa = self._crear_boton("Vista previa", self._abrir_vista_previa)
        self.boton_iniciar = self._crear_boton("Iniciar", self._iniciar_proceso, primary=True)
        self.boton_cancelar = self._crear_boton("Cancelar", self._cancelar_proceso)
        self.boton_cancelar.setEnabled(False)
        botones.addWidget(self.boton_vista_previa)
        botones.addWidget(self.boton_iniciar)
        botones.addWidget(self.boton_cancelar)
        layout.addLayout(botones)

    def _crear_boton(self, texto, callback, primary=False):
        boton = QPushButton(texto)
        if primary:
            boton.setObjectName("primary")
        boton.clicked.connect(callback)
        return boton

    def _guardar_reglas_estado(self):
        guardar_reglas(self.reglas)
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_reglas()

    def _actualizar_tabla_reglas(self):
        self.tree_reglas.setRowCount(0)
        for indice, regla in enumerate(self.reglas, start=1):
            palabras = ", ".join(regla.get("palabras", []))
            destino = regla.get("destino", "")
            row = self.tree_reglas.rowCount()
            self.tree_reglas.insertRow(row)
            self.tree_reglas.setItem(row, 0, QTableWidgetItem(str(indice)))
            self.tree_reglas.setItem(row, 1, QTableWidgetItem(palabras))
            self.tree_reglas.setItem(row, 2, QTableWidgetItem(destino))
        self.var_reglas_count.setText(f"Reglas configuradas: {len(self.reglas)}")

    def _actualizar_resumen_reglas(self):
        self.var_reglas_activas.setText(f"REGLAS ACTIVAS: {len(self.reglas)}")
        if not self.reglas:
            self.var_estado.setText("Debes crear al menos una regla de clasificación.")

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
        if bool(regla.get("filtrar_extensiones", False)):
            extensiones = normalizar_extensiones(regla.get("extensiones", []))
            if not extensiones:
                raise ValueError("Debes introducir al menos una extensión cuando activas el filtro.")
            regla["extensiones"] = extensiones
        else:
            regla["extensiones"] = []
        for palabra in palabras:
            if not palabra.strip():
                raise ValueError("Las palabras clave no pueden estar vacías.")
        for indice, item in enumerate(self.reglas):
            if indice == indice_actual:
                continue
            if normalizar_regla(item) == regla:
                raise ValueError("Esta regla ya existe.")
        return regla

    def _mostrar_ventana_regla(self, regla=None):
        editar = regla is not None
        ventana = QDialog(self)
        ventana.setWindowTitle("Editar regla" if editar else "Agregar regla")
        ventana.resize(700, 720)
        ventana.setMinimumSize(680, 680)
        layout = QVBoxLayout(ventana)
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Palabras clave:"))
        entrada_palabras = QLineEdit()
        layout.addWidget(entrada_palabras)

        origen_default = (regla or {}).get("origen", "")
        destino_default = (regla or {}).get("destino", "")
        modo_default = (regla or {}).get("modo", "copy")
        eliminar_default = bool((regla or {}).get("eliminar_duplicados", False))
        crear_default = bool((regla or {}).get("crear_subcarpetas", True))
        filtrar_extensiones_default = bool((regla or {}).get("filtrar_extensiones", False))
        extensiones_default = ", ".join((regla or {}).get("extensiones", []))
        fecha_default = (regla or {}).get("fecha_archivo", {})

        frame_origen = QFrame()
        origen_layout = QVBoxLayout(frame_origen)
        origen_layout.addWidget(QLabel("Carpeta de origen:"))
        var_origen = QLineEdit(origen_default)
        row_origen = QHBoxLayout()
        row_origen.addWidget(var_origen)
        btn_origen = QPushButton("Buscar")
        btn_origen.clicked.connect(lambda: self._seleccionar_origen_regla(var_origen))
        row_origen.addWidget(btn_origen)
        origen_layout.addLayout(row_origen)
        layout.addWidget(frame_origen)

        frame_destino = QFrame()
        destino_layout = QVBoxLayout(frame_destino)
        destino_layout.addWidget(QLabel("Carpeta de destino:"))
        var_destino = QLineEdit(destino_default)
        row_destino = QHBoxLayout()
        row_destino.addWidget(var_destino)
        btn_destino = QPushButton("Buscar")
        btn_destino.clicked.connect(lambda: self._seleccionar_destino_regla(var_destino))
        row_destino.addWidget(btn_destino)
        destino_layout.addLayout(row_destino)
        layout.addWidget(frame_destino)

        var_filtrar_extensiones = QCheckBox("Filtrar por extensiones")
        var_filtrar_extensiones.setChecked(filtrar_extensiones_default)
        layout.addWidget(var_filtrar_extensiones)

        extensiones_layout = QVBoxLayout()
        label_extensiones = QLabel("Extensiones:")
        extensiones_layout.addWidget(label_extensiones)
        var_extensiones = QLineEdit(extensiones_default)
        var_extensiones.setPlaceholderText("Ejemplo: jpg, png, pdf")
        var_extensiones.setEnabled(filtrar_extensiones_default)
        extensiones_layout.addWidget(var_extensiones)
        layout.addLayout(extensiones_layout)

        var_filtrar_extensiones.toggled.connect(var_extensiones.setEnabled)

        constructor_fecha = ConstructorFecha(fecha_default)
        layout.addWidget(constructor_fecha)

        def reajustar_tamaño_ventana():
            ventana.setMinimumHeight(680)
            layout.activate()
            altura = max(ventana.minimumHeight(), layout.sizeHint().height())
            ventana.resize(ventana.width(), altura)

        constructor_fecha.activado.toggled.connect(
            lambda: QTimer.singleShot(0, reajustar_tamaño_ventana)
        )
        constructor_fecha.tipo.currentIndexChanged.connect(
            lambda: QTimer.singleShot(0, reajustar_tamaño_ventana)
        )

        layout.addWidget(QLabel("Acción:"))
        var_modo = QComboBox()
        var_modo.addItem("Copiar archivos", "copy")
        var_modo.addItem("Mover archivos", "move")
        var_modo.setCurrentIndex(0 if modo_default == "copy" else 1)
        layout.addWidget(var_modo)

        var_crear_subcarpetas = QCheckBox("Crear carpetas automáticamente según la regla")
        var_crear_subcarpetas.setChecked(crear_default)
        layout.addWidget(var_crear_subcarpetas)

        var_eliminar_duplicados = QCheckBox("Eliminar archivos del origen si ya existen exactamente iguales en el destino")
        var_eliminar_duplicados.setChecked(eliminar_default)
        layout.addWidget(var_eliminar_duplicados)

        if editar and regla:
            entrada_palabras.setText(", ".join(regla.get("palabras", [])))

        accept_buttons = QHBoxLayout()
        accept_buttons.addStretch()
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(ventana.close)
        guardar_btn = QPushButton("Guardar regla")
        guardar_btn.setObjectName("primary")

        def guardar():
            try:
                palabras_texto = entrada_palabras.text().strip()
                palabras = [p.strip() for p in palabras_texto.split(",") if p.strip()]
                nueva_regla = {
                    "palabras": palabras,
                    "origen": var_origen.text().strip(),
                    "destino": normalizar_destino_regla(var_destino.text().strip()),
                    "modo": var_modo.currentData(),
                    "crear_subcarpetas": bool(var_crear_subcarpetas.isChecked()),
                    "eliminar_duplicados": bool(var_eliminar_duplicados.isChecked()),
                    "filtrar_extensiones": bool(var_filtrar_extensiones.isChecked()),
                    "extensiones": var_extensiones.text().strip(),
                    "fecha_archivo": constructor_fecha.obtener_condicion(),
                }
                indice_actual = self.reglas.index(regla) if editar else None
                regla_validada = self._validar_regla(nueva_regla, indice_actual=indice_actual)
                if editar:
                    self.reglas[indice_actual] = regla_validada
                else:
                    self.reglas.append(regla_validada)
                guardar_reglas(self.reglas)
                self._invalidar_vista_previa()
                self._actualizar_tabla_reglas()
                self._actualizar_resumen_reglas()
                ventana.accept()
            except ValueError as exc:
                QMessageBox.warning(self, "Error", str(exc))

        guardar_btn.clicked.connect(guardar)
        accept_buttons.addWidget(cancelar)
        accept_buttons.addWidget(guardar_btn)
        layout.addLayout(accept_buttons)
        QTimer.singleShot(0, reajustar_tamaño_ventana)
        ventana.exec()

    def _seleccionar_origen_regla(self, var_origen):
        carpeta = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta de origen de la regla")
        if carpeta:
            var_origen.setText(carpeta)

    def _seleccionar_destino_regla(self, var_destino_regla):
        destino_rel = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta destino de la regla")
        if destino_rel:
            var_destino_regla.setText(normalizar_destino_regla(destino_rel))

    def _agregar_regla(self):
        self._mostrar_ventana_regla()

    def _editar_regla(self):
        row = self.tree_reglas.currentRow()
        if row < 0:
            QMessageBox.information(self, "Reglas", "Selecciona una regla para editar.")
            return
        regla = self.reglas[row]
        self._mostrar_ventana_regla(regla)

    def _eliminar_regla(self):
        row = self.tree_reglas.currentRow()
        if row < 0:
            QMessageBox.information(self, "Reglas", "Selecciona una regla para eliminar.")
            return
        regla = self.reglas[row]
        texto = f"{', '.join(regla.get('palabras', []))} → {regla.get('destino', '')}"
        respuesta = QMessageBox.question(self, "Eliminar regla", f"¿Quieres eliminar la regla \"{texto}\"?")
        if respuesta != QMessageBox.Yes:
            return
        del self.reglas[row]
        guardar_reglas(self.reglas)
        self._invalidar_vista_previa()
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_reglas()

    def _subir_regla(self):
        row = self.tree_reglas.currentRow()
        if row <= 0:
            return
        self.reglas[row - 1], self.reglas[row] = self.reglas[row], self.reglas[row - 1]
        guardar_reglas(self.reglas)
        self._invalidar_vista_previa()
        self._actualizar_tabla_reglas()

    def _bajar_regla(self):
        row = self.tree_reglas.currentRow()
        if row < 0 or row >= len(self.reglas) - 1:
            return
        self.reglas[row], self.reglas[row + 1] = self.reglas[row + 1], self.reglas[row]
        guardar_reglas(self.reglas)
        self._invalidar_vista_previa()
        self._actualizar_tabla_reglas()

    def _invalidar_vista_previa(self):
        self._seleccion_preview_vigente = None

    def _registrar_log(self, mensaje):
        self.log_text.appendPlainText(mensaje)

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
                self.var_progreso_actual = float(dato.get("valor", 0))
                self.barra_actual.setValue(int(self.var_progreso_actual))
                self.var_texto_actual.setText(dato.get("texto", "0%"))
                if dato.get("estado"):
                    self.var_estado.setText(dato["estado"])
            elif tipo == "analisis":
                self.var_progreso_analisis = float(dato.get("valor", 0))
                self.barra_analisis.setValue(int(self.var_progreso_analisis))
                self.var_texto_analisis.setText(dato.get("texto", "0% analizado"))
            elif tipo == "estado":
                self.var_estado.setText(dato.get("estado", "Listo para iniciar."))
            elif tipo == "log":
                self._registrar_log(dato.get("mensaje", ""))
            elif tipo == "total":
                self.var_total_archivos.setText(f"Total encontrados: {dato.get('valor', 0)}")
            elif tipo == "total_archivos":
                self.var_total_archivos.setText(f"Total encontrados: {dato.get('valor', 0)}")
            elif tipo == "error":
                mensaje = dato.get("mensaje", "Error desconocido.")
                self.var_estado.setText(f"Error: {mensaje}")
                self._registrar_log(f"ERROR: {mensaje}")
                QMessageBox.critical(self, "Error", mensaje)
            elif tipo == "terminado":
                cancelado = dato.get("cancelado", False)
                error = dato.get("error")
                self._procesando = False
                self.boton_iniciar.setEnabled(True)
                self.boton_vista_previa.setEnabled(True)
                self.boton_cancelar.setEnabled(False)
                if error is not None:
                    self.var_estado.setText(f"Error: {error}")
                elif cancelado:
                    self.var_estado.setText("Proceso cancelado por el usuario.")
                else:
                    self.var_estado.setText("Proceso finalizado.")
                    self.var_progreso_actual = 100
                    self.var_progreso_analisis = 100
                    self.barra_actual.setValue(100)
                    self.barra_analisis.setValue(100)
                    self.var_texto_actual.setText("100%")
                    self.var_texto_analisis.setText("100% procesado")
                self._registrar_log("Proceso finalizado.")
                self.cancel_event = None

    def _cancelar_proceso(self):
        if not self._procesando:
            return
        evento = self.cancel_event
        if evento is not None:
            evento.set()
        self.var_estado.setText("Cancelando proceso...")
        self.boton_cancelar.setEnabled(False)

    def _toggle_preview_button_state(self, activo=True):
        self.boton_vista_previa.setEnabled(activo)

    def _abrir_vista_previa(self):
        if self._procesando:
            return
        if not self.reglas:
            QMessageBox.critical(self, "Error", "Debes crear al menos una regla de clasificación.")
            return
        reglas_para_proceso = [normalizar_regla(regla) for regla in self.reglas]
        reglas_para_proceso = [regla for regla in reglas_para_proceso if regla["palabras"] and regla["origen"] and regla["destino"]]
        if not reglas_para_proceso:
            QMessageBox.critical(self, "Error", "Cada regla debe incluir una carpeta de origen y una de destino.")
            return

        self._preview_queue = queue.Queue()
        self._preview_cancel_event = threading.Event()
        self._preview_operaciones = []

        ventana = QDialog(self)
        ventana.setWindowTitle("Vista previa - FileFlow")
        ventana.resize(1100, 700)
        ventana.setMinimumSize(900, 600)
        layout = QVBoxLayout(ventana)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.preview_total_var = QLabel("Archivos encontrados: 0")
        self.preview_pendientes_var = QLabel("Operaciones pendientes: 0")
        self.preview_excluidos_var = QLabel("Excluidos: 0")
        self.preview_copiar_var = QLabel("Copiar: 0")
        self.preview_mover_var = QLabel("Mover: 0")
        self.preview_duplicados_var = QLabel("Duplicados detectados: 0")
        self.preview_errores_var = QLabel("Errores: 0")

        resumen = QHBoxLayout()
        resumen.addWidget(self.preview_total_var)
        resumen.addWidget(self.preview_pendientes_var)
        resumen.addWidget(self.preview_excluidos_var)
        resumen.addWidget(self.preview_copiar_var)
        resumen.addWidget(self.preview_mover_var)
        resumen.addWidget(self.preview_duplicados_var)
        resumen.addWidget(self.preview_errores_var)
        layout.addLayout(resumen)

        filtro = QHBoxLayout()
        filtro.addWidget(QLabel("Buscar archivo:"))
        self.preview_busqueda = QLineEdit()
        filtro.addWidget(self.preview_busqueda)
        layout.addLayout(filtro)
        self.preview_busqueda.textChanged.connect(self._filtrar_preview)

        self.preview_barra = QProgressBar()
        self.preview_barra.setRange(0, 100)
        layout.addWidget(self.preview_barra)
        self.preview_barra_label = QLabel("Analizando archivos para generar vista previa...")
        layout.addWidget(self.preview_barra_label)

        self.preview_table = QTableWidget(0, 8)
        self.preview_table.setHorizontalHeaderLabels(["ID", "Seleccionado", "Archivo", "Regla", "Palabra clave", "Acción", "Origen", "Destino"])
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.doubleClicked.connect(self._alternar_fila_preview)
        layout.addWidget(self.preview_table)

        botones_preview = QHBoxLayout()
        botones_preview.addWidget(self._crear_boton("Seleccionar todos", self._seleccionar_todos_preview))
        botones_preview.addWidget(self._crear_boton("Deseleccionar todos", self._deseleccionar_todos_preview))
        botones_preview.addWidget(self._crear_boton("Quitar de la ejecución", self._quitar_de_ejecucion_preview))
        botones_preview.addWidget(self._crear_boton("Cancelar análisis", self._cancelar_analisis_preview))
        layout.addLayout(botones_preview)

        footer = QHBoxLayout()
        footer.addStretch()
        self.preview_cancelar = self._crear_boton("Cancelar", self._preview_cancelar)
        self.preview_continuar = self._crear_boton("Continuar con 0 archivos", self._continuar_con_vista_previa, primary=True)
        self.preview_continuar.setEnabled(False)
        footer.addWidget(self.preview_cancelar)
        footer.addWidget(self.preview_continuar)
        layout.addLayout(footer)

        self._preview_ventana = ventana
        self._preview_cancel_event = threading.Event()
        self._preview_queue = queue.Queue()
        self._preview_operaciones = []

        self._preview_hilo = threading.Thread(target=self._generar_preview_en_hilo, args=(reglas_para_proceso,), daemon=True)
        self._preview_hilo.start()
        ventana.show()
        self._procesar_cola_preview()

    def _generar_preview_en_hilo(self, reglas):
        try:
            operaciones = generar_vista_previa(reglas, ui_callback=self._preview_ui_callback, cancel_event=self._preview_cancel_event)
            self._preview_ui_callback({"tipo": "preview_done", "data": operaciones})
        except Exception as exc:
            if self._preview_cancel_event.is_set():
                self._preview_ui_callback({"tipo": "preview_cancelado", "mensaje": "Análisis cancelado"})
            else:
                self._preview_ui_callback({"tipo": "preview_error", "mensaje": str(exc)})

    def _preview_ui_callback(self, dato):
        self._preview_queue.put(dato)

    def _procesar_cola_preview(self):
        if hasattr(self, "_preview_queue"):
            while True:
                try:
                    dato = self._preview_queue.get_nowait()
                except queue.Empty:
                    break
                tipo = dato.get("tipo")
                if tipo == "preview_total":
                    self.preview_barra_label.setText(f"Analizando archivos para generar vista previa... {dato.get('valor', 0)} operaciones detectadas")
                elif tipo == "preview_done":
                    self._preview_operaciones = dato.get("data", [])
                    self._refrescar_preview()
                    self.preview_barra_label.setText("Vista previa lista.")
                elif tipo == "preview_error":
                    QMessageBox.critical(self._preview_ventana, "Error", dato.get("mensaje", "Error desconocido."))
                    self._preview_cancelar()
                elif tipo == "preview_cancelado":
                    self._preview_cancelar()
        if hasattr(self, "_preview_ventana") and self._preview_ventana.isVisible():
            QTimer.singleShot(80, self._procesar_cola_preview)

    def _refrescar_preview(self):
        if not hasattr(self, "_preview_ventana") or not self._preview_ventana.isVisible():
            return
        self.preview_table.setRowCount(0)
        total = len(self._preview_operaciones)
        pendientes = sum(1 for op in self._preview_operaciones if op.get("seleccionado", False))
        excluidos = total - pendientes
        copiar = sum(1 for op in self._preview_operaciones if op.get("seleccionado", False) and op.get("modo", "copy") == "copy")
        mover = sum(1 for op in self._preview_operaciones if op.get("seleccionado", False) and op.get("modo", "copy") == "move")
        duplicados = sum(1 for op in self._preview_operaciones if op.get("duplicado", False) and op.get("seleccionado", False))
        errores = sum(1 for op in self._preview_operaciones if op.get("estado", "").lower().startswith("error"))

        self.preview_total_var.setText(f"Archivos encontrados: {total}")
        self.preview_pendientes_var.setText(f"Operaciones pendientes: {pendientes}")
        self.preview_excluidos_var.setText(f"Excluidos: {excluidos}")
        self.preview_copiar_var.setText(f"Copiar: {copiar}")
        self.preview_mover_var.setText(f"Mover: {mover}")
        self.preview_duplicados_var.setText(f"Duplicados detectados: {duplicados}")
        self.preview_errores_var.setText(f"Errores: {errores}")

        texto_filtro = (self.preview_busqueda.text() or "").strip().lower()
        for operacion in self._preview_operaciones:
            if texto_filtro:
                hay_coincidencia = texto_filtro in (operacion.get("archivo", "") + " " + str(operacion.get("regla", "")) + " " + operacion.get("destino", "") + " " + operacion.get("palabra", "")).lower()
                if not hay_coincidencia:
                    continue
            row = self.preview_table.rowCount()
            self.preview_table.insertRow(row)
            self.preview_table.setItem(row, 0, QTableWidgetItem(str(operacion.get("id", ""))))
            self.preview_table.setItem(row, 1, QTableWidgetItem("Sí" if operacion.get("seleccionado", False) else "No"))
            self.preview_table.setItem(row, 2, QTableWidgetItem(str(operacion.get("archivo", ""))))
            self.preview_table.setItem(row, 3, QTableWidgetItem(str(operacion.get("regla", ""))))
            self.preview_table.setItem(row, 4, QTableWidgetItem(str(operacion.get("palabra", ""))))
            self.preview_table.setItem(row, 5, QTableWidgetItem(str(operacion.get("accion", ""))))
            self.preview_table.setItem(row, 6, QTableWidgetItem(str(operacion.get("origen", ""))))
            self.preview_table.setItem(row, 7, QTableWidgetItem(str(operacion.get("destino_final", operacion.get("destino", "")))))
        self.preview_continuar.setText(f"Continuar con {pendientes} archivos")
        self.preview_continuar.setEnabled(pendientes > 0)

    def _alternar_fila_preview(self, index=None):
        if not hasattr(self, "_preview_operaciones"):
            return
        row = self.preview_table.currentRow()
        if row < 0:
            return
        operacion_id = self.preview_table.item(row, 0).text() if self.preview_table.item(row, 0) else None
        for operacion in self._preview_operaciones:
            if operacion.get("id") == operacion_id:
                operacion["seleccionado"] = not bool(operacion.get("seleccionado", False))
                break
        self._refrescar_preview()

    def _filtrar_preview(self):
        if hasattr(self, "_preview_operaciones"):
            self._refrescar_preview()

    def _seleccionar_todos_preview(self):
        for op in self._preview_operaciones:
            op["seleccionado"] = True
        self._refrescar_preview()

    def _deseleccionar_todos_preview(self):
        for op in self._preview_operaciones:
            op["seleccionado"] = False
        self._refrescar_preview()

    def _quitar_de_ejecucion_preview(self):
        rows = [index.row() for index in self.preview_table.selectionModel().selectedRows()]
        if not rows:
            QMessageBox.information(self._preview_ventana, "Vista previa", "Selecciona al menos una fila para quitarla de esta ejecución.")
            return
        confirm = QMessageBox.question(
            self._preview_ventana,
            "Quitar de la ejecución",
            "¿Quieres quitar los archivos seleccionados de esta ejecución?\n\nLos archivos no serán eliminados del disco.",
        )
        if confirm != QMessageBox.Yes:
            return
        for row in rows:
            operacion_id = self.preview_table.item(row, 0).text() if self.preview_table.item(row, 0) else None
            for op in self._preview_operaciones:
                if op.get("id") == operacion_id:
                    op["seleccionado"] = False
                    break
        self._refrescar_preview()

    def _cancelar_analisis_preview(self):
        if hasattr(self, "_preview_cancel_event"):
            self._preview_cancel_event.set()
        if hasattr(self, "preview_barra_label"):
            self.preview_barra_label.setText("Cancelando análisis de la vista previa...")

    def _preview_cancelar(self):
        if hasattr(self, "_preview_cancel_event"):
            self._preview_cancel_event.set()
        if hasattr(self, "_preview_ventana"):
            self._preview_ventana.close()
        self._toggle_preview_button_state(True)

    def _continuar_con_vista_previa(self):
        if not hasattr(self, "_preview_operaciones"):
            return
        ops = [op.copy() for op in self._preview_operaciones if op.get("seleccionado", False)]
        self._seleccion_preview_vigente = ops
        if hasattr(self, "_preview_ventana"):
            self._preview_ventana.close()
        if not ops:
            self.var_estado.setText("La vista previa quedó sin archivos seleccionados. Presiona Iniciar para confirmar.")
            QMessageBox.information(self, "Vista previa", "No queda ninguna operación seleccionada. La lista de ejecución quedó vacía.")
            return
        self.var_estado.setText("Selección de vista previa aplicada. Presiona Iniciar para ejecutar.")

    def _iniciar_proceso(self):
        if self._procesando:
            return
        if not self.reglas:
            QMessageBox.critical(self, "Error", "Debes crear al menos una regla de clasificación.")
            return
        reglas_para_proceso = [normalizar_regla(regla) for regla in self.reglas]
        reglas_para_proceso = [regla for regla in reglas_para_proceso if regla["palabras"] and regla["origen"] and regla["destino"]]
        if not reglas_para_proceso:
            QMessageBox.critical(self, "Error", "Cada regla debe incluir una carpeta de origen y una de destino.")
            return

        operaciones_previas = None
        if self._seleccion_preview_vigente is not None:
            operaciones_previas = [op.copy() for op in self._seleccion_preview_vigente if bool(op.get("seleccionado", False))]
            if not operaciones_previas:
                QMessageBox.information(self, "Vista previa", "La selección previa quedó vacía. No habrá archivos para mover o copiar.")
                self._seleccion_preview_vigente = []
                return

        self.var_estado.setText("Iniciando proceso...")
        self.barra_actual.setValue(0)
        self.barra_analisis.setValue(0)
        self.var_texto_actual.setText("0%")
        self.var_texto_analisis.setText("0% analizado")
        self.var_total_archivos.setText("Total encontrados: 0")
        self.log_text.clear()

        if operaciones_previas is not None:
            self._registrar_log("Inicio del proceso desde la selección de vista previa.")
            for idx, op in enumerate(operaciones_previas, start=1):
                self._registrar_log(f"{idx}. {op.get('archivo', '')} | Regla: {op.get('regla', '')} | Acción: {op.get('accion', '')} | Destino: {op.get('destino_final', op.get('destino', ''))}")
        else:
            self._registrar_log("Inicio del proceso con reglas independientes por regla.")
            for idx, regla in enumerate(reglas_para_proceso, start=1):
                self._registrar_log(f"{idx}. {', '.join(regla['palabras'])} | Origen: {regla['origen']} | Destino: {regla['destino']} | Modo: {regla['modo']}")
            self._registrar_log("Procesando...")

        self._cola = queue.Queue()
        self._procesando = True
        self.cancel_event = threading.Event()

        self.boton_vista_previa.setEnabled(False)
        self.boton_iniciar.setEnabled(False)
        self.boton_cancelar.setEnabled(True)

        def ejecutar():
            error = None
            cancelado = False
            try:
                if operaciones_previas is not None:
                    ejecutar_operaciones(operaciones_previas, ui_callback=self._ui_callback, cancel_event=self.cancel_event)
                else:
                    procesar_archivos(reglas=reglas_para_proceso, ui_callback=self._ui_callback, cancel_event=self.cancel_event)
                cancelado = self.cancel_event.is_set()
            except Exception as e:
                if self.cancel_event.is_set():
                    cancelado = True
                    self._ui_callback({"tipo": "log", "mensaje": "Proceso cancelado por el usuario."})
                else:
                    error = str(e)
                    self._ui_callback({"tipo": "error", "mensaje": error})
            finally:
                self._seleccion_preview_vigente = None
                self._ui_callback({"tipo": "terminado", "cancelado": cancelado, "error": error})

        self._hilo_proceso = threading.Thread(target=ejecutar, daemon=True, name="HiloProcesamiento")
        self._hilo_proceso.start()


def main():
    app = QApplication([])
    ventana = Aplicacion()
    ventana.show()
    app.exec()


if __name__ == "__main__":
    main()
