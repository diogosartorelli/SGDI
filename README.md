# SGDI - Sistema de Gestão de Demandas Internas

Sistema para gerenciar demandas internas da empresa.

## Como rodar

```bash
pip install -r requirements.txt
python init_db.py
python app.py
```

O nome que aparece no cabeçalho dos relatórios fica em `NOME_EMPRESA` no `app.py`
(ou na variável de ambiente `NOME_EMPRESA`).

## Testes

```bash
python -m unittest test_sgdi -v
```

Usam um banco temporário: o seu `demandas.db` não é tocado.

Acesse: http://localhost:5000

## Funcionalidades

- Criar demandas
- Editar demandas
- Deletar demandas
- Visualizar detalhes
- Comentários
- Prazo por demanda (com destaque de atrasadas)
- Painel de KPIs em `/painel`: total, abertas/concluídas/atrasadas/canceladas (com %), demandas críticas, demandas por responsável e tempo médio de resolução
- Gráficos no painel: por status, por prioridade e evolução no tempo (criadas x concluídas), desenhados em SVG puro, sem biblioteca externa
- Filtros combinados (período, responsável, prioridade e status) no painel e na lista; o painel atualiza sem recarregar a página (e a cada 30 s)
- **Visão "Críticas + atrasadas"** (pedido da diretoria): bloco em destaque no topo do painel e filtro `Visão` (`?visao=criticas_atrasadas`) no painel e na lista. A exportação (PDF/Excel/CSV) respeita esse filtro e traz só esses casos, com o título "Relatório de Demandas Críticas Atrasadas"
- Status `Cancelada`
- Exportação do relatório em **PDF, Excel (.xlsx) e CSV** pelos botões do painel (ou direto em `/exportar/pdf`, `/exportar/xlsx`, `/exportar/csv`). O relatório respeita os mesmos filtros do painel, tem **cabeçalho com nome da empresa e data de geração** e **rodapé com os filtros aplicados** (ex.: `Gerado com: Prioridade Alta · Jan–Mar 2025`). No PDF o cabeçalho e o rodapé se repetem em todas as páginas, com "Página X de Y"; no Excel eles também vão para o cabeçalho/rodapé de impressão.

### Regras de negócio do painel

- **Abertas** = Aberta + Em andamento. Concluída e Cancelada não contam como abertas.
- **Atrasadas** = abertas com prazo vencido; aparecem em vermelho (painel e lista). Cancelada nunca é atrasada.
- **Críticas** = prioridade Alta ainda aberta.
- **Tempo médio de resolução** = dias entre criação e conclusão, só das Concluídas (Canceladas ficam fora). É uma média ponderada: críticas pesam 2x (`PESO_CRITICA` em `app.py`).
- Todo responsável é obrigatório, então não existe demanda sem responsável.

---

**TODO:**
- Adicionar prioridades
- Melhorar busca
- Adicionar usuários

---

*Desenvolvido em 2024*