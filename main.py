#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Exportador de sueño Mi Fit / Zepp (API no oficial)

Resumen del flujo:
1) Login con email/contraseña (flujo clásico “no oficial”):
   - POST a /registrations/{email}/tokens -> leemos la cabecera Location sin seguir redirección
   - En la URL de Location vienen 'access' y 'country_code'
   - Intercambiamos esos valores en /v2/client/login para obtener credenciales completas
   => token_info { app_token, user_id } que usaremos para acceder a los datos

2) Descarga de datos:
   - GET /v1/data/band_data.json con:
     query_type=summary, userid, from_date, to_date, device_type
     y cabecera HTTP 'apptoken' con el app_token del paso anterior.

3) Transformación:
   - 'summary' viene en base64 → lo decodificamos → JSON.
   - En 'slp' (sleep) están los campos abreviados:
       dp = deep sleep (minutos)
       lt = light sleep (minutos)
       wk = tiempo despierto (minutos)
       st = inicio de sueño (epoch segundos)
       ed = fin de sueño (epoch segundos)
       stage[] = lista de tramos (cada tramo tiene 'mode', 'start', 'stop' en minutos relativos al día)
         * mode = 4 → sueño ligero
         * mode = 5 → sueño profundo
         * mode = 7 → posible REM (episodios breves / menos confiables)
         * mode = 8 → posible REM (episodios más largos / más confiables)
     ⚠ No hay documentación oficial: estos significados provienen de ingeniería inversa.
       En la práctica, la fase REM observable en la app ≈ suma de mode 7 + mode 8.
       Por eso aquí exponemos REM7Time, REM8Time y su suma REMTime.

4) Salida:
   - CSV con columnas:
     date, deepSleepTime, shallowSleepTime, wakeTime, start, stop, REM7Time, REM8Time, REMTime, naps
   - Impresión en consola en formato tabla (tabulate).
