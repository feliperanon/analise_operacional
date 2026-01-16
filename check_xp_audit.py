from database import get_session
from models import GameXPTransaction, Employee
from sqlmodel import select, desc

def check_audit():
    session = next(get_session())
    print("🔍 Diagnosticando últimas 20 transações de XP...")
    
    txs = session.exec(select(GameXPTransaction).order_by(desc(GameXPTransaction.created_at)).limit(20)).all()
    
    if not txs:
        print("❌ Nenhuma transação encontrada.")
        return

    print("\n🔍 Buscando transação com '2068kg'...")
    txs = session.exec(select(GameXPTransaction).where(GameXPTransaction.reason.contains("2068kg"))).all()
    
    if not txs:
        print("❌ Nenhuma transação com '2068kg' encontrada.")
        # Let's list ALL transactions for that day just in case
        print("   Listando TUDO de 2026-01-12:")
        all_day = session.exec(select(GameXPTransaction).where(GameXPTransaction.reason.contains("2026-01-12"))).all()
        for t in all_day:
             print(f"   - ID={t.id} | {t.reason[:30]}... | {t.amount}")
    else:
        for tx in txs:
            emp = session.get(Employee, tx.employee_id)
            if emp:
                print(f"✅ ENCONTRADA: ID={tx.id} | Status={tx.status} | EmpID={tx.employee_id} ({emp.name}) | Reason={tx.reason}")
            else:
                print(f"❌ ORFÃ: ID={tx.id} | Status={tx.status} | EmpID={tx.employee_id} (Employee Missing)")

if __name__ == "__main__":
    check_audit()
