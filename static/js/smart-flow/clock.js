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

    isWithinShift(hour, minute, startH, startM, endH, endM) {
        const current = hour * 60 + minute;
        const start = startH * 60 + startM;
        const end = endH * 60 + endM;
        if (start < end) {
            return current >= start && current < end;
        }
        return current >= start || current < end;
    },

    getCurrentShift(hour, minute) {
        if (this.isWithinShift(hour, minute, 18, 0, 6, 0)) {
            return { name: 'Noite', id: 'Noite', color: 'purple', startH: 18, startM: 0, endH: 6, endM: 0 };
        }
        if (this.isWithinShift(hour, minute, 5, 0, 13, 20)) {
            return { name: 'Manhã', id: 'Manhã', color: 'blue', startH: 5, startM: 0, endH: 13, endM: 20 };
        }
        return { name: 'Tarde', id: 'Tarde', color: 'orange', startH: 12, startM: 0, endH: 20, endM: 20 };
    },

    getShiftProgress(hour, minute) {
        const shift = this.getCurrentShift(hour, minute);
        let currentMinutes = hour * 60 + minute;
        let startMinutes = shift.startH * 60 + shift.startM;
        let endMinutes = shift.endH * 60 + shift.endM;
        
        // Turno noite cruza meia-noite (18:00 - 06:00 = 12 horas)
        if (shift.name === 'Noite') {
            if (hour >= 18) {
                currentMinutes = (hour - 18) * 60 + minute;
            } else {
                currentMinutes = (hour + 6) * 60 + minute; // horas apos meia-noite + 6
            }
            startMinutes = 0;
            endMinutes = 12 * 60; // 12 horas de turno
        }
        
        const total = endMinutes - startMinutes;
        let elapsed = currentMinutes - startMinutes;
        if (elapsed < 0) elapsed = 0;
        
        return Math.min(100, Math.max(0, (elapsed / total) * 100));
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
                blue: 'text-blue-400',
                orange: 'text-orange-400',
                purple: 'text-purple-400'
            };
            // Reset classes
            shiftNameEl.className = 'text-sm font-bold ' + (colorClasses[shift.color] || 'text-slate-400');
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
                        window.changeShift(shift.id);
                    }
                }
            }
        }, 500); // 500ms delay to allow Store init
    }
};

document.addEventListener('DOMContentLoaded', () => {
    window.SmartFlowClock.init();
});
