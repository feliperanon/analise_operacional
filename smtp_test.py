import smtplib

USER = "feliperanon@feliperanon.com.br"
PASS = "gekpzrakugipqrrx"

with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
    s.starttls()
    s.login(USER, PASS)
    print("SMTP login OK")
