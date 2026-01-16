
from typing import List, Optional
from datetime import datetime, timedelta
from sqlmodel import Session, select, func
from models import Employee, Route, GameXPTransaction, GameLevel, GameAchievement, EmployeeAchievement

# --- Config ---
XP_PER_UO = 100 # 1 UO = 1500kg -> 100 XP
KG_PER_UO = 1500.0

def calculate_daily_xp(session: Session, target_date_str: str):
    """
    Calculates XP for a specific date based on Routes.
    Generates a PROVISIONAL transaction.
    """
    print(f"--- Calculating XP for {target_date_str} ---")
    
    # 1. Fetch Routes for the day
    routes = session.exec(
        select(Route).where(Route.date == target_date_str, Route.status == "completed")
    ).all()
    
    # Group by Employee
    employee_stats = {}
    for r in routes:
        if r.employee_id not in employee_stats:
            employee_stats[r.employee_id] = {"kg": 0.0, "seconds": 0.0}
        
        employee_stats[r.employee_id]["kg"] += r.tonnage
        
        # Duration calc
        if r.start_time and r.end_time:
            try:
                s = datetime.strptime(r.start_time, "%H:%M")
                e = datetime.strptime(r.end_time, "%H:%M")
                diff = (e - s).total_seconds()
                if diff > 0:
                    employee_stats[r.employee_id]["seconds"] += diff
            except:
                pass

    created_count = 0
    
    # 2. Process Stats
    for emp_id, stats in employee_stats.items():
        kg = stats["kg"]
        seconds = stats["seconds"]
        
        if kg <= 0: continue

        # --- Metrics ---
        uo = kg / KG_PER_UO
        hours = seconds / 3600.0 if seconds > 0 else 0
        uo_per_hour = uo / hours if hours > 0 else 0
        
        # --- XP Formula ---
        # Base XP: UO * Multiplier
        base_xp = uo * XP_PER_UO
        
        # Efficiency Bonus (Multiplier)
        # If UO/h > 1.0 (1500kg/h) -> +10% bonus
        bonus_mult = 1.0
        if uo_per_hour >= 1.0:
            bonus_mult = 1.10
        elif uo_per_hour >= 1.5:
            bonus_mult = 1.25
            
        final_xp = int(base_xp * bonus_mult)
        
        reference_id = f"daily_{target_date_str}"
        
        # Check if already exists to avoid duplicates
        existing = session.exec(select(GameXPTransaction).where(
            GameXPTransaction.employee_id == emp_id,
            GameXPTransaction.source_type == "daily_auto",
            GameXPTransaction.reason.contains(reference_id)
        )).first()
        
        if existing:
            print(f"   🔄 Updating existing XP for {emp_id}: {existing.amount} -> {final_xp}")
            existing.amount = final_xp
            existing.reason = f"Produtividade {target_date_str} (ref: {reference_id}) | {kg:.0f}kg | {uo:.2f} UO"
            existing.updated_at = datetime.now()
            session.add(existing)
            created_count += 1
            continue
            
        # Create Transaction
        tx = GameXPTransaction(
            employee_id=emp_id,
            amount=final_xp,
            source_type="daily_auto",
            status="provisional", # Requires confirmation
            reason=f"Produtividade {target_date_str} (ref: {reference_id}) | {kg:.0f}kg | {uo:.2f} UO",
            created_at=datetime.now()
        )
        session.add(tx)
        created_count += 1
        
    session.commit()
    return created_count

def confirm_pending_xp(session: Session):
    """
    Confirms all 'provisional' transactions older than X hours/days.
    In V2 spec: 'No dia seguinte, o XP é CONFIRMADO'.
    """
    # Find provisional transactions created calculated for YESTERDAY (or older)
    # Actually, we rely on the `created_at`. If created > 24h ago, confirm.
    
    threshold = datetime.now() - timedelta(hours=20) # Almost a day
    
    pending = session.exec(select(GameXPTransaction).where(
        GameXPTransaction.status == "provisional",
        GameXPTransaction.created_at <= threshold
    )).all()
    
    confirmed_count = 0
    for tx in pending:
        tx.status = "confirmed"
        tx.confirmed_at = datetime.now()
        
        # Update Employee Total XP
        emp = session.get(Employee, tx.employee_id)
        if emp:
            emp.total_xp += tx.amount
            session.add(emp)
            
        confirmed_count += 1
        
    session.commit()
    return confirmed_count

def get_employee_progress(session: Session, employee_id: int):
    """
    Returns (CurrentLevel, NextLevel, ProgressPercent) respecting Time Caps.
    """
    emp = session.get(Employee, employee_id)
    if not emp: return None
    
    # Calculate MONTHS in company
    months_in_company = 0
    if emp.admission_date:
        today = datetime.now()
        # diff in months
        months_in_company = (today.year - emp.admission_date.year) * 12 + (today.month - emp.admission_date.month)
    
    # Get all levels ordered
    levels = session.exec(select(GameLevel).order_by(GameLevel.level)).all()
    
    current_level_obj = levels[0]
    next_level_obj = None
    
    # Find highest eligible level
    for lvl in levels:
        # Check XP
        if emp.total_xp >= lvl.min_xp:
            # Check Time Cap
            if months_in_company >= lvl.min_months:
                current_level_obj = lvl
            else:
                # XP is enough, but Time is not -> CAP REACHED
                # Effectively they are at the previous level (or this one is the ceiling)
                # But logic: they STAY at the highest level they qualify for.
                pass
        else:
            # Not enough XP, this is the NEXT potential level
            next_level_obj = lvl
            break
            
    # Calculate progress to next
    progress = 100
    if next_level_obj:
        xp_needed = next_level_obj.min_xp - current_level_obj.min_xp
        xp_have = emp.total_xp - current_level_obj.min_xp
        if xp_needed > 0:
            progress = int((xp_have / xp_needed) * 100)
        else:
            progress = 0 # Should not happen unless levels equal
            
    return {
        "level": current_level_obj,
        "next_level": next_level_obj,
        "progress": progress,
        "months_tenure": months_in_company
    }
