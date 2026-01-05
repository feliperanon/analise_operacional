"""
Script para atualizar configuração de setores no banco de dados
Corrige metas incorretas e remove setores que não existem mais
"""
from database import engine
from sqlmodel import Session, select
import models
import json

def update_sector_configuration():
    session = Session(engine)
    
    print("=" * 60)
    print("ATUALIZANDO CONFIGURACAO DE SETORES")
    print("=" * 60)
    
    # Buscar configuração para o turno Manhã
    config = session.exec(
        select(models.SectorConfiguration)
        .where(models.SectorConfiguration.shift_name == "Manhã")
    ).first()
    
    # Configuração correta baseada no Smart Flow atual
    # Total: 3+3+16+16+3+1+2 = 44
    correct_config = {
        "sectors": [
            {
                "key": "recebimento",
                "label": "Recebimento",
                "target": 3,
                "subsectors": ["Conferente", "Descarga", "Operador de Equipamento"]
            },
            {
                "key": "camara_fria",
                "label": "Câmara Fria",
                "target": 3,  # Corrigido: 2 → 3
                "subsectors": ["Operador de Câmara"]
            },
            {
                "key": "selecao",
                "label": "Seleção",
                "target": 16,  # Corrigido: 14 → 16
                "subsectors": ["Cebola", "UVA", "BATATA", "Mamão", "Pacote", "Balança", "Legumes"]
            },
            {
                "key": "expedicao",
                "label": "Expedição",
                "target": 16,  # Mantido: 16
                "subsectors": ["Separação", "Conferente"]
            },
            # Removido: Gerência (não existe mais)
            {
                "key": "estoque",
                "label": "Estoque",
                "target": 3,  # Corrigido: 2 → 3
                "subsectors": ["Geral"]
            },
            {
                "key": "ceasa",
                "label": "Ceasa",
                "target": 1,
                "subsectors": ["Geral"]
            },
            {
                "key": "lideranca",
                "label": "Liderança",
                "target": 2,  # Corrigido: 3 → 2
                "subsectors": ["Lider Expedição", "Lider Câmara Fria", "Lider Logística"]
            }
        ]
    }
    
    total_meta = sum(s['target'] for s in correct_config['sectors'])
    
    print(f"\n[INFO] Configuracao correta:")
    for sector in correct_config['sectors']:
        print(f"   - {sector['label']}: meta {sector['target']}")
    print(f"\n[TOTAL] Meta Total: {total_meta}")
    
    if config:
        print(f"\n[OK] Atualizando configuracao existente (ID: {config.id})")
        config.config_json = correct_config
    else:
        print(f"\n[CRIAR] Criando nova configuracao para turno 'Manha'")
        config = models.SectorConfiguration(
            shift_name="Manhã",
            config_json=correct_config
        )
        session.add(config)
    
    session.commit()
    print(f"\n[SUCESSO] Configuracao atualizada com sucesso!")
    print("=" * 60)
    
    session.close()

if __name__ == "__main__":
    update_sector_configuration()
