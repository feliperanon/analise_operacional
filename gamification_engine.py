
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
            employee_stats[r.employee_id] = {
                "kg": 0.0, 
                "seconds": 0.0,
                "earliest_end_time": None,  # Para verificar bônus por horário
                "latest_end_time": None     # Última rota concluída
            }
        
        employee_stats[r.employee_id]["kg"] += r.tonnage
        
        # Track earliest and latest end times for bonus calculation
        if r.end_time:
            if employee_stats[r.employee_id]["earliest_end_time"] is None or r.end_time < employee_stats[r.employee_id]["earliest_end_time"]:
                employee_stats[r.employee_id]["earliest_end_time"] = r.end_time
            if employee_stats[r.employee_id]["latest_end_time"] is None or r.end_time > employee_stats[r.employee_id]["latest_end_time"]:
                employee_stats[r.employee_id]["latest_end_time"] = r.end_time
        
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
        
        productivity_bonus = 0

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
        
        # Usar latest_end_time do funcionário (não a variável r do loop anterior!)
        emp_latest_end = stats.get("latest_end_time")
        if emp_latest_end:
            try:
                end_dt = datetime.strptime(emp_latest_end, "%H:%M")
                current_date_obj = datetime.strptime(target_date_str, "%Y-%m-%d")
                weekday = current_date_obj.weekday() # 0=Mon, 6=Sun
                
                for rule in time_rules:
                    # Check Days Constraint (if exists and not empty)
                    if "days" in rule and rule["days"] and len(rule["days"]) > 0:
                        if weekday not in rule["days"]:
                            continue
                    
                    limit = datetime.strptime(rule['stop_time'], "%H:%M")
                    if end_dt <= limit:
                        # Suporta bonus_percent (%) OU bonus_xp (XP fixo)
                        bonus_pct = float(rule.get('bonus_percent', 0)) / 100.0
                        bonus_xp_fixed = float(rule.get('bonus_xp', 0))
                        
                        if bonus_pct > 0:
                            bonus_mult += bonus_pct
                            reason_parts.append(f"⏰ Horário {rule['stop_time']} (+{rule['bonus_percent']}%)")
                        
                        # Adicionar XP fixo ao productivity_bonus se configurado
                        if bonus_xp_fixed > 0:
                            productivity_bonus += int(bonus_xp_fixed)
                            reason_parts.append(f"⏰ Horário {rule['stop_time']} (+{int(bonus_xp_fixed)} XP)")
                        
                        print(f"   ✅ Time Bonus applied for {emp_id}: finished at {emp_latest_end}, limit {rule['stop_time']}, pct={bonus_pct}, xp={bonus_xp_fixed}")
                        break # Apply best rule only
            except Exception as e:
                print(f"   ⚠️ Error checking time bonus: {e}")

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

        # 4. Productivity Challenge Bonus (NEW)
        # Compare with yesterday
        # productivity_bonus already initialized at start of loop
        try:
            target_date_obj = datetime.strptime(target_date_str, "%Y-%m-%d")
            yesterday_obj = target_date_obj - timedelta(days=1)
            if yesterday_obj.weekday() == 6: # Sunday -> Saturday
                yesterday_obj -= timedelta(days=1)
            yesterday_str = yesterday_obj.strftime("%Y-%m-%d")

            y_routes = session.exec(
                select(Route).where(Route.employee_id == emp_id, Route.date == yesterday_str, Route.status == "completed")
            ).all()
            
            y_kg = sum([r.tonnage for r in y_routes if r.tonnage]) or 0.0
            y_seconds = 0
            for yr in y_routes:
                if yr.start_time and yr.end_time:
                    try:
                        ys = datetime.strptime(yr.start_time, "%H:%M")
                        ye = datetime.strptime(yr.end_time, "%H:%M")
                        y_seconds += (ye - ys).total_seconds()
                    except: pass
            
            # If today did more weight (or same) in less time
            if y_kg > 0 and kg >= y_kg and seconds < y_seconds and seconds > 0:
                productivity_bonus = 100
                reason_parts.append("Desafio Lucro +100XP")
        except Exception as e:
            print(f"Error calc productivity bonus: {e}")
        
        # Final Calc: Base * (Sum of Efficiency/Time Bonuses) * Event Multiplier + Fixed Productivity Bonus
        final_xp = int(base_xp * bonus_mult * event_mult) + productivity_bonus
        
        # --- Build Detailed Breakdown ---
        xp_base = int(base_xp)
        xp_efficiency = int(base_xp * (bonus_mult - 1.0)) if bonus_mult > 1.0 else 0
        xp_event = int(base_xp * bonus_mult * (event_mult - 1.0)) if event_mult > 1.0 else 0
        
        breakdown_parts = [f"📦 Sua Entrega: {xp_base} XP"] # Base
        
        # Recover efficiency part from bonus_mult logic (bit hacky but works since we sum up pct)
        # Better: iterate parts. But for now let's construct based on calcs if possible or just use the parts list.
        # Actually most robust is to use what we added to reason_parts?
        # reason_parts has strings like "⏰ Horário...". Let's use those for specific bonuses.
        
        # Mas queremos separar o VALOR de XP de cada um.
        # Simplificação: O cálculo de XP Total é fechado. O breakdown é aproximado visualmente ou exato?
        # Vamos tentar ser exatos.
        
        # 1. Base (UO * 100)
        
        # 2. Eficiência (Base * bonus_efficiency_pct)
        # Precisamos saber quanto do bonus_mult é eficiência vs horário.
        # Re-scan reason_parts
        
        eff_pct = 0.0
        time_bonus_val = 0
        
        for p in reason_parts:
            if "Eff" in p: eff_pct += 0.10
            if "Turbo" in p: eff_pct += 0.25
            # Time bonuses are tricky because they can be % OR fixed XP now.
            # But we added them to productivity_bonus if fixed? No, code line 122 adds to productivity_bonus.
            # Code line 117 adds to bonus_mult if %.
            
        current_eff_xp = int(base_xp * eff_pct)
        if current_eff_xp > 0:
            breakdown_parts.append(f"⚡ Rapidez: +{current_eff_xp} XP")
            
        # 3. Horário (Fixed XP added to productivity_bonus OR % added to bonus_mult)
        # Vamos ler novamente os reason_parts para achar bonus de horário de %
        time_pct = 0.0
        for p in reason_parts:
            if "Horário" in p and "%" in p:
                 # Extract number... clean string parsing
                 try:
                     # "⏰ Horário 09:00 (+15%)"
                     pct_str = p.split("+")[1].split("%")[0]
                     time_pct += float(pct_str) / 100.0
                 except: pass
        
        current_time_pct_xp = int(base_xp * time_pct)
        if current_time_pct_xp > 0:
            breakdown_parts.append(f"⏰ Bônus Horário: +{current_time_pct_xp} XP")

        # 4. Evento
        if xp_event > 0:
            breakdown_parts.append(f"🎉 Evento Especial: +{xp_event} XP")
            
        # 5. Fixed Bonuses (Desafio + Fixed Time Bonus)
        # productivity_bonus now contains BOTH challenge AND fixed time bonus.
        # We need to distinguish them?
        # The logic at line 122 adds to productivity_bonus.
        # The logic at line 143 (original) adds to productivity_bonus (Desafio).
        
        # Let's verify what is inside productivity_bonus
        # It is just an integer sum.
        # We can look at reason_parts.
        
        for p in reason_parts:
            if "Desafio" in p:
                breakdown_parts.append(f"🏆 Superou Ontem: +100 XP") # Assumed 100 fixed
            if "Horário" in p and "XP" in p:
                # "⏰ Horário ... (+150 XP)"
                try:
                    xp_str = p.split("+")[1].split(" XP")[0]
                    breakdown_parts.append(f"⏰ Bônus Horário: +{xp_str} XP")
                except: pass

        breakdown_str = " | ".join(breakdown_parts)
        
        extra_info = " | ".join(reason_parts) if reason_parts else ""
        if extra_info:
             extra_info = "| " + extra_info # Keep for internal ref or admin view if needed
        
        reference_id = f"daily_{target_date_str}"
        
        reference_id = f"daily_{target_date_str}"
        
        # Standard format for parser compatibility, preserving ludic breakdown
        reason_text = f"Produtividade {target_date_str} (ref: {reference_id}) | {kg:.0f}kg | {uo:.2f} UO | [{breakdown_str}] = {final_xp} XP {extra_info}"
        
        # Check if already exists to avoid duplicates
        existing = session.exec(select(GameXPTransaction).where(
            GameXPTransaction.employee_id == emp_id,
            GameXPTransaction.source_type == "daily_auto",
            GameXPTransaction.reason.contains(reference_id)
        )).first()
        
        if existing:
            print(f"   🔄 Updating existing XP for {emp_id}: {existing.amount} -> {final_xp}")
            existing.amount = final_xp
            existing.reason = reason_text
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
            reason=reason_text,
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


