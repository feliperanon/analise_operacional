// Pet class to manage the Tamagotchi
class Pet {
    constructor() {
        this.canvas = document.getElementById('petCanvas');
        this.ctx = this.canvas.getContext('2d');
        
        // Scale for pixel art
        this.scale = 4;
        
        // Pet stats
        this.happiness = 100;
        this.hunger = 100;
        this.energy = 100;
        this.health = 100;
        this.age = 0;
        this.isDirty = false;
        this.isSleeping = false;
        
        // Animation
        this.frame = 0;
        this.animationSpeed = 0;
        
        // Statistics
        this.stats = {
            meals: 0,
            games: 0,
            cleans: 0,
            heals: 0,
            birthDate: new Date()
        };
        
        // Load saved data
        this.load();
        
        // Start updates
        this.startUpdates();
    }
    
    // Draw pixelated pet
    draw() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.imageSmoothingEnabled = false;
        
        // Center position
        const centerX = 8;
        const centerY = 8;
        
        // Bounce animation when awake
        let bounceOffset = 0;
        if (!this.isSleeping) {
            bounceOffset = Math.sin(this.frame * 0.1) * 1;
        }
        
        // Draw body (egg shape)
        this.drawPixel(centerX, centerY - 4 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 1, centerY - 3 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 1, centerY - 3 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 2, centerY - 2 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 1, centerY - 2 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX, centerY - 2 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 1, centerY - 2 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 2, centerY - 2 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 2, centerY - 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 1, centerY - 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX, centerY - 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 1, centerY - 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 2, centerY - 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 2, centerY + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 1, centerY + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX, centerY + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 1, centerY + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 2, centerY + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 2, centerY + 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 1, centerY + 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX, centerY + 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 1, centerY + 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 2, centerY + 1 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX - 1, centerY + 2 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX, centerY + 2 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX + 1, centerY + 2 + bounceOffset, this.getBodyColor());
        this.drawPixel(centerX, centerY + 3 + bounceOffset, this.getBodyColor());
        
        // Draw eyes
        if (this.isSleeping) {
            // Closed eyes (horizontal lines)
            this.drawPixel(centerX - 2, centerY - 1 + bounceOffset, '#000000');
            this.drawPixel(centerX + 2, centerY - 1 + bounceOffset, '#000000');
        } else {
            // Open eyes
            const eyeColor = this.health < 30 ? '#666666' : '#000000';
            this.drawPixel(centerX - 2, centerY - 1 + bounceOffset, eyeColor);
            this.drawPixel(centerX + 2, centerY - 1 + bounceOffset, eyeColor);
        }
        
        // Draw mouth based on happiness
        if (this.happiness > 60) {
            // Happy smile
            this.drawPixel(centerX - 1, centerY + 1 + bounceOffset, '#000000');
            this.drawPixel(centerX + 1, centerY + 1 + bounceOffset, '#000000');
            this.drawPixel(centerX, centerY + 2 + bounceOffset, '#000000');
        } else if (this.happiness > 30) {
            // Neutral
            this.drawPixel(centerX - 1, centerY + 1 + bounceOffset, '#000000');
            this.drawPixel(centerX, centerY + 1 + bounceOffset, '#000000');
            this.drawPixel(centerX + 1, centerY + 1 + bounceOffset, '#000000');
        } else {
            // Sad
            this.drawPixel(centerX, centerY + 1 + bounceOffset, '#000000');
            this.drawPixel(centerX - 1, centerY + 2 + bounceOffset, '#000000');
            this.drawPixel(centerX + 1, centerY + 2 + bounceOffset, '#000000');
        }
        
        // Draw dirt if dirty
        if (this.isDirty) {
            this.drawPixel(centerX - 3, centerY + 2 + bounceOffset, '#8B4513');
            this.drawPixel(centerX + 3, centerY + 2 + bounceOffset, '#8B4513');
            this.drawPixel(centerX - 2, centerY + 3 + bounceOffset, '#8B4513');
        }
        
        // Draw sleep Z's if sleeping
        if (this.isSleeping) {
            this.drawPixel(centerX + 4, centerY - 5, '#4a4a4a');
            this.drawPixel(centerX + 5, centerY - 6, '#4a4a4a');
            this.drawPixel(centerX + 6, centerY - 7, '#4a4a4a');
        }
        
