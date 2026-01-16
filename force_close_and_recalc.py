from database import get_session
from models import Route
from gamification_engine import calculate_daily_xp
from sqlmodel import select

def fix_routes():
    session = next(get_session())
    TARGET_DATES = ["2026-01-13", "2026-01-14"]
    
    print("🚑 INICIANDO CORREÇÃO DE ROTAS PENDENTES (13/01 e 14/01)...")
    
    routes_fixed = 0
    
    for date_str in TARGET_DATES:
        print(f"\n📅 Processando data: {date_str}")
        
        # 1. Find PENDING routes
        pending_routes = session.exec(select(Route).where(
            Route.date == date_str,
            Route.status == "pending"
        )).all()
        
        if not pending_routes:
            print(f"   ✅ Nenhuma rota pendente encontrada para {date_str}.")
        else:
            print(f"   ⚠️ Encontradas {len(pending_routes)} rotas pendentes. Corrigindo...")
            for r in pending_routes:
                r.status = "completed"
                session.add(r)
                routes_fixed += 1
            
            session.commit()
            print("   ✅ Status atualizado para 'completed'.")
            
        # 2. Recalculate XP (Always run to ensure coverage even if routes were already closed but XP missing)
        print(f"   🔄 Recalculando XP para {date_str}...")
        try:
            created = calculate_daily_xp(session, date_str)
            print(f"   💰 Transações de XP geradas: {created}")
        except Exception as e:
            print(f"   ❌ Erro ao calcular XP: {e}")

    print(f"\n🏁 CONCLUÍDO! Total de rotas corrigidas: {routes_fixed}")

if __name__ == "__main__":
    fix_routes()
