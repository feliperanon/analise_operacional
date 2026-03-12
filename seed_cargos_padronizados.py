#!/usr/bin/env python3
"""
Script para popular CargoMaster com a lista padronizada de cargos e atualizar
os colaboradores (Employee.role) conforme as equivalências.
Execute: python seed_cargos_padronizados.py
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from database import engine, create_db_and_tables
from sqlmodel import Session, select
import models

# Lista padronizada: (nome, salario_base) - usar sempre o maior quando havia variação
CARGOS_PADRAO = [
    ("AJUDANTE", None),
    ("AJUDANTE DE MOTORISTA", 1720.93),
    ("AJUDANTE DE PÁTIO", 1720.93),
    ("ANALISTA DE LOGÍSTICA", 2524.02),
    ("ANALISTA DE RESULTADOS", 2621.00),
    ("APRENDIZ EM LOGÍSTICA", 761.55),
    ("ASSISTENTE ADMINISTRATIVO", 2007.75),
    ("ASSISTENTE DE LOGÍSTICA", None),
    ("ASSISTENTE FINANCEIRO", 2224.80),
    ("AUXILIAR ADMINISTRATIVO", 1473.00),
    ("AUXILIAR DE LOGÍSTICA", None),
    ("AUXILIAR DE SERVIÇOS GERAIS", 1720.93),
    ("AUXILIAR FINANCEIRO", 2012.85),
    ("CANAL", None),
    ("CONFERENTE", 1979.06),
    ("COORDENADOR DE LOGÍSTICA", 2224.37),
    ("COORDENADOR DE VENDAS ESPECIALIZADO", 2188.28),
    ("COORDENADOR DE VDI", 1866.78),
    ("ENCARREGADO DE OFICINA", 1964.31),
    ("ENCARREGADO DE VENDAS DO AUTO SERVIÇO", None),
    ("GERENTE DE LOGÍSTICA", 4056.82),
    ("GERENTE DE VENDAS SÊNIOR", 7658.98),
    ("JOVEM APRENDIZ", 761.55),
    ("MOTORISTA", 2244.96),
    ("MOTORISTA DE PUXADA", 2244.96),
    ("OPERADOR DE EMPILHADEIRA", 1957.08),
    ("OPERADOR LOGÍSTICO", 2426.07),
    ("PORTEIRO", 1720.93),
    ("RECEPCIONISTA", 1544.70),
    ("REPOSITOR DE MERCADORIAS", 1628.63),
    ("SÓCIO", None),
    ("SUPERVISOR COMERCIAL", 5645.92),
    ("SUPERVISOR DE CARGA", 3831.84),
    ("SUPERVISOR DE CONTAS", None),
    ("SUPERVISOR DE VENDAS", 1961.05),
    ("SUPERVISORA ADMINISTRATIVA", 2600.00),
    ("VENDEDOR", None),
    ("VENDEDOR INTERNO", 1628.63),
]

# Mapeamento: role original (normalizado para match) -> role padrão
# Usamos .strip().upper() para comparar
EQUIVALENCIAS = {
    "AJUD. DE PÁTIO": "AJUDANTE DE PÁTIO",
    "AJUDANTE DE PÁTIO": "AJUDANTE DE PÁTIO",
    "AUX. SERV. GERAIS": "AUXILIAR DE SERVIÇOS GERAIS",
    "AUX.DE SERVIÇOS GERAIS": "AUXILIAR DE SERVIÇOS GERAIS",
    "AUXILIAR DE SERVIÇOS GERAIS": "AUXILIAR DE SERVIÇOS GERAIS",
    "COORDENADOR DE LOGISTICA": "COORDENADOR DE LOGÍSTICA",
    "ENC. OFICINA": "ENCARREGADO DE OFICINA",
    "ENCARREGADO DE OFICINA": "ENCARREGADO DE OFICINA",
    "GERENTE DE OP. E LOG.": "GERENTE DE LOGÍSTICA",
    "GERENTE DE LOGISTICA": "GERENTE DE LOGÍSTICA",
    "MOT. DE PUXADA": "MOTORISTA DE PUXADA",
    "OP. EMPILHADEIRA": "OPERADOR DE EMPILHADEIRA",
    "OPERADOR DE EMPILHADEIRA": "OPERADOR DE EMPILHADEIRA",
    "REPOSITORA DE MERCADORIAS": "REPOSITOR DE MERCADORIAS",
    "SUP. DE CARGA": "SUPERVISOR DE CARGA",
    "SUPERVISOR DE CARGA": "SUPERVISOR DE CARGA",
    "SUPEVISOR DE CONTAS": "SUPERVISOR DE CONTAS",
    "SUPERVISOR DE CONTAS": "SUPERVISOR DE CONTAS",
    "SUPERVISORA ADMINISTRATIVO": "SUPERVISORA ADMINISTRATIVA",
    "VENDEDOR INTERNO": "VENDEDOR INTERNO",
    "APRENDIZ DE LOGÍSTICA": "APRENDIZ EM LOGÍSTICA",
    "JOVEM APRENDIZ": "JOVEM APRENDIZ",
    "ASSISTENTE DE LOGISTICA": "ASSISTENTE DE LOGÍSTICA",
    "AUXILIAR DE LOGISTICA": "AUXILIAR DE LOGÍSTICA",
    "COORDENADOR DE LOGISTICA": "COORDENADOR DE LOGÍSTICA",
    "AUX. DE SERVIÇOS GERAIS": "AUXILIAR DE SERVIÇOS GERAIS",
    "AJUD. DE PATIO": "AJUDANTE DE PÁTIO",
    "AJUDANTE DE PATIO": "AJUDANTE DE PÁTIO",
}


def _normalize(s: str) -> str:
    """Remove acentos para comparação."""
    import unicodedata
    if not s:
        return ""
    n = (s or "").strip().upper()
    return "".join(c for c in unicodedata.normalize("NFD", n) if unicodedata.category(c) != "Mn")


def build_equiv_map():
    """Retorna mapa normalizado -> padrão para match flexível."""
    out = {}
    for orig, padrao in EQUIVALENCIAS.items():
        key = _normalize(orig)
        out[key] = padrao
    # Incluir os cargos padrão como identidade
    for nome, _ in CARGOS_PADRAO:
        key = _normalize(nome)
        if key not in out:
            out[key] = nome
    return out


def main():
    create_db_and_tables()
    equiv_map = build_equiv_map()

    with Session(engine) as sess:
        # 1. Popular/atualizar CargoMaster
        existentes = {c.nome: c for c in sess.exec(select(models.CargoMaster)).all()}
        for nome, sal in CARGOS_PADRAO:
            if nome in existentes:
                c = existentes[nome]
                if sal is not None and (c.salario_base is None or c.salario_base < sal):
                    c.salario_base = sal
                    sess.add(c)
            else:
                sess.add(models.CargoMaster(nome=nome, salario_base=sal))
        sess.commit()
        print(f"[OK] CargoMaster: {len(CARGOS_PADRAO)} cargos")

        # 2. Atualizar Employee.role
        employees = sess.exec(select(models.Employee).where(models.Employee.replaced_by.is_(None))).all()
        updated = 0
        for emp in employees:
            r = (emp.role or "").strip()
            if not r:
                continue
            r_norm = _normalize(r)
            novo = equiv_map.get(r_norm)
            if novo and novo != r:
                emp.role = novo
                sess.add(emp)
                updated += 1
                print(f"  {r} -> {novo}")
        sess.commit()
        print(f"[OK] Colaboradores atualizados: {updated} de {len(employees)}")

    print("Concluído.")


if __name__ == "__main__":
    main()
