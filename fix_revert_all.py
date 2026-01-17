"""
Reverter TODAS as correções de fuso horário feitas hoje.
Adiciona +3h em start_time e end_time para rotas do dia atual
que foram modificadas (07:00 ou anterior para start, 06:00 ou anterior para end).
"""
import sys
import os
sys.path.append(os.getcwd())

from sqlmodel import Session, select
from database import engine
import models
from datetime import datetime, timedelta

def revert_all_today(dry_run=True):
    with Session(engine) as session:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"Revertendo rotas de: {today}")
        
        stmt = select(models.Route).where(models.Route.date == today)
        routes = session.exec(stmt).all()
        
        print(f"Total de rotas encontradas: {len(routes)}")
        
        fixed = 0
        for r in routes:
            changes = []
            
            # Reverter Start Time se < 08:00 (provavelmente foi subtraído -3h)
            if r.start_time:
                try:
                    s_dt = datetime.strptime(r.start_time, "%H:%M")
                    # Se hora < 8, provavelmente era 08:xx-11:xx e foi "corrigido" para 05:xx-08:xx
                    if s_dt.hour < 8:
                        new_s = (s_dt + timedelta(hours=3)).strftime("%H:%M")
                        changes.append(f"Start: {r.start_time} -> {new_s}")
                        if not dry_run:
                            r.start_time = new_s
                except Exception as e:
                    print(f"Erro parsing start_time {r.start_time}: {e}")
            
            # Reverter End Time se < 08:00
            if r.end_time:
                try:
                    e_dt = datetime.strptime(r.end_time, "%H:%M")
                    if e_dt.hour < 8:
                        new_e = (e_dt + timedelta(hours=3)).strftime("%H:%M")
                        changes.append(f"End: {r.end_time} -> {new_e}")
                        if not dry_run:
                            r.end_time = new_e
                except Exception as e:
                    print(f"Erro parsing end_time {r.end_time}: {e}")
            
            if changes:
                emp = session.get(models.Employee, r.employee_id)
                emp_name = emp.name if emp else f"ID:{r.employee_id}"
                print(f"[REVERT] Rota {r.id} | {emp_name} | {' | '.join(changes)}")
                if not dry_run:
                    session.add(r)
                fixed += 1
        
        if not dry_run:
            session.commit()
            print(f"\n✅ {fixed} rotas revertidas com sucesso!")
        else:
            print(f"\n[DRY RUN] {fixed} rotas seriam revertidas. Use 'commit' para aplicar.")

if __name__ == "__main__":
    dry = "commit" not in sys.argv
    revert_all_today(dry_run=dry)
