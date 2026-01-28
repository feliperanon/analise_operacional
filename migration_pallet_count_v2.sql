-- Migration: Atualizar tabela palletcount para suportar contagem por quantidade
-- Data: 2026-01-28
-- Descrição: Adiciona campos para contagem por quantidade por setor (não por número individual)
--            e detecção de ruptura vs sumiço

-- 1. Adicionar novas colunas (se não existirem)
DO $$ 
BEGIN
    -- Adicionar coluna quantity (quantidade de paleteiras no setor)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'palletcount' AND column_name = 'quantity') THEN
        ALTER TABLE palletcount ADD COLUMN quantity INTEGER DEFAULT 0;
    END IF;
    
    -- Adicionar coluna previous_quantity (quantidade do dia anterior)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'palletcount' AND column_name = 'previous_quantity') THEN
        ALTER TABLE palletcount ADD COLUMN previous_quantity INTEGER;
    END IF;
    
    -- Adicionar coluna quantity_difference (diferença calculada)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'palletcount' AND column_name = 'quantity_difference') THEN
        ALTER TABLE palletcount ADD COLUMN quantity_difference INTEGER DEFAULT 0;
    END IF;
    
    -- Adicionar coluna detection_type (rupture/missing/normal)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'palletcount' AND column_name = 'detection_type') THEN
        ALTER TABLE palletcount ADD COLUMN detection_type VARCHAR(20) DEFAULT 'normal';
        CREATE INDEX IF NOT EXISTS idx_palletcount_detection_type ON palletcount(detection_type);
    END IF;
    
    -- Adicionar coluna email_sent_at (para rastrear envio de e-mails)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'palletcount' AND column_name = 'email_sent_at') THEN
        ALTER TABLE palletcount ADD COLUMN email_sent_at TIMESTAMP;
    END IF;
    
    -- Adicionar coluna email_error (para rastrear erros de e-mail)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'palletcount' AND column_name = 'email_error') THEN
        ALTER TABLE palletcount ADD COLUMN email_error TEXT;
    END IF;
    
    -- Tornar pallet_number opcional (nullable) para compatibilidade com sistema antigo
    -- Mas não vamos remover, caso já existam dados
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'palletcount' AND column_name = 'pallet_number' 
               AND is_nullable = 'NO') THEN
        ALTER TABLE palletcount ALTER COLUMN pallet_number DROP NOT NULL;
    END IF;
    
    -- Garantir que sector_id não seja NULL (obrigatório no novo sistema)
    -- Primeiro, atualizar registros NULL com um setor padrão (se existir)
    UPDATE palletcount 
    SET sector_id = (SELECT id FROM palletsector WHERE is_active = TRUE LIMIT 1)
    WHERE sector_id IS NULL 
    AND EXISTS (SELECT 1 FROM palletsector WHERE is_active = TRUE);
    
    -- Depois, tornar NOT NULL (se não houver mais NULLs e a coluna for nullable)
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'palletcount' AND column_name = 'sector_id' 
               AND is_nullable = 'YES') THEN
        -- Verificar se ainda há NULLs
        PERFORM 1 FROM palletcount WHERE sector_id IS NULL LIMIT 1;
        IF NOT FOUND THEN
            ALTER TABLE palletcount ALTER COLUMN sector_id SET NOT NULL;
        END IF;
    END IF;
    
END $$;

-- 2. Atualizar valores padrão para registros existentes (se houver)
-- Se já existirem registros com pallet_number, podemos calcular quantity = 1 para cada
-- (assumindo que cada registro antigo = 1 paleteira)
UPDATE palletcount 
SET quantity = 1 
WHERE quantity = 0 
AND pallet_number IS NOT NULL 
AND pallet_number != '';

-- 3. Criar índices para melhor performance
CREATE INDEX IF NOT EXISTS idx_palletcount_date_shift_sector 
ON palletcount(date, shift, sector_id);

CREATE INDEX IF NOT EXISTS idx_palletcount_detection_type 
ON palletcount(detection_type) 
WHERE detection_type IN ('rupture', 'missing');

-- 4. Comentários nas colunas (documentação)
COMMENT ON COLUMN palletcount.quantity IS 'Quantidade de paleteiras encontradas neste setor (contagem por quantidade, não por número individual)';
COMMENT ON COLUMN palletcount.previous_quantity IS 'Quantidade do dia anterior no mesmo setor/turno (para comparação)';
COMMENT ON COLUMN palletcount.quantity_difference IS 'Diferença calculada: quantity - previous_quantity';
COMMENT ON COLUMN palletcount.detection_type IS 'Tipo de detecção: normal, rupture (movimentação entre setores), missing (sumiço real)';
COMMENT ON COLUMN palletcount.status IS 'Status: ok, shortage (faltando), surplus (a mais), first_count (primeira contagem)';
