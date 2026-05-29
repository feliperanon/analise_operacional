import os
from collections import defaultdict
from sqlmodel import Session, select
from database import engine
from models import Employee

print("=" * 60)
print("ACTIVE_DATABASE_SOURCE:", os.environ.get("ACTIVE_DATABASE_SOURCE"))
print("ACTIVE_DATABASE_URL_SOURCE:", os.environ.get("ACTIVE_DATABASE_URL_SOURCE"))
try:
    url = engine.url
    safe = f"{url.drivername}://{url.username}@{url.host}:{url.port}/{url.database}"
    print("ENGINE URL:", safe)
except Exception as e:
    print("ENGINE URL: (erro)", e)
print("=" * 60)

with Session(engine) as db:
    emps = db.exec(select(Employee)).all()
    print(f"TOTAL colaboradores: {len(emps)}")

    # Quantos com sufixo .0
    dot = [e for e in emps if (e.registration_id and str(e.registration_id).endswith(".0")) or (e.seller_code and str(e.seller_code).endswith(".0"))]
    print(f"Com sufixo .0 (reg ou seller): {len(dot)}")

    # Duplicados por nome
    groups = defaultdict(list)
    for e in emps:
        if e.name:
            key = " ".join(e.name.strip().upper().split())
            groups[key].append(e)
    dups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"Grupos de nomes duplicados: {len(dups)}")
    for k, v in list(dups.items())[:10]:
        ids = [(e.id, e.registration_id) for e in v]
        print(f"  {k}: {ids}")
