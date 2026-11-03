# SGDI — Sistema de Gestão de Demandas Internas

Sistema web construído em **Flask + SQLite** para registrar, acompanhar e auditar demandas internas de uma empresa.

---

## Início rápido (5 minutos)

```bash
# 1. Instale as dependências
pip install -r requirements.txt

# 2. Crie o banco e popule com dados de exemplo
python init_db.py

# 3. Suba o servidor
python app.py
```

Acesse **http://localhost:5000**

Para rodar os testes (banco temporário isolado — não toca o `demandas.db`):

```bash
python -m unittest test_sgdi -v
```

---

## Estrutura dos arquivos

```
SGDI-main/
├── app.py          # Servidor Flask: todas as rotas e regras de negócio
├── auditoria.py    # Módulo de log imutável (independente do Flask)
├── exportacao.py   # Geração de relatórios: PDF, Excel (.xlsx) e CSV
├── init_db.py      # Cria o banco e insere dados de exemplo
├── test_sgdi.py    # 63 testes automatizados (unittest)
├── requirements.txt
└── templates/      # HTMLs Jinja2
    ├── base.html          # Layout base com cabeçalho e nav
    ├── index.html         # Lista de demandas + filtros
    ├── detalhe.html       # Detalhe de uma demanda + histórico de alterações
    ├── form_demanda.html  # Criar / editar demanda
    ├── painel.html        # KPIs, gráficos e exportação
    ├── auditoria.html     # Consulta de logs de auditoria
    └── usuarios.html      # Listagem de usuários cadastrados
```

---

## Modelo de dados (SQLite)

Todas as tabelas ficam em `demandas.db`.

### `demandas`
| coluna       | tipo    | descrição                                              |
|--------------|---------|--------------------------------------------------------|
| id           | INTEGER | PK autoincrement                                       |
| titulo       | TEXT    | Título curto da demanda                                |
| descricao    | TEXT    | Descrição completa                                     |
| status       | TEXT    | `Aberta` · `Em andamento` · `Concluída` · `Cancelada` |
| prioridade   | TEXT    | `Alta` · `Média` · `Baixa`                            |
| responsavel  | TEXT    | Nome do responsável (obrigatório)                      |
| prazo        | TEXT    | Data ISO `YYYY-MM-DD` (opcional)                       |
| criado_em    | TEXT    | Timestamp ISO gerado automaticamente                   |
| atualizado_em| TEXT    | Atualizado a cada edição                               |

### `comentarios`
| coluna      | tipo    | descrição                       |
|-------------|---------|---------------------------------|
| id          | INTEGER | PK autoincrement                |
| demanda_id  | INTEGER | FK → demandas.id                |
| autor       | TEXT    | Nome de quem comentou           |
| texto       | TEXT    | Conteúdo do comentário          |
| criado_em   | TEXT    | Timestamp ISO                   |

### `usuarios`
| coluna | tipo    | descrição              |
|--------|---------|------------------------|
| id     | INTEGER | PK autoincrement       |
| nome   | TEXT    | Nome único do usuário  |

### `logs_auditoria` (somente leitura — ver seção Auditoria)
| coluna      | tipo    | descrição                              |
|-------------|---------|----------------------------------------|
| id          | INTEGER | PK autoincrement                       |
| criado_em   | TEXT    | Timestamp ISO                          |
| usuario     | TEXT    | Nome copiado no momento da ação        |
| ip          | TEXT    | IP do cliente                          |
| user_agent  | TEXT    | Navegador/cliente                      |
| acao        | TEXT    | Código fixo (ver `auditoria.ACOES`)    |
| entidade_id | INTEGER | ID do registro afetado (pode ser NULL) |
| descricao   | TEXT    | Resumo legível da ação                 |
| detalhes    | TEXT    | JSON com dados extras (campos mudados) |

---

## Rotas principais

| método | URL                    | o que faz                                              |
|--------|------------------------|--------------------------------------------------------|
| GET    | `/`                    | Lista de demandas com filtros                          |
| GET    | `/nova`                | Formulário de nova demanda                             |
| POST   | `/nova`                | Salva nova demanda                                     |
| GET    | `/editar/<id>`         | Formulário de edição                                   |
| POST   | `/editar/<id>`         | Salva edição                                           |
| POST   | `/deletar/<id>`        | Exclui demanda                                         |
| GET    | `/detalhe/<id>`        | Detalhe + comentários + histórico                      |
| POST   | `/comentar/<id>`       | Adiciona comentário                                    |
| GET    | `/painel`              | KPIs, gráficos (SVG puro) e botões de exportação      |
| GET    | `/exportar/pdf`        | Relatório PDF (respeita filtros do painel)             |
| GET    | `/exportar/xlsx`       | Relatório Excel                                        |
| GET    | `/exportar/csv`        | Relatório CSV                                          |
| GET    | `/auditoria`           | Consulta de logs com filtros                           |
| GET    | `/auditoria/exportar`  | Exporta logs filtrados em CSV                          |
| GET    | `/usuarios`            | Lista de usuários                                      |
| POST   | `/usuarios`            | Cadastra novo usuário                                  |
| POST   | `/usuarios/deletar/<id>` | Remove usuário                                      |
| POST   | `/trocar_usuario`      | Troca o "usuário ativo" da sessão (sem senha)          |

### Filtros suportados (query string)
Todos os filtros funcionam em `/`, `/painel` e nas exportações:

