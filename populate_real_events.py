"""
Script para popular eventos reais de faltas e atestados
Limpa eventos antigos e adiciona dados reais fornecidos
"""

from sqlmodel import Session, select
from database import engine
import models
from datetime import datetime

def clear_old_events(session: Session):
    """Remove todos os eventos existentes"""
    print("🗑️  Limpando eventos antigos...")
    events = session.exec(select(models.Event)).all()
    for event in events:
        session.delete(event)
    session.commit()
    print(f"   ✅ {len(events)} eventos removidos")

def add_absences(session: Session):
    """Adiciona faltas (1 dia)"""
    print("\n📌 Adicionando faltas...")
    
    absences = [
        ("1025", "CRISTIANO RICARDO", ["2025-11-11"]),
        ("779", "LAUSTON DIVINO DE REZENDE", ["2025-12-05"]),
        ("3127", "PAMELA SA DE FREITAS RAMOS", ["2025-11-27", "2025-12-14"]),
        ("3230", "POLLYANNE KAROLINE FREITAS TEIXEIRA", ["2025-11-02", "2025-11-03"]),
        ("3029", "VINICIUS LOYOLA DE OLIVEIRA", ["2025-11-18", "2025-11-19"]),
        ("2542", "WELLINGTON LUIZ DE OLIVEIRA DUARTE", ["2025-11-24", "2025-11-28"])
    ]
    
    count = 0
    for reg_id, name, dates in absences:
        emp = session.exec(select(models.Employee).where(models.Employee.registration_id == reg_id)).first()
        
        if not emp:
            print(f"   ⚠️  Colaborador {name} ({reg_id}) não encontrado")
            continue
            
        for date_str in dates:
            event_date = datetime.strptime(date_str, "%Y-%m-%d")
            event = models.Event(
                timestamp=event_date.replace(hour=8, minute=0),
                text=f"Falta registrada em {date_str}",
                type="falta",
                category="pessoas",
                sector=emp.cost_center or "Geral",
                impact="medium",
                employee_id=emp.id
            )
            session.add(event)
            count += 1
    
    session.commit()
    print(f"   ✅ {count} faltas adicionadas")

def add_sick_leaves(session: Session):
    """Adiciona atestados médicos"""
    print("\n🏥 Adicionando atestados...")
    
    sick_leaves = [
        ("3068", "ALEXIS PATRICIO FERREIRA", [
            "2025-11-10", "2025-11-11", "2025-11-12", "2025-11-13", "2025-11-14",
            "2025-12-15", "2025-12-16", "2025-12-17", "2025-12-18", "2025-12-19",
            "2025-12-22", "2025-12-23", "2025-12-24"
        ]),
        ("3034", "ELVIS HENRIQUE MARTINS ROSA", [
            "2025-12-03", "2025-12-04", "2025-12-05", "2025-12-06",
            "2025-12-17", "2025-12-18", "2025-12-19", "2025-12-20", "2025-12-21",
            "2025-12-22", "2025-12-23", "2025-12-24", "2025-12-25", "2025-12-26",
            "2025-12-27", "2025-12-28", "2025-12-29", "2025-12-30", "2025-12-31"
        ]),
        ("779", "LAUSTON DIVINO DE REZENDE", [
            "2025-11-20", "2025-11-21", "2025-11-22", "2025-11-23",
            "2025-12-23", "2025-12-24", "2025-12-25"
        ]),
        ("3117", "MATHEUS HENRICK PEREIRA DA SILVA", [
            "2025-12-01", "2025-12-02", "2025-12-03", "2025-12-04",
            "2025-12-15", "2025-12-16", "2025-12-17"
        ]),
        ("2907", "SAMIRA PRISCILA MARTINS DA SILVA", [
            "2025-12-11", "2025-12-12"
        ]),
        ("2563", "THIAGO LUIZ DIAS DE SOUZA", [
            "2025-11-25", "2025-11-26", "2025-11-27"
        ]),
        ("2542", "WELLINGTON LUIZ DE OLIVEIRA DUARTE", [
            "2025-12-12", "2025-12-13", "2025-12-14",
            "2025-12-22", "2025-12-23"
        ])
    ]
    
    count = 0
    for reg_id, name, dates in sick_leaves:
        emp = session.exec(select(models.Employee).where(models.Employee.registration_id == reg_id)).first()
        
        if not emp:
            print(f"   ⚠️  Colaborador {name} ({reg_id}) não encontrado")
            continue
            
        for date_str in dates:
            event_date = datetime.strptime(date_str, "%Y-%m-%d")
            event = models.Event(
                timestamp=event_date.replace(hour=8, minute=0),
                text=f"Atestado médico - {date_str}",
                type="atestado",
                category="pessoas",
                sector=emp.cost_center or "Geral",
                impact="medium",
                employee_id=emp.id
            )
            session.add(event)
            count += 1
    
    session.commit()
    print(f"   ✅ {count} atestados adicionados")

def main():
    print("=" * 60)
    print("POPULAÇÃO DE EVENTOS REAIS - FALTAS E ATESTADOS")
    print("=" * 60)
    
    with Session(engine) as session:
        clear_old_events(session)
        add_absences(session)
        add_sick_leaves(session)
    
    print("\n" + "=" * 60)
    print("✅ PROCESSO CONCLUÍDO COM SUCESSO!")
    print("=" * 60)
    print("\n💡 Acesse /people-intelligence para ver os dados atualizados")

if __name__ == "__main__":
    main()
