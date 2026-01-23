import argparse
import base64
import hashlib
import hmac
import secrets
from datetime import datetime

from sqlmodel import Session, select

import models
from database import engine, create_db_and_tables

PASSWORD_ITERATIONS = 120_000

def normalize_email(value: str) -> str:
    return (value or "").strip().lower()

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii")
    )

def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    try:
        algo, iterations_str, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False

def cmd_list():
    with Session(engine) as session:
        users = session.exec(select(models.User).order_by(models.User.id)).all()
        if not users:
            print("Nenhum usuário encontrado.")
            return
        for u in users:
            status = "ativo" if u.is_active else "inativo"
            print(f"{u.id}: {u.username} | role={u.role} | {status} | google={'sim' if u.google_sub else 'não'}")

def cmd_create(args):
    email = normalize_email(args.email)
    if not email:
        raise SystemExit("E-mail inválido.")
    if not args.employee_id:
        raise SystemExit("employee_id é obrigatório.")
    with Session(engine) as session:
        exists = session.exec(select(models.User).where(models.User.username == email)).first()
        if exists:
            raise SystemExit("Usuário já existe.")
        employee = session.get(models.Employee, args.employee_id)
        if not employee or employee.status == "fired":
            raise SystemExit("Colaborador inválido.")
        linked = session.exec(select(models.User).where(models.User.employee_id == args.employee_id)).first()
        if linked:
            raise SystemExit("Colaborador já vinculado a outro usuário.")
        user = models.User(
            username=email,
            password_hash=hash_password(args.password),
            role=args.role,
            is_active=True,
            employee_id=args.employee_id,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        session.add(user)
        session.commit()
        print(f"Usuário criado: {email} ({args.role})")

def cmd_set_password(args):
    email = normalize_email(args.email)
    with Session(engine) as session:
        user = session.exec(select(models.User).where(models.User.username == email)).first()
        if not user:
            raise SystemExit("Usuário não encontrado.")
        user.password_hash = hash_password(args.password)
        user.reset_token_hash = None
        user.reset_token_expires_at = None
        user.updated_at = datetime.now()
        session.add(user)
        session.commit()
        print("Senha atualizada.")

def cmd_set_role(args):
    email = normalize_email(args.email)
    with Session(engine) as session:
        user = session.exec(select(models.User).where(models.User.username == email)).first()
        if not user:
            raise SystemExit("Usuário não encontrado.")
        user.role = args.role
        user.updated_at = datetime.now()
        session.add(user)
        session.commit()
        print(f"Role atualizado para {args.role}.")

def cmd_set_status(args, active: bool):
    email = normalize_email(args.email)
    with Session(engine) as session:
        user = session.exec(select(models.User).where(models.User.username == email)).first()
        if not user:
            raise SystemExit("Usuário não encontrado.")
        user.is_active = active
        user.updated_at = datetime.now()
        session.add(user)
        session.commit()
        print("Status atualizado.")

def main():
    parser = argparse.ArgumentParser(description="Gerenciar usuários locais")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Listar usuários")

    create = sub.add_parser("create", help="Criar usuário")
    create.add_argument("--email", required=True)
    create.add_argument("--password", required=True)
    create.add_argument("--role", default="leader")
    create.add_argument("--employee-id", type=int, required=True)

    setpass = sub.add_parser("set-password", help="Atualizar senha")
    setpass.add_argument("--email", required=True)
    setpass.add_argument("--password", required=True)

    setrole = sub.add_parser("set-role", help="Atualizar role")
    setrole.add_argument("--email", required=True)
    setrole.add_argument("--role", required=True)

    deactivate = sub.add_parser("deactivate", help="Desativar usuário")
    deactivate.add_argument("--email", required=True)

    activate = sub.add_parser("activate", help="Ativar usuário")
    activate.add_argument("--email", required=True)

    args = parser.parse_args()
    create_db_and_tables()

    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "create":
        cmd_create(args)
    elif args.cmd == "set-password":
        cmd_set_password(args)
    elif args.cmd == "set-role":
        cmd_set_role(args)
    elif args.cmd == "deactivate":
        cmd_set_status(args, False)
    elif args.cmd == "activate":
        cmd_set_status(args, True)

if __name__ == "__main__":
    main()