| parâmetro    | exemplo                | descrição                       |
|--------------|------------------------|---------------------------------|
| `status`     | `?status=Aberta`       | Filtra por status               |
| `prioridade` | `?prioridade=Alta`     | Filtra por prioridade           |
| `responsavel`| `?responsavel=Joana`   | Filtra por responsável          |
| `de` / `ate` | `?de=2025-01-01`       | Intervalo de datas de criação   |
| `visao`      | `?visao=criticas_atrasadas` | Só demandas críticas e atrasadas |

---

## Regras de negócio

- **Aberta** = status `Aberta` ou `Em andamento` (conta para KPIs de "abertas").
- **Atrasada** = aberta com `prazo < hoje`. Aparece em vermelho. `Cancelada` nunca é atrasada.
- **Crítica** = prioridade `Alta` e ainda aberta.
- **Tempo médio de resolução** = média de dias entre `criado_em` e `atualizado_em` das demandas `Concluídas`. Demandas críticas pesam 2× (constante `PESO_CRITICA` em `app.py`).
- O campo `responsavel` é obrigatório — não existe demanda sem responsável.
- O nome da empresa nos relatórios fica em `NOME_EMPRESA` (`app.py`) ou na variável de ambiente `NOME_EMPRESA`.

---

## Auditoria e rastreabilidade

Toda ação relevante gera um registro imutável em `logs_auditoria` via `auditoria.py`.

**O que é registrado:** criação, edição (campo a campo: "de → para"), exclusão, comentário, exportação (formato + quantidade), troca de usuário ativo e exportação de logs.

**Como usar o módulo diretamente:**

```python
import auditoria

# Registrar uma ação
auditoria.registrar(
    conn,               # conexão SQLite já aberta (mesma transação da ação)
    acao='DEMANDA_CRIADA',
    entidade_id=42,
    descricao='Demanda "Bug urgente" criada',
    usuario='Maria',
    ip='127.0.0.1',
    user_agent='Firefox',
    detalhes={'titulo': 'Bug urgente', 'prioridade': 'Alta'},
)

# Consultar logs
logs = auditoria.consultar(conn, usuario='Maria', acao='DEMANDA_CRIADA')

# Histórico de uma demanda específica
historico = auditoria.historico_da_entidade(conn, entidade_id=42)

# Comparar dois momentos (retorna lista de mudanças)
mudancas = auditoria.comparar(antes, depois)
```

**Imutabilidade:** triggers SQLite bloqueiam `UPDATE` e `DELETE` na tabela — qualquer tentativa gera `SQLITE_CONSTRAINT`. O log é gravado na mesma transação da operação (atomicidade).

**Usuário ativo:** a barra "Atuando como" (cabeçalho) define quem aparece no log. Sem nenhum usuário selecionado a ação fica como "Não identificado". Isso **não é autenticação com senha** — qualquer pessoa pode escolher qualquer nome.

---

## Onde adicionar uma nova feature

Siga este roteiro para não quebrar nada:

1. **Nova rota:** adicione a função em `app.py` seguindo o padrão existente — use `get_db()` para obter a conexão e chame `registrar_log()` para logar a ação.
2. **Novo template:** estenda `base.html` com `{% extends "base.html" %}`.
3. **Nova tabela:** adicione o `CREATE TABLE IF NOT EXISTS` em `init_db.py` e rode `python init_db.py` novamente.
4. **Novos testes:** adicione uma classe em `test_sgdi.py` herdando de `SGDITestCase` (que já configura banco isolado em memória).

### Funções utilitárias em `app.py`

| função              | o que faz                                                 |
|---------------------|-----------------------------------------------------------|
| `get_db()`          | Abre (ou reutiliza) conexão com o banco da requisição     |
| `usuario_ativo()`   | Retorna o nome do usuário da sessão (ou "Não identificado") |
| `registrar_log(acao, entidade_id, descricao, detalhes)` | Atalho para `auditoria.registrar()` com conn, usuário e IP já preenchidos |
| `hoje_iso()`        | Data de hoje em `YYYY-MM-DD`                              |
| `agora_str()`       | Timestamp atual em `YYYY-MM-DD HH:MM:SS`                  |

---

## Variáveis de ambiente

| variável      | padrão                       | descrição                               |
|---------------|------------------------------|-----------------------------------------|
| `SGDI_DB`     | `demandas.db`                | Caminho do arquivo SQLite               |
| `NOME_EMPRESA`| `McLovin`                    | Nome exibido nos cabeçalhos de relatório|
| `SECRET_KEY`  | `dev-only-change-in-production` | Chave de sessão Flask               |

---

## Testes

63 testes automatizados cobrindo:

| classe                        | nº   | o que testa                                      |
|-------------------------------|------|--------------------------------------------------|
| `TestAuditoria`               | 25   | Log imutável, triggers, comparação de campos     |
| `TestExportacao`              | 18   | PDF, Excel, CSV com e sem filtros                |
| `TestFiltros`                 | 4    | Combinação de filtros via query string           |
| `TestFluxoDeStatus`           | 5    | Transições de status                             |
| `TestMigracao`                | 1    | Banco existente sem tabela de auditoria          |
| `TestPainel`                  | 6    | KPIs do painel                                   |
| `TestVisaoCriticasAtrasadas`  | 4    | Filtro `visao=criticas_atrasadas`                |

Todos usam banco SQLite **em memória** — não dependem do `demandas.db` e não deixam rastro no disco.

---

*Desenvolvido em 2025 — Disciplina Desafios da Tecnologia · IMED*
