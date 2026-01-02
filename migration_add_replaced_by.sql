-- Migração: Adicionar coluna replaced_by à tabela employee
-- Data: 2026-01-02
-- Descrição: Adiciona rastreamento de substituição de colaboradores

ALTER TABLE employee 
ADD COLUMN replaced_by INTEGER;

-- Adicionar foreign key constraint
ALTER TABLE employee
ADD CONSTRAINT fk_employee_replaced_by 
FOREIGN KEY (replaced_by) REFERENCES employee(id);

-- Comentário para documentação
COMMENT ON COLUMN employee.replaced_by IS 'ID do colaborador que substituiu este colaborador';
