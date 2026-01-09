from sqlmodel import Session, select
from database import engine
from models import Employee
import sys

# List of Registration IDs identified by the user as Ghost Employees
GHOST_IDS = [
    "1446", # JOAO BATISTA SILVA RODRIGUES
    "2731", # VITOR EMANUEL BRAGA FIDELIS
    "2955", # SAMUEL DOS SANTOS RODRIGUES
    "2912", # YAGO FERNANDES SIMOES
    "2669", # EMERSON DANIEL MOREIRA CARDOSO DE SOUZA
    "2917", # CHRISTIAN DE CARVALHO JUNIOR
    "2572", # KAYLANE APARECIDA DA CRUZ COSTA
    "3007", # GUSTAVO HENRIQUE DA SILVA BRAGA
    "3025", # GUSTAVO HENRIQUE DE OLIVEIRA BRAZ
    "2995", # GUSTAVO LARA CERCEAU CHAVES
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
    "829"   # NILSON DA SILVA PIMENTEL MENDES
]

def fire_ghosts():
    sys.stdout.reconfigure(encoding='utf-8')
    with Session(engine) as session:
        print(f"🔍 Iniciando limpeza de {len(GHOST_IDS)} colaboradores fantasmas...\n")
        
        count = 0
        for reg_id in GHOST_IDS:
            statement = select(Employee).where(Employee.registration_id == reg_id).where(Employee.status == "active")
            results = session.exec(statement).all()
            
            for emp in results:
                print(f"⛔ Desligando: {emp.name} (Matrícula: {emp.registration_id})")
                emp.status = "fired"
                session.add(emp)
                count += 1
                
        session.commit()
        print(f"\n✅ Concluído! {count} colaboradores foram marcados como 'fired'.")

if __name__ == "__main__":
    fire_ghosts()
