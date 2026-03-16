// Main game logic
class Game {
    constructor() {
        this.pet = new Pet();
        this.setupUI();
        this.setupButtons();
        this.startUIUpdates();
    }
    
    setupUI() {
        this.elements = {
            time: document.getElementById('time'),
            happinessBar: document.getElementById('happinessBar'),
            hungerBar: document.getElementById('hungerBar'),
            energyBar: document.getElementById('energyBar'),
            healthBar: document.getElementById('healthBar'),
            happinessValue: document.getElementById('happinessValue'),
            hungerValue: document.getElementById('hungerValue'),
            energyValue: document.getElementById('energyValue'),
            healthValue: document.getElementById('healthValue'),
            petName: document.getElementById('petName'),
            petAge: document.getElementById('petAge'),
            petMood: document.getElementById('petMood'),
            message: document.getElementById('message'),
            statMeals: document.getElementById('statMeals'),
            statGames: document.getElementById('statGames'),
            statCleans: document.getElementById('statCleans'),
            statHeals: document.getElementById('statHeals'),
            statBirth: document.getElementById('statBirth')
        };
    }
    
    setupButtons() {
        document.getElementById('feedBtn').addEventListener('click', () => {
            this.showMessage(this.pet.feed());
        });
        
        document.getElementById('playBtn').addEventListener('click', () => {
            this.showMessage(this.pet.play());
        });
        
        document.getElementById('sleepBtn').addEventListener('click', () => {
            this.showMessage(this.pet.sleep());
        });
        
        document.getElementById('cleanBtn').addEventListener('click', () => {
            this.showMessage(this.pet.clean());
        });
        
        document.getElementById('healBtn').addEventListener('click', () => {
            this.showMessage(this.pet.heal());
        });
    }
    
    updateUI() {
        // Update time
        const now = new Date();
        this.elements.time.textContent = now.toLocaleTimeString();
        
        // Update status bars
        this.updateBar(this.elements.happinessBar, this.elements.happinessValue, this.pet.happiness);
        this.updateBar(this.elements.hungerBar, this.elements.hungerValue, this.pet.hunger);
        this.updateBar(this.elements.energyBar, this.elements.energyValue, this.pet.energy);
        this.updateBar(this.elements.healthBar, this.elements.healthValue, this.pet.health);
        
        // Update pet info
        this.elements.petAge.textContent = this.pet.age;
        this.elements.petMood.textContent = this.pet.getMood();
        
        // Update statistics
        this.elements.statMeals.textContent = this.pet.stats.meals;
        this.elements.statGames.textContent = this.pet.stats.games;
        this.elements.statCleans.textContent = this.pet.stats.cleans;
        this.elements.statHeals.textContent = this.pet.stats.heals;
        this.elements.statBirth.textContent = this.pet.stats.birthDate.toLocaleDateString();
    }
    
    updateBar(barElement, valueElement, value) {
        const rounded = Math.round(value);
        barElement.style.width = rounded + '%';
        valueElement.textContent = rounded;
    }
    
    showMessage(text) {
        this.elements.message.textContent = text;
        this.elements.message.classList.add('show');
        
        setTimeout(() => {
            this.elements.message.classList.remove('show');
        }, 3000);
    }
    
    startUIUpdates() {
        // Update UI every second
        setInterval(() => {
            this.updateUI();
        }, 1000);
        
        // Initial update
        this.updateUI();
    }
}

// Start the game when page loads
window.addEventListener('DOMContentLoaded', () => {
    new Game();
});
