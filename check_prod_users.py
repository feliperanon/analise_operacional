from sqlmodel import create_engine, Session, select
import models
import sys

# Production URL
url = "postgresql://analise_operacional_db_user:kPOjvZIGlvlC1TpAuJmdhkWJ75zWwclB@dpg-d51shhu3jp1c73f3u2kg-a.virginia-postgres.render.com/analise_operacional_db"

try:
    print(f"🔌 Conectando em: {url.split('@')[1]}...")
    engine = create_engine(url)
    
    with Session(engine) as session:
        print("🔍 Buscando colaboradores...")
        employees = session.exec(select(models.Employee).limit(5)).all()
        
        if not employees:
            print("❌ NENHUM Colaborador encontrado no banco de produção!")
        else:
            print(f"✅ Encontrados {len(employees)} colaboradores (amostra):")
            for emp in employees:
                print(f"   - {emp.name} (Matrícula: {emp.registration_id}) Status: {emp.status}")

except Exception as e:
    print(f"❌ Erro de conexão: {e}")
