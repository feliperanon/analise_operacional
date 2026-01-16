from database import get_session
from models import Route, Employee, GameXPTransaction
from sqlmodel import select, col
from datetime import datetime

def debug_14():
    session = next(get_session())
    print("🔍 DEEP DEBUG: 14 de Janeiro (2026-01-14)")
    
    # Get Welbert
    emp = session.exec(select(Employee).where(col(Employee.name).contains("WELBERT"))).first()
    if not emp: return
    
    print(f"👤 {emp.name} (ID: {emp.id})")
    
    # 1. Check Routes
    routes = session.exec(select(Route).where(
        Route.employee_id == emp.id,
        Route.date == "2026-01-14"
    )).all()
    
    if not routes:
        print("❌ Nenhuma rota encontrada para 14/01.")
    else:
        for r in routes:
            print(f"🚛 Rota {r.id} | Status: {r.status} | Ton: {r.tonnage}kg")
    
    # 2. Check Exising XP
    xp = session.exec(select(GameXPTransaction).where(
        GameXPTransaction.employee_id == emp.id,
        GameXPTransaction.reason.contains("2026-01-14")
    )).all()
    
    if xp:
        for x in xp:
            print(f"   ✅ XP EXISTENTE: ID={x.id}, Val={x.amount}, Status={x.status}")
    else:
        print("   ❌ NENHUMA TRANSAÇÃO XP (Ainda).")

if __name__ == "__main__":
    debug_14()
