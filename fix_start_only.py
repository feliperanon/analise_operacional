"""
Corrigir APENAS horários de início que estão errados.
Adiciona +3h para start_time < 08:00, NÃO mexe no end_time.
"""
import sys
import os
sys.path.append(os.getcwd())

from sqlmodel import Session, select
from database import engine
import models
from datetime import datetime, timedelta

def fix_start_only(dry_run=True):
    with Session(engine) as session:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"Corrigindo APENAS Start Time para: {today}")
        
        stmt = select(models.Route).where(models.Route.date == today)
        routes = session.exec(stmt).all()
        
        print(f"Total de rotas encontradas: {len(routes)}")
        
        fixed = 0
        for r in routes:
            if not r.start_time: continue
            
            try:
                s_dt = datetime.strptime(r.start_time, "%H:%M")
                
                # Se Start Time < 08:00, provavelmente era 08:xx-10:xx (adicionar +3h)
                if s_dt.hour < 8:
                    new_s = (s_dt + timedelta(hours=3)).strftime("%H:%M")
                    
                    emp = session.get(models.Employee, r.employee_id)
                    emp_name = emp.name if emp else f"ID:{r.employee_id}"
                    print(f"[FIX] Rota {r.id} | {emp_name} | Start: {r.start_time} -> {new_s} | End: {r.end_time} (inalterado)")
                    
                    if not dry_run:
                        r.start_time = new_s
                        session.add(r)
                    fixed += 1
                    
            except Exception as e:
                print(f"Erro parsing start_time {r.start_time}: {e}")
        
        if not dry_run:
            session.commit()
            print(f"\n✅ {fixed} rotas corrigidas com sucesso!")
        else:
            print(f"\n[DRY RUN] {fixed} rotas seriam corrigidas. Use 'commit' para aplicar.")

if __name__ == "__main__":
    dry = "commit" not in sys.argv
    fix_start_only(dry_run=dry)
