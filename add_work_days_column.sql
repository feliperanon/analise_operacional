-- Adicionar coluna work_days à tabela employee
ALTER TABLE employee ADD COLUMN work_days TEXT DEFAULT '["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]';

-- Atualizar colaboradores existentes que não têm work_days
UPDATE employee 
SET work_days = '["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]'
WHERE work_days IS NULL OR work_days = '';
