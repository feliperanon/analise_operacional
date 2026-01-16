from database import get_session
from models import GameXPTransaction, Employee, Route
from sqlmodel import select, desc, col

def diagnose():
    session = next(get_session())
    print("🔍 Diagnosticando WELBERT (13, 14, 15 Jan)...")
    
    # 1. Find Welbert
    welbert = session.exec(select(Employee).where(col(Employee.name).contains("WELBERT"))).first()
    if not welbert:
        print("❌ Funcionario WELBERT nâo encontrado!")
        return
    
    print(f"👤 Encontrado: {welbert.name} (ID: {welbert.id})")
    
    dates = ["2026-01-13", "2026-01-14", "2026-01-15"]
    
    for d in dates:
        print(f"\n📅 Analisando DATA: {d}")
        
        # Check Routes
        routes = session.exec(select(Route).where(
            Route.employee_id == welbert.id,
            Route.date == d
        )).all()
        
        if not routes:
            print(f"   ⚠️ Nenhuma rota encontrada para esta data.")
        else:
            for r in routes:
                print(f"   🚛 Rota ID={r.id} | Status={r.status} | Ton={r.tonnage}kg | Start={r.start_time} | End={r.end_time}")
                
        # Check XP Transactions
        txs = session.exec(select(GameXPTransaction).where(
            GameXPTransaction.employee_id == welbert.id,
            GameXPTransaction.reason.contains(d)
        )).all()
        
        if not txs:
            print(f"   ❌ Nenhuma transação de XP encontrada com ref '{d}'.")
        else:
            for tx in txs:
                print(f"   💰 XP ID={tx.id} | Status={tx.status} | Amount={tx.amount} | Reason={tx.reason[:50]}...")

if __name__ == "__main__":
    diagnose()