def evaluate_achievement_criteria(session: Session, employee_id: int, achievement: GameAchievement) -> bool:
    """
    Evaluates if an employee meets the criteria for a specific achievement.
    Returns True if criteria are met, False otherwise.
    """
    emp = session.get(Employee, employee_id)
    if not emp: return False

    rules = {}
    try:
        if achievement.trigger_value:
            rules = json.loads(achievement.trigger_value)
    except:
        return False

    is_triggered = False
    
    # Pre-fetch generic stats
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    months_tenure = 0
    if emp.admission_date:
        months_tenure = (now.year - emp.admission_date.year) * 12 + (now.month - emp.admission_date.month)

    # --- LOGIC BY TRIGGER TYPE ---
    
    if achievement.trigger_type == "auto_production":
        # Check cumulative_kg
        if "cumulative_kg" in rules:
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

        # Check min_routes (Milestone: First Separation, 100th route, etc)
        if "min_routes" in rules:
            count = session.exec(select(func.count(Route.id)).where(
                Route.employee_id == employee_id,
                Route.status == "completed"
            )).one() or 0
            if count >= rules["min_routes"]:
                is_triggered = True

    elif achievement.trigger_type == "auto_tenure":
        if "months" in rules:
            if months_tenure >= rules["months"]:
                is_triggered = True

    elif achievement.trigger_type == "auto_health":
        # Days without certificates
        if "days_without_certificate" in rules:
            days = rules["days_without_certificate"]
            limit_date = now - timedelta(days=days)
            
            # 2026 RESET RULE
            reset_date = datetime(2026, 1, 1, tzinfo=ZoneInfo("America/Sao_Paulo"))
            if limit_date < reset_date:
                return False # Not enough time passed in 2026 yet

            # Check for 'atestado' events in this period
            exists = session.exec(select(Event).where(
                Event.employee_id == employee_id,
                Event.type == "atestado",
                Event.timestamp >= limit_date
            )).first()
            
            # Verify admission date with timezone safety
            admission_safe = emp.admission_date
            if admission_safe and admission_safe.tzinfo is None:
                admission_safe = admission_safe.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))

            # If no atestado found AND enough time passed since admission
            if not exists and admission_safe and admission_safe <= limit_date:
                is_triggered = True

    elif achievement.trigger_type == "auto_attendance":
        # Prepare admission safe (reused or created)
        admission_safe = emp.admission_date
        if admission_safe and admission_safe.tzinfo is None:
            admission_safe = admission_safe.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
            
        reset_date = datetime(2026, 1, 1, tzinfo=ZoneInfo("America/Sao_Paulo"))

        if "perfect_month" in rules:
            limit_date = now - timedelta(days=30)
            
            if limit_date < reset_date:
                return False # 2026 Reset
                
            exists = session.exec(select(Event).where(
                Event.employee_id == employee_id,
                Event.type == "falta",
                Event.timestamp >= limit_date
            )).first()
            if not exists and admission_safe and admission_safe <= limit_date:
                is_triggered = True
        
        elif "perfect_week" in rules:
            limit_date = now - timedelta(days=7)
            
            if limit_date < reset_date:
                return False # 2026 Reset
                
            exists = session.exec(select(Event).where(
                Event.employee_id == employee_id,
                Event.type == "falta",
                Event.timestamp >= limit_date
            )).first()
            if not exists and admission_safe and admission_safe <= limit_date:
                is_triggered = True

    elif achievement.trigger_type == "auto_time":
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

    return is_triggered


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

    # 3. Evaluate each achievement
    for ach in available:
        if evaluate_achievement_criteria(session, employee_id, ach):
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


