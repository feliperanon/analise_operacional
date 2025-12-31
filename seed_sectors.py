"""
Script para popular setores e sub-setores iniciais no Smart Flow
"""
from database import get_session
from models import Sector, SubSector
from sqlmodel import select

def seed_sectors():
    """Cria setores e sub-setores padrão para cada turno"""
    
    session = next(get_session())
    
    turnos = ["Manhã", "Tarde", "Noite"]
    
    for turno in turnos:
        # Verificar se já existem setores para este turno
        existing = session.exec(select(Sector).where(Sector.shift == turno)).first()
        if existing:
            print(f"Setores já existem para o turno {turno}, pulando...")
            continue
        
        print(f"Criando setores para o turno {turno}...")
        
        # 1. Recebimento
        recebimento = Sector(
            name="Recebimento",
            shift=turno,
            max_employees=10,
            color="blue",
            order=1
        )
        session.add(recebimento)
        session.flush()  # Para obter o ID
        
        session.add(SubSector(sector_id=recebimento.id, name="Doca 1", max_employees=3, order=1))
        session.add(SubSector(sector_id=recebimento.id, name="Doca 2", max_employees=3, order=2))
        session.add(SubSector(sector_id=recebimento.id, name="Paletização", max_employees=4, order=3))
        
        # 2. Câmara Fria
        camara = Sector(
            name="Câmara Fria",
            shift=turno,
            max_employees=8,
            color="purple",
            order=2
        )
        session.add(camara)
        session.flush()
        
        session.add(SubSector(sector_id=camara.id, name="Armazenagem", max_employees=4, order=1))
        session.add(SubSector(sector_id=camara.id, name="Abastecimento", max_employees=4, order=2))
        
        # 3. Seleção
        selecao = Sector(
            name="Seleção",
            shift=turno,
            max_employees=15,
            color="green",
            order=3
        )
        session.add(selecao)
        session.flush()
        
        session.add(SubSector(sector_id=selecao.id, name="Linha 1", max_employees=8, order=1))
        session.add(SubSector(sector_id=selecao.id, name="Linha 2", max_employees=7, order=2))
        
        # 4. Expedição
        expedicao = Sector(
            name="Expedição",
            shift=turno,
            max_employees=12,
            color="orange",
            order=4
        )
        session.add(expedicao)
        session.flush()
        
        session.add(SubSector(sector_id=expedicao.id, name="Separação", max_employees=6, order=1))
        session.add(SubSector(sector_id=expedicao.id, name="Carregamento", max_employees=6, order=2))
        
        session.commit()
        print(f"✅ Setores criados para o turno {turno}")
    
    print("\n🎉 Seed concluído com sucesso!")

if __name__ == "__main__":
    seed_sectors()
