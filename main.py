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

def last_n_days_range(days: int = 7,tz_name: str = "Europe/Madrid") -> tuple[str, str]:
    """Devuelve FROM-TO en formato YYYY-MM-DD para los últimos N días INCLUYENDO hoy, en la zona horaria indicada.
    Para 7 días, hoy y los 6 anteriores."""
    today = datetime.datetime.now(tz=ZoneInfo(tz_name)).date()
    from_date = today - datetime.timedelta(days=days-1)
    return from_date.isoformat(), today.isoformat()

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
        start_iso = datetime.datetime.fromtimestamp(slp.get("st", 0)).isoformat()
        stop_iso  = datetime.datetime.fromtimestamp(slp.get("ed", 0)).isoformat()

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

def analyze_with_openai_from_rows(rows: list[dict], window_label: str, model: str = "gpt-4o-mini") -> str:
    """
    Envía la lista de 'rows' (tal cual la devuelve get_band_data) a OpenAI
    y devuelve un análisis conciso en español.
    Requiere la variable de entorno OPENAI_API_KEY con tu clave.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[openai] Falta OPENAI_API_KEY en el entorno. Salto análisis.")
        return ""

    # Instrucciones al modelo: qué columnas hay y qué debe producir
    system_prompt = (
        "Eres un coach de sueño. Analiza una lista de diccionarios con las claves: "
        "date, deepSleepTime, shallowSleepTime, wakeTime, start, stop, REMTime, naps. "
        "Devuelve un informe semanal breve en español con: "
        "1) resumen de métricas clave (medias y rangos), "
        "2) consistencia de acostarse/levantarse (menciona hora media y variabilidad), "
        "3) 3–5 recomendaciones accionables. Sé preciso y usa cifras."
    )

    # Metemos los datos tal cual
    user_payload = {
        "ventana": window_label,
        "rows": rows
    }

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ],
        "temperature": 0.2
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.HTTPError as e:
        print(f"[openai] HTTP {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:
        print(f"[openai] Error: {e}")
    return ""


def main():
    # Rango de ejemplo: ajusta a lo que necesites
    FROM, TO = last_n_days_range(days=7, tz_name="Europe/Madrid") # últimos 7 días incluyendo hoy
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


if __name__ == "__main__":
    main()
