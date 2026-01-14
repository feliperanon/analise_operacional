
from sqlmodel import SQLModel, Session, select
from database import engine
from models import GameLevel, GameAchievement

def migrate():
    print("Creating new tables...")
    SQLModel.metadata.create_all(engine)
    print("Tables created.")
    
    with Session(engine) as session:
        # 1. Seed Levels if empty
        existing_levels = session.exec(select(GameLevel)).all()
        if not existing_levels:
            print("Seeding Game Levels...")
            levels_data = [
                # Junior
                {"level": 1, "name": "Novato", "min_xp": 0, "min_months": 0, "badge": "badge_1.png"},
                {"level": 2, "name": "Aprendiz", "min_xp": 1000, "min_months": 0, "badge": "badge_2.png"},
                {"level": 3, "name": "Assistente", "min_xp": 3000, "min_months": 1, "badge": "badge_3.png"},
                # Pleno
                {"level": 4, "name": "Operador I", "min_xp": 6000, "min_months": 3, "badge": "badge_4.png"},
                {"level": 5, "name": "Operador II", "min_xp": 10000, "min_months": 3, "badge": "badge_5.png"},
                {"level": 6, "name": "Operador III", "min_xp": 15000, "min_months": 6, "badge": "badge_6.png"},
                # Senior
                {"level": 7, "name": "Especialista I", "min_xp": 22000, "min_months": 9, "badge": "badge_7.png"},
                {"level": 8, "name": "Especialista II", "min_xp": 30000, "min_months": 9, "badge": "badge_8.png"},
                {"level": 9, "name": "Mestre Operacional", "min_xp": 40000, "min_months": 12, "badge": "badge_9.png"},
                {"level": 10, "name": "Lenda", "min_xp": 50000, "min_months": 12, "badge": "badge_10.png"},
                # Levels 11-20 can be added later
            ]
            
            for l in levels_data:
                level = GameLevel(
                    level=l["level"], 
                    name=l["name"], 
                    min_xp=l["min_xp"], 
                    min_months=l["min_months"],
                    badge_image=l["badge"]
                )
                session.add(level)
            print(f" seeded {len(levels_data)} levels.")
        
        # 2. Seed Basic Achievements
        existing_achievements = session.exec(select(GameAchievement)).all()
        if not existing_achievements:
            print("Seeding Achievements...")
            achievements = [
                {
                    "slug": "first_shift",
                    "name": "Primeiro Turno",
                    "description": "Completou o primeiro dia de trabalho.",
                    "icon": "flag",
                    "xp_reward": 50
                },
                {
                    "slug": "tonnage_10t",
                    "name": "Heavy Lifter",
                    "description": "Separou 10 toneladas em um único dia.",
                    "icon": "weight",
                    "xp_reward": 200
                },
                {
                    "slug": "perfect_week",
                    "name": "Semana Perfeita",
                    "description": "100% de presença e pontualidade na semana.",
                    "icon": "calendar-check",
                    "xp_reward": 500
                }
            ]
            for a in achievements:
                ach = GameAchievement(
                    slug=a["slug"],
                    name=a["name"],
                    description=a["description"],
                    icon=a["icon"],
                    xp_reward=a["xp_reward"]
                )
                session.add(ach)
            print(f" seeded {len(achievements)} achievements.")
            
        session.commit()
        print("Migration Complete.")

if __name__ == "__main__":
    migrate()
