from main import get_session, models
from sqlmodel import select

session = next(get_session())
employees = session.exec(select(models.Employee)).all()

names = {}
for e in employees:
    if e.name in names:
        names[e.name].append(e.id)
    else:
        names[e.name] = [e.id]

found = False
for name, ids in names.items():
    if len(ids) > 1:
        print(f"DUPLICATE FOUND: {name} -> IDs: {ids}")
        found = True

if not found:
    print("No duplicates found.")
