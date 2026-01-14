
from sqlmodel import Session, select
from database import engine, create_db_and_tables
from models import GameConfiguration
from datetime import datetime

def seed_config():
    create_db_and_tables()
    with Session(engine) as session:
        defaults = [
            # Penalties / Rewards
            GameConfiguration(key="xp_absence_penalty", value="-500", description="Penalidade por Falta Injustificada", category="rules"),
            GameConfiguration(key="xp_sick_reward", value="0", description="XP por Atestado Médico (Neutro)", category="rules"),
            GameConfiguration(key="xp_tenure_bonus_per_year", value="1000", description="Bônus por Ano de Casa", category="rules"),
            
            # Special Events (Day Bonus)
            GameConfiguration(key="special_event_date", value="", description="Data do Evento Especial (YYYY-MM-DD)", category="events"),
            GameConfiguration(key="special_event_bonus", value="0", description="Bônus Fixo no Dia Especial", category="events"),
            GameConfiguration(key="special_event_multiplier", value="1.0", description="Multiplicador de XP no Dia Especial", category="events"),
            
            # System Limits
            GameConfiguration(key="xp_daily_limit", value="5000", description="Limite Máximo de XP Diário (Anti-Cheat)", category="system"),
        ]
        
        print("--- Seeding Game Configuration ---")
        for d in defaults:
            existing = session.get(GameConfiguration, d.key)
            if not existing:
                print(f"Creating {d.key} = {d.value}")
                session.add(d)
            else:
                print(f"Skipping {d.key} (already exists)")
        
        session.commit()
        print("Done.")

if __name__ == "__main__":
    seed_config()