"""

import requests, urllib.parse, json, base64, datetime, csv
from tabulate import tabulate  # pip install tabulate
from zoneinfo import ZoneInfo  # Python 3.9+
import os
from dotenv import load_dotenv  # pip install python-dotenv
import smtplib                # librería estándar para hablar con servidores SMTP (enviar correos)
import mimetypes              # para adivinar el tipo de archivo de los adjuntos
from email.message import EmailMessage  # clase para construir emails completos (texto + adjuntos)


load_dotenv()  # carga variables de .env si existe



# ========= CREDENCIALES =========
EMAIL = os.getenv("ZEPPEMAIL")
PASSWORD = os.getenv("ZEPP_PASSWORD")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# ===========================================================

if not EMAIL or not PASSWORD:
    raise SystemExit("❌ Faltan ZEPPEMAIL o ZEPP_PASSWORD en el entorno")


def fail(msg: str):
    """Imprime un error y termina el programa."""
    print(f"Error: {msg}")
    raise SystemExit(1)

def to_madrid_iso(ts: int) -> str:
    """Convierte epoch (seg) a ISO en Europe/Madrid, siempre igual en local y en Actions."""
    if not ts:
        return ""
    utc_dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return utc_dt.astimezone(ZoneInfo("Europe/Madrid")).replace(microsecond=0).isoformat()

def last_n_days_range(days: int = 7,tz_name: str = "Europe/Madrid") -> tuple[str, str]:
    """Devuelve FROM-TO en formato YYYY-MM-DD para los últimos N días INCLUYENDO hoy, en la zona horaria indicada.
    Para 7 días, hoy y los 6 anteriores."""
    today = datetime.datetime.now(tz=ZoneInfo(tz_name)).date()
    from_date = today - datetime.timedelta(days=days-1)
    return from_date.isoformat(), today.isoformat()

def last_complete_week_range(tz_name: str = "Europe/Madrid") -> tuple[str, str]:
    """
    Devuelve el lunes-domingo de la SEMANA COMPLETA ANTERIOR (fechas YYYY-MM-DD).
    Ej.: si hoy es miércoles 2025-09-10, devuelve 2025-09-01 a 2025-09-07.
    """
    today = datetime.datetime.now(tz=ZoneInfo(tz_name)).date()
    week_start = today - datetime.timedelta(days=today.weekday() + 7)  # lunes anterior
    week_end = week_start + datetime.timedelta(days=6)                 # domingo de esa semana
    return week_start.isoformat(), week_end.isoformat()

def mifit_auth_email(email: str, password: str) -> dict:
    """
    1) Login inicial con email/contraseña para obtener 'access' y 'country_code'
       desde la cabecera Location (sin seguir la redirección).
    """
    print(f"[login] Logging in with email {email}")

    # Endpoint que emite la redirección con los parámetros en la URL
    auth_url = f"https://api-user.huami.com/registrations/{urllib.parse.quote(email)}/tokens"

    # Payload requerido por el backend de Huami en este flujo
    data = {
        "state": "REDIRECTION",
        "client_id": "HuaMi",
        "redirect_uri": "https://s3-us-west-2.amazonws.com/hm-registration/successsignin.html",
        "token": "access",   # queremos obtener 'access' en la redirección
        "password": password,
    }

    # No seguimos la redirección: necesitamos leer la cabecera 'Location'
    r = requests.post(auth_url, data=data, allow_redirects=False)
    r.raise_for_status()

    # Parseamos la URL de la cabecera Location para extraer la query string
    loc = urllib.parse.urlparse(r.headers.get("location", ""))
    q = urllib.parse.parse_qs(loc.query)

    # Validaciones mínimas
    if "access" not in q:
        fail("No access token in response")
    if "country_code" not in q:
        fail("No country_code in response")

    print("[login] Obtained access token; exchanging for app token...")

    # 2) Intercambiamos por credenciales completas (app_token, user_id, ...)
    return mifit_login_with_token({
        "grant_type": "access_token",
        "country_code": q["country_code"],  # viene como lista; el endpoint lo tolera
        "code": q["access"],                # idem
    })

def mifit_login_with_token(login_data: dict) -> dict:
    """
    2) Intercambio del 'access' por credenciales completas en:
       https://account.huami.com/v2/client/login
    """
    login_url = "https://account.huami.com/v2/client/login"

    # Metadatos “de app” que históricamente espera este endpoint
    data = {
        "app_name": "com.xiaomi.hm.health",
        "dn": "account.huami.com,api-user.huami.com,api-watch.huami.com,api-analytics.huami.com,app-analytics.huami.com,api-mifit.huami.com",
        "device_id": "02:00:00:00:00:00",
        "device_model": "android_phone",
        "app_version": "4.0.9",
        "allow_registration": "false",
        "third_name": "huami",
    }
    data.update(login_data)

    r = requests.post(login_url, data=data, allow_redirects=False)
    result = r.json()

    # Validación rápida
    if "token_info" not in result or "app_token" not in result["token_info"]:
        fail("Login did not return token_info/app_token")

    print("[login] App token and user id obtained.")
    return result

def get_band_data(auth_info: dict, from_date: str, to_date: str, output_file: str = "sleep_export.csv"):
    """
    Descarga el rango [from_date, to_date] y construye las filas para CSV/tabla.

    Importante sobre las unidades:
    - dp/lt/wk ya vienen en minutos.
    - stage[].start / stage[].stop también vienen en minutos (referidos al mismo día),
      por lo que (stop - start) nos da minutos de cada tramo.
    """
    print(f"[fetch] Retrieving mi band data from {from_date} to {to_date}")

    url = "https://api-mifit.huami.com/v1/data/band_data.json"
    headers = {"apptoken": auth_info["token_info"]["app_token"]}
    params = {
        "query_type": "summary",
        "device_type": "android_phone",
        "userid": auth_info["token_info"]["user_id"],
        "from_date": from_date,
        "to_date": to_date,
    }

    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()

    rows = []

    for daydata in resp.json().get("data", []):
        day = daydata["date_time"]

        # 'summary' viene en base64 → decodificar → JSON
        summary_b = base64.b64decode(daydata.get("summary", ""))
        summary = json.loads(summary_b) if summary_b else {}

        # Solo procesamos si hay bloque de sueño
        if "slp" not in summary:
            continue

        slp = summary["slp"]

        # Lectura directa de métricas en minutos
        deep  = slp.get("dp", 0)  # deep sleep
        light = slp.get("lt", 0)  # light sleep
        wake  = slp.get("wk", 0)  # awake minutes

        # Tiempos absolutos de inicio y fin (epoch seg → ISO8601)
        start_iso = to_madrid_iso(slp.get("st", 0))
        stop_iso  = to_madrid_iso(slp.get("ed", 0))


        # --- Cálculo de REM a partir de tramos ---
        # Sumamos por separado los minutos de mode 7 y mode 8 para inspección,
        # y luego exponemos también la suma (REMTime).
        rem7 = 0
        rem8 = 0
        for s in slp.get("stage", []):
            mode = s.get("mode")
            dur = (s.get("stop", 0) - s.get("start", 0))  # minutos de ese tramo
            if mode == 7:
                rem7 += dur
            elif mode == 8:
                rem8 += dur
            # otros modes (4,5, etc.) no se cuentan aquí porque REM = 7 + 8

        rows.append({
            "date": day,
            "deepSleepTime": deep,
            "shallowSleepTime": light,
            "wakeTime": wake,
            "start": start_iso,
            "stop": stop_iso,
            #"REM7Time": rem7,           # posible REM (heurística 1)
            #"REM8Time": rem8,           # posible REM (heurística 2 / más estable)
            "REMTime": rem7 + rem8,     # REM total = suma explícita de mode 7 + mode 8
            "naps": slp.get("nap", 0),  # si existe, minutos de siestas
        })

    # ====== Guardar CSV ======
    fields = [
        "date","deepSleepTime","shallowSleepTime","wakeTime","start","stop","REMTime","naps"
    ]
    with open(output_file, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # ====== Salida por consola ======
    print(f"\n[done] Exported {len(rows)} rows to {output_file}\n")
    print(tabulate(rows, headers="keys", tablefmt="github"))

    return rows

def analyze_with_openai_from_rows(
    rows: list[dict],
    window_label: str,
    model: str = "gpt-4o-mini",
) -> str:
    """
    OBJETIVO:
      - Tomar las filas exportadas (rows) y pedir a OpenAI un informe semanal en texto.
      - DEVUELVE un string (el informe) o "" si no hay clave/errores.

    CÓMO LO HACE (resumen):
      1) Lee tu clave de OpenAI desde la variable de entorno OPENAI_API_KEY (no se hardcodea).
      2) Define un "system prompt": es el rol/instrucciones fijas para el modelo (qué debe hacer y cómo).
      3) Empaqueta TUS DATOS (rows + etiqueta de ventana) como contenido del "user".
      4) Llama al endpoint REST /v1/chat/completions con requests.
      5) Extrae el texto de la respuesta y lo devuelve.

    NOTAS:
      - Para "ver qué hemos enviado", OpenAI NO muestra el payload en el dashboard.
        *Puedes verlo tú guardando una copia local del request/response (ver DEBUG más abajo).*
      - En el panel de OpenAI sí podrás ver USAGE (tokens por día/modelo).
    """
    import os, json
    import requests

    # === 1) Seguridad: leer la API key del entorno ===
    #   - Nunca imprimas la clave. Si no está, seguimos el script sin análisis.
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[openai] Falta OPENAI_API_KEY en el entorno. Salto análisis.")
        return ""

    # === (Opcional) DEBUG: si pones OPENAI_DEBUG=1 en tu .env, guardamos request/response en disco ===
    debug = str(os.getenv("OPENAI_DEBUG", "0")).lower() in ("1", "true", "yes")

    # === 2) System prompt: le dice al modelo "quién es" y QUÉ debe producir ===
    #   - Aquí fijas el comportamiento (coach de sueño) y el formato que quieres en la salida.
    system_prompt = (
        "Eres un coach de sueño que quiere lo mejor para esta persona. Analiza una lista de diccionarios con las claves: "
        "date, deepSleepTime, shallowSleepTime, wakeTime, start, stop, REMTime, naps. "
        "Devuelve un informe semanal breve en español con: "
        "1) métricas clave y lo que significan: lo bueno y a mejorar, "
        "2) incluye consistencia de acostarse/levantarse (menciona hora media y variabilidad), y lo que significa "
        "3) 2 puntos fuertes y 2 a mejorar. Sé preciso, accionable, específico y usa cifras. "
        "Da recomendaciones específicas para este usuario, no genéricas: qué días lo hizo mejor y por qué, y qué días mejorar y cómo."
    )

    # === 3) Payload de USUARIO: tus datos reales que el modelo debe analizar ===
    #   - Enviamos la 'ventana' (texto tipo "Semana 2025-08-18 a 2025-08-24") y las filas.
    #   - json.dumps con ensure_ascii=False mantiene tildes/ñ correctamente.
    user_payload = {
        "ventana": window_label,
        "rows": rows,  # lista de dicts: [{"date": "...", "deepSleepTime": ..., ...}, ...]
    }

    # === 4) Construcción de la llamada HTTP ===
    url = "https://api.openai.com/v1/chat/completions"  # endpoint Chat Completions
    headers = {
        "Authorization": f"Bearer {api_key}",  # pasa tu clave en el header
        "Content-Type": "application/json",
    }
    body = {
        "model": model,      # modelo a usar (puedes cambiarlo desde el argumento de la función)
        "messages": [
            {"role": "system", "content": system_prompt},                           # instrucciones
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}  # tus datos
        ],
        "temperature": 0.2,  # baja = más determinista; sube si quieres más creatividad
        # "top_p": 1.0,      # (opcional) muestreo por núcleo; normalmente no hace falta tocarlo
    }

    # Guarda el request si está activado el modo DEBUG (para poder "ver" lo enviado)
    if debug:
        try:
            with open("openai_request.json", "w", encoding="utf-8") as f:
                json.dump({"url": url, "headers": {"Content-Type": "application/json", "Authorization": "Bearer ***redacted***"},
                           "body": body}, f, ensure_ascii=False, indent=2)
        except Exception as _:
            pass

    # === 5) Hacer la petición y manejar errores de red/HTTP ===
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        request_id = resp.headers.get("x-request-id")  # útil para soporte/diagnóstico
        resp.raise_for_status()  # lanza error si HTTP != 2xx

        data = resp.json()

        # Guarda la respuesta cruda si DEBUG
        if debug:
            try:
                with open("openai_response.json", "w", encoding="utf-8") as f:
                    json.dump({"request_id": request_id, "response": data}, f, ensure_ascii=False, indent=2)
            except Exception as _:
                pass

        # === 6) Extraer el texto del mensaje del asistente ===
        # Estructura típica: {"choices":[{"message":{"content": "..."}}, ...]}
        content = (
            data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
        )

        # Limpieza final
        return (content or "").strip()

    except requests.HTTPError as e:
        # Muestra código HTTP y un trozo del cuerpo para diagnosticar, sin claves
        snippet = ""
        try:
            snippet = resp.text[:400]
        except Exception:
            pass
        print(f"[openai] HTTP {getattr(e.response,'status_code', '???')}: {snippet}")
    except Exception as e:
        print(f"[openai] Error: {e}")

    # Si algo falla, devolvemos string vacío (el resto del script sigue)
    return ""


def send_email(subject: str, body: str, to_addrs, attachments: list[str] | None = None) -> bool:
    """
    Envía un email con asunto, cuerpo de texto y opcionalmente adjuntos.
    Usa las variables de entorno SMTP_* y MAIL_* para configuración.

    subject:    Asunto del email
    body:       Texto del mensaje (se envía como plain text)
    to_addrs:   Destinatario(s). Puede ser un string ("a@x.com") o lista.
    attachments: Lista de rutas de archivos a adjuntar (CSV, MD, etc.)
    Devuelve True si se envió con éxito, False si hubo error.
    """

    # --- 1. Leer credenciales y configuración desde variables de entorno ---
    host = os.getenv("SMTP_HOST")       # Servidor SMTP (ej: smtp.gmail.com)
    port = int(os.getenv("SMTP_PORT", "465"))  # Puerto (465=SSL, 587=STARTTLS)
    user = os.getenv("SMTP_USER")       # Usuario (normalmente tu email)
    password = os.getenv("SMTP_PASS")   # Contraseña de aplicación (16 chars de Google)
    from_addr = os.getenv("MAIL_FROM", user)  # Dirección remitente (lo que verá el receptor)

    # --- 2. Normalizar destinatarios (acepta string o lista) ---
    if isinstance(to_addrs, str):
        to_addrs_list = [a.strip() for a in to_addrs.split(",") if a.strip()]
    else:
        to_addrs_list = to_addrs or []

    # --- 3. Validar que no falta nada crítico ---
    if not all([host, port, user, password, from_addr]) or not to_addrs_list:
        print("❌ Faltan SMTP_HOST/PORT/USER/PASS/MAIL_FROM o MAIL_TO en .env")
        return False

    # --- 4. Construir el mensaje ---
    msg = EmailMessage()
    msg["From"] = from_addr                # Quién lo envía
    msg["To"] = ", ".join(to_addrs_list)   # A quién va
    msg["Subject"] = subject               # Asunto
    msg.set_content(body)                   # Texto plano del mensaje

    # --- 5. Adjuntar archivos (si los hay) ---
    for path in (attachments or []):
        try:
            # Detectar tipo de archivo (text/csv, text/markdown, etc.)
            ctype, _ = mimetypes.guess_type(path)
            if not ctype:
                ctype = "application/octet-stream"  # si no lo detecta, genérico binario
            maintype, subtype = ctype.split("/", 1)

            # Abrir archivo y añadir como adjunto
            with open(path, "rb") as f:
                msg.add_attachment(
                    f.read(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=os.path.basename(path)
                )
        except Exception as e:
            print(f"⚠️ No pude adjuntar {path}: {e}")

    # --- 6. Conectarse al servidor y enviar ---
    try:
        if port == 465:
            # Caso típico Gmail → conexión SSL directa
            with smtplib.SMTP_SSL(host, port, timeout=60) as s:
                s.login(user, password)     # autenticación con usuario y app password
                s.send_message(msg)         # envío del email completo
        else:
            # Caso STARTTLS (puerto 587)
            with smtplib.SMTP(host, port, timeout=60) as s:
                s.starttls()                # eleva a conexión segura
                s.login(user, password)
                s.send_message(msg)

        print("✉️  Email enviado correctamente.")
        return True

    except Exception as e:
        print(f"❌ Error enviando email: {e}")
        return False


def main():
    # Rango de ejemplo: ajusta a lo que necesites
    FROM, TO = last_complete_week_range("Europe/Madrid") # semana completa anterior
    #FROM, TO = last_n_days_range(7, "Europe/Madrid") # últimos 7 días incluyendo hoy
    print(f"[range] Using last week -> FROM={FROM}, TO={TO} (Madrid timezone)")

    # Login + fetch
    auth = mifit_auth_email(EMAIL, PASSWORD)
    rows = get_band_data(auth, from_date=FROM, to_date=TO, output_file="sleep_export.csv")

    window_label = f"Semana {FROM} a {TO}"
    analysis = analyze_with_openai_from_rows(rows, window_label)

    if analysis:
        with open("sleep_report_ai.md", "w", encoding="utf-8") as f:
            f.write(f"# Informe de sueño Mi Fit / Zepp ({window_label})\n\n")
            f.write(analysis + "\n")
        print("\n[AI] Análisis semanal (OpenAI):\n")
        print(analysis)
        print("\n[AI] Informe guardado en sleep_report_ai.md")


    subject = f"Informe de sueño Zepp — {window_label}"
    body = (analysis or f"(Sin análisis de IA)\nSe exportaron {len(rows)} filas del {FROM} al {TO}.")
    attachments = ["sleep_export.csv"]
    if os.path.exists("sleep_report_ai.md"):
        attachments.append("sleep_report_ai.md")

    send_email(subject, body, os.getenv("MAIL_TO", ""), attachments=attachments)



if __name__ == "__main__":
    main()
