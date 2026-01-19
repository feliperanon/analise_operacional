"""
Seed achievements with various categories and trigger types
"""
import os
import sys
from datetime import datetime
from typing import Optional

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import Session, select
from database import engine
import models

# Achievement categories with trigger types:
# - auto_production: Triggered automatically based on daily/cumulative production
# - auto_attendance: Triggered based on attendance records
# - auto_health: Triggered based on medical certificate absence
# - auto_time: Triggered based on work schedule
# - auto_tenure: Triggered based on time at company
# - auto_streak: Triggered based on consecutive achievements
# - manual: Admin manually awards (e.g., helping colleague)

ACHIEVEMENTS = [
    # === PRODUCTION ACHIEVEMENTS ===
    {
        "name": "Primeiro Passo",
        "description": "Complete sua primeira separação",
        "icon": "🚀",
        "xp_reward": 50,
        "category": "production",
        "trigger_type": "auto_production",
        "trigger_value": '{"cumulative_kg": 1}'
    },
    {
        "name": "Tonelada de Ferro",
        "description": "Separe 1.000 kg em um único dia",
        "icon": "💪",
        "xp_reward": 100,
        "category": "production",
        "trigger_type": "auto_production",
        "trigger_value": '{"daily_kg": 1000}'
    },
    {
        "name": "Monstro da Produção",
        "description": "Separe 5.000 kg em um único dia",
        "icon": "🔥",
        "xp_reward": 500,
        "category": "production",
        "trigger_type": "auto_production",
        "trigger_value": '{"daily_kg": 5000}'
    },
    {
        "name": "Impossível? Não Para Mim!",
        "description": "Separe 10.000 kg em um único dia",
        "icon": "⚡",
        "xp_reward": 1000,
        "category": "production",
        "trigger_type": "auto_production",
        "trigger_value": '{"daily_kg": 10000}'
    },
    {
        "name": "Veterano das Toneladas",
        "description": "Acumule 100.000 kg separados no total",
        "icon": "🏋️",
        "xp_reward": 300,
        "category": "production",
        "trigger_type": "auto_production",
        "trigger_value": '{"cumulative_kg": 100000}'
    },
    {
        "name": "Mestre Separador",
        "description": "Acumule 500.000 kg separados no total",
        "icon": "👑",
        "xp_reward": 800,
        "category": "production",
        "trigger_type": "auto_production",
        "trigger_value": '{"cumulative_kg": 500000}'
    },
    {
        "name": "Lenda Viva",
        "description": "Acumule 1.000.000 kg separados no total",
        "icon": "🌟",
        "xp_reward": 2000,
        "category": "production",
        "trigger_type": "auto_production",
        "trigger_value": '{"cumulative_kg": 1000000}'
    },

    # === SPEED/EFFICIENCY ACHIEVEMENTS ===
    {
        "name": "Raio",
        "description": "Alcance 1.500 kg/h de produtividade",
        "icon": "⚡",
        "xp_reward": 200,
        "category": "speed",
        "trigger_type": "auto_production",
        "trigger_value": '{"kgh_min": 1500}'
    },
    {
        "name": "Velocidade Máxima",
        "description": "Alcance 2.000 kg/h de produtividade",
        "icon": "🚄",
        "xp_reward": 400,
        "category": "speed",
        "trigger_type": "auto_production",
        "trigger_value": '{"kgh_min": 2000}'
    },
    {
        "name": "Madrugador",
        "description": "Termine todas as separações antes das 8h",
        "icon": "🌅",
        "xp_reward": 150,
        "category": "time",
        "trigger_type": "auto_time",
        "trigger_value": '{"finish_before": "08:00"}'
    },
    {
        "name": "Coruja Noturna",
        "description": "Trabalhe após as 20h",
        "icon": "🦉",
        "xp_reward": 100,
        "category": "time",
        "trigger_type": "auto_time",
        "trigger_value": '{"work_after": "20:00"}'
    },

    # === ATTENDANCE ACHIEVEMENTS ===
    {
        "name": "Semana Perfeita",
        "description": "Feche a semana sem nenhuma falta",
        "icon": "📅",
        "xp_reward": 150,
        "category": "attendance",
        "trigger_type": "auto_attendance",
        "trigger_value": '{"perfect_week": true}'
    },
    {
        "name": "Mês Impecável",
        "description": "Feche o mês sem nenhuma falta",
        "icon": "🗓️",
        "xp_reward": 400,
        "category": "attendance",
        "trigger_type": "auto_attendance",
        "trigger_value": '{"perfect_month": true}'
    },
    {
        "name": "Pontualidade Britânica",
        "description": "Chegue no horário por 30 dias consecutivos",
        "icon": "⏰",
        "xp_reward": 300,
        "category": "attendance",
        "trigger_type": "auto_attendance",
        "trigger_value": '{"on_time_streak": 30}'
    },

    # === HEALTH ACHIEVEMENTS ===
    {
        "name": "Saúde de Ferro",
        "description": "30 dias sem apresentar nenhum atestado",
        "icon": "💚",
        "xp_reward": 200,
        "category": "health",
        "trigger_type": "auto_health",
        "trigger_value": '{"days_without_certificate": 30}'
    },
    {
        "name": "Imune a Tudo",
        "description": "90 dias sem apresentar nenhum atestado",
        "icon": "🛡️",
        "xp_reward": 500,
        "category": "health",
        "trigger_type": "auto_health",
        "trigger_value": '{"days_without_certificate": 90}'
    },
    {
        "name": "Indestrutível",
        "description": "1 ano sem apresentar nenhum atestado",
        "icon": "💎",
        "xp_reward": 1500,
        "category": "health",
        "trigger_type": "auto_health",
        "trigger_value": '{"days_without_certificate": 365}'
    },

    # === TENURE ACHIEVEMENTS ===
    {
        "name": "Bem-Vindo à Família",
        "description": "Complete 3 meses de empresa",
        "icon": "🎉",
        "xp_reward": 100,
        "category": "tenure",
        "trigger_type": "auto_tenure",
        "trigger_value": '{"months": 3}'
    },
    {
        "name": "Veterano de 1 Ano",
        "description": "Complete 1 ano de empresa",
        "icon": "🥉",
        "xp_reward": 500,
        "category": "tenure",
        "trigger_type": "auto_tenure",
        "trigger_value": '{"months": 12}'
    },
    {
        "name": "Veterano de 3 Anos",
        "description": "Complete 3 anos de empresa",
        "icon": "🥈",
        "xp_reward": 1000,
        "category": "tenure",
        "trigger_type": "auto_tenure",
        "trigger_value": '{"months": 36}'
    },
    {
        "name": "Veterano de 5 Anos",
        "description": "Complete 5 anos de empresa",
        "icon": "🥇",
        "xp_reward": 2000,
        "category": "tenure",
        "trigger_type": "auto_tenure",
        "trigger_value": '{"months": 60}'
    },
    {
        "name": "Lenda da Empresa",
        "description": "Complete 10 anos de empresa",
        "icon": "🏆",
        "xp_reward": 5000,
        "category": "tenure",
        "trigger_type": "auto_tenure",
        "trigger_value": '{"months": 120}'
    },

    # === STREAK ACHIEVEMENTS ===
    {
        "name": "Em Chamas",
        "description": "Trabalhe 7 dias consecutivos",
        "icon": "🔥",
        "xp_reward": 100,
        "category": "streak",
        "trigger_type": "auto_streak",
        "trigger_value": '{"work_days": 7}'
    },
    {
        "name": "Imparável",
        "description": "Trabalhe 30 dias consecutivos",
        "icon": "🌊",
        "xp_reward": 400,
        "category": "streak",
        "trigger_type": "auto_streak",
        "trigger_value": '{"work_days": 30}'
    },
    {
        "name": "Máquina Humana",
        "description": "Trabalhe 90 dias consecutivos",
        "icon": "🤖",
        "xp_reward": 1000,
        "category": "streak",
        "trigger_type": "auto_streak",
        "trigger_value": '{"work_days": 90}'
    },

    # === SOCIAL/MANUAL ACHIEVEMENTS ===
    {
        "name": "Mão Amiga",
        "description": "Ajudou um colega em dificuldade",
        "icon": "🤝",
        "xp_reward": 100,
        "category": "social",
        "trigger_type": "manual",
        "trigger_value": '{}'
    },
    {
        "name": "Mentor",
        "description": "Ensinou um novo colaborador",
        "icon": "👨‍🏫",
        "xp_reward": 200,
        "category": "social",
        "trigger_type": "manual",
        "trigger_value": '{}'
    },
    {
        "name": "Espírito de Equipe",
        "description": "Contribuiu para um recorde do time",
        "icon": "⭐",
        "xp_reward": 300,
        "category": "social",
        "trigger_type": "manual",
        "trigger_value": '{}'
    },
    {
        "name": "Sugestão de Ouro",
        "description": "Deu uma ideia que melhorou o processo",
        "icon": "💡",
        "xp_reward": 500,
        "category": "social",
        "trigger_type": "manual",
        "trigger_value": '{}'
    },
    {
        "name": "Herói do Dia",
        "description": "Fez algo excepcional reconhecido pela gestão",
        "icon": "🦸",
        "xp_reward": 1000,
        "category": "social",
        "trigger_type": "manual",
        "trigger_value": '{}'
    },

    # === SPECIAL/RARE ACHIEVEMENTS ===
    {
        "name": "Sorte Grande",
        "description": "Ganhou um sorteio ou premiação especial",
        "icon": "🍀",
        "xp_reward": 250,
        "category": "special",
        "trigger_type": "manual",
        "trigger_value": '{}'
    },
    {
        "name": "Recordista",
        "description": "Quebrou um recorde pessoal ou da empresa",
        "icon": "📈",
        "xp_reward": 500,
        "category": "special",
        "trigger_type": "manual",
        "trigger_value": '{}'
    },
    {
        "name": "Colecionador",
        "description": "Desbloqueie 10 conquistas diferentes",
        "icon": "🎖️",
        "xp_reward": 300,
        "category": "special",
        "trigger_type": "auto_meta",
        "trigger_value": '{"achievements_count": 10}'
    },
    {
        "name": "Completista",
        "description": "Desbloqueie 25 conquistas diferentes",
        "icon": "🏅",
        "xp_reward": 1000,
        "category": "special",
        "trigger_type": "auto_meta",
        "trigger_value": '{"achievements_count": 25}'
    },
]

