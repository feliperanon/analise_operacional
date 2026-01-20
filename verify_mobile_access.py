import asyncio
import os
import sys

# Ensure we can import from current directory
sys.path.append(os.getcwd())

# 0. FORCE LOCAL TEST DATABASE
os.environ["DATABASE_URL"] = "sqlite:///test_access.db"
if os.path.exists("test_access.db"):
    os.remove("test_access.db")

from sqlmodel import Session, select, SQLModel
# database must be imported AFTER setting env var
from database import engine, create_db_and_tables 
import models
import main
from fastapi import Request
from starlette.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

# Setup Tables
models.SQLModel.metadata.create_all(engine)

# Mock Request
class MockRequest:
    def __init__(self, session_data=None, query_params=None):
        self.session = session_data if session_data is not None else {}
        self.query_params = query_params if query_params is not None else {}
        self.headers = {}

async def run_verification():
    print("🚀 Iniciando Verificação de Agente Mobile (Access Control) - LOCAL DB")
    
    # 1. Setup Test User
    with Session(engine) as session:
        # Create user with NO ACCESS
        employee = models.Employee(
            registration_id="TEST_999",
            name="Test User Mobile",
            role="Tester",
            mobile_access=False, # BLOCKED
            status="active"
        )
        session.add(employee)
        session.commit()
        session.refresh(employee)
        emp_id = employee.id
        print(f"✅ Usuário de teste criado (ID: {emp_id}) com mobile_access=False")

    try:
        # 2. Test Login Block (POST /mobile/auth)
        print("\n🧪 Teste 1: Tentativa de Login SEM PERMISSÃO")
        req = MockRequest()
        
        # Need a fresh session for the function call
        with Session(engine) as session:
            response = await main.mobile_auth(req, registration_id="TEST_999", session=session)
            
            # Expect TemplateResponse (returning to login page with error)
            if hasattr(response, "template") and response.template.name == "mobile/login.html":
                ctx = response.context
                err = ctx.get("error")
                if "não possui permissão" in str(err):
                    print("✅ SUCESSO: Login bloqueado corretamente com mensagem apropriada.")
                else:
                    print(f"❌ FALHA: Mensagem de erro inesperada: {err}")
            else:
                print(f"❌ FALHA: Resposta inesperada: {type(response)}")

        # 3. Test Login Success (POST /mobile/auth) after granting access
        print("\n🧪 Teste 2: Login COM PERMISSÃO")
        with Session(engine) as session:
            # Grant access
            emp = session.get(models.Employee, emp_id)
            emp.mobile_access = True
            session.add(emp)
            session.commit()
            print("   -> Permissão concedida via DB.")
            
            req = MockRequest()
            response = await main.mobile_auth(req, registration_id="TEST_999", session=session)
            
            # Expect RedirectResponse to /mobile/dashboard
            if isinstance(response, RedirectResponse) and response.headers["location"] == "/mobile/dashboard":
                print("✅ SUCESSO: Redirecionamento para Dashboard ocorreu.")
                # Capture session state
                user_session = req.session
                print(f"   -> Sessão criada: {user_session}")
            else:
                print(f"❌ FALHA: Não redirecionou. Resp: {response}")

        # 4. Test Access Revocation (GET /mobile/dashboard)
        print("\n🧪 Teste 3: Revogação de Acesso (Sessão Ativa mas mobile_access=False)")
        with Session(engine) as session:
            # Revoke access
            emp = session.get(models.Employee, emp_id)
            emp.mobile_access = False
            session.add(emp)
            session.commit()
            print("   -> Permissão revogada via DB.")
            
            # Use session from previous step
            req = MockRequest(session_data={'user_id': emp_id, 'user_role': 'employee'})
            
            # Mock current_user dependency result for dashboard
            current_user = {'type': 'employee', 'id': emp_id}
            
            # We mock session.exec().all() for the history part or ensure empty DB doesn't crash
            # main.py does some queries on routes. Need to ensure they don't crash.
            # But since test db is empty (except test user), queries should return empty lists.
            
            response = await main.mobile_dashboard(req, current_user=current_user, session=session)
            
            # Expect RedirectResponse to login with error
            if isinstance(response, RedirectResponse):
                loc = response.headers["location"]
                if "mobile/login" in loc and "access_revoked" in loc:
                    print(f"✅ SUCESSO: Redirecionado para login com erro de revogação. ({loc})")
                else:
                    print(f"❌ FALHA: Redirecionamento incorreto: {loc}")
            else:
                print(f"❌ FALHA: Dashboard permitiu acesso ou retornou 200 OK inesperado.")

    finally:
        # Cleanup
        if os.path.exists("test_access.db"):
            try:
                os.remove("test_access.db")
            except: pass
        print("\n🧹 Limpeza realizada.")

if __name__ == "__main__":
    asyncio.run(run_verification())
