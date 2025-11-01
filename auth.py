"""Authentication functions for Mi Fit/Zepp API."""

import requests
import urllib.parse
from utils import fail


def mifit_auth_email(email: str, password: str) -> dict:
    """
    Initial login with email/password to obtain 'access' and 'country_code'
    from Location header (without following redirect).
    """
    print(f"[login] Logging in with email {email}")

    auth_url = f"https://api-user.huami.com/registrations/{urllib.parse.quote(email)}/tokens"

    data = {
        "state": "REDIRECTION",
        "client_id": "HuaMi",
        "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
        "token": "access",
        "password": password,
    }

    headers = {
        'User-Agent': 'Mi Fit/4.0.9 (iPhone; iOS 14.0; Scale/2.0)',
        'Accept': 'application/json',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
    }
    
    r = requests.post(auth_url, data=data, headers=headers, allow_redirects=False)
    
    # Handle rate limits
    if r.status_code == 429:
        retry_after = r.headers.get('Retry-After', 'desconocido')
        print(f"❌ Rate limit alcanzado (429). Retry-After: {retry_after}")
        print("💡 Sugerencia: La API de Huami puede tener límites diarios/semanales.")
        print("   Intenta de nuevo en unas horas o mañana.")
        raise SystemExit("Script detenido por rate limit")
    
    r.raise_for_status()

    loc = urllib.parse.urlparse(r.headers.get("location", ""))
    q = urllib.parse.parse_qs(loc.query)

    if "access" not in q:
        fail("No access token in response")
    if "country_code" not in q:
        fail("No country_code in response")

    print("[login] Obtained access token; exchanging for app token...")

    return mifit_login_with_token({
        "grant_type": "access_token",
        "country_code": q["country_code"],
        "code": q["access"],
    })


def mifit_login_with_token(login_data: dict) -> dict:
    """
    Exchange 'access' token for full credentials at:
    https://account.huami.com/v2/client/login
    """
    login_url = "https://account.huami.com/v2/client/login"

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

    if "token_info" not in result or "app_token" not in result["token_info"]:
        fail("Login did not return token_info/app_token")

    print("[login] App token and user id obtained.")
    return result

