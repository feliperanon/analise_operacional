feat(mobile): implementação completa de UX mobile-first (bottom-sheet, accordion)

- Refatoração de Layout:
  - Sidebar oculta em dispositivos móveis (< md).
  - Header responsivo (empilhado em mobile, linha em desktop).
  - Remoção de altura fixa (`h-screen`) para permitir scroll nativo.

- Novas Funcionalidades:
  - **Bottom Sheet**: Substitui interações de modal para gestão de colaboradores.
  - **Accordion**: Listas de sub-setores agora são expansíveis/colapsáveis.
  - **Atividades**: Rastreamento de tempo (start/end) e campo de observação.

- Fixes:
  - Correção de renderização HTML em `sector-management.js` (tags malformadas).
  - Ajuste de z-index do modal de gestão.

- Chore:
  - Limpeza de scripts de debug temporários.
  - Atualização de documentação (README, PARECER_TECNICO).
