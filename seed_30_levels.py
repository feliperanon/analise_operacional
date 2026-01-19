"""
Seed 30 game levels with XP progression from 6,000 to 1,400,000
and months from 0 to 120 (10 years)
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import Session, select
from database import engine
import models

# Level definitions with creative names
LEVELS = [
    # Nível, Nome, XP Mínimo, Meses Mínimos
    (1, "Novato", 0, 0),
    (2, "Aprendiz", 6000, 0),
    (3, "Iniciante", 12000, 0),
    (4, "Explorador", 20000, 1),
    (5, "Trabalhador", 30000, 2),
    (6, "Dedicado", 42000, 3),
    (7, "Esforçado", 56000, 3),
    (8, "Comprometido", 72000, 4),
    (9, "Persistente", 90000, 5),
    (10, "Confiável", 110000, 6),
    (11, "Profissional", 135000, 8),
    (12, "Especialista", 165000, 10),
    (13, "Experiente", 200000, 12),
    (14, "Veterano", 240000, 14),
    (15, "Mestre", 285000, 16),
    (16, "Grão-Mestre", 335000, 18),
    (17, "Elite", 390000, 20),
    (18, "Campeão", 450000, 24),
    (19, "Herói", 520000, 28),
    (20, "Lendário", 600000, 32),
    (21, "Mítico", 690000, 36),
    (22, "Épico", 790000, 42),
    (23, "Imortal", 900000, 48),
    (24, "Divino", 1000000, 54),
    (25, "Transcendente", 1080000, 60),  # 5 anos
    (26, "Celestial", 1150000, 72),  # 6 anos
    (27, "Supremo", 1220000, 84),  # 7 anos
    (28, "Onipotente", 1290000, 96),  # 8 anos
    (29, "Infinito", 1350000, 108),  # 9 anos
    (30, "O Escolhido", 1400000, 120),  # 10 anos
]

def seed_levels():
    with Session(engine) as session:
        # Clear existing levels
        existing = session.exec(select(models.GameLevel)).all()
        for level in existing:
            session.delete(level)
        session.commit()
        
        print("[OK] Niveis existentes removidos")
        
        # Insert new levels
        for level_num, name, min_xp, min_months in LEVELS:
            level = models.GameLevel(
                level=level_num,
                name=name,
                min_xp=min_xp,
                min_months=min_months,
                badge_image=f"badge_{level_num}.png"
            )
            session.add(level)
            print(f"[+] Nivel {level_num:2d}: {name:15s} | XP: {min_xp:>10,} | Meses: {min_months:3d}")
        
        session.commit()
        print(f"\n[DONE] {len(LEVELS)} niveis criados com sucesso!")
        
        # Summary
        print("\nResumo:")
        print(f"   - Nivel inicial: {LEVELS[0][1]} (0 XP)")
        print(f"   - Nivel final: {LEVELS[-1][1]} ({LEVELS[-1][2]:,} XP, {LEVELS[-1][3]//12} anos)")

if __name__ == "__main__":
    seed_levels()
