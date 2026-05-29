import json
from datetime import datetime

from sqlmodel import Session, select

from database import engine
from models import Employee


def _serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def main():
    with Session(engine) as db:
        employees = db.exec(select(Employee)).all()
        data = []
        for emp in employees:
            row = {}
            for column in emp.__table__.columns:
                row[column.name] = _serialize(getattr(emp, column.name))
            data.append(row)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_employees_{stamp}.json"
    with open(filename, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)

    print(f"Backup concluido: {len(data)} colaboradores salvos em {filename}")


if __name__ == "__main__":
    main()
