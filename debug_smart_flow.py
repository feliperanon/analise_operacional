
import sys
import os
from datetime import datetime
from typing import Optional
from sqlmodel import Session, create_engine, select

# Adicionar o diretório atual ao path para importar models e main
sys.path.append(os.getcwd())

import models
import main

# Configurar engine similar ao main.py
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url)

def debug_flow():
    with Session(engine) as session:
        print("--- Iniciando Depuração do smart_flow_page ---")
        try:
            # Simular parâmetros da rota
            shift = "Manhã"
            date = datetime.now().strftime("%Y-%m-%d")
            
            # 1. Buscar funcionários
            employees = session.exec(select(models.Employee).where(models.Employee.status != "fired")).all()
            emp_map = {e.registration_id: e for e in employees}
            print(f"Funcionários encontrados: {len(employees)}")
            
            # 2. Buscar Daily Op
            daily_op = session.exec(
                select(models.DailyOperation)
                .where(models.DailyOperation.date == date)
                .where(models.DailyOperation.shift == shift)
            ).first()
            if daily_op:
                print(f"DailyOperation encontrada: ID={daily_op.id}")
            else:
                print("DailyOperation não encontrada, criando transiente...")
                # Simular lógica de cópia
                last_op = session.exec(
                    select(models.DailyOperation)
                    .where(models.DailyOperation.shift == shift)
                    .where(models.DailyOperation.date < date)
                    .order_by(models.DailyOperation.date.desc())
                ).first()
                initial_log = {}
                if last_op and last_op.attendance_log:
                    for reg_id, entry in last_op.attendance_log.items():
                        if reg_id in emp_map:
                            emp_record = emp_map[reg_id]
                            new_entry = entry.copy()
                            if emp_record.status == 'vacation': new_entry['status'] = 'vacation'
                            elif emp_record.status == 'sick': new_entry['status'] = 'sick'
                            elif emp_record.status == 'away': new_entry['status'] = 'away'
                            else: new_entry['status'] = 'present'
                            initial_log[reg_id] = new_entry
                daily_op = models.DailyOperation(date=date, shift=shift, attendance_log=initial_log)

            # 3. Targets
            targets_db = session.exec(select(models.HeadcountTarget).where(models.HeadcountTarget.shift_name == shift)).first()
            shift_target_hr = targets_db.target_value if targets_db else 0
            print(f"Target RH: {shift_target_hr}")

            # 4. Sector Config
            sector_config_db = session.exec(select(models.SectorConfiguration).where(models.SectorConfiguration.shift_name == shift)).first()
            if sector_config_db and sector_config_db.config_json:
                sector_config = sector_config_db.config_json
                print("Config de setores carregada do DB.")
            else:
                print("Usando config de setores padrão.")
                sector_config = { "sectors": [] } # Simplificado

            # 5. Cálculo de demanda
            print("Calculando demanda...")
            if isinstance(sector_config, str):
                import json
                print("Aviso: sector_config é uma string. Tentando parsear...")
                sector_config = json.loads(sector_config)
            
            sectors_total_demand = sum(s.get("target", 0) for s in sector_config.get("sectors", []))
            print(f"Demanda Total: {sectors_total_demand}")

            # 6. Rotas e Tonelagem
            routes_in_shift = session.exec(
                select(models.Route)
                .where(models.Route.date == date)
                .where(models.Route.shift == shift)
            ).all()
            total_tonnage_real = sum(r.tonnage for r in routes_in_shift if r.tonnage)
            print(f"Tonelagem Real: {total_tonnage_real}")

            print("--- Sucesso na execução da lógica do backend ---")

        except Exception as e:
            print(f"--- ERRO DETECTADO ---")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    debug_flow()
