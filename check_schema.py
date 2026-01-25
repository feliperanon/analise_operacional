from database import engine
from sqlalchemy import inspect

def check_columns():
    inspector = inspect(engine)
    columns = inspector.get_columns('equipmentticket')
    print("Columns in EquipmentTicket:")
    for c in columns:
        print(f"- {c['name']}")

    print("\nColumns in TranspalletChecklist:")
    columns = inspector.get_columns('transpalletchecklist')
    for c in columns:
        print(f"- {c['name']}")

if __name__ == "__main__":
    check_columns()
