"""
Teste local de SMTP — credenciais apenas via variáveis de ambiente ou .env.
Uso: python smtp_test.py
"""
import os
import smtplib

from dotenv import load_dotenv

load_dotenv()

host = (os.getenv("SMTP_HOST") or "").strip()
port = int(os.getenv("SMTP_PORT") or "587")
user = (os.getenv("SMTP_USER") or "").strip()
password = (os.getenv("SMTP_PASS") or "").strip()
use_tls = (os.getenv("SMTP_TLS", "true") or "").strip().lower() in ("1", "true", "yes", "on")
use_ssl_raw = (os.getenv("SMTP_USE_SSL") or "").strip().lower()
use_ssl = use_ssl_raw in ("1", "true", "yes", "on") or (not use_ssl_raw and port == 465)

if not host or not user or not password:
    raise SystemExit(
        "Defina SMTP_HOST, SMTP_USER e SMTP_PASS no ambiente ou no .env (não use credenciais no código)."
    )

if use_ssl:
    with smtplib.SMTP_SSL(host, port, timeout=20) as s:
        s.login(user, password)
else:
    with smtplib.SMTP(host, port, timeout=20) as s:
        if use_tls:
            s.starttls()
        s.login(user, password)

print("SMTP login OK")