        this.frame++;
    }
    
    drawPixel(x, y, color) {
        this.ctx.fillStyle = color;
        this.ctx.fillRect(x * this.scale, y * this.scale, this.scale, this.scale);
    }
    
    getBodyColor() {
        if (this.health < 30) return '#cccccc'; // Gray when sick
        if (this.happiness < 30) return '#9999ff'; // Blue when sad
        return '#ffb3d9'; // Pink when happy/healthy
    }
    
    // Update stats over time
    updateStats() {
        if (!this.isSleeping) {
            this.hunger = Math.max(0, this.hunger - 0.5);
            this.happiness = Math.max(0, this.happiness - 0.3);
            this.energy = Math.max(0, this.energy - 0.2);
        } else {
            this.energy = Math.min(100, this.energy + 1);
        }
        
        // Health depends on other stats
        if (this.hunger < 30 || this.happiness < 30 || this.energy < 20) {
            this.health = Math.max(0, this.health - 0.3);
        } else if (this.hunger > 70 && this.happiness > 70 && this.energy > 50) {
            this.health = Math.min(100, this.health + 0.1);
        }
        
        // Random chance of getting dirty
        if (Math.random() < 0.001 && !this.isDirty) {
            this.isDirty = true;
            this.happiness = Math.max(0, this.happiness - 10);
        }
        
        // Age increases every 24 hours of real time
        const daysPassed = Math.floor((Date.now() - this.stats.birthDate.getTime()) / (1000 * 60 * 60 * 24));
        this.age = daysPassed;
        
        this.save();
    }
    
    // Actions
    feed() {
        if (this.hunger >= 95) {
            return "I'm already full!";
        }
        this.hunger = Math.min(100, this.hunger + 25);
        this.happiness = Math.min(100, this.happiness + 5);
        this.stats.meals++;
        this.save();
        return "Yum! That was delicious!";
    }
    
    play() {
        if (this.energy < 20) {
            return "I'm too tired to play...";
        }
        if (this.isSleeping) {
            return "Zzz... I'm sleeping!";
        }
        this.happiness = Math.min(100, this.happiness + 20);
        this.energy = Math.max(0, this.energy - 15);
        this.hunger = Math.max(0, this.hunger - 10);
        this.stats.games++;
        this.save();
        return "That was fun! 🎮";
    }
    
    sleep() {
        if (this.isSleeping) {
            this.isSleeping = false;
            return "I'm awake now!";
        } else {
            this.isSleeping = true;
            return "Going to sleep... Zzz...";
        }
    }
    
    clean() {
        if (!this.isDirty) {
            return "I'm already clean!";
        }
        this.isDirty = false;
        this.happiness = Math.min(100, this.happiness + 15);
        this.health = Math.min(100, this.health + 5);
        this.stats.cleans++;
        this.save();
        return "Sparkle and shine! ✨";
    }
    
    heal() {
        if (this.health >= 95) {
            return "I'm already healthy!";
        }
        this.health = Math.min(100, this.health + 30);
        this.stats.heals++;
        this.save();
        return "Feeling better now! 💊";
    }
    
    getMood() {
        const avgStats = (this.happiness + this.hunger + this.energy + this.health) / 4;
        
        if (this.health < 30) return "😷 Sick";
        if (this.isSleeping) return "😴 Sleeping";
        if (avgStats >= 80) return "😊 Happy";
        if (avgStats >= 60) return "🙂 Content";
        if (avgStats >= 40) return "😐 Okay";
        if (avgStats >= 20) return "😟 Unhappy";
        return "😢 Critical";
    }
    
    // Start periodic updates
    startUpdates() {
        // Update stats every 5 seconds
        setInterval(() => {
            this.updateStats();
        }, 5000);
        
        // Draw animation loop
        const animate = () => {
            this.draw();
            requestAnimationFrame(animate);
        };
        animate();
    }
    
    // Save/Load
    save() {
        const data = {
            happiness: this.happiness,
            hunger: this.hunger,
            energy: this.energy,
            health: this.health,
            age: this.age,
            isDirty: this.isDirty,
            isSleeping: this.isSleeping,
            stats: this.stats
        };
        localStorage.setItem('tamagotchi', JSON.stringify(data));
    }
    
    load() {
        const saved = localStorage.getItem('tamagotchi');
        if (saved) {
            const data = JSON.parse(saved);
            this.happiness = data.happiness || 100;
            this.hunger = data.hunger || 100;
            this.energy = data.energy || 100;
            this.health = data.health || 100;
            this.age = data.age || 0;
            this.isDirty = data.isDirty || false;
            this.isSleeping = data.isSleeping || false;
            if (data.stats) {
                this.stats = {
                    ...data.stats,
                    birthDate: new Date(data.stats.birthDate)
                };
            }
        }
    }
}
