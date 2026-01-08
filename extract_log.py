
import os

def extract():
    try:
        with open('logs.txt', 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            last_lines = lines[-100:]
            
        with open('last_error.txt', 'w', encoding='utf-8') as out:
            out.writelines(last_lines)
            
        print("Success")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    extract()
