import os
import sys
# Ensure current dir is in path to import models
sys.path.append(os.getcwd())

from sqlmodel import SQLModel, create_engine, Session, select
from database import engine as local_engine
import models

# LIST OF MODELS TO MIGRATE
# Order matters because of Foreign Keys!
MODELS_ORDER = [
    models.Shift,
    models.HeadcountTarget,
    models.SectorConfiguration,
    models.Sector,       # Has no dependency
    models.SubSector,    # Depends on Sector
    models.Employee,     # Independent
    models.Client,       # Independent
    models.EmployeeRoutine, # Depends on Employee
    models.Route,        # Depends on Employee, Client
    models.Event,        # Depends on Employee, Shift
    models.DailyOperation,
    models.EmployeeAllocation, # Depends on Employee, SubSector
    models.XPLedger,      # Depends on Employee
    models.GameLevel,
    models.GameAchievement,
    models.EmployeeAchievement,
    models.GameConfiguration,
    models.GameXPTransaction
]

def migrate(external_db_url):
    print(f"🚀 Iniciando migração para: {external_db_url.split('@')[1] if '@' in external_db_url else 'Destino'}")
    
    # 1. Create Remote Engine
    if external_db_url.startswith("postgres://"):
        external_db_url = external_db_url.replace("postgres://", "postgresql://", 1)
        
    remote_engine = create_engine(external_db_url)
    
    # 2. Ensure Schema Exists on Remote
    print("📦 Criando tabelas no banco de destino...")
    SQLModel.metadata.create_all(remote_engine)
    
    # 3. Migrate Data
    with Session(local_engine) as local_session:
        with Session(remote_engine) as remote_session:
            
            for model in MODELS_ORDER:
                model_name = model.__name__
                print(f"🔄 Migrando {model_name}...")
                
                # Fetch all from local
                items = local_session.exec(select(model)).all()
                count = len(items)
                
                if count == 0:
                    print(f"   ⚠️  Nenhum dado em {model_name}.")
                    continue
                
                print(f"   📥 Lendo {count} registros...")
                
                for item in items:
                    # Safe Migration: Dump raw data (exclude relationships)
                    data = item.model_dump()
                    
                    # Create clean instance for remote DB
                    # This prevents SQLAlchemy from trying to lazy-load old relationships from the closed/expunged session
                    clean_item = model(**data)
                    
                    remote_session.merge(clean_item)
                    
                remote_session.commit()
                print(f"   ✅ {count} registros salvos em {model_name}!")

    print("\n✨ Migração Concluída com Sucesso! ✨")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Database URL")
    args = parser.parse_args()
    
    print("--- MIGRATOR SQLITE -> POSTGRES ---")
    
    if args.url:
        url = args.url
    else:
        url = input("Cole a 'External Database URL' do Render aqui: ").strip()
    
    if not url:
        print("❌ URL inválida.")
        sys.exit(1)
        
    try:
        migrate(url)
    except Exception as e:
        print(f"\n❌ ERRO FATAL: {e}")
        import traceback
        traceback.print_exc()
