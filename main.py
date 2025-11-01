#!/usr/bin/env python3

"""
Sleep data exporter for Mi Fit/Zepp devices using unofficial API.

Exports sleep data (deep sleep, light sleep, REM, wake time) to CSV,
analyzes it with OpenAI, and sends automated email reports.

See README.md for detailed API flow and technical implementation details.
"""

import os
from ai_analysis import analyze_with_openai_from_rows
from auth import mifit_auth_email
from config import get_credentials, get_openai_api_key
from data_fetch import get_band_data
from email_service import send_email
from utils import last_complete_week_range, last_n_days_range


def main():
    FROM, TO = last_complete_week_range("Europe/Madrid")
    # FROM, TO = last_n_days_range(7, "Europe/Madrid")
    print(f"[range] Using last week -> FROM={FROM}, TO={TO} (Madrid timezone)")

    email, password = get_credentials()
    auth = mifit_auth_email(email, password)
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
