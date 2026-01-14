# PROMPT – SISTEMA DE GAMIFICAÇÃO OPERACIONAL COM CONTROLE GERENCIAL

Quero desenvolver um sistema de gamificação operacional corporativa, focado em produtividade, eficiência e constância, aplicado a equipes de operação (expedição/separação/logística).

O sistema não é um jogo lúdico, mas um mecanismo de gestão comportamental, onde métricas reais de operação geram XP, níveis e conquistas, sempre com governança e validação humana.

## 🎯 Objetivo principal
Transformar rotinas operacionais em um sistema de progressão profissional, onde:
- o colaborador evolui por mérito e constância
- o gestor mantém controle total sobre liberações e correções
- métricas não são manipuláveis nem injustas

## 🧠 Conceito central
O sistema mede três pilares simultaneamente:
1. **Entrega** (tonelagem / volume)
2. **Eficiência** (tempo / produtividade por hora)
3. **Tempo de casa** (maturidade)

Nenhum pilar isolado gera progressão máxima.

### ⚙️ Métrica base
- **Unidade Operacional (UO)**: UO = tonelagem ÷ 1.500 kg
- **Eficiência (UO/h)**: UO/h = UO ÷ horas efetivas da operação

Essas métricas geram XP automático diário.

## 🎮 XP e Progressão
XP é calculado automaticamente com base em UO e UO/h
- **XP diário** nasce com status **PROVISÓRIO**
- No dia seguinte, o XP é **CONFIRMADO**, salvo se houver ajuste do gestor

O gestor pode:
- creditar ou debitar XP
- sempre com motivo obrigatório
- sempre com registro em auditoria

## 🧱 Níveis (carreira)
Total de 20 níveis
Trava por tempo de casa:
- até 6 meses → nível máximo 10
- de 6 a 12 meses → progressão parcial
- acima de 12 meses → nível máximo 20

XP nunca é perdido; fica em banco aguardando liberação por tempo.

## 🏆 Conquistas (Achievements)
Existem conquistas automáticas candidatas, mas:
- nenhuma conquista aparece ao colaborador sem aprovação do gestor
- o sistema apenas sugere conquistas quando regras são atingidas

Tipos de conquistas:
- presença (dias sem falta / atestado)
- volume acumulado (tonelagem)
- eficiência sustentada (UO/h acima do padrão)
- carreira (tempo de empresa)

O colaborador visualiza:
- últimas 3 conquistas no cabeçalho
- lista completa em modal
- conquistas “em progresso” mostrando exatamente o que falta
- conquistas bloqueadas por tempo de casa

## 👑 Papel do gestor (controle total)
Existe uma página externa exclusiva do gestor, com autenticação forte, onde ele pode:
- visualizar resumo diário da operação
- ver rankings positivos (eficiência e evolução)
- aprovar ou reprovar conquistas sugeridas
- lançar ajustes de XP (crédito/débito)
- consultar histórico completo de cada colaborador
- acessar auditoria de todas as ações

Nada entra no jogo sem passar por essa camada de controle.

## 📊 Princípios de UX
- O colaborador nunca vê ranking negativo
- Só aparecem destaques positivos (Top 5)
- Transparência sem exposição
- O jogo incentiva melhoria contínua, não competição tóxica

## 🧾 Governança e auditoria
Todo evento relevante gera log:
- cálculo automático de XP
- ajuste manual (quem, quando, por quê)
- concessão de conquista
- alteração de regras

O sistema deve ser defensável, confiável e rastreável.
