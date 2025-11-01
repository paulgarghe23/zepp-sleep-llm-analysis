"""Functions for AI-powered sleep analysis using OpenAI."""

import json
import os
import requests


def analyze_with_openai_from_rows(
    rows: list[dict],
    window_label: str,
    model: str = "gpt-4o-mini",
) -> str:
    """
    Take exported rows and request a weekly sleep report from OpenAI.
    Returns the report string or "" if no API key/errors.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[openai] Falta OPENAI_API_KEY en el entorno. Salto análisis.")
        return ""

    debug = str(os.getenv("OPENAI_DEBUG", "0")).lower() in ("1", "true", "yes")

    system_prompt = (
        "Eres un experto en sueño analítico. Analiza el sueño semanal en la lista de diccionarios con las claves: "
        "date, deepSleepTime, shallowSleepTime, wakeTime (tiempo despierto durante la noche), start (comienzo del sueño), stop (final del sueño), REMTime, naps(siestas). "
        "Devuelve un informe semanal breve en español con: "
        "1) métricas clave y lo que significan: lo bueno y a mejorar, "
        "2) 2 puntos fuertes y 2 a mejorar. Sé preciso, accionable, específico, usa cifras. "
        "Da recomendaciones específicas para este usuario, no genéricas: qué días lo hizo mejor y por qué, y qué días mejorar y cómo. Menciona el día de la semana (lunes, martes, etc.)"
    )

    user_payload = {
        "ventana": window_label,
        "rows": rows,
    }

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ],
        "temperature": 0.2,
    }

    if debug:
        try:
            with open("openai_request.json", "w", encoding="utf-8") as f:
                json.dump({"url": url, "headers": {"Content-Type": "application/json", "Authorization": "Bearer ***redacted***"},
                           "body": body}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        request_id = resp.headers.get("x-request-id")
        resp.raise_for_status()

        data = resp.json()

        if debug:
            try:
                with open("openai_response.json", "w", encoding="utf-8") as f:
                    json.dump({"request_id": request_id, "response": data}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        content = (
            data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
        )

        return (content or "").strip()

    except requests.HTTPError as e:
        snippet = ""
        try:
            snippet = resp.text[:400]
        except Exception:
            pass
        print(f"[openai] HTTP {getattr(e.response,'status_code', '???')}: {snippet}")
    except Exception as e:
        print(f"[openai] Error: {e}")

    return ""

