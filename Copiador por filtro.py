import hashlib
import json
import ntpath
import os
import queue
import re
import shutil
import threading
import time
import uuid
from datetime import date, datetime

from PySide6.QtCore import QTimer, Qt, QSize
from PySide6.QtGui import QFont, QIcon, QIntValidator, QPixmap, QPainter
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
    QToolButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMenu,
    QScrollArea,
    QStackedWidget,
)


# ============================================================
#  Funciones auxiliares y de normalización
# ============================================================

def normalizar_palabras_clave(palabras):
    return [p.lower().strip() for p in palabras if p and p.strip()]


def normalizar_ruta_regla(ruta):
    if ruta is None:
        return ""
    ruta = str(ruta).strip().strip('"')
    if not ruta:
        return ""
    return ntpath.normpath(ruta.replace("/", "\\"))


def normalizar_destino_regla(destino):
    return normalizar_ruta_regla(destino)


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


def normalizar_categoria_extension(categoria):
    if categoria is None:
        return ""
    texto = str(categoria).strip()
    if not texto:
        return ""
    return texto[0].upper() + texto[1:].lower()


def cargar_biblioteca_extensiones():
    """
    Carga la biblioteca de extensiones desde el archivo 'biblioteca.txt'
    ubicado en el mismo directorio que este script.
    Formato del archivo:
        - Líneas que comienzan con '//' son comentarios.
        - Líneas con formato: | .ext1, .ext2 | Categoría |
    Devuelve un diccionario {extension_sin_punto: categoria}.
    Las primeras asociaciones tienen prioridad (no se sobrescriben).
    """
    ruta_biblioteca = os.path.join(os.path.dirname(os.path.abspath(__file__)), "biblioteca.txt")
    biblioteca = {}

    biblioteca_respaldo = {
        "jpg": "Imágenes", "jpeg": "Imágenes", "png": "Imágenes", "gif": "Imágenes",
        "bmp": "Imágenes", "svg": "Imágenes", "webp": "Imágenes",
        "mp3": "Audio", "wav": "Audio", "flac": "Audio", "aac": "Audio", "ogg": "Audio",
        "mp4": "Vídeo", "avi": "Vídeo", "mkv": "Vídeo", "mov": "Vídeo", "wmv": "Vídeo",
        "flv": "Vídeo",
        "pdf": "Documentos", "doc": "Documentos", "docx": "Documentos",
        "xls": "Documentos", "xlsx": "Documentos", "ppt": "Documentos",
        "pptx": "Documentos", "txt": "Documentos", "rtf": "Documentos", "csv": "Documentos",
        "zip": "Comprimidos", "rar": "Comprimidos", "7z": "Comprimidos",
        "tar": "Comprimidos", "gz": "Comprimidos",
        "exe": "Ejecutables", "msi": "Ejecutables", "apk": "Ejecutables",
        "iso": "Imágenes de disco", "dmg": "Imágenes de disco",
        "py": "Código", "js": "Código", "html": "Código", "css": "Código",
        "java": "Código", "c": "Código", "cpp": "Código", "json": "Código", "xml": "Código",
    }

    if not os.path.exists(ruta_biblioteca):
        return biblioteca_respaldo

    try:
        with open(ruta_biblioteca, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea or linea.startswith("//"):
                    continue
                partes = linea.split("|")
                if len(partes) < 3:
                    continue
                ext_part = partes[1].strip()
                categoria = partes[2].strip()
                if not ext_part or not categoria:
                    continue
                for ext in ext_part.split(","):
                    ext = ext.strip().lower().lstrip(".")
                    if ext and ext not in biblioteca:
                        biblioteca[ext] = categoria
    except (OSError, UnicodeDecodeError):
        return biblioteca_respaldo

    return biblioteca


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


def normalizar_condicion_tamano(condicion):
    condicion = condicion if isinstance(condicion, dict) else {}
    activo = condicion.get("activo", False)
    if isinstance(activo, str):
        activo = activo.strip().lower() in ("1", "true", "si", "yes", "on")
    comparacion = str(condicion.get("comparacion", "mayor")).strip().lower()
    if comparacion not in ("mayor", "igual", "menor"):
        comparacion = "mayor"
    try:
        valor = int(condicion.get("valor", 0))
    except (TypeError, ValueError):
        valor = 0
    valor = max(0, valor)
    unidad = str(condicion.get("unidad", "MB")).strip().upper()
    if unidad not in ("TB", "GB", "MB", "KB"):
        unidad = "MB"
    return {
        "activo": bool(activo),
        "comparacion": comparacion,
        "valor": valor,
        "unidad": unidad,
    }


def archivo_cumple_tamano(ruta_archivo, condicion):
    condicion = normalizar_condicion_tamano(condicion)
    if not condicion["activo"]:
        return True
    try:
        tamaño_archivo = os.path.getsize(ruta_archivo)
    except OSError:
        return False
    multiplicadores = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
    tamaño_requerido = condicion["valor"] * multiplicadores[condicion["unidad"]]
    comparacion = condicion["comparacion"]
    if comparacion == "mayor":
        return tamaño_archivo > tamaño_requerido
    if comparacion == "igual":
        return tamaño_archivo == tamaño_requerido
    return tamaño_archivo < tamaño_requerido


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
    if regla["palabras"] and obtener_palabra_clave_coincidente(ruta_archivo, regla["palabras"]) is None:
        return False
    if bool(regla.get("filtrar_extensiones", False)):
        if not extension_permitida(ruta_archivo, regla.get("extensiones", [])):
            return False
    if not archivo_cumple_fecha(ruta_archivo, regla.get("fecha_archivo")):
        return False
    if not archivo_cumple_tamano(ruta_archivo, regla.get("tamaño_archivo")):
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
            "tamaño_archivo": normalizar_condicion_tamano({}),
            "organizar_por_extension": False,
            "organizar_por_fecha": False,
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
    tamaño_archivo = normalizar_condicion_tamano(regla.get("tamaño_archivo"))

    organizar_por_extension = regla.get("organizar_por_extension", False)
    if isinstance(organizar_por_extension, str):
        organizar_por_extension = organizar_por_extension.strip().lower() in ("1", "true", "yes", "si", "on")
    organizar_por_fecha = regla.get("organizar_por_fecha", False)
    if isinstance(organizar_por_fecha, str):
        organizar_por_fecha = organizar_por_fecha.strip().lower() in ("1", "true", "yes", "si", "on")

    return {
        "palabras": normalizar_palabras_clave(palabras),
        "origen": normalizar_ruta_regla(regla.get("origen", "")),
        "destino": normalizar_destino_regla(regla.get("destino", "")),
        "modo": modo,
        "crear_subcarpetas": bool(crear_subcarpetas),
        "eliminar_duplicados": bool(eliminar_duplicados),
        "filtrar_extensiones": bool(filtrar_extensiones),
        "extensiones": extensiones,
        "fecha_archivo": fecha_archivo,
        "tamaño_archivo": tamaño_archivo,
        "organizar_por_extension": bool(organizar_por_extension),
        "organizar_por_fecha": bool(organizar_por_fecha),
    }


def regla_tiene_filtro_activo(regla):
    regla = normalizar_regla(regla)
    tiene_extensiones = bool(regla.get("filtrar_extensiones")) and bool(regla.get("extensiones"))
    tiene_fecha = bool(regla.get("fecha_archivo", {}).get("activo"))
    tiene_tamano = bool(regla.get("tamaño_archivo", {}).get("activo"))
    return tiene_extensiones or tiene_fecha or tiene_tamano


def regla_tiene_criterio(regla):
    regla = normalizar_regla(regla)
    return (
        bool(regla.get("palabras"))
        or regla_tiene_filtro_activo(regla)
        or bool(regla.get("organizar_por_extension"))
    )


def guardar_reglas(reglas):
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reglas.json")
    reglas_limpias = [normalizar_regla(regla) for regla in (reglas or [])]
    reglas_limpias = [
        regla for regla in reglas_limpias
        if regla["origen"] and regla["destino"] and regla_tiene_criterio(regla)
    ]
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
        if not isinstance(regla, dict):
            continue
        regla_normalizada = normalizar_regla(regla)
        if (
            regla_normalizada["origen"]
            and regla_normalizada["destino"]
            and regla_tiene_criterio(regla_normalizada)
        ):
            reglas_validas.append(regla_normalizada)
    return reglas_validas


def guardar_reglas_fflw(ruta, reglas):
    reglas_limpias = [normalizar_regla(regla) for regla in (reglas or [])]
    reglas_limpias = [
        regla for regla in reglas_limpias
        if regla["origen"] and regla["destino"] and regla_tiene_criterio(regla)
    ]
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(
            {"formato": "fflw", "version": 1, "reglas": reglas_limpias},
            archivo,
            ensure_ascii=False,
            indent=2,
        )


def cargar_reglas_fflw(ruta):
    with open(ruta, "r", encoding="utf-8") as archivo:
        datos = json.load(archivo)

    if isinstance(datos, dict):
        if datos.get("formato") not in (None, "fflw"):
            raise ValueError("El archivo no es un paquete de reglas FileFlow válido.")
        reglas = datos.get("reglas", [])
    elif isinstance(datos, list):
        reglas = datos
    else:
        raise ValueError("El archivo no contiene una lista de reglas válida.")

    if not isinstance(reglas, list):
        raise ValueError("El archivo no contiene una lista de reglas válida.")

    reglas_validas = []
    for regla in reglas:
        if not isinstance(regla, dict):
            continue
        regla_normalizada = normalizar_regla(regla)
        if (
            regla_normalizada["origen"]
            and regla_normalizada["destino"]
            and regla_tiene_criterio(regla_normalizada)
        ):
            reglas_validas.append(regla_normalizada)
    return reglas_validas


def obtener_palabra_clave_coincidente(ruta_archivo, palabras_clave):
    if not os.path.isfile(ruta_archivo):
        return None
    nombre_archivo = os.path.basename(ruta_archivo).lower()
    tokens = re.findall(r"[a-záéíóúñ0-9]+", nombre_archivo)
    for palabra in palabras_clave:
        palabra_normalizada = re.sub(r"[^a-záéíóúñ0-9]+", "", palabra.lower())
        if not palabra_normalizada:
            continue
        for token in tokens:
            if token == palabra_normalizada or token == palabra_normalizada + "s":
                return palabra
    return None


def obtener_regla_coincidente(ruta_archivo, reglas):
    if not os.path.isfile(ruta_archivo):
        return None
    for regla in reglas:
        regla_normalizada = normalizar_regla(regla)
        if not regla_normalizada["origen"] or not regla_normalizada["destino"]:
            continue
        if not regla_tiene_criterio(regla_normalizada):
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


def crear_metadatos_operacion(origen, destino, accion, operation_id=None):
    """Construye la evidencia verificable de una operación ya completada."""
    return {
        "operation_id": operation_id or uuid.uuid4().hex,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": accion,
        "source": origen,
        "destination": destino,
        "size": os.path.getsize(destino),
        "sha256": calcular_hash_archivo(destino),
        "status": "success",
    }


def analizar_reversion(operaciones, cancel_event=None, ui_callback=None):
    resultados = []
    for operacion in operaciones or []:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Análisis de reversión cancelado por el usuario.")
        origen = operacion.get("source") or operacion.get("origen")
        destino = operacion.get("destination") or operacion.get("destino_final")
        accion = operacion.get("action") or operacion.get("modo")
        esperado_tamaño = operacion.get("size")
        esperado_hash = operacion.get("sha256")
        resultado = dict(operacion)
        resultado["status"] = "unsafe"
        resultado["path"] = destino
        if not origen or not destino or accion not in ("copy", "move") or not esperado_hash:
            resultado["status"] = "unsafe"
        elif not os.path.isfile(destino):
            resultado["status"] = "missing"
        else:
            try:
                tamaño_actual = os.path.getsize(destino)
                hash_actual = calcular_hash_archivo(destino)
            except (OSError, ValueError):
                tamaño_actual = None
                hash_actual = None
            if tamaño_actual != esperado_tamaño or hash_actual != esperado_hash:
                resultado["status"] = "modified"
            elif accion == "copy":
                resultado["status"] = "safe"
            elif os.path.exists(origen):
                try:
                    resultado["status"] = (
                        "already_reverted"
                        if os.path.isfile(origen)
                        and os.path.getsize(origen) == esperado_tamaño
                        and calcular_hash_archivo(origen) == esperado_hash
                        else "conflict"
                    )
                except (OSError, ValueError):
                    resultado["status"] = "conflict"
            else:
                resultado["status"] = "safe"
        resultados.append(resultado)
        if ui_callback is not None:
            ui_callback({"tipo": "reversion_item", "operacion": resultado})
    return resultados


def ejecutar_reversion(resultados, ui_callback=None, cancel_event=None):
    seguras = [item for item in resultados if item.get("status") == "safe"]
    revertidas = []

    def enviar(tipo, **datos):
        if ui_callback is not None:
            ui_callback({"tipo": tipo, **datos})

    for indice, operacion in enumerate(seguras, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Reversión cancelada por el usuario.")
        origen = operacion["source"]
        destino = operacion["destination"]
        accion = operacion["action"]
        try:
            if accion == "copy":
                os.remove(destino)
            else:
                if os.path.exists(origen):
                    raise FileExistsError(origen)
                os.makedirs(os.path.dirname(origen), exist_ok=True)
                shutil.move(destino, origen)
            revertida = dict(operacion)
            revertida["status"] = "reverted"
            revertidas.append(revertida)
            enviar("log", mensaje=f"Revertido: {os.path.basename(destino)}")
        except (OSError, shutil.Error) as exc:
            enviar("log", mensaje=f"No se pudo revertir {os.path.basename(destino)}: {exc}")
        enviar("actual", valor=(indice / len(seguras) * 100) if seguras else 100,
               texto=f"{indice}/{len(seguras)} revertidos")
    return revertidas


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
                ui_callback({"tipo": "actual", "valor": porcentaje, "texto": f"{porcentaje:.0f}%"})

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


def crear_operacion_analisis(ruta_archivo, regla, indice_regla, biblioteca=None):
    if not os.path.isfile(ruta_archivo):
        return None
    palabra_coincidente = obtener_palabra_clave_coincidente(ruta_archivo, regla["palabras"])
    if regla["palabras"] and palabra_coincidente is None:
        return None
    if bool(regla.get("filtrar_extensiones", False)) and not extension_permitida(ruta_archivo, regla.get("extensiones", [])):
        return None

    nombre_archivo = os.path.basename(ruta_archivo)
    destino_directorio = os.path.normpath(regla["destino"])

    if regla.get("organizar_por_extension", False):
        ext = obtener_extension_archivo(ruta_archivo)
        if ext:
            # Usar categoría de la biblioteca si está disponible, si no, extensión en mayúsculas
            categoria = biblioteca.get(ext, ext.upper()) if biblioteca else ext.upper()
            destino_directorio = os.path.normpath(os.path.join(regla["destino"], categoria))

    if regla.get("organizar_por_fecha", False):
        fecha = obtener_fecha_archivo(ruta_archivo, "modificacion")
        if fecha:
            año = str(fecha.year)
            mes = f"{fecha.month:02d} - {MESES[fecha.month-1]}"
            destino_directorio = os.path.normpath(os.path.join(destino_directorio, año, mes))

    if regla.get("crear_subcarpetas", True) and palabra_coincidente:
        destino_directorio = os.path.normpath(os.path.join(destino_directorio, palabra_coincidente))

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
        "palabra": palabra_coincidente or "",
        "modo": regla.get("modo", "copy"),
        "accion": "Mover" if regla.get("modo", "copy") == "move" else "Copiar",
        "destino": destino_directorio,
        "destino_final": destino_final,
        "estado": estado,
        "duplicado": duplicado is not None,
        "eliminar_duplicados": bool(regla.get("eliminar_duplicados", False)),
    }


def generar_operaciones_analisis(reglas, ui_callback=None, cancel_event=None, biblioteca=None):
    reglas = [normalizar_regla(regla) for regla in (reglas or [])]
    reglas = [
        regla for regla in reglas
        if regla["origen"] and regla["destino"] and regla_tiene_criterio(regla)
    ]
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Proceso cancelado por el usuario.")
    if not reglas:
        return []

    operaciones = []
    archivos_vistos = set()
    if ui_callback is not None:
        ui_callback({"tipo": "analisis_indeterminado"})

    archivos_analizados = 0
    ultimo_progreso = time.monotonic()
    for indice_regla, regla in enumerate(reglas, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Proceso cancelado por el usuario.")
        origen = regla["origen"]
        if not os.path.isdir(origen):
            continue
        for raiz, _, lista_archivos in os.walk(origen):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Proceso cancelado por el usuario.")
            for nombre in lista_archivos:
                ruta_archivo = os.path.join(raiz, nombre)
                archivos_analizados += 1
                ahora = time.monotonic()
                if ui_callback is not None and ahora - ultimo_progreso >= 0.2:
                    ui_callback({
                        "tipo": "analisis",
                        "valor": 0,
                        "texto": f"{archivos_analizados} archivos analizados"
                    })
                    ultimo_progreso = ahora
                if ruta_archivo in archivos_vistos:
                    continue
                if not archivo_cumple_regla(ruta_archivo, regla):
                    continue
                operacion = crear_operacion_analisis(ruta_archivo, regla, indice_regla, biblioteca)
                if operacion is None:
                    continue
                operaciones.append(operacion)
                archivos_vistos.add(ruta_archivo)

    if ui_callback is not None:
        ui_callback({
            "tipo": "analisis",
            "valor": 100,
            "texto": f"{archivos_analizados} archivos analizados",
        })
        ui_callback({"tipo": "preview_total", "valor": len(operaciones)})
    return operaciones


def procesar_archivos(reglas, ui_callback=None, cancel_event=None, biblioteca=None):
    reglas = [normalizar_regla(regla) for regla in (reglas or [])]
    reglas = [
        regla for regla in reglas
        if regla["origen"] and regla["destino"] and regla_tiene_criterio(regla)
    ]
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

    operaciones = generar_operaciones_analisis(reglas, ui_callback=ui_callback, cancel_event=cancel_event, biblioteca=biblioteca)
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


def generar_vista_previa(reglas, ui_callback=None, cancel_event=None, biblioteca=None):
    return generar_operaciones_analisis(reglas, ui_callback=ui_callback, cancel_event=cancel_event, biblioteca=biblioteca)


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
                datos_operacion = crear_metadatos_operacion(origen, destino_final, "copy", operacion.get("id"))
                actualizar_actual(100, "100%", f"Copiado: {archivo}")
                registrar_log(f"Archivo copiado correctamente: {archivo}")
            elif modo == "move":
                actualizar_actual(0, "0%", f"Moviendo: {archivo}")
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Proceso cancelado por el usuario.")
                if os.path.exists(destino_final):
                    destino_final = obtener_nombre_unico(destino_directorio, archivo)
                shutil.move(origen, destino_final)
                datos_operacion = crear_metadatos_operacion(origen, destino_final, "move", operacion.get("id"))
                actualizar_actual(100, "100%", f"Movido: {archivo}")
                registrar_log(f"Archivo movido correctamente: {archivo}")
            enviar({"tipo": "operacion_completada", "operacion": datos_operacion})
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


# ============================================================
#  Clases de interfaz
# ============================================================

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


class ConstructorTamano(QFrame):
    def __init__(self, condicion=None, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.activado = QCheckBox("Tamaño de archivo")
        layout.addWidget(self.activado)

        self.contenido = QWidget()
        contenido_layout = QHBoxLayout(self.contenido)
        contenido_layout.setContentsMargins(0, 0, 0, 0)
        contenido_layout.setSpacing(8)

        self.comparacion = QComboBox()
        self.comparacion.addItem("Mayor", "mayor")
        self.comparacion.addItem("Igual", "igual")
        self.comparacion.addItem("Menor", "menor")
        contenido_layout.addWidget(self.comparacion)

        self.valor = QLineEdit()
        self.valor.setValidator(QIntValidator(0, 2 ** 31 - 1, self.valor))
        self.valor.setPlaceholderText("Tamaño")
        contenido_layout.addWidget(self.valor)

        self.unidad = QComboBox()
        for unidad in ("TB", "GB", "MB", "KB"):
            self.unidad.addItem(unidad, unidad)
        contenido_layout.addWidget(self.unidad)
        contenido_layout.addStretch()
        layout.addWidget(self.contenido)

        self.activado.toggled.connect(self._actualizar_estado)
        self._establecer_condicion(condicion or {})

    def _establecer_condicion(self, condicion):
        condicion = normalizar_condicion_tamano(condicion)
        self.activado.setChecked(condicion["activo"])
        self.comparacion.setCurrentIndex(max(0, self.comparacion.findData(condicion["comparacion"])))
        self.valor.setText(str(condicion["valor"]))
        self.unidad.setCurrentIndex(max(0, self.unidad.findData(condicion["unidad"])))
        self._actualizar_estado()

    def _actualizar_estado(self):
        self.contenido.setVisible(self.activado.isChecked())

    def obtener_condicion(self):
        return normalizar_condicion_tamano({
            "activo": self.activado.isChecked(),
            "comparacion": self.comparacion.currentData(),
            "valor": self.valor.text().strip() or 0,
            "unidad": self.unidad.currentData(),
        })


class FolderDropLineEdit(QLineEdit):
    """QLineEdit que acepta carpetas arrastradas desde el Explorador de Windows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setPlaceholderText("Arrastra aquí una carpeta o escribe la ruta...")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and os.path.isdir(url.toLocalFile()):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                ruta = url.toLocalFile()
                if os.path.isdir(ruta):
                    self.setText(normalizar_ruta_regla(ruta))
                    event.acceptProposedAction()
                    return
        event.ignore()


# ============================================================
#  Clase principal Aplicacion
# ============================================================

class Aplicacion(QMainWindow):
    NAV_ITEMS = (
        ("inicio.png", "Inicio", "Inicio"),
        ("organizar.png", "Organizar", "Organizar"),
        ("reglas.png", "Reglas", "Reglas"),
        ("biblioteca.png", "Biblioteca", "Biblioteca"),
        ("ia.png", "IA", "IA"),
        ("historial.png", "Historial", "Historial"),
        ("ajustes.png", "Ajustes", "Ajustes"),
    )

    def __init__(self):
        super().__init__()
        icon_path = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "Iconos"), "pluma.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle("FileFlow")
        self.resize(1280, 820)
        self.setMinimumSize(1000, 680)

        self._procesando = False
        self._cola = queue.Queue(maxsize=2000)
        self.cancel_event = None
        self._hilo_proceso = None
        self._seleccion_preview_vigente = None
        self._preview_hilo = None
        self._preview_queue = queue.Queue()
        self._preview_cancel_event = threading.Event()
        self._preview_operaciones = []
        self._history_current = []
        self._history_operations = []
        self._reversion_context = None
        self._reversion_decision = None
        self._confirmacion_ejecucion_event = None
        self._confirmacion_ejecucion_aceptada = False
        self._metricas_archivos_cache = {}
        self._metricas_en_curso = {}
        self._metricas_versiones = {}
        self._navigation_buttons = {}
        self._page_names = {}

        reglas_guardadas = cargar_reglas()
        self.reglas = reglas_guardadas if reglas_guardadas is not None else []
        if reglas_guardadas is None:
            QMessageBox.warning(
                self,
                "Reglas",
                "El archivo de reglas está corrupto o no se pudo leer. Se inició con una lista vacía."
            )

        self.biblioteca = cargar_biblioteca_extensiones()
        self.biblioteca_usuario = self._cargar_biblioteca_usuario()
        self.biblioteca_completa = {**self.biblioteca, **self.biblioteca_usuario}

        self.var_progreso_actual = 0
        self.var_progreso_analisis = 0
        self.var_estado = None
        self.barra_actual = None
        self.barra_analisis = None
        self.var_texto_actual = None
        self.var_texto_analisis = None
        self.var_total_archivos = None
        self.log_text = None

        self._aplicar_estilo()
        self._crear_interfaz()
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_inicio()
        self._actualizar_biblioteca_ui()
        self._actualizar_historial_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._procesar_cola)
        self._timer.start(50)

    # ------------------------------------------------------------------
    # Estilo / navegación
    # ------------------------------------------------------------------

    def _aplicar_estilo(self):
        self.setStyleSheet(
            """
            * { font-family: Segoe UI, Arial, sans-serif; }
            QMainWindow, QWidget#root { background: #f4f7fb; color: #172033; }
            QFrame#sidebar { background: #111827; border: none; }
            QLabel#brand { color: #ffffff; font-size: 23px; font-weight: 800; }
            QLabel#brand_sub { color: #94a3b8; font-size: 10px; }
            QPushButton#nav {
                text-align: left;
                border: none;
                border-radius: 10px;
                padding: 11px 14px;
                padding-left: 20px;
                color: #cbd5e1;
                background: transparent;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#nav:hover { background: #1f2937; color: #ffffff; }
            QPushButton#nav[active="true"] { background: #2563eb; color: #ffffff; }
            QLabel#page_title { font-size: 28px; font-weight: 800; color: #0f172a; }
            QLabel#page_subtitle { color: #64748b; font-size: 12px; }
            QFrame#card {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 16px;
            }
            QFrame#soft_card {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 14px;
            }
            QLabel#card_title { color: #475569; font-size: 11px; font-weight: 700; }
            QLabel#metric { color: #0f172a; font-size: 25px; font-weight: 800; }
            QLabel#small_muted { color: #64748b; font-size: 11px; }
            QLabel#status { color: #334155; font-size: 12px; }
            QPushButton#primary {
                background: #2563eb;
                color: white;
                border: none;
                border-radius: 11px;
                padding: 11px 18px;
                font-weight: 700;
            }
            QPushButton#primary:hover { background: #1d4ed8; }
            QPushButton#primary:pressed { background: #1e40af; }
            QPushButton#secondary {
                background: #eaf0f7;
                color: #172033;
                border: none;
                border-radius: 11px;
                padding: 10px 16px;
                font-weight: 700;
            }
            QPushButton#secondary:hover { background: #dce5f0; }
            QPushButton#danger {
                background: #fee2e2;
                color: #991b1b;
                border: none;
                border-radius: 10px;
                padding: 9px 14px;
                font-weight: 700;
            }
            QPushButton#ghost {
                background: transparent;
                color: #334155;
                border: 1px solid #d7e0ea;
                border-radius: 10px;
                padding: 9px 14px;
                font-weight: 700;
            }
            QPushButton#ghost:hover { background: #f8fafc; }
            QPushButton:disabled { background: #cbd5e1; color: #64748b; }
            QLineEdit, QComboBox, QPlainTextEdit, QCheckBox {
                background: #ffffff;
                color: #172033;
                border: 1px solid #d7e0ea;
                border-radius: 10px;
                padding: 9px 11px;
            }
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #2563eb; }
            QProgressBar {
                border: none;
                border-radius: 7px;
                background: #e8edf3;
                text-align: center;
                height: 13px;
            }
            QProgressBar::chunk { background: #2563eb; border-radius: 7px; }
            QTableWidget {
                background: #ffffff;
                alternate-background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                gridline-color: #edf2f7;
            }
            QHeaderView::section {
                background: #f8fafc;
                color: #475569;
                border: none;
                padding: 9px;
                font-weight: 700;
            }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: transparent; width: 10px; margin: 4px; }
            QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 5px; min-height: 30px; }
            QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
            """
        )

    def _crear_interfaz(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = self._crear_sidebar()
        root_layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(28, 24, 28, 24)
        right_layout.setSpacing(18)

        self.content_stack = QStackedWidget()
        right_layout.addWidget(self.content_stack, 1)
        root_layout.addWidget(right, 1)

        self._crear_paginas()
        self._mostrar_pagina("Inicio")

    def _crear_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(245)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(15)
        brand_row.setContentsMargins(0, 0, 0, 0)
        icon = QLabel()
        icon_path = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "Iconos"), "pluma.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon.setPixmap(pixmap)
        icon.setFixedSize(50, 50)
        brand_row.addWidget(icon, 0, Qt.AlignVCenter)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        brand = QLabel("FileFlow")
        brand.setObjectName("brand")
        brand_col.addWidget(brand)
        sub = QLabel("Intelligent file organization")
        sub.setObjectName("brand_sub")
        brand_col.addWidget(sub)
        brand_row.addLayout(brand_col)
        layout.addLayout(brand_row)
        layout.addSpacing(18)

        icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Iconos")

        for icon_name, label, page_name in self.NAV_ITEMS:
            button = QPushButton(f"    {label}")
            button.setObjectName("nav")
            button.setProperty("active", False)
            button.clicked.connect(lambda checked=False, p=page_name: self._mostrar_pagina(p))

            icon_path = os.path.join(icon_dir, icon_name)
            if os.path.exists(icon_path):
                original_icon = QIcon(icon_path)
                # Recolorear a blanco
                pixmap = original_icon.pixmap(QSize(20, 20))
                if not pixmap.isNull():
                    painter = QPainter(pixmap)
                    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
                    painter.fillRect(pixmap.rect(), Qt.white)
                    painter.end()
                    white_icon = QIcon(pixmap)
                    button.setIcon(white_icon)
                else:
                    button.setIcon(original_icon)
                button.setIconSize(QSize(20, 20))
            else:
                # Fallback: sin icono
                pass

            self._navigation_buttons[page_name] = button
            self._page_names[button] = page_name
            layout.addWidget(button)
            layout.addSpacing(10)

        layout.addStretch(1)
        version = QLabel("FileFlow\nVersión 2 • UI renovada")
        version.setStyleSheet("color:#64748b; font-size:10px;")
        layout.addWidget(version)
        return sidebar

    def _crear_paginas(self):
        pages = [
            ("Inicio", self._crear_pagina_inicio()),
            ("Organizar", self._crear_pagina_organizar()),
            ("Reglas", self._crear_pagina_reglas()),
            ("Biblioteca", self._crear_pagina_biblioteca()),
            ("IA", self._crear_pagina_ia()),
            ("Historial", self._crear_pagina_historial()),
            ("Ajustes", self._crear_pagina_ajustes()),
        ]
        for name, widget in pages:
            self.content_stack.addWidget(widget)
            widget.setProperty("page_name", name)

    def _mostrar_pagina(self, nombre):
        for idx in range(self.content_stack.count()):
            widget = self.content_stack.widget(idx)
            if widget.property("page_name") == nombre:
                self.content_stack.setCurrentIndex(idx)
                break
        for page, button in self._navigation_buttons.items():
            button.setProperty("active", page == nombre)
            button.style().unpolish(button)
            button.style().polish(button)
        if nombre == "Organizar" and self._preview_operaciones:
            self._refrescar_preview()
        elif nombre == "Reglas":
            self._actualizar_tabla_reglas()
        elif nombre == "Biblioteca":
            self._actualizar_biblioteca_ui()
        elif nombre == "Historial":
            self._actualizar_historial_ui()

    # ------------------------------------------------------------------
    # Componentes visuales
    # ------------------------------------------------------------------

    def _titulo_pagina(self, titulo, subtitulo):
        box = QVBoxLayout()
        t = QLabel(titulo)
        t.setObjectName("page_title")
        box.addWidget(t)
        s = QLabel(subtitulo)
        s.setObjectName("page_subtitle")
        box.addWidget(s)
        return box

    def _crear_tarjeta_metrica(self, titulo, valor="0", subtitulo=""):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel(titulo)
        label.setObjectName("card_title")
        layout.addWidget(label)
        metric = QLabel(str(valor))
        metric.setObjectName("metric")
        layout.addWidget(metric)
        if subtitulo:
            sm = QLabel(subtitulo)
            sm.setObjectName("small_muted")
            layout.addWidget(sm)
        frame.metric_label = metric
        return frame

    def _crear_boton(self, texto, callback, primary=False, danger=False, ghost=False):
        boton = QPushButton(texto)
        boton.setObjectName("primary" if primary else "danger" if danger else "ghost" if ghost else "secondary")
        if callback is not None:
            boton.clicked.connect(callback)
        return boton

    # ------------------------------------------------------------------
    # Inicio
    # ------------------------------------------------------------------

    def _crear_pagina_inicio(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        head = self._titulo_pagina(
            self._obtener_saludo(),
            "FileFlow está listo para analizar y organizar los archivos definidos por tus reglas."
        )
        layout.addLayout(head)

        stats = QHBoxLayout()
        self.metric_carpetas = self._crear_tarjeta_metrica("Carpetas en reglas", "0")
        self.metric_archivos = self._crear_tarjeta_metrica("Archivos encontrados", "0")
        self.metric_coincidencias = self._crear_tarjeta_metrica("Coincidencias", "0")
        self.metric_procesados = self._crear_tarjeta_metrica("Procesados", "0")
        for card in (self.metric_carpetas, self.metric_archivos, self.metric_coincidencias, self.metric_procesados):
            stats.addWidget(card, 1)
        layout.addLayout(stats)

        progreso = QFrame()
        progreso.setObjectName("card")
        p = QVBoxLayout(progreso)
        p.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Estado del proceso")
        title.setStyleSheet("font-size:15px; font-weight:800;")
        p.addWidget(title)

        p.addSpacing(8)
        p.addWidget(QLabel("Análisis de documentos y carpetas"))
        self.barra_analisis = QProgressBar()
        self.barra_analisis.setRange(0, 100)
        p.addWidget(self.barra_analisis)
        self.var_texto_analisis = QLabel("0% analizado")
        self.var_texto_analisis.setObjectName("small_muted")
        p.addWidget(self.var_texto_analisis)

        p.addSpacing(10)
        p.addWidget(QLabel("Copia / movimiento de archivos"))
        self.barra_actual = QProgressBar()
        self.barra_actual.setRange(0, 100)
        p.addWidget(self.barra_actual)
        self.var_texto_actual = QLabel("0%")
        self.var_texto_actual.setObjectName("small_muted")
        p.addWidget(self.var_texto_actual)

        self.var_total_archivos = QLabel("Sin proceso en ejecución")
        self.var_total_archivos.setObjectName("status")
        p.addWidget(self.var_total_archivos)

        self.var_estado = QLabel("Listo para iniciar.")
        self.var_estado.setObjectName("status")
        p.addWidget(self.var_estado)
        layout.addWidget(progreso)

        actions = QHBoxLayout()
        self.boton_iniciar = self._crear_boton("▶  Iniciar proceso", self._iniciar_proceso, primary=True)
        self.boton_organizar_desde_inicio = self._crear_boton("✨  Revisar organización", lambda: self._mostrar_pagina("Organizar"))
        self.boton_cancelar = self._crear_boton("Cancelar", self._cancelar_proceso, ghost=True)
        self.boton_cancelar.setEnabled(False)
        actions.addWidget(self.boton_iniciar)
        actions.addWidget(self.boton_organizar_desde_inicio)
        actions.addWidget(self.boton_cancelar)
        actions.addStretch(1)
        layout.addLayout(actions)

        log_frame = QFrame()
        log_frame.setObjectName("soft_card")
        lf = QVBoxLayout(log_frame)
        lf.setContentsMargins(14, 12, 14, 12)
        log_title = QLabel("Actividad reciente")
        log_title.setStyleSheet("font-weight:800;")
        lf.addWidget(log_title)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(150)
        self.log_text.setMaximumBlockCount(2000)
        lf.addWidget(self.log_text)
        layout.addWidget(log_frame, 1)
        return page

    def _obtener_saludo(self):
        hora = datetime.now().hour
        if hora < 12:
            momento = "Buenos días"
        elif hora < 19:
            momento = "Buenas tardes"
        else:
            momento = "Buenas noches"
        try:
            usuario = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        except Exception:
            usuario = ""
        return f"{momento}{', ' + usuario if usuario else ''}"

    def _actualizar_resumen_inicio(self):
        origenes = set()
        for regla in self.reglas:
            origen = normalizar_ruta_regla(regla.get("origen", ""))
            if origen:
                origenes.add(origen)

        clave_origenes = tuple(sorted(origenes))
        cache = self._metricas_archivos_cache.get(clave_origenes)
        total_archivos = (
            cache[0]
            if cache is not None and time.monotonic() - cache[1] < 30
            else None
        )
        if total_archivos is None:
            self.metric_archivos.metric_label.setText("…")
            if clave_origenes not in self._metricas_en_curso:
                version = self._metricas_versiones.get(clave_origenes, 0)
                self._metricas_en_curso[clave_origenes] = version
                threading.Thread(
                    target=self._contar_archivos_origenes,
                    args=(clave_origenes, version),
                    daemon=True,
                    name="HiloConteoArchivos",
                ).start()
        else:
            self.metric_archivos.metric_label.setText(str(total_archivos))

        coincidencias = len(self._preview_operaciones)
        procesados = self._contar_procesados_historial()
        self.metric_carpetas.metric_label.setText(str(len(origenes)))
        self.metric_coincidencias.metric_label.setText(str(coincidencias))
        self.metric_procesados.metric_label.setText(str(procesados))
        self.boton_iniciar.setEnabled(bool(self.reglas) and not self._procesando)

        if not self.reglas:
            self.var_estado.setText("Crea al menos una regla para comenzar.")
        elif not self._procesando:
            self.var_estado.setText("Listo para iniciar.")

    def _contar_archivos_origenes(self, origenes, version):
        total_archivos = 0
        for origen in origenes:
            if os.path.isdir(origen):
                for _, _, archivos in os.walk(origen):
                    total_archivos += len(archivos)
        self._ui_callback({
            "tipo": "metricas_archivos",
            "origenes": origenes,
            "version": version,
            "valor": total_archivos,
        })

    # ------------------------------------------------------------------
    # Organizar / Preview
    # ------------------------------------------------------------------

    def _crear_pagina_organizar(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        layout.addLayout(self._titulo_pagina(
            "Organizar",
            "Revisa las coincidencias de tus reglas y decide qué operaciones quieres ejecutar."
        ))

        top = QHBoxLayout()
        self.preview_total_var = QLabel("Archivos encontrados: 0")
        self.preview_pendientes_var = QLabel("Pendientes: 0")
        self.preview_excluidos_var = QLabel("Descartados: 0")
        self.preview_copiar_var = QLabel("Copiar: 0")
        self.preview_mover_var = QLabel("Mover: 0")
        self.preview_duplicados_var = QLabel("Duplicados: 0")
        self.preview_errores_var = QLabel("Errores: 0")
        for label in (
            self.preview_total_var,
            self.preview_pendientes_var,
            self.preview_excluidos_var,
            self.preview_copiar_var,
            self.preview_mover_var,
            self.preview_duplicados_var,
            self.preview_errores_var,
        ):
            label.setObjectName("small_muted")
            top.addWidget(label)
        top.addStretch(1)
        top.addWidget(self._crear_boton("↻ Analizar reglas", self._abrir_vista_previa, ghost=True))
        layout.addLayout(top)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Buscar:"))
        self.preview_busqueda = QLineEdit()
        self.preview_busqueda.setPlaceholderText("Archivo, regla, palabra o destino...")
        self.preview_busqueda.textChanged.connect(self._filtrar_preview)
        tools.addWidget(self.preview_busqueda, 1)
        tools.addWidget(self._crear_boton("Seleccionar todos", self._seleccionar_todos_preview, ghost=True))
        tools.addWidget(self._crear_boton("Deseleccionar todos", self._deseleccionar_todos_preview, ghost=True))
        tools.addWidget(self._crear_boton("Quitar seleccionados", self._quitar_de_ejecucion_preview, ghost=True))
        layout.addLayout(tools)

        self.preview_barra = QProgressBar()
        self.preview_barra.setRange(0, 100)
        self.preview_barra.setValue(0)
        layout.addWidget(self.preview_barra)
        self.preview_barra_label = QLabel("Pulsa 'Analizar reglas' para generar la previsualización.")
        self.preview_barra_label.setObjectName("small_muted")
        layout.addWidget(self.preview_barra_label)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        self.preview_table = QTableWidget(0, 7)
        self.preview_table.setHorizontalHeaderLabels(["Seleccionado", "Archivo", "Regla", "Palabra", "Acción", "Origen", "Destino"])
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.doubleClicked.connect(self._alternar_fila_preview)
        card_layout.addWidget(self.preview_table)
        layout.addWidget(card, 1)

        footer = QHBoxLayout()
        self.preview_cancelar = self._crear_boton("Cancelar análisis", self._cancelar_analisis_preview, ghost=True)
        self.preview_continuar = self._crear_boton("Usar selección en Inicio", self._continuar_con_vista_previa, primary=True)
        self.preview_continuar.setEnabled(False)
        footer.addWidget(self.preview_cancelar)
        footer.addStretch(1)
        footer.addWidget(self.preview_continuar)
        layout.addLayout(footer)
        return page

    def _abrir_vista_previa(self):
        if self._procesando:
            return
        if not self.reglas:
            QMessageBox.information(self, "Organizar", "Debes crear al menos una regla de clasificación primero.")
            self._mostrar_pagina("Reglas")
            return

        reglas_para_proceso = [normalizar_regla(regla) for regla in self.reglas]
        reglas_para_proceso = [
            regla for regla in reglas_para_proceso
            if regla["origen"] and regla["destino"] and regla_tiene_criterio(regla)
        ]
        if not reglas_para_proceso:
            QMessageBox.warning(self, "Organizar", "No hay reglas válidas para analizar.")
            return

        self._preview_cancel_event = threading.Event()
        self._preview_queue = queue.Queue()
        self._preview_operaciones = []
        self.preview_barra.setValue(0)
        self.preview_barra_label.setText("Analizando reglas y archivos...")
        self.preview_continuar.setEnabled(False)
        self._mostrar_pagina("Organizar")

        self._preview_hilo = threading.Thread(
            target=self._generar_preview_en_hilo,
            args=(reglas_para_proceso, self.biblioteca_completa),
            daemon=True,
            name="HiloPreview"
        )
        self._preview_hilo.start()
        self._procesar_cola_preview()

    def _generar_preview_en_hilo(self, reglas, biblioteca):
        try:
            operaciones = generar_vista_previa(
                reglas,
                ui_callback=self._preview_ui_callback,
                cancel_event=self._preview_cancel_event,
                biblioteca=biblioteca,
            )
            self._preview_ui_callback({"tipo": "preview_done", "data": operaciones})
        except Exception as exc:
            if self._preview_cancel_event.is_set():
                self._preview_ui_callback({"tipo": "preview_cancelado", "mensaje": "Análisis cancelado."})
            else:
                self._preview_ui_callback({"tipo": "preview_error", "mensaje": str(exc)})

    def _preview_ui_callback(self, dato):
        self._preview_queue.put(dato)

    def _procesar_cola_preview(self):
        while True:
            try:
                dato = self._preview_queue.get_nowait()
            except queue.Empty:
                break

            tipo = dato.get("tipo")
            if tipo == "analisis":
                self.preview_barra.setValue(int(dato.get("valor", 0)))
                self.preview_barra_label.setText(str(dato.get("texto", "Analizando...")))
            elif tipo == "analisis_indeterminado":
                self.preview_barra.setRange(0, 0)
            elif tipo == "preview_total":
                self.preview_barra_label.setText(
                    f"Análisis completado: {dato.get('valor', 0)} operaciones detectadas."
                )
            elif tipo == "preview_done":
                self._preview_operaciones = dato.get("data", [])
                self._refrescar_preview()
                self.preview_barra.setRange(0, 100)
                self.preview_barra.setValue(100)
                self.preview_barra_label.setText("Vista previa lista.")
                self._actualizar_resumen_inicio()
            elif tipo == "preview_error":
                self.preview_barra.setRange(0, 100)
                QMessageBox.critical(self, "Error en análisis", dato.get("mensaje", "Error desconocido."))
                self.preview_barra_label.setText("Error durante el análisis.")
            elif tipo == "preview_cancelado":
                self.preview_barra.setRange(0, 100)
                self.preview_barra_label.setText("Análisis cancelado.")

        if self.content_stack.currentWidget() is not None:
            QTimer.singleShot(80, self._procesar_cola_preview)

    def _refrescar_preview(self):
        self.preview_table.setRowCount(0)
        total = len(self._preview_operaciones)
        pendientes = sum(1 for op in self._preview_operaciones if op.get("seleccionado", False))
        excluidos = total - pendientes
        copiar = sum(1 for op in self._preview_operaciones if op.get("seleccionado", False) and op.get("modo", "copy") == "copy")
        mover = sum(1 for op in self._preview_operaciones if op.get("seleccionado", False) and op.get("modo", "copy") == "move")
        duplicados = sum(1 for op in self._preview_operaciones if op.get("duplicado", False) and op.get("seleccionado", False))
        errores = sum(1 for op in self._preview_operaciones if op.get("estado", "").lower().startswith("error"))

        self.preview_total_var.setText(f"Archivos encontrados: {total}")
        self.preview_pendientes_var.setText(f"Pendientes: {pendientes}")
        self.preview_excluidos_var.setText(f"Descartados: {excluidos}")
        self.preview_copiar_var.setText(f"Copiar: {copiar}")
        self.preview_mover_var.setText(f"Mover: {mover}")
        self.preview_duplicados_var.setText(f"Duplicados: {duplicados}")
        self.preview_errores_var.setText(f"Errores: {errores}")

        texto_filtro = (self.preview_busqueda.text() or "").strip().lower()
        for op in self._preview_operaciones:
            contenido_busqueda = " ".join([
                op.get("archivo", ""),
                str(op.get("regla", "")),
                op.get("destino", ""),
                op.get("palabra", ""),
            ]).lower()
            if texto_filtro and texto_filtro not in contenido_busqueda:
                continue

            row = self.preview_table.rowCount()
            self.preview_table.insertRow(row)
            self.preview_table.setItem(row, 0, QTableWidgetItem("✓" if op.get("seleccionado", False) else ""))
            self.preview_table.setItem(row, 1, QTableWidgetItem(str(op.get("archivo", ""))))
            self.preview_table.setItem(row, 2, QTableWidgetItem(str(op.get("regla", ""))))
            self.preview_table.setItem(row, 3, QTableWidgetItem(str(op.get("palabra", ""))))
            self.preview_table.setItem(row, 4, QTableWidgetItem(str(op.get("accion", ""))))
            self.preview_table.setItem(row, 5, QTableWidgetItem(str(op.get("origen", ""))))
            self.preview_table.setItem(row, 6, QTableWidgetItem(str(op.get("destino_final", op.get("destino", "")))))

        self.preview_continuar.setText(f"Usar selección en Inicio ({pendientes})")
        self.preview_continuar.setEnabled(pendientes > 0)

    def _alternar_fila_preview(self, index=None):
        row = self.preview_table.currentRow()
        if row < 0:
            return
        archivo_item = self.preview_table.item(row, 1)
        destino_item = self.preview_table.item(row, 6)
        if not archivo_item:
            return
        archivo = archivo_item.text()
        destino = destino_item.text() if destino_item else ""
        for op in self._preview_operaciones:
            if op.get("archivo") == archivo and str(op.get("destino_final", op.get("destino", ""))) == destino:
                op["seleccionado"] = not bool(op.get("seleccionado", False))
                break
        self._refrescar_preview()

    def _filtrar_preview(self):
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
            QMessageBox.information(self, "Organizar", "Selecciona al menos una fila.")
            return
        ids = []
        for row in rows:
            archivo = self.preview_table.item(row, 1).text() if self.preview_table.item(row, 1) else ""
            destino = self.preview_table.item(row, 6).text() if self.preview_table.item(row, 6) else ""
            ids.append((archivo, destino))
        for op in self._preview_operaciones:
            clave = (op.get("archivo", ""), str(op.get("destino_final", op.get("destino", ""))))
            if clave in ids:
                op["seleccionado"] = False
        self._refrescar_preview()

    def _cancelar_analisis_preview(self):
        self._preview_cancel_event.set()
        self.preview_barra_label.setText("Cancelando análisis...")

    def _continuar_con_vista_previa(self):
        ops = [op.copy() for op in self._preview_operaciones if op.get("seleccionado", False)]
        if not ops:
            QMessageBox.information(self, "Organizar", "No queda ninguna operación seleccionada.")
            return
        self._seleccion_preview_vigente = ops
        self._actualizar_resumen_inicio()
        self.var_estado.setText(f"Selección preparada: {len(ops)} archivos listos para procesar.")
        self._mostrar_pagina("Inicio")

    # ------------------------------------------------------------------
    # Reglas
    # ------------------------------------------------------------------

    def _crear_pagina_reglas(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.addLayout(self._titulo_pagina(
            "Reglas",
            "Define cómo FileFlow identifica, clasifica y organiza tus archivos."
        ), 1)
        header.addWidget(self._crear_boton("Importar", self._importar_reglas, ghost=True))
        header.addWidget(self._crear_boton("Exportar", self._exportar_reglas, ghost=True))
        header.addWidget(self._crear_boton("+ Nueva regla", self._agregar_regla, primary=True))
        layout.addLayout(header)

        self.reglas_scroll = QScrollArea()
        self.reglas_scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(2, 2, 8, 2)
        container_layout.setSpacing(12)
        self.reglas_cards_layout = container_layout
        container_layout.addStretch(1)
        self.reglas_scroll.setWidget(container)
        layout.addWidget(self.reglas_scroll, 1)
        return page

    def _crear_tarjeta_regla(self, indice, regla):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel(f"#{indice:02d}   {', '.join(regla.get('palabras', [])) or 'Sin palabra clave'}")
        title.setStyleSheet("font-size:16px; font-weight:800; color:#0f172a;")
        head.addWidget(title, 1)
        active = QLabel("● ACTIVA")
        active.setStyleSheet("color:#16a34a; font-size:11px; font-weight:800;")
        head.addWidget(active)
        layout.addLayout(head)

        details = QGridLayout()
        details.setHorizontalSpacing(18)
        details.setVerticalSpacing(5)
        details.addWidget(QLabel("Origen"), 0, 0)
        details.addWidget(QLabel("Destino"), 0, 1)
        o = QLabel(regla.get("origen", ""))
        d = QLabel(regla.get("destino", ""))
        o.setObjectName("small_muted")
        d.setObjectName("small_muted")
        details.addWidget(o, 1, 0)
        details.addWidget(d, 1, 1)
        details.addWidget(QLabel("Acción"), 2, 0)
        details.addWidget(QLabel("Opciones"), 2, 1)
        a = QLabel("Copiar" if regla.get("modo") == "copy" else "Mover")
        a.setObjectName("small_muted")
        opciones = []
        if regla.get("organizar_por_extension"):
            opciones.append("Extensión")
        if regla.get("organizar_por_fecha"):
            opciones.append("Fecha")
        if regla.get("crear_subcarpetas"):
            opciones.append("Subcarpeta")
        if regla.get("eliminar_duplicados"):
            opciones.append("Duplicados")
        opt = QLabel(" · ".join(opciones) or "Ninguna especial")
        opt.setObjectName("small_muted")
        details.addWidget(a, 3, 0)
        details.addWidget(opt, 3, 1)
        layout.addLayout(details)

        actions = QHBoxLayout()
        actions.addWidget(self._crear_boton("Editar", lambda: self._editar_regla(indice - 1), ghost=True))
        actions.addWidget(self._crear_boton("Duplicar", lambda: self._duplicar_regla(indice - 1), ghost=True))
        actions.addWidget(self._crear_boton("↑", lambda: self._subir_regla(indice - 1), ghost=True))
        actions.addWidget(self._crear_boton("↓", lambda: self._bajar_regla(indice - 1), ghost=True))
        actions.addStretch(1)
        actions.addWidget(self._crear_boton("Eliminar", lambda: self._eliminar_regla(indice - 1), danger=True))
        layout.addLayout(actions)
        return frame

    def _actualizar_tabla_reglas(self):
        if not hasattr(self, "reglas_cards_layout"):
            return
        
        while self.reglas_cards_layout.count() > 0:
            item = self.reglas_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self.reglas:
            empty = QFrame()
            empty.setObjectName("card")
            el = QVBoxLayout(empty)

            # Icono de reglas
            icon_label = QLabel()
            icon_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "Iconos",
                "reglas.png"
            )

            if os.path.exists(icon_path):
                pixmap = QPixmap(icon_path).scaled(
                48,
                48,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
                )
                icon_label.setPixmap(pixmap)

            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setFixedHeight(60)
            el.addWidget(icon_label)

            t = QLabel("No tienes reglas configuradas")
            t.setStyleSheet("font-size:18px; font-weight:800;")
            t.setAlignment(Qt.AlignCenter)
            el.addWidget(t)
            s = QLabel("Crea tu primera regla para indicar a FileFlow cómo organizar tus archivos.")
            s.setObjectName("small_muted")
            s.setAlignment(Qt.AlignCenter)
            el.addWidget(s)
            el.addWidget(self._crear_boton("+ Crear regla", self._agregar_regla, primary=True), 0, Qt.AlignCenter)
            self.reglas_cards_layout.addWidget(empty)
        else:
            for indice, regla in enumerate(self.reglas, start=1):
                self.reglas_cards_layout.addWidget(self._crear_tarjeta_regla(indice, regla))
        self.reglas_cards_layout.addStretch(1)

    def _exportar_reglas(self):
        if not self.reglas:
            QMessageBox.information(self, "Exportar reglas", "No hay reglas creadas para exportar.")
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar reglas", "reglas.fflw", "Reglas FileFlow (*.fflw)")
        if not ruta:
            return
        if not ruta.lower().endswith(".fflw"):
            ruta += ".fflw"
        try:
            guardar_reglas_fflw(ruta, self.reglas)
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Exportar reglas", f"No se pudieron exportar las reglas:\n{exc}")
            return
        QMessageBox.information(self, "Exportar reglas", f"Se exportaron {len(self.reglas)} reglas correctamente.")

    def _importar_reglas(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Importar reglas", "", "Reglas FileFlow (*.fflw)")
        if not ruta:
            return
        try:
            reglas_importadas = cargar_reglas_fflw(ruta)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Importar reglas", f"No se pudieron importar las reglas:\n{exc}")
            return

        def clave_regla(regla):
            return json.dumps(normalizar_regla(regla), ensure_ascii=False, sort_keys=True)

        existentes = {clave_regla(regla) for regla in self.reglas}
        nuevas = []
        for regla in reglas_importadas:
            clave = clave_regla(regla)
            if clave not in existentes:
                existentes.add(clave)
                nuevas.append(regla)
        if nuevas:
            self.reglas.extend(nuevas)
            guardar_reglas(self.reglas)
            self._invalidar_vista_previa()
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_inicio()
        QMessageBox.information(
            self,
            "Importar reglas",
            f"Se importaron {len(nuevas)} reglas nuevas. {len(reglas_importadas) - len(nuevas)} duplicadas fueron omitidas."
        )

    def _validar_regla(self, regla, indice_actual=None):
        regla = normalizar_regla(regla)
        palabras = regla.get("palabras", [])
        origen = regla.get("origen", "")
        destino = regla.get("destino", "")
        if not origen:
            raise ValueError("Debes indicar una carpeta de origen.")
        if not destino:
            raise ValueError("Debes indicar una carpeta de destino.")
        if not os.path.isdir(origen):
            raise ValueError("La carpeta de origen no existe o no es válida.")
        if bool(regla.get("filtrar_extensiones", False)):
            extensiones = normalizar_extensiones(regla.get("extensiones", []))
            if not extensiones:
                raise ValueError("Debes introducir al menos una extensión cuando activas el filtro.")
            regla["extensiones"] = extensiones
        else:
            regla["extensiones"] = []
        if not palabras and not regla_tiene_filtro_activo(regla):
            raise ValueError("Debes indicar una palabra clave o activar al menos un filtro de extensión, fecha o tamaño.")
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
        ventana.setWindowTitle("Editar regla" if editar else "Nueva regla")
        ventana.resize(760, 760)
        ventana.setMinimumSize(700, 700)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_container = QWidget()
        layout = QVBoxLayout(form_container)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        scroll.setWidget(form_container)

        titulo = QLabel("Editar regla" if editar else "Crear nueva regla")
        titulo.setStyleSheet("font-size:22px; font-weight:800;")
        layout.addWidget(titulo)
        subtitulo = QLabel("Configura los criterios y el comportamiento de esta regla.")
        subtitulo.setObjectName("small_muted")
        layout.addWidget(subtitulo)

        layout.addWidget(QLabel("Palabras clave (opcional)"))
        entrada_palabras = QLineEdit()
        entrada_palabras.setPlaceholderText("Ejemplo: factura, facturas, recibo")
        if editar:
            entrada_palabras.setText(", ".join(regla.get("palabras", [])))
        layout.addWidget(entrada_palabras)

        origen_default = (regla or {}).get("origen", "")
        destino_default = (regla or {}).get("destino", "")
        modo_default = (regla or {}).get("modo", "copy")
        eliminar_default = bool((regla or {}).get("eliminar_duplicados", False))
        crear_default = bool((regla or {}).get("crear_subcarpetas", True))
        organizar_por_extension_default = bool((regla or {}).get("organizar_por_extension", False))
        organizar_por_fecha_default = bool((regla or {}).get("organizar_por_fecha", False))
        filtrar_extensiones_default = bool((regla or {}).get("filtrar_extensiones", False))
        extensiones_default = ", ".join((regla or {}).get("extensiones", []))
        fecha_default = (regla or {}).get("fecha_archivo", {})
        tamaño_default = (regla or {}).get("tamaño_archivo", {})

        layout.addWidget(QLabel("Carpeta de origen"))
        var_origen = FolderDropLineEdit()
        var_origen.setText(origen_default)
        row_origen = QHBoxLayout()
        row_origen.addWidget(var_origen, 1)
        btn_origen = self._crear_boton("Seleccionar", lambda: self._seleccionar_origen_regla(var_origen), ghost=True)
        row_origen.addWidget(btn_origen)
        layout.addLayout(row_origen)

        layout.addWidget(QLabel("Carpeta de destino"))
        var_destino = FolderDropLineEdit()
        var_destino.setText(destino_default)
        row_destino = QHBoxLayout()
        row_destino.addWidget(var_destino, 1)
        btn_destino = self._crear_boton("Seleccionar", lambda: self._seleccionar_destino_regla(var_destino), ghost=True)
        row_destino.addWidget(btn_destino)
        layout.addLayout(row_destino)

        opciones = QFrame()
        opciones.setObjectName("soft_card")
        ol = QVBoxLayout(opciones)
        ol.setContentsMargins(14, 12, 14, 12)
        ol.addWidget(QLabel("Organización"))

        var_crear_subcarpetas = QCheckBox("Crear subcarpeta según palabra clave")
        var_crear_subcarpetas.setChecked(crear_default)
        ol.addWidget(var_crear_subcarpetas)

        var_organizar_por_extension = QCheckBox("Organizar automáticamente según la extensión")
        var_organizar_por_extension.setChecked(organizar_por_extension_default)
        ol.addWidget(var_organizar_por_extension)

        ext_info = QLabel("Utiliza la Biblioteca de extensiones de FileFlow para construir parte del destino.")
        ext_info.setObjectName("small_muted")
        ol.addWidget(ext_info)

        var_organizar_por_fecha = QCheckBox("Organizar automáticamente según la fecha")
        var_organizar_por_fecha.setChecked(organizar_por_fecha_default)
        ol.addWidget(var_organizar_por_fecha)

        layout.addWidget(opciones)

        filtrar_frame = QFrame()
        filtrar_frame.setObjectName("soft_card")
        fl = QVBoxLayout(filtrar_frame)
        fl.setContentsMargins(14, 12, 14, 12)
        var_filtrar_extensiones = QCheckBox("Filtrar por extensiones")
        var_filtrar_extensiones.setChecked(filtrar_extensiones_default)
        fl.addWidget(var_filtrar_extensiones)
        var_extensiones = QLineEdit(extensiones_default)
        var_extensiones.setPlaceholderText("Ejemplo: jpg, png, pdf")
        var_extensiones.setEnabled(filtrar_extensiones_default)
        fl.addWidget(var_extensiones)
        var_filtrar_extensiones.toggled.connect(var_extensiones.setEnabled)
        layout.addWidget(filtrar_frame)

        constructor_fecha = ConstructorFecha(fecha_default)
        layout.addWidget(constructor_fecha)
        constructor_tamano = ConstructorTamano(tamaño_default)
        layout.addWidget(constructor_tamano)

        accion_frame = QFrame()
        accion_frame.setObjectName("soft_card")
        al = QVBoxLayout(accion_frame)
        al.setContentsMargins(14, 12, 14, 12)
        al.addWidget(QLabel("Acción"))
        var_modo = QComboBox()
        var_modo.addItem("Copiar archivos", "copy")
        var_modo.addItem("Mover archivos", "move")
        var_modo.setCurrentIndex(0 if modo_default == "copy" else 1)
        al.addWidget(var_modo)
        var_eliminar_duplicados = QCheckBox("Eliminar del origen los duplicados exactamente iguales")
        var_eliminar_duplicados.setChecked(eliminar_default)
        al.addWidget(var_eliminar_duplicados)
        layout.addWidget(accion_frame)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = self._crear_boton("Cancelar", ventana.reject, ghost=True)
        save = self._crear_boton("Guardar regla", None, primary=True)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        def guardar():
            try:
                palabras = [p.strip() for p in entrada_palabras.text().split(",") if p.strip()]
                nueva_regla = {
                    "palabras": palabras,
                    "origen": var_origen.text().strip(),
                    "destino": normalizar_destino_regla(var_destino.text().strip()),
                    "modo": var_modo.currentData(),
                    "crear_subcarpetas": var_crear_subcarpetas.isChecked(),
                    "organizar_por_extension": var_organizar_por_extension.isChecked(),
                    "organizar_por_fecha": var_organizar_por_fecha.isChecked(),
                    "eliminar_duplicados": var_eliminar_duplicados.isChecked(),
                    "filtrar_extensiones": var_filtrar_extensiones.isChecked(),
                    "extensiones": var_extensiones.text().strip(),
                    "fecha_archivo": constructor_fecha.obtener_condicion(),
                    "tamaño_archivo": constructor_tamano.obtener_condicion(),
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
                self._actualizar_resumen_inicio()
                ventana.accept()
            except ValueError as exc:
                QMessageBox.warning(ventana, "Regla no válida", str(exc))

        save.clicked.connect(guardar)
        ventana_layout = QVBoxLayout(ventana)
        ventana_layout.setContentsMargins(0, 0, 0, 0)
        ventana_layout.addWidget(scroll)
        ventana.exec()

    def _seleccionar_origen_regla(self, var_origen):
        carpeta = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta de origen de la regla")
        if carpeta:
            var_origen.setText(normalizar_ruta_regla(carpeta))

    def _seleccionar_destino_regla(self, var_destino_regla):
        carpeta = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta destino de la regla")
        if carpeta:
            var_destino_regla.setText(normalizar_destino_regla(carpeta))

    def _agregar_regla(self):
        self._mostrar_ventana_regla()

    def _editar_regla(self, indice):
        if indice < 0 or indice >= len(self.reglas):
            return
        self._mostrar_ventana_regla(self.reglas[indice])

    def _duplicar_regla(self, indice):
        if indice < 0 or indice >= len(self.reglas):
            return
        copia = normalizar_regla(self.reglas[indice])
        copia["palabras"] = list(copia.get("palabras", []))
        if "origen" in copia:
            self.reglas.insert(indice + 1, copia)
            guardar_reglas(self.reglas)
            self._actualizar_tabla_reglas()
            self._actualizar_resumen_inicio()

    def _eliminar_regla(self, indice):
        if indice < 0 or indice >= len(self.reglas):
            return
        regla = self.reglas[indice]
        texto = f"{', '.join(regla.get('palabras', [])) or 'Sin palabra clave'} → {regla.get('destino', '')}"
        respuesta = QMessageBox.question(self, "Eliminar regla", f"¿Quieres eliminar la regla?\n\n{texto}")
        if respuesta != QMessageBox.Yes:
            return
        del self.reglas[indice]
        guardar_reglas(self.reglas)
        self._invalidar_vista_previa()
        self._actualizar_tabla_reglas()
        self._actualizar_resumen_inicio()

    def _subir_regla(self, indice):
        if indice <= 0 or indice >= len(self.reglas):
            return
        self.reglas[indice - 1], self.reglas[indice] = self.reglas[indice], self.reglas[indice - 1]
        guardar_reglas(self.reglas)
        self._invalidar_vista_previa()
        self._actualizar_tabla_reglas()

    def _bajar_regla(self, indice):
        if indice < 0 or indice >= len(self.reglas) - 1:
            return
        self.reglas[indice], self.reglas[indice + 1] = self.reglas[indice + 1], self.reglas[indice]
        guardar_reglas(self.reglas)
        self._invalidar_vista_previa()
        self._actualizar_tabla_reglas()

    def _invalidar_vista_previa(self):
        self._seleccion_preview_vigente = None
        self._preview_operaciones = []
        if hasattr(self, "preview_table"):
            self._refrescar_preview()

    # ------------------------------------------------------------------
    # Biblioteca
    # ------------------------------------------------------------------

    def _ruta_biblioteca_usuario(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "biblioteca_usuario.json")

    def _cargar_biblioteca_usuario(self):
        ruta = self._ruta_biblioteca_usuario()
        if not os.path.exists(ruta):
            return {}
        try:
            with open(ruta, "r", encoding="utf-8") as archivo:
                datos = json.load(archivo)
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(datos, dict):
            return {}
        resultado = {}
        for categoria, extensiones in datos.items():
            categoria_limpia = normalizar_categoria_extension(categoria)
            if not categoria_limpia:
                continue
            for extension in normalizar_extensiones(extensiones):
                resultado[extension] = categoria_limpia
        return resultado

    def _guardar_biblioteca_usuario(self, categoria, extensiones):
        ruta = self._ruta_biblioteca_usuario()
        existentes = {}
        if os.path.exists(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as archivo:
                    existentes = json.load(archivo)
            except (OSError, ValueError, json.JSONDecodeError):
                existentes = {}
        if not isinstance(existentes, dict):
            existentes = {}
        existentes[categoria] = normalizar_extensiones(extensiones)
        with open(ruta, "w", encoding="utf-8") as archivo:
            json.dump(existentes, archivo, ensure_ascii=False, indent=2)

    def _crear_pagina_biblioteca(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addLayout(self._titulo_pagina(
            "Biblioteca",
            "Catálogo de extensiones y sus clasificaciones. Las asociaciones oficiales son de solo lectura."
        ), 1)
        header.addWidget(self._crear_boton("+ Nueva categoría", self._agregar_categoria_biblioteca, primary=True))
        layout.addLayout(header)

        self.biblioteca_busqueda = QLineEdit()
        self.biblioteca_busqueda.setPlaceholderText("Buscar categoría o extensión...")
        self.biblioteca_busqueda.textChanged.connect(self._actualizar_biblioteca_ui)
        layout.addWidget(self.biblioteca_busqueda)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.biblioteca_layout = QVBoxLayout(container)
        self.biblioteca_layout.setContentsMargins(2, 2, 8, 2)
        self.biblioteca_layout.setSpacing(10)
        scroll.setWidget(container)
        self.biblioteca_scroll = scroll
        layout.addWidget(scroll, 1)
        return page

    def _actualizar_biblioteca_ui(self):
        if not hasattr(self, "biblioteca_layout"):
            return
        while self.biblioteca_layout.count() > 0:
            item = self.biblioteca_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        grupos = {}
        for extension, categoria in self.biblioteca.items():
            grupos.setdefault(categoria, set()).add(extension)
        for extension, categoria in self.biblioteca_usuario.items():
            grupos.setdefault(categoria, set()).add(extension)

        filtro = (self.biblioteca_busqueda.text() if hasattr(self, "biblioteca_busqueda") else "").strip().lower()
        for categoria in sorted(grupos, key=str.lower):
            extensiones = sorted(grupos[categoria], key=lambda x: (len(x), x))
            if filtro and filtro not in categoria.lower() and not any(filtro in ext.lower() for ext in extensiones):
                continue
            card = QFrame()
            card.setObjectName("card")
            l = QHBoxLayout(card)
            l.setContentsMargins(16, 14, 16, 14)
            emoji = "📚"
            nombre = QLabel(f"{emoji}  {categoria}")
            nombre.setStyleSheet("font-size:16px; font-weight:800;")
            l.addWidget(nombre, 1)
            count = QLabel(str(len(extensiones)))
            count.setObjectName("metric")
            count.setStyleSheet("font-size:20px; font-weight:800;")
            l.addWidget(count)
            btn = self._crear_boton("Ver", lambda checked=False, c=categoria: self._ver_categoria_biblioteca(c), ghost=True)
            l.addWidget(btn)
            self.biblioteca_layout.addWidget(card)
        self.biblioteca_layout.addStretch(1)

    def _ver_categoria_biblioteca(self, categoria):
        extensiones = []
        for ext, cat in {**self.biblioteca, **self.biblioteca_usuario}.items():
            if cat == categoria:
                extensiones.append(ext)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Biblioteca · {categoria}")
        dlg.resize(620, 600)
        layout = QVBoxLayout(dlg)
        title = QLabel(categoria)
        title.setStyleSheet("font-size:22px; font-weight:800;")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"{len(extensiones)} extensiones reconocidas"))
        table = QTableWidget(len(extensiones), 2)
        table.setHorizontalHeaderLabels(["Extensión", "Clasificación"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for row, ext in enumerate(sorted(extensiones)):
            table.setItem(row, 0, QTableWidgetItem(f".{ext}"))
            table.setItem(row, 1, QTableWidgetItem(categoria))
        layout.addWidget(table)
        close = self._crear_boton("Cerrar", dlg.accept, ghost=True)
        layout.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()

    def _agregar_categoria_biblioteca(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Nueva categoría personalizada")
        dlg.resize(520, 320)
        layout = QVBoxLayout(dlg)
        title = QLabel("Agregar categoría")
        title.setStyleSheet("font-size:21px; font-weight:800;")
        layout.addWidget(title)
        info = QLabel("Las categorías oficiales de FileFlow no se modifican. Esta categoría quedará en tu biblioteca personalizada.")
        info.setWordWrap(True)
        info.setObjectName("small_muted")
        layout.addWidget(info)
        layout.addWidget(QLabel("Nombre"))
        nombre = QLineEdit()
        layout.addWidget(nombre)
        layout.addWidget(QLabel("Extensiones"))
        extensiones = QLineEdit()
        extensiones.setPlaceholderText("Ejemplo: abc, xyz, foo")
        layout.addWidget(extensiones)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._crear_boton("Cancelar", dlg.reject, ghost=True))
        guardar = self._crear_boton("Crear categoría", None, primary=True)
        buttons.addWidget(guardar)
        layout.addLayout(buttons)

        def crear():
            categoria = normalizar_categoria_extension(nombre.text())
            exts = normalizar_extensiones(extensiones.text())
            if not categoria:
                QMessageBox.warning(dlg, "Categoría", "Introduce un nombre de categoría.")
                return
            if not exts:
                QMessageBox.warning(dlg, "Extensiones", "Introduce al menos una extensión.")
                return
            conflicto = [ext for ext in exts if ext in self.biblioteca]
            if conflicto:
                QMessageBox.warning(
                    dlg,
                    "Extensiones oficiales",
                    "Estas extensiones ya pertenecen a la biblioteca oficial y no pueden redefinirse:\n\n" + ", ".join(conflicto)
                )
                return
            self._guardar_biblioteca_usuario(categoria, exts)
            self.biblioteca_usuario = self._cargar_biblioteca_usuario()
            self.biblioteca_completa = {**self.biblioteca, **self.biblioteca_usuario}
            self._actualizar_biblioteca_ui()
            dlg.accept()

        guardar.clicked.connect(crear)
        dlg.exec()

    # ------------------------------------------------------------------
    # IA
    # ------------------------------------------------------------------

    def _crear_pagina_ia(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(self._titulo_pagina(
            "FileFlow Intelligence",
            "Automatización inteligente local para crear reglas y clasificar archivos."
        ))

        card = QFrame()
        card.setObjectName("card")
        l = QVBoxLayout(card)
        l.setContentsMargins(24, 24, 24, 24)
        icon = QLabel("🧠")
        icon.setStyleSheet("font-size:42px;")
        icon.setAlignment(Qt.AlignCenter)
        l.addWidget(icon)
        title = QLabel("La IA todavía está en desarrollo")
        title.setStyleSheet("font-size:22px; font-weight:800;")
        title.setAlignment(Qt.AlignCenter)
        l.addWidget(title)
        desc = QLabel(
            "La futura IA podrá analizar archivos, crear reglas automáticamente y clasificar "
            "archivos utilizando distintos niveles de confianza, manteniendo el procesamiento local."
        )
        desc.setWordWrap(True)
        desc.setObjectName("small_muted")
        desc.setAlignment(Qt.AlignCenter)
        l.addWidget(desc)
        l.addSpacing(10)
        for texto in (
            "✓ Crear reglas automáticamente",
            "✓ Clasificar por contenido y contexto",
            "✓ Aprender de las decisiones del usuario",
            "✓ Reducir la intervención cuando exista alta confianza",
        ):
            lb = QLabel(texto)
            lb.setAlignment(Qt.AlignCenter)
            l.addWidget(lb)
        estado = QLabel("● Próximamente")
        estado.setStyleSheet("color:#64748b; font-weight:800;")
        estado.setAlignment(Qt.AlignCenter)
        l.addSpacing(10)
        l.addWidget(estado)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Historial
    # ------------------------------------------------------------------

    def _historial_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "historial.jsonl")

    def _guardar_historial_proceso(self, dato):
        ruta = self._historial_path()
        registro = {
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "estado": "cancelado" if dato.get("cancelado") else "error" if dato.get("error") else "finalizado",
            "mensajes": list(self._history_current),
        }
        if self._history_operations:
            registro["operaciones"] = list(self._history_operations)
        if dato.get("tipo") == "reversion":
            registro.update({
                "tipo": "reversion",
                "reversion_of": dato.get("reversion_of"),
            })
        try:
            with open(ruta, "a", encoding="utf-8") as archivo:
                archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _leer_historial(self):
        ruta = self._historial_path()
        if not os.path.exists(ruta):
            return []
        registros = []
        try:
            with open(ruta, "r", encoding="utf-8") as archivo:
                for linea in archivo:
                    try:
                        datos = json.loads(linea)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(datos, dict):
                        registros.append(datos)
        except OSError:
            return []
        return list(reversed(registros))

    def _contar_procesados_historial(self):
        total = 0
        for registro in self._leer_historial():
            for mensaje in registro.get("mensajes", []):
                if "Archivo copiado correctamente:" in mensaje or "Archivo movido correctamente:" in mensaje:
                    total += 1
        return total

    def _crear_pagina_historial(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(self._titulo_pagina(
            "Historial",
            "Registro de los procesos de copia, movimiento, duplicados y errores."
        ))
        self.historial_scroll = QScrollArea()
        self.historial_scroll.setWidgetResizable(True)
        container = QWidget()
        self.historial_layout = QVBoxLayout(container)
        self.historial_layout.setContentsMargins(2, 2, 8, 2)
        self.historial_layout.setSpacing(10)
        self.historial_scroll.setWidget(container)
        layout.addWidget(self.historial_scroll, 1)
        return page

    def _actualizar_historial_ui(self):
        if not hasattr(self, "historial_layout"):
            return
        while self.historial_layout.count() > 0:
            item = self.historial_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        registros = self._leer_historial()
        if not registros:
            card = QFrame()
            card.setObjectName("card")
            l = QVBoxLayout(card)
            l.addWidget(QLabel("📜"), 0, Qt.AlignCenter)
            t = QLabel("Todavía no hay procesos registrados.")
            t.setAlignment(Qt.AlignCenter)
            t.setStyleSheet("font-size:18px; font-weight:800;")
            l.addWidget(t)
            s = QLabel("Tus operaciones aparecerán aquí después de ejecutar FileFlow.")
            s.setAlignment(Qt.AlignCenter)
            s.setObjectName("small_muted")
            l.addWidget(s)
            self.historial_layout.addWidget(card)
        else:
            for registro in registros:
                card = QFrame()
                card.setObjectName("card")
                l = QVBoxLayout(card)
                l.setContentsMargins(16, 14, 16, 14)
                fecha_texto = registro.get("fecha", "").replace("T", "  ")
                estado = registro.get("estado", "desconocido").capitalize()
                header = QHBoxLayout()
                t = QLabel(fecha_texto)
                t.setStyleSheet("font-weight:800;")
                header.addWidget(t, 1)
                estado_label = QLabel(estado)
                estado_label.setStyleSheet("color:#2563eb; font-weight:800;")
                header.addWidget(estado_label)
                l.addLayout(header)
                mensajes = registro.get("mensajes", [])
                operaciones = registro.get("operaciones", [])
                if not isinstance(operaciones, list):
                    operaciones = []
                resumen = QLabel(
                    f"{len(operaciones)} operaciones registradas"
                    if operaciones else f"{len(mensajes)} eventos registrados"
                )
                resumen.setObjectName("small_muted")
                l.addWidget(resumen)
                detalles = QPlainTextEdit("\n".join(mensajes[-25:]))
                detalles.setReadOnly(True)
                detalles.setMaximumHeight(150)
                l.addWidget(detalles)
                if operaciones and registro.get("tipo") != "reversion":
                    boton_revertir = self._crear_boton(
                        f"Revertir ({len(operaciones)})",
                        lambda checked=False, r=registro: self._iniciar_reversion(r),
                        ghost=True,
                    )
                    l.addWidget(boton_revertir)
                self.historial_layout.addWidget(card)
        self.historial_layout.addStretch(1)

    # ------------------------------------------------------------------
    # Ajustes
    # ------------------------------------------------------------------

    def _crear_pagina_ajustes(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(self._titulo_pagina(
            "Ajustes",
            "Preferencias de apariencia, organización y automatización."
        ))

        def panel(titulo, widgets):
            frame = QFrame()
            frame.setObjectName("card")
            l = QVBoxLayout(frame)
            l.setContentsMargins(16, 14, 16, 14)
            h = QLabel(titulo)
            h.setStyleSheet("font-size:16px; font-weight:800;")
            l.addWidget(h)
            for w in widgets:
                l.addWidget(w)
            return frame

        tema = QComboBox()
        tema.addItems(["Sistema", "Claro", "Oscuro"])
        tema.setCurrentIndex(1)
        apariencia_info = QLabel("Las preferencias visuales se preparan para futuras variantes de tema.")
        apariencia_info.setObjectName("small_muted")
        layout.addWidget(panel("Apariencia", [QLabel("Tema"), tema, apariencia_info]))

        sonido = QCheckBox("Activar sonidos del sistema")
        sonido.setEnabled(False)
        sonido.setToolTip("Próximamente")
        sonido_info = QLabel("Los sonidos se agregarán en una versión futura.")
        sonido_info.setObjectName("small_muted")
        layout.addWidget(panel("Sonido", [sonido, sonido_info]))

        vista_previa = QCheckBox("Mostrar vista previa antes de ejecutar")
        vista_previa.setChecked(True)
        confirmar = QCheckBox("Confirmar operaciones destructivas")
        confirmar.setChecked(True)
        sobrescribir = QCheckBox("Evitar sobrescribir archivos existentes")
        sobrescribir.setChecked(True)
        layout.addWidget(panel("Organización", [vista_previa, confirmar, sobrescribir]))

        vigilancia = QCheckBox("Permitir vigilancia automática mediante reglas")
        vigilancia.setEnabled(False)
        vigilancia.setToolTip("Próximamente")
        vigilancia_info = QLabel(
            "Más adelante podrás elegir qué reglas pueden actuar como reglas de vigilancia."
        )
        vigilancia_info.setObjectName("small_muted")
        vigilancia_info.setWordWrap(True)
        layout.addWidget(panel("Automatización", [vigilancia, vigilancia_info]))
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Procesamiento
    # ------------------------------------------------------------------

    def _registrar_log(self, mensaje):
        texto = str(mensaje)
        self._history_current.append(texto)
        if self.log_text is not None:
            self.log_text.appendPlainText(texto)

    def _iniciar_reversion(self, registro):
        if self._procesando:
            QMessageBox.information(self, "FileFlow", "Hay otro proceso en ejecución.")
            return
        operaciones = registro.get("operaciones")
        if not isinstance(operaciones, list) or not operaciones:
            return
        self._history_current = []
        self.log_text.clear()
        self._procesando = True
        self.cancel_event = threading.Event()
        self._reversion_context = {
            "registro": registro,
            "resultados": None,
            "decision_event": threading.Event(),
        }
        self.boton_iniciar.setEnabled(False)
        self.boton_cancelar.setEnabled(True)
        self.var_estado.setText("Analizando reversión...")
        self._hilo_proceso = threading.Thread(
            target=self._ejecutar_reversion_worker,
            args=(operaciones,),
            daemon=True,
            name="HiloReversion",
        )
        self._hilo_proceso.start()

    def _ejecutar_reversion_worker(self, operaciones):
        try:
            self._ui_callback({"tipo": "log", "mensaje": "Inicio de análisis de reversión..."})
            resultados = analizar_reversion(operaciones, self.cancel_event, self._ui_callback)
            self._ui_callback({"tipo": "reversion_analisis", "resultados": resultados})
            self._reversion_context["decision_event"].wait()
            if not self._reversion_decision:
                self._ui_callback({"tipo": "terminado", "cancelado": True, "error": None})
                return
            self._ui_callback({"tipo": "log", "mensaje": "Iniciando reversión..."})
            revertidas = ejecutar_reversion(resultados, self._ui_callback, self.cancel_event)
            self._ui_callback({
                "tipo": "reversion_terminado",
                "revertidas": revertidas,
                "reversion_of": self._reversion_context["registro"].get("fecha"),
            })
        except Exception as exc:
            self._ui_callback({"tipo": "error", "mensaje": str(exc)})
            self._ui_callback({"tipo": "terminado", "cancelado": False, "error": str(exc)})

    def _ui_callback(self, dato):
        self._cola.put(dato)

    def _procesar_cola(self):
        procesados_cola = 0
        while procesados_cola < 100:
            try:
                dato = self._cola.get_nowait()
            except queue.Empty:
                break
            procesados_cola += 1

            tipo = dato.get("tipo")
            if tipo == "actual":
                self.var_progreso_actual = float(dato.get("valor", 0))
                self.barra_actual.setValue(int(self.var_progreso_actual))
                self.var_texto_actual.setText(dato.get("texto", "0%"))
                if dato.get("estado"):
                    self.var_estado.setText(dato["estado"])
            elif tipo == "analisis":
                self.var_progreso_analisis = float(dato.get("valor", 0))
                if self.barra_analisis.maximum() != 0 or self.var_progreso_analisis >= 100:
                    self.barra_analisis.setRange(0, 100)
                    self.barra_analisis.setValue(int(self.var_progreso_analisis))
                self.var_texto_analisis.setText(dato.get("texto", "0% analizado"))
            elif tipo == "analisis_indeterminado":
                self.barra_analisis.setRange(0, 0)
                self.var_texto_analisis.setText("Analizando archivos...")
            elif tipo == "metricas_archivos":
                origenes = tuple(dato.get("origenes", ()))
                version = dato.get("version")
                if self._metricas_en_curso.get(origenes) != version:
                    continue
                self._metricas_en_curso.pop(origenes, None)
                valor = int(dato.get("valor", 0))
                self._metricas_archivos_cache[origenes] = (valor, time.monotonic())
                clave_actual = tuple(sorted({
                    normalizar_ruta_regla(regla.get("origen", ""))
                    for regla in self.reglas
                    if normalizar_ruta_regla(regla.get("origen", ""))
                }))
                if clave_actual == origenes:
                    self.metric_archivos.metric_label.setText(str(valor))
            elif tipo == "estado":
                self.var_estado.setText(dato.get("estado", "Listo para iniciar."))
            elif tipo == "log":
                self._registrar_log(dato.get("mensaje", ""))
            elif tipo == "operacion_completada":
                self._history_operations.append(dict(dato.get("operacion", {})))
            elif tipo == "reversion_item":
                operacion = dato.get("operacion", {})
                estado = operacion.get("status", "unsafe")
                nombre = os.path.basename(operacion.get("path", ""))
                self._registrar_log(f"Verificado: {nombre} ({estado})")
            elif tipo == "reversion_analisis":
                resultados = dato.get("resultados", [])
                self._reversion_context["resultados"] = resultados
                seguros = [r for r in resultados if r.get("status") == "safe"]
                problemas = [r for r in resultados if r.get("status") != "safe"]
                etiquetas = {
                    "missing": "no encontrado",
                    "modified": "modificado",
                    "conflict": "conflicto",
                    "already_reverted": "ya revertido",
                    "unsafe": "no verificable",
                }
                detalle = "\n".join(
                    f"• {r.get('path', '')}: {etiquetas.get(r.get('status'), r.get('status'))}"
                    for r in problemas
                ) or "Ningún archivo presenta problemas."
                mensaje = QMessageBox(self)
                mensaje.setIcon(QMessageBox.Warning if problemas else QMessageBox.Information)
                mensaje.setWindowTitle("Confirmar reversión")
                mensaje.setText(f"{len(seguros)} archivos pueden revertirse.")
                mensaje.setInformativeText(
                    f"{len(problemas)} archivos se omitirán por seguridad.\n\n{detalle}"
                )
                mensaje.addButton("Cancelar", QMessageBox.RejectRole)
                continuar = mensaje.addButton(
                    f"Continuar con {len(seguros)} archivos", QMessageBox.AcceptRole
                )
                self._reversion_decision = mensaje.exec() and mensaje.clickedButton() == continuar
                self._reversion_context["decision_event"].set()
            elif tipo == "ejecucion_preparada":
                cuenta_eliminar = dato.get("cuenta_eliminar", 0)
                aceptada = True
                if cuenta_eliminar:
                    mensaje = QMessageBox(self)
                    mensaje.setIcon(QMessageBox.Warning)
                    mensaje.setWindowTitle("Confirmar eliminación de duplicados")
                    mensaje.setText(
                        f"Esta operación eliminará {cuenta_eliminar} archivos del origen."
                    )
                    mensaje.setInformativeText("Esta acción no se puede deshacer.")
                    mensaje.addButton("Cancelar", QMessageBox.RejectRole)
                    btn_delete = mensaje.addButton(
                        f"Eliminar {cuenta_eliminar} archivos", QMessageBox.AcceptRole
                    )
                    mensaje.exec()
                    aceptada = mensaje.clickedButton() == btn_delete
                if not aceptada:
                    self._registrar_log(
                        "Operación cancelada por el usuario (confirmación de eliminación)."
                    )
                self._confirmacion_ejecucion_aceptada = aceptada
                if self._confirmacion_ejecucion_event is not None:
                    self._confirmacion_ejecucion_event.set()
            elif tipo == "reversion_terminado":
                revertidas = {
                    item.get("operation_id") for item in dato.get("revertidas", [])
                }
                self._history_operations = []
                for resultado in self._reversion_context.get("resultados", []):
                    registro_operacion = dict(resultado)
                    if registro_operacion.get("operation_id") in revertidas:
                        registro_operacion["status"] = "reverted"
                    self._history_operations.append(registro_operacion)
                self._history_current.append(
                    f"Reversión completada: {len(revertidas)} archivos revertidos."
                )
                self._guardar_historial_proceso({
                    "tipo": "reversion",
                    "reversion_of": dato.get("reversion_of"),
                })
                self._procesando = False
                self.boton_cancelar.setEnabled(False)
                self.boton_iniciar.setEnabled(bool(self.reglas))
                self._reversion_context = None
                self._actualizar_historial_ui()
            elif tipo in ("total", "total_archivos"):
                self.var_total_archivos.setText(f"Operaciones preparadas: {dato.get('valor', 0)}")
            elif tipo == "error":
                mensaje = dato.get("mensaje", "Error desconocido.")
                self.var_estado.setText(f"Error: {mensaje}")
                self._registrar_log(f"ERROR: {mensaje}")
                QMessageBox.critical(self, "Error", mensaje)
            elif tipo == "terminado":
                cancelado = dato.get("cancelado", False)
                error = dato.get("error")
                self._procesando = False
                self.boton_iniciar.setEnabled(bool(self.reglas))
                self.boton_cancelar.setEnabled(False)
                self._guardar_historial_proceso(dato)
                self._history_operations = []
                if error is not None:
                    self.var_estado.setText(f"Error: {error}")
                elif cancelado:
                    self.var_estado.setText("Proceso cancelado por el usuario.")
                else:
                    self.var_estado.setText("Proceso finalizado correctamente.")
                    self.barra_actual.setValue(100)
                    self.barra_analisis.setValue(100)
                    self.var_texto_actual.setText("100%")
                    self.var_texto_analisis.setText("100% procesado")
                self.cancel_event = None
                self.barra_analisis.setRange(0, 100)
                self._confirmacion_ejecucion_event = None
                self._reversion_context = None
                self._reversion_decision = None
                self._actualizar_historial_ui()
                origenes = tuple(sorted({
                    normalizar_ruta_regla(regla.get("origen", ""))
                    for regla in self.reglas
                    if normalizar_ruta_regla(regla.get("origen", ""))
                }))
                self._metricas_versiones[origenes] = (
                    self._metricas_versiones.get(origenes, 0) + 1
                )
                self._metricas_en_curso.pop(origenes, None)
                self._metricas_archivos_cache.pop(origenes, None)
                self._actualizar_resumen_inicio()

    def _cancelar_proceso(self):
        if not self._procesando:
            return
        evento = self.cancel_event
        if evento is not None:
            evento.set()
        self._confirmacion_ejecucion_aceptada = False
        if self._confirmacion_ejecucion_event is not None:
            self._confirmacion_ejecucion_event.set()
        if self._reversion_context is not None:
            self._reversion_decision = False
            self._reversion_context["decision_event"].set()
        self.var_estado.setText("Cancelando proceso...")
        self.boton_cancelar.setEnabled(False)

    def _iniciar_proceso(self):
        if self._procesando:
            return
        if not self.reglas:
            QMessageBox.information(self, "FileFlow", "Debes crear al menos una regla de clasificación.")
            self._mostrar_pagina("Reglas")
            return

        reglas_para_proceso = [normalizar_regla(regla) for regla in self.reglas]
        reglas_para_proceso = [
            regla for regla in reglas_para_proceso
            if regla["origen"] and regla["destino"] and regla_tiene_criterio(regla)
        ]
        if not reglas_para_proceso:
            QMessageBox.warning(self, "FileFlow", "No hay reglas válidas para ejecutar.")
            return

        operaciones_previas = None
        if self._seleccion_preview_vigente is not None:
            operaciones_previas = [op.copy() for op in self._seleccion_preview_vigente if bool(op.get("seleccionado", False))]
            if not operaciones_previas:
                self._seleccion_preview_vigente = None

        self._history_current = []
        self._history_operations = []
        self.log_text.clear()
        self.var_estado.setText("Iniciando proceso...")
        self.barra_actual.setValue(0)
        self.barra_analisis.setRange(0, 100)
        self.barra_analisis.setValue(0)
        self.var_texto_actual.setText("0%")
        self.var_texto_analisis.setText("0% analizado")
        self.var_total_archivos.setText("Preparando operaciones...")
        self._cola = queue.Queue(maxsize=2000)
        self._procesando = True
        self.cancel_event = threading.Event()
        self._confirmacion_ejecucion_event = threading.Event()
        self._confirmacion_ejecucion_aceptada = False
        self.boton_iniciar.setEnabled(False)
        self.boton_cancelar.setEnabled(True)

        if operaciones_previas is not None:
            self._registrar_log("Inicio del proceso desde la selección de Organizar.")
            self._registrar_log(f"Operaciones seleccionadas en Organizar: {len(operaciones_previas)}")

        self._hilo_proceso = threading.Thread(
            target=self._ejecutar_proceso_worker,
            args=(
                reglas_para_proceso,
                operaciones_previas,
                dict(self.biblioteca_completa),
                self.cancel_event,
                self._confirmacion_ejecucion_event,
            ),
            daemon=True,
            name="HiloProcesamiento"
        )
        self._hilo_proceso.start()

    def _ejecutar_proceso_worker(
        self, reglas, operaciones_previas, biblioteca, cancel_event, confirmacion_event
    ):
        error = None
        cancelado = False
        try:
            if operaciones_previas is None:
                self._ui_callback({"tipo": "estado", "estado": "Analizando reglas y archivos..."})
                self._ui_callback({"tipo": "log", "mensaje": f"Reglas activas: {len(reglas)}"})
                for indice, regla in enumerate(reglas, start=1):
                    self._ui_callback({
                        "tipo": "log",
                        "mensaje": f"{indice}. {', '.join(regla['palabras'])} -> {regla['origen']} -> {regla['destino']}",
                    })
                operaciones = generar_vista_previa(
                    reglas,
                    ui_callback=self._ui_callback,
                    cancel_event=cancel_event,
                    biblioteca=biblioteca,
                )
            else:
                operaciones = operaciones_previas

            if cancel_event.is_set():
                raise RuntimeError("Proceso cancelado por el usuario.")
            total = len(operaciones)
            self._ui_callback({"tipo": "total", "valor": total})
            if total == 0:
                self._ui_callback({"tipo": "estado", "estado": "Sin coincidencias por procesar."})
                self._ui_callback({
                    "tipo": "log",
                    "mensaje": "No se encontraron coincidencias con ninguna regla activa.",
                })
                return

            cuenta_eliminar = sum(
                1 for op in operaciones
                if op.get("duplicado") and op.get("eliminar_duplicados", False)
            )
            self._ui_callback({
                "tipo": "ejecucion_preparada",
                "cuenta_eliminar": cuenta_eliminar,
            })
            confirmacion_event.wait()
            if not self._confirmacion_ejecucion_aceptada or cancel_event.is_set():
                cancelado = True
                return

            if operaciones_previas is None:
                self._ui_callback({"tipo": "log", "mensaje": f"Operaciones preparadas: {total}"})
            ejecutar_operaciones(
                operaciones,
                ui_callback=self._ui_callback,
                cancel_event=cancel_event,
            )
            cancelado = cancel_event.is_set()
        except Exception as exc:
            if cancel_event.is_set():
                cancelado = True
                self._ui_callback({"tipo": "log", "mensaje": "Proceso cancelado por el usuario."})
            else:
                error = str(exc)
                self._ui_callback({"tipo": "error", "mensaje": error})
        finally:
            self._seleccion_preview_vigente = None
            self._ui_callback({"tipo": "terminado", "cancelado": cancelado, "error": error})

    # ------------------------------------------------------------------
    # utilidades
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._procesando:
            respuesta = QMessageBox.question(
                self,
                "Proceso en ejecución",
                "Hay un proceso en ejecución. ¿Quieres cancelarlo y cerrar FileFlow?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if respuesta != QMessageBox.Yes:
                event.ignore()
                return
            self._cancelar_proceso()
        if hasattr(self, "_preview_cancel_event"):
            self._preview_cancel_event.set()
        event.accept()


def main():
    app = QApplication([])
    app.setApplicationName("FileFlow")
    app.setStyle("Fusion")
    ventana = Aplicacion()
    ventana.show()
    app.exec()


if __name__ == "__main__":
    main()