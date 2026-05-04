/**
 * Smart Flow Clock & Auto-Shift Logic
 * Ported from Dashboard (index.html)
 */

window.SmartFlowClock = {
    init() {
        this.updateClock();
        setInterval(() => this.updateClock(), 1000);
        
        // Auto-select shift on load based on time
        // Only if not explicitly overriding via URL (which usually sets INITIAL_DATA or similar)
        // But for this request, "turno selecionado automaticamente" implies we enforce it or default it.
        // We will default to the current shift if the current selected shift doesn't match the time-based shift
        // AND we want to be helpful. 
        // For now, let's just make sure the visual indicator matches.
        // If the user wants the DATA to change, we call changeShift.
        
        // Let's call changeShift to the calculated shift on load, 
        // preventing mismatch between "Real Time" and "Displayed Data".
        // Use a flag to avoid checking URL params if we want strict enforcement.
        // However, standard behavior is: URL param > Auto. 
        // But the prompt implies "use the same logic... automatically".
        // I will attempt to detect the right shift and switch to it if not already set.
        
        this.autoSelectShift();
    },

    /** Manhã 07:00–17:00 | Tarde 17:01–19:00 | Noite 19:01–06:59 */
    getCurrentShift(hour, minute) {
        const c = hour * 60 + minute;
        if (c >= 19 * 60 + 1 || c < 7 * 60) {
            return { name: 'Noite', id: 'Noite', color: 'purple', startH: 19, startM: 1, endH: 6, endM: 59 };
        }
        if (c >= 17 * 60 + 1) {
            return { name: 'Tarde', id: 'Tarde', color: 'orange', startH: 17, startM: 1, endH: 19, endM: 0 };
        }
        return { name: 'Manhã', id: 'Manhã', color: 'blue', startH: 7, startM: 0, endH: 17, endM: 0 };
    },

    getShiftProgress(hour, minute) {
        const c = hour * 60 + minute;
        if (c >= 19 * 60 + 1 || c < 7 * 60) {
            const el = c >= 19 * 60 + 1 ? c - (19 * 60 + 1) : (1440 - (19 * 60 + 1)) + c;
            return Math.min(100, Math.max(0, (el / 719) * 100));
        }
        if (c >= 17 * 60 + 1) {
            return Math.min(100, Math.max(0, ((c - (17 * 60 + 1)) / 120) * 100));
        }
        return Math.min(100, Math.max(0, ((c - 7 * 60) / 600) * 100));
    },

    updateClock() {
        const now = new Date();
        const hours = now.getHours();
        const minutes = now.getMinutes();
        
        const timeStr = String(hours).padStart(2, '0') + ':' + String(minutes).padStart(2, '0');
        
        const timeEl = document.getElementById('dash-time');
        if (timeEl) timeEl.textContent = timeStr;
        
        const days = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sab'];
        const dateStr = days[now.getDay()] + ', ' + now.getDate() + '/' + String(now.getMonth() + 1).padStart(2, '0');
        
        const dateEl = document.getElementById('dash-date');
        if (dateEl) dateEl.textContent = dateStr;
        
        const shift = this.getCurrentShift(hours, minutes);
        const shiftNameEl = document.getElementById('dash-shift-name');
        const shiftBarEl = document.getElementById('dash-shift-bar');
        
        if (shiftNameEl) {
            shiftNameEl.textContent = 'Turno ' + shift.name;
            const colorClasses = {
                blue: 'text-[10px] font-bold uppercase tracking-wide text-blue-600 dark:text-blue-400',
                orange: 'text-[10px] font-bold uppercase tracking-wide text-orange-600 dark:text-orange-400',
                purple: 'text-[10px] font-bold uppercase tracking-wide text-purple-600 dark:text-purple-400'
            };
            shiftNameEl.className = colorClasses[shift.color] || 'text-[10px] font-bold uppercase tracking-wide text-slate-500';
        }
        
        const progress = this.getShiftProgress(hours, minutes);
        if (shiftBarEl) {
            const barColors = {
                blue: 'bg-blue-500',
                orange: 'bg-orange-500',
                purple: 'bg-purple-500'
            };
            shiftBarEl.className = 'h-full ' + (barColors[shift.color] || 'bg-slate-500') + ' rounded-full transition-all';
            shiftBarEl.style.width = progress + '%';
        }
    },

    autoSelectShift() {
        if (window.SMART_FLOW_SKIP_AUTO_SHIFT) {
            return;
        }
        const now = new Date();
        const shift = this.getCurrentShift(now.getHours(), now.getMinutes());
        
        // Check current selected shift in Store (if available)
        // We defer this slightly to ensure Store is initialized
        setTimeout(() => {
            if (window.Store && window.Store.state) {
                const current = window.Store.state.currentShift;
                // Note: Store uses 'Manhã', 'Tarde', 'Noite' (Capitalized, accented)
                // My getCurrentShift uses 'Manhã' etc.
                
                if (current !== shift.id) {
                    console.log(`🕒 Auto-selecting shift based on time: ${current} -> ${shift.id}`);
                    if (window.changeShift) {
                        window.changeShift(shift.id, { alignNightDate: shift.id === 'Noite' });
                    }
                }
            }
        }, 500); // 500ms delay to allow Store init
    }
};

document.addEventListener('DOMContentLoaded', () => {
    window.SmartFlowClock.init();
});
