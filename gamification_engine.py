
from typing import List, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlmodel import Session, select, func
from models import Employee, Route, GameXPTransaction, GameLevel, GameAchievement, EmployeeAchievement, Event
import json

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
        reason_parts = []
        
        # 1. Native Efficiency Bonus
        if uo_per_hour >= 1.0:
            bonus_mult += 0.10
            reason_parts.append("Eff +10%")
        elif uo_per_hour >= 1.5:
            bonus_mult += 0.25
            reason_parts.append("Turbo +25%")
            
        # 2. Configurable Time Rules (Bonus per Route End Time)
        # Fetch Config (Cached/Optimized in real app, here fetch per call or passed arg)
        # TODO: Pass config as arg to optimize. For now fetch.
        from models import GameConfiguration
        import json
        
        config_rules_json = session.get(GameConfiguration, "xp_time_rules")
        time_rules = json.loads(config_rules_json.value) if config_rules_json else []
        
        if r.end_time:
            try:
                end_dt = datetime.strptime(r.end_time, "%H:%M")
                current_date_obj = datetime.strptime(r.date, "%Y-%m-%d")
                weekday = current_date_obj.weekday() # 0=Mon, 6=Sun
                
                for rule in time_rules:
                    # Check Days Constraint (if exists and not empty)
                    if "days" in rule and rule["days"] and len(rule["days"]) > 0:
                        if weekday not in rule["days"]:
                            continue
                    
                    limit = datetime.strptime(rule['stop_time'], "%H:%M")
                    if end_dt <= limit:
                        bonus_pct = float(rule.get('bonus_percent', 0)) / 100.0
                        bonus_mult += bonus_pct
                        reason_parts.append(f"Early {rule['stop_time']} (+{rule['bonus_percent']}%)")
                        break # Apply best rule only? or cumulative? Assume one rule matches or first best.
            except:
                pass

        # 3. Special Event Multiplier (Date-based)
        config_events_json = session.get(GameConfiguration, "xp_special_events")
        special_events = json.loads(config_events_json.value) if config_events_json else []
        
        event_mult = 1.0
        for evt in special_events:
            if evt.get('date') == target_date_str:
                m = float(evt.get('multiplier', 1.0))
                if m > 1.0:
                    event_mult = m
                    reason_parts.append(f"Event: {evt.get('name')} ({m}x)")
        
        # Final Calc: Base * (Sum of Efficiency/Time Bonuses) * Event Multiplier
        final_xp = int(base_xp * bonus_mult * event_mult)
        
        extra_info = " | ".join(reason_parts) if reason_parts else ""
        if extra_info:
             extra_info = "| " + extra_info
        
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
            existing.reason = f"Produtividade {target_date_str} (ref: {reference_id}) | {kg:.0f}kg | {uo:.2f} UO {extra_info}"
            # existing.updated_at = datetime.now() # Removed: Field does not exist in model
            session.add(existing)
            created_count += 1
            continue
            
        # Create Transaction
        tx = GameXPTransaction(
            employee_id=emp_id,
            amount=final_xp,
            source_type="daily_auto",
            status="provisional", # Requires confirmation
            reason=f"Produtividade {target_date_str} (ref: {reference_id}) | {kg:.0f}kg | {uo:.2f} UO {extra_info}",
            created_at=datetime.now(ZoneInfo("America/Sao_Paulo"))
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
    
    tz = ZoneInfo("America/Sao_Paulo")
    threshold = datetime.now(tz) - timedelta(hours=20) # Almost a day
    
    pending = session.exec(select(GameXPTransaction).where(
        GameXPTransaction.status == "provisional",
        GameXPTransaction.created_at <= threshold
    )).all()
    
    confirmed_count = 0
    for tx in pending:
        tx.status = "confirmed"
        tx.confirmed_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
        
        # Update Employee Total XP
        emp = session.get(Employee, tx.employee_id)
        if emp:
            emp.total_xp += tx.amount
            session.add(emp)
            
            # Check for Achievements after XP confirmation
            check_and_award_achievements(session, tx.employee_id)
            
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
        today = datetime.now(ZoneInfo("America/Sao_Paulo"))
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

def check_and_award_achievements(session: Session, employee_id: int):
    """
    Evaluates all automatic achievement triggers for an employee.
    Called after XP confirmation or specific events.
    """
    emp = session.get(Employee, employee_id)
    if not emp: return
    
    # 1. Get all achievements already earned by this employee
    earned_ids = session.exec(select(EmployeeAchievement.achievement_id).where(
        EmployeeAchievement.employee_id == employee_id
    )).all()
    
    # 2. Get all available automatic achievements NOT yet earned
    available = session.exec(select(GameAchievement).where(
        GameAchievement.trigger_type != "manual",
        ~GameAchievement.id.in_(earned_ids) if earned_ids else True
    )).all()
    
    if not available: return
    
    # Pre-fetch some generic stats for performance
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    months_tenure = 0
    if emp.admission_date:
        months_tenure = (now.year - emp.admission_date.year) * 12 + (now.month - emp.admission_date.month)

    # 3. Evaluate each achievement
    for ach in available:
        rules = {}
        try:
            if ach.trigger_value:
                rules = json.loads(ach.trigger_value)
        except:
            continue
            
        is_triggered = False
        
        # --- LOGIC BY TRIGGER TYPE ---
        
        if ach.trigger_type == "auto_production":
            # Check cumulative_kg
            if "cumulative_kg" in rules:
                # Sum of all confirmed XP from productivity (proxy for tonnage if we don't have a direct tonnage ledger)
                # Or better: check confirmed productivity transactions
                total_kg = session.exec(select(func.sum(Route.tonnage)).where(
                    Route.employee_id == employee_id,
                    Route.status == "completed"
                )).one() or 0.0
                if total_kg >= rules["cumulative_kg"]:
                    is_triggered = True
            
            # Check daily_kg (Ever reached this in a single day?)
            if "daily_kg" in rules:
                max_daily = session.exec(select(func.max(Route.tonnage)).where(
                    Route.employee_id == employee_id,
                    Route.status == "completed"
                )).one() or 0.0
                if max_daily >= rules["daily_kg"]:
                    is_triggered = True

            # Check kgh_min (Efficiency)
            if "kgh_min" in rules:
                # Need to calculate kg/h for all routes and find max
                # This is more complex, let's check recent routes
                routes = session.exec(select(Route).where(
                    Route.employee_id == employee_id,
                    Route.status == "completed"
                )).all()
                for r in routes:
                    if r.start_time and r.end_time:
                        try:
                            s = datetime.strptime(r.start_time, "%H:%M")
                            e = datetime.strptime(r.end_time, "%H:%M")
                            h = (e-s).total_seconds() / 3600.0
                            if h > 0 and (r.tonnage / h) >= rules["kgh_min"]:
                                is_triggered = True
                                break
                        except: pass

        elif ach.trigger_type == "auto_tenure":
            if "months" in rules:
                if months_tenure >= rules["months"]:
                    is_triggered = True

        elif ach.trigger_type == "auto_health":
            # Days without certificates
            if "days_without_certificate" in rules:
                days = rules["days_without_certificate"]
                limit_date = now - timedelta(days=days)
                # Check for 'atestado' events in this period
                exists = session.exec(select(Event).where(
                    Event.employee_id == employee_id,
                    Event.type == "atestado",
                    Event.timestamp >= limit_date
                )).first()
                # If no atestado found AND enough time passed since admission
                if not exists and emp.admission_date and emp.admission_date <= limit_date:
                    is_triggered = True

        elif ach.trigger_type == "auto_attendance":
            # Perfect week/month logic would require checking daily records
            # For now, let's check for 'falta' events
            if "perfect_month" in rules:
                limit_date = now - timedelta(days=30)
                exists = session.exec(select(Event).where(
                    Event.employee_id == employee_id,
                    Event.type == "falta",
                    Event.timestamp >= limit_date
                )).first()
                if not exists and emp.admission_date and emp.admission_date <= limit_date:
                    is_triggered = True
            
            if "perfect_week" in rules:
                limit_date = now - timedelta(days=7)
                exists = session.exec(select(Event).where(
                    Event.employee_id == employee_id,
                    Event.type == "falta",
                    Event.timestamp >= limit_date
                )).first()
                if not exists and emp.admission_date and emp.admission_date <= limit_date:
                    is_triggered = True

        elif ach.trigger_type == "auto_time":
            # Finish before
            if "finish_before" in rules:
                limit_time = rules["finish_before"]
                # Ever finished a route before this time?
                exists = session.exec(select(Route).where(
                    Route.employee_id == employee_id,
                    Route.status == "completed",
                    Route.end_time <= limit_time
                )).first()
                if exists:
                    is_triggered = True

        # 4. Award Achievement
        if is_triggered:
            print(f"   🏆 AWARDED: {ach.name} to {emp.name}!")
            
            # Create link
            ea = EmployeeAchievement(
                employee_id=employee_id,
                achievement_id=ach.id,
                earned_at=datetime.now(ZoneInfo("America/Sao_Paulo")),
                status="approved" # Auto-achievements are auto-approved
            )
            session.add(ea)
            
            # Create XP Transaction
            tx = GameXPTransaction(
                employee_id=employee_id,
                amount=ach.xp_reward,
                source_type="achievement_grant",
                status="confirmed",
                reason=f"Conquista Desbloqueada: {ach.name} {ach.icon}",
                created_at=datetime.now(ZoneInfo("America/Sao_Paulo")),
                confirmed_at=datetime.now(ZoneInfo("America/Sao_Paulo"))
            )
            session.add(tx)
            
            # Add XP directly
            emp.total_xp += ach.xp_reward
            session.add(emp)
    
    session.commit()