def audit_and_revoke_achievements(session: Session, employee_id: int):
    """
    Audits currently earned achievements. 
    If an achievement's criteria are NO LONGER met (e.g. late sick note), it is revoked.
    """
    print(f"--- Auditing Achievements for Employee {employee_id} ---")
    emp = session.get(Employee, employee_id)
    if not emp: return

    # Get earned achievements
    earned_records = session.exec(select(EmployeeAchievement).where(
        EmployeeAchievement.employee_id == employee_id,
        EmployeeAchievement.status == "approved"
    )).all()

    revoked_count = 0

    for record in earned_records:
        ach = session.get(GameAchievement, record.achievement_id)
        if not ach or ach.trigger_type == "manual": 
            continue # Skip manual achievements, they are permanent unless manually revoked

        # Re-evaluate logic
        is_still_valid = evaluate_achievement_criteria(session, employee_id, ach)
        
        if not is_still_valid:
            print(f"   ⚠️ REVOKING: {ach.name} from {emp.name} (Criteria no longer met)")
            
            # 1. Update status to revoked
            record.status = "revoked"
            # record.revoked_at = datetime.now(...) # If column existed
            session.add(record)
            
            # 2. Deduct XP
            # Create negative transaction
            tx = GameXPTransaction(
                employee_id=employee_id,
                amount=-ach.xp_reward,
                source_type="achievement_revoke",
                status="confirmed",
                reason=f"Conquista Revogada: {ach.name} (Requisitos não atendidos)",
                created_at=datetime.now(ZoneInfo("America/Sao_Paulo")),
                confirmed_at=datetime.now(ZoneInfo("America/Sao_Paulo"))
            )
            session.add(tx)
            
            # 3. Update Employee Total XP
            emp.total_xp -= ach.xp_reward
            session.add(emp)
            
            revoked_count += 1
            
    session.commit()
    return revoked_count
