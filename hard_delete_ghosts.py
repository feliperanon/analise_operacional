from sqlmodel import Session, select, delete
from database import engine
from models import Employee, EmployeeRoutine, Route, Event, EmployeeAllocation, XPLedger
import sys

# List of Registration IDs to HARD DELETE
DELETE_IDS = [
    "2669", # EMERSON DANIEL MOREIRA CARDOSO DE SOUZA
    "2917", # CHRISTIAN DE CARVALHO JUNIOR
    "2572", # KAYLANE APARECIDA DA CRUZ COSTA
    "3007", # GUSTAVO HENRIQUE DA SILVA BRAGA
    "3025", # GUSTAVO HENRIQUE DE OLIVEIRA BRAZ
    "2995", # GUSTAVO LARA CERCEAU CHAVES
    "1446", # JOAO BATISTA SILVA RODRIGUES
    "2731", # VITOR EMANUEL BRAGA FIDELIS
    "2955", # SAMUEL DOS SANTOS RODRIGUES
    "2912", # YAGO FERNANDES SIMOES
    "2843", # GABRIEL GOMES DOS SANTOS
    "2198", # MAICON DOUGLAS RODRIGUES DOS SANTOS
    "3142", # WAGNER RODRIGUES VIEIRA
    "2773", # GUILHERME HENRIQUE DE FARIA MACHADO
    "2282", # THIAGO MARCIO SILVA COSTA
    "2335", # EMERSON DO CARMO SILVA
    "1844", # TAIS TALITA RODRIGUES SILVA
    "2751", # CRISTIANO MAIA
    "2924", # GABRIEL GONCALVES RUAS JUNIOR
    "2944", # MARCELO BARBOSA FERREIRA SANTOS
    "2880", # GABRIEL MARQUES SILVA
    "829",  # NILSON DA SILVA PIMENTEL MENDES
    "3052"  # DAVI SANTOS SILVA
]

def hard_delete_ghosts():
    sys.stdout.reconfigure(encoding='utf-8')
    with Session(engine) as session:
        print(f"🔥 Iniciando EXCLUSÃO PERMANENTE de {len(DELETE_IDS)} registros...\n")
        
        count = 0
        for reg_id in DELETE_IDS:
            emp = session.exec(select(Employee).where(Employee.registration_id == reg_id)).first()
            
            if emp:
                print(f"🗑️ Excluindo: {emp.name} (Matrícula: {emp.registration_id})")
                
                # Delete Dependencies explicitly to avoid FK errors
                session.exec(delete(EmployeeRoutine).where(EmployeeRoutine.employee_id == emp.id))
                session.exec(delete(Route).where(Route.employee_id == emp.id))
                session.exec(delete(Event).where(Event.employee_id == emp.id))
                session.exec(delete(EmployeeAllocation).where(EmployeeAllocation.employee_id == emp.id))
                session.exec(delete(XPLedger).where(XPLedger.employee_id == emp.id))
                
                # Delete Employee
                session.delete(emp)
                count += 1
            else:
                print(f"⚠️ Não encontrado: Matrícula {reg_id}")
                
        session.commit()
        print(f"\n💀 Concluído! {count} colaboradores foram removidos permanentemente do banco de dados.\n")

if __name__ == "__main__":
    hard_delete_ghosts()