def seed_achievements():
    print(f"--- Iniciando Seeding de Conquistas ---")
    with Session(engine) as session:
        # Clear existing
        try:
            existing = session.exec(select(models.GameAchievement)).all()
            for ach in existing:
                session.delete(ach)
            session.commit()
            print("[OK] Conquistas existentes removidas")
        except Exception as e:
            session.rollback()
            print(f"[!] Erro ao limpar conquistas: {e}")
            print("[!] Tentando prosseguir sem deletar...")
        
        # Insert new
        inserted_count = 0
        for ach_data in ACHIEVEMENTS:
            try:
                ach = models.GameAchievement(
                    name=ach_data["name"],
                    description=ach_data["description"],
                    icon=ach_data["icon"],
                    xp_reward=ach_data["xp_reward"],
                    category=ach_data.get("category", "general"),
                    trigger_type=ach_data.get("trigger_type", "manual"),
                    trigger_value=ach_data.get("trigger_value", "{}")
                )
                session.add(ach)
                inserted_count += 1
            except Exception as e:
                print(f"[!] Erro ao preparar {ach_data['name']}: {e}")
        
        try:
            session.commit()
            print(f"\n[DONE] {inserted_count} conquistas criadas com sucesso!")
        except Exception as e:
            print(f"\n[CRITICAL] Falha ao comitar conquistas: {e}")
        
if __name__ == "__main__":
    seed_achievements()
