from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort
import io
import exportacao
import sqlite3
from datetime import datetime, date, timedelta
from collections import Counter
from markupsafe import Markup
import os

# Caminho do banco (pode ser trocado pela variável SGDI_DB, útil nos testes).
DB_PATH = os.environ.get('SGDI_DB', 'demandas.db')

# Nome que aparece no cabeçalho dos relatórios exportados. Troque aqui ou
# defina a variável de ambiente NOME_EMPRESA.
NOME_EMPRESA = os.environ.get('NOME_EMPRESA', 'McLovin')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-in-production')


def _parse_data(valor):
    try:
        return datetime.strptime(valor, '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return None


@app.template_filter('data_br')
def formatar_data(valor):
    """Formata '2024-01-15 10:30:00' como '15/01/2024'. Se não conseguir
    entender o valor, devolve ele sem alteração em vez de quebrar a tela."""
    dt = _parse_data(valor)
    return dt.strftime('%d/%m/%Y') if dt else valor


@app.template_filter('hora_br')
def formatar_hora(valor):
    """Formata '2024-01-15 10:30:00' como '10:30'."""
    dt = _parse_data(valor)
    return dt.strftime('%H:%M') if dt else ''


@app.template_filter('data_hora_br')
def formatar_data_hora(valor):
    """Formata '2024-01-15 10:30:00' como '15/01/2024 às 10:30'."""
    dt = _parse_data(valor)
    return dt.strftime('%d/%m/%Y às %H:%M') if dt else valor


@app.template_filter('prazo_br')
def formatar_prazo(valor):
    """Formata '2024-01-15' como '15/01/2024'."""
    try:
        return datetime.strptime(valor, '%Y-%m-%d').strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return valor or '—'


@app.template_filter('num_br')
def formatar_numero(valor):
    """Número com vírgula decimal: 3.3 -> '3,3'."""
    return str(valor).replace('.', ',')


def hoje_iso():
    return date.today().strftime('%Y-%m-%d')


def agora_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


PRIORIDADES = ['Alta', 'Média', 'Baixa']
STATUS_OPCOES = ['Aberta', 'Em andamento', 'Concluída', 'Cancelada']
# Status em que a demanda ainda está "viva" (conta como aberta, pode atrasar
# e pode ser crítica). Concluída e Cancelada ficam de fora.
SQL_ABERTA = "demandas.status IN ('Aberta', 'Em andamento')"
# Valor do filtro ?visao= que mostra só críticas atrasadas.
VISAO_CRITICAS_ATRASADAS = 'criticas_atrasadas'
# Regra de negócio: demandas críticas (prioridade Alta) pesam mais na média
# de tempo de resolução. Peso 2 = uma crítica vale por duas demandas comuns.
PESO_CRITICA = 2
PAGINA_TAMANHO = 8


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def _garantir_status_cancelada(conn):
    """Bancos criados antes do status 'Cancelada' têm um CHECK que não o
    aceita, e o SQLite não permite alterar um CHECK. Então a tabela é
    recriada com o CHECK novo, copiando todos os dados (e sem apagar os
    comentários, por isso as chaves estrangeiras ficam desligadas só
    durante a troca)."""
    linha = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'demandas'"
    ).fetchone()
    if linha is None or "'Cancelada'" in (linha[0] or ''):
        return

    conn.commit()
    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.execute('DROP TABLE IF EXISTS demandas_nova')
        conn.execute('''
            CREATE TABLE demandas_nova (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                solicitante_id INTEGER NOT NULL,
                responsavel_id INTEGER NOT NULL,
                data_criacao TEXT NOT NULL,
                prioridade TEXT NOT NULL DEFAULT 'Média' CHECK(prioridade IN ('Alta', 'Média', 'Baixa')),
                status TEXT NOT NULL DEFAULT 'Aberta' CHECK(status IN ('Aberta', 'Em andamento', 'Concluída', 'Cancelada')),
                prazo TEXT,
                data_conclusao TEXT,
                FOREIGN KEY (solicitante_id) REFERENCES usuarios(id),
                FOREIGN KEY (responsavel_id) REFERENCES usuarios(id)
            )
        ''')
        conn.execute('''
            INSERT INTO demandas_nova
                (id, titulo, descricao, solicitante_id, responsavel_id, data_criacao,
                 prioridade, status, prazo, data_conclusao)
            SELECT id, titulo, descricao, solicitante_id, responsavel_id, data_criacao,
                   COALESCE(prioridade, 'Média'), COALESCE(status, 'Aberta'), prazo, data_conclusao
            FROM demandas
        ''')
        conn.execute('DROP TABLE demandas')
        conn.execute('ALTER TABLE demandas_nova RENAME TO demandas')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute('PRAGMA foreign_keys = ON')


def migrar_banco():
    """Evolui bancos criados antes desta mudança sem perder dados:
    - garante as colunas 'prioridade' e 'status' (com CHECK) se ainda não existirem;
    - transforma o campo livre 'solicitante' (texto) em vínculo com a
      tabela 'usuarios' via 'solicitante_id', preservando os nomes já
      cadastrados como usuários;
    - garante a coluna 'responsavel_id': se não existir, cada demanda
      recebe como responsável o próprio solicitante (valor de partida
      razoável, editável depois pela tela)."""
    try:
        conn = get_db()
        colunas = [col[1] for col in conn.execute('PRAGMA table_info(demandas)').fetchall()]

        if 'prioridade' not in colunas:
            conn.execute(
                "ALTER TABLE demandas ADD COLUMN prioridade TEXT DEFAULT 'Média' "
                "CHECK(prioridade IN ('Alta', 'Média', 'Baixa'))"
            )
            conn.commit()

        if 'status' not in colunas:
            conn.execute(
                "ALTER TABLE demandas ADD COLUMN status TEXT DEFAULT 'Aberta' "
                "CHECK(status IN ('Aberta', 'Em andamento', 'Concluída', 'Cancelada'))"
            )
            conn.commit()

        if 'solicitante' in colunas and 'solicitante_id' not in colunas:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL UNIQUE
                )
            ''')

            nomes = [r[0] for r in conn.execute(
                'SELECT DISTINCT solicitante FROM demandas WHERE solicitante IS NOT NULL'
            ).fetchall()]
            for nome in nomes:
                conn.execute('INSERT OR IGNORE INTO usuarios (nome) VALUES (?)', (nome,))

            conn.execute('ALTER TABLE demandas ADD COLUMN solicitante_id INTEGER REFERENCES usuarios(id)')
            conn.execute('''
                UPDATE demandas
                SET solicitante_id = (
                    SELECT id FROM usuarios WHERE usuarios.nome = demandas.solicitante
                )
            ''')
            conn.commit()

            # Remove a coluna antiga só se o SQLite instalado suportar
            # DROP COLUMN (3.35+); se não suportar, ela fica sem uso.
            try:
                conn.execute('ALTER TABLE demandas DROP COLUMN solicitante')
                conn.commit()
            except sqlite3.OperationalError:
                pass

            colunas = [col[1] for col in conn.execute('PRAGMA table_info(demandas)').fetchall()]

        if 'responsavel_id' not in colunas:
            conn.execute('ALTER TABLE demandas ADD COLUMN responsavel_id INTEGER REFERENCES usuarios(id)')
            # Ponto de partida razoável: responsável = o próprio solicitante.
            # Dá pra trocar depois editando a demanda.
            conn.execute('UPDATE demandas SET responsavel_id = solicitante_id WHERE responsavel_id IS NULL')
            conn.commit()

        # Painel de KPIs: prazo (para saber o que está atrasado) e data de
        # conclusão (para calcular o tempo médio de resolução). Demandas já
        # existentes ficam com prazo vazio (nunca contam como atrasadas) e
        # concluídas antigas sem data_conclusao ficam fora da média.
        if 'prazo' not in colunas:
            conn.execute('ALTER TABLE demandas ADD COLUMN prazo TEXT')
            conn.commit()

        if 'data_conclusao' not in colunas:
            conn.execute('ALTER TABLE demandas ADD COLUMN data_conclusao TEXT')
            conn.commit()

        _garantir_status_cancelada(conn)

        conn.execute('CREATE INDEX IF NOT EXISTS idx_demandas_prioridade ON demandas(prioridade)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_demandas_solicitante ON demandas(solicitante_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_demandas_responsavel ON demandas(responsavel_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_demandas_status ON demandas(status)')
        conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        # Banco/tabela ainda não existe: rode "python init_db.py" primeiro.
        pass


def listar_usuarios(conn):
    return conn.execute('SELECT * FROM usuarios ORDER BY nome').fetchall()


ORDEM_STATUS_SQL = '''
    CASE demandas.status
        WHEN 'Aberta' THEN 1
        WHEN 'Em andamento' THEN 2
        WHEN 'Concluída' THEN 3
        WHEN 'Cancelada' THEN 4
        ELSE 5
    END
'''

ORDEM_PRIORIDADE_SQL = '''
    CASE demandas.prioridade
        WHEN 'Alta' THEN 1
        WHEN 'Média' THEN 2
        WHEN 'Baixa' THEN 3
        ELSE 4
    END
'''


def _filtros_comuns(args):
    """Lê da URL os filtros compartilhados pela lista e pelo painel:
    período (de/ate, sobre a data de criação), prioridade, status e
    responsável. Todos valem ao mesmo tempo (E). Valores inválidos são
    ignorados sem quebrar a tela."""
    condicoes, params, filtros = [], [], {}

    for chave, operador in (('de', '>='), ('ate', '<=')):
        valor = args.get(chave, '').strip()
        try:
            datetime.strptime(valor, '%Y-%m-%d')
        except ValueError:
            continue
        condicoes.append(f'substr(demandas.data_criacao, 1, 10) {operador} ?')
        params.append(valor)
        filtros[chave] = valor

    prioridade = args.get('prioridade', '').strip()
    if prioridade in PRIORIDADES:
        condicoes.append('demandas.prioridade = ?')
        params.append(prioridade)
        filtros['prioridade'] = prioridade

    status = args.get('status', '').strip()
    if status in STATUS_OPCOES:
        condicoes.append('demandas.status = ?')
        params.append(status)
        filtros['status'] = status

    responsavel = args.get('responsavel_id', '').strip()
    if responsavel.isdigit():
        condicoes.append('demandas.responsavel_id = ?')
        params.append(int(responsavel))
        filtros['responsavel_id'] = responsavel

    # Visão dedicada da diretoria: só demandas críticas (prioridade Alta)
    # que estão em aberto E com o prazo vencido. Como entra nas condições
    # comuns, painel, lista e exportações (PDF/Excel/CSV) respeitam juntos.
    if args.get('visao', '').strip() == VISAO_CRITICAS_ATRASADAS:
        condicoes.append(
            f"(demandas.prioridade = 'Alta' AND {SQL_ABERTA} "
            "AND demandas.prazo IS NOT NULL AND demandas.prazo < ?)"
        )
        params.append(hoje_iso())
        filtros['visao'] = VISAO_CRITICAS_ATRASADAS

    return condicoes, params, filtros


@app.route('/')
def index():
    termo_busca = request.args.get('q', '').strip()

    try:
        pagina = int(request.args.get('pagina', 1))
    except ValueError:
        pagina = 1
    if pagina < 1:
        pagina = 1

    condicoes, params, filtros_ativos = _filtros_comuns(request.args)
    prioridade = filtros_ativos.get('prioridade', '')
    status = filtros_ativos.get('status', '')
    responsavel_filtro = filtros_ativos.get('responsavel_id', '')

    if termo_busca:
        like = f'%{termo_busca}%'
        condicoes.append(
            '(demandas.titulo LIKE ? OR demandas.descricao LIKE ? '
            'OR solicitantes.nome LIKE ? OR responsaveis.nome LIKE ?)'
        )
        params.extend([like, like, like, like])
        filtros_ativos['q'] = termo_busca

    where_sql = ('WHERE ' + ' AND '.join(condicoes)) if condicoes else ''

    conn = get_db()

    total = conn.execute(f'''
        SELECT COUNT(*) AS total
        FROM demandas
        JOIN usuarios AS solicitantes ON solicitantes.id = demandas.solicitante_id
        JOIN usuarios AS responsaveis ON responsaveis.id = demandas.responsavel_id
        {where_sql}
    ''', params).fetchone()['total']

    total_paginas = max(1, (total + PAGINA_TAMANHO - 1) // PAGINA_TAMANHO)
    if pagina > total_paginas:
        pagina = total_paginas
    offset = (pagina - 1) * PAGINA_TAMANHO

    query = f'''
        SELECT demandas.id, demandas.titulo, demandas.descricao,
               demandas.solicitante_id, demandas.responsavel_id,
               demandas.data_criacao, demandas.prioridade, demandas.status,
               demandas.prazo, demandas.data_conclusao,
               solicitantes.nome AS solicitante_nome,
               responsaveis.nome AS responsavel_nome
        FROM demandas
        JOIN usuarios AS solicitantes ON solicitantes.id = demandas.solicitante_id
        JOIN usuarios AS responsaveis ON responsaveis.id = demandas.responsavel_id
        {where_sql}
        ORDER BY {ORDEM_STATUS_SQL}, {ORDEM_PRIORIDADE_SQL}, demandas.id
        LIMIT ? OFFSET ?
    '''
    demandas = conn.execute(query, params + [PAGINA_TAMANHO, offset]).fetchall()
    lista_usuarios = listar_usuarios(conn)
    conn.close()

    return render_template(
        'index.html',
        demandas=demandas,
        termo_busca=termo_busca,
        prioridade_selecionada=prioridade,
        status_selecionado=status,
        responsavel_selecionado=responsavel_filtro,
        prioridades=PRIORIDADES,
        status_opcoes=STATUS_OPCOES,
        usuarios=lista_usuarios,
        pagina=pagina,
        total_paginas=total_paginas,
        total=total,
        filtros_ativos=filtros_ativos,
        pagina_tamanho=PAGINA_TAMANHO,
        hoje=hoje_iso(),
    )


def _percentual(parte, total):
    return round(parte * 100 / total, 1) if total else 0


def _data_curta(texto):
    """'2024-01-15' -> '15/01'  ·  '2024-01' -> '01/2024'."""
    if len(texto) == 7:
        return f'{texto[5:7]}/{texto[:4]}'
    return f'{texto[8:10]}/{texto[5:7]}'


def _serie_temporal(linhas):
    """Evolução no tempo: demandas criadas x concluídas por período.
    Até ~2 meses de intervalo agrupa por dia; acima disso, por mês."""
    criadas = [datetime.strptime(l['data_criacao'][:10], '%Y-%m-%d').date() for l in linhas]
    concluidas = [
        datetime.strptime(l['data_conclusao'][:10], '%Y-%m-%d').date()
        for l in linhas if l['status'] == 'Concluída' and l['data_conclusao']
    ]
    if not criadas:
        return None

    inicio, fim = min(criadas + concluidas), max(criadas + concluidas)
    mensal = (fim - inicio).days > 62

    chaves = []
    if mensal:
        ano, mes = inicio.year, inicio.month
        while (ano, mes) <= (fim.year, fim.month):
            chaves.append(f'{ano:04d}-{mes:02d}')
            mes += 1
            if mes > 12:
                ano, mes = ano + 1, 1
    else:
        dia = inicio
        while dia <= fim:
            chaves.append(dia.isoformat())
            dia += timedelta(days=1)

    tamanho = 7 if mensal else 10
    contar_criadas = Counter(d.isoformat()[:tamanho] for d in criadas)
    contar_concluidas = Counter(d.isoformat()[:tamanho] for d in concluidas)
    return {
        'rotulos': [_data_curta(c) for c in chaves],
        'criadas': [contar_criadas.get(c, 0) for c in chaves],
        'concluidas': [contar_concluidas.get(c, 0) for c in chaves],
        'mensal': mensal,
    }


def _svg_evolucao(serie):
    """Gráfico de linhas (SVG puro, sem biblioteca externa) com as duas
    séries: criadas e concluídas."""
    if not serie:
        return Markup('')

    largura, altura = 900, 300
    margem_e, margem_d, margem_t, margem_b = 52, 20, 20, 44
    util_l = largura - margem_e - margem_d
    util_a = altura - margem_t - margem_b
    n = len(serie['rotulos'])
    maximo = max(1, max(serie['criadas'] + serie['concluidas']))
    passo = max(1, -(-maximo // 4))  # ceil(maximo / 4)
    topo = passo * (-(-maximo // passo))

    def pos_x(i):
        return margem_e + (util_l * i / (n - 1) if n > 1 else util_l / 2)

    def pos_y(v):
        return margem_t + util_a - util_a * v / topo

    partes = [f'<svg viewBox="0 0 {largura} {altura}" role="img" '
              f'aria-label="Evolução de demandas criadas e concluídas" class="grafico-svg">']
    for v in range(0, topo + 1, passo):
        y = pos_y(v)
        partes.append(f'<line x1="{margem_e}" x2="{largura - margem_d}" y1="{y:.1f}" y2="{y:.1f}" stroke="#3a3629"/>')
        partes.append(f'<text x="{margem_e - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="#a39d86">{v}</text>')

    # no máximo ~8 rótulos no eixo X
    salto = max(1, -(-n // 8))
    for i, rotulo in enumerate(serie['rotulos']):
        if i % salto == 0 or i == n - 1:
            partes.append(f'<text x="{pos_x(i):.1f}" y="{altura - 14}" text-anchor="middle" font-size="12" fill="#a39d86">{rotulo}</text>')

    for chave, cor, nome in (('criadas', '#5aa9ff', 'Criadas'), ('concluidas', '#4cc38a', 'Concluídas')):
        pontos = [(pos_x(i), pos_y(v)) for i, v in enumerate(serie[chave])]
        if len(pontos) > 1:
            lista = ' '.join(f'{x:.1f},{y:.1f}' for x, y in pontos)
            partes.append(f'<polyline points="{lista}" fill="none" stroke="{cor}" stroke-width="3" stroke-linejoin="round"/>')
        for i, (x, y) in enumerate(pontos):
            partes.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{cor}"><title>{serie["rotulos"][i]} · {nome}: {serie[chave][i]}</title></circle>'
            )
    partes.append('</svg>')
    return Markup(''.join(partes))


def calcular_painel(conn, condicoes, params, responsavel_id=None):
    """Calcula todos os números e gráficos do painel sobre o conjunto de
    demandas que passa nos filtros (as mesmas regras valem para tudo).

    Regras de negócio:
    - Abertas = Aberta + Em andamento. Concluída e Cancelada não são abertas.
    - Atrasadas = abertas com prazo anterior a hoje (aparecem em vermelho).
      Cancelada nunca conta como atrasada, mesmo com prazo vencido.
    - Críticas = prioridade Alta ainda aberta.
    - Por responsável = demandas abertas de cada pessoa.
    - Tempo médio de resolução = dias entre criação e conclusão, só das
      Concluídas (Canceladas ficam de fora). Média ponderada: demandas
      críticas (Alta) têm peso PESO_CRITICA.
    - Todo responsável é obrigatório no cadastro, então não existe demanda
      sem responsável para contar fora da média.
    """
    hoje = hoje_iso()

    def onde(*extras):
        todas = list(condicoes) + list(extras)
        return ('WHERE ' + ' AND '.join(todas)) if todas else ''

    r = conn.execute(f'''
        SELECT COUNT(*) AS total,
               COALESCE(SUM({SQL_ABERTA}), 0) AS abertas,
               COALESCE(SUM(demandas.status = 'Em andamento'), 0) AS em_andamento,
               COALESCE(SUM(demandas.status = 'Concluída'), 0) AS concluidas,
               COALESCE(SUM(demandas.status = 'Cancelada'), 0) AS canceladas,
               COALESCE(SUM({SQL_ABERTA} AND demandas.prazo IS NOT NULL AND demandas.prazo < ?), 0) AS atrasadas
        FROM demandas
        {onde()}
    ''', [hoje] + params).fetchone()
    total = r['total']

    kpis = {
        'total': total,
        'abertas': r['abertas'],
        'em_andamento': r['em_andamento'],
        'concluidas': r['concluidas'],
        'canceladas': r['canceladas'],
        'atrasadas': r['atrasadas'],
        'pct_abertas': _percentual(r['abertas'], total),
        'pct_concluidas': _percentual(r['concluidas'], total),
        'pct_canceladas': _percentual(r['canceladas'], total),
        'pct_atrasadas': _percentual(r['atrasadas'], total),
    }

    contagem_status = {
        l['status']: l['qtd'] for l in conn.execute(
            f'SELECT demandas.status AS status, COUNT(*) AS qtd FROM demandas {onde()} GROUP BY demandas.status',
            params,
        ).fetchall()
    }
    por_status = [{'nome': s, 'qtd': contagem_status.get(s, 0)} for s in STATUS_OPCOES]

    contagem_prio = {
        l['prioridade']: l['qtd'] for l in conn.execute(
            f'SELECT demandas.prioridade AS prioridade, COUNT(*) AS qtd FROM demandas {onde()} GROUP BY demandas.prioridade',
            params,
        ).fetchall()
    }
    por_prioridade = [{'nome': p, 'qtd': contagem_prio.get(p, 0)} for p in PRIORIDADES]

    criticas = conn.execute(f'''
        SELECT demandas.id, demandas.titulo, demandas.status, demandas.prazo,
               responsaveis.nome AS responsavel_nome
        FROM demandas
        JOIN usuarios AS responsaveis ON responsaveis.id = demandas.responsavel_id
        {onde("demandas.prioridade = 'Alta'", SQL_ABERTA)}
        ORDER BY {ORDEM_STATUS_SQL}, demandas.id
    ''', params).fetchall()

    # Condições do filtro entram no ON do LEFT JOIN para que quem não tem
    # demandas no recorte continue aparecendo com zero.
    extras_join = ''.join(f' AND {c}' for c in condicoes)
    filtro_usuario = 'WHERE usuarios.id = ?' if responsavel_id else ''
    params_resp = list(params) + ([responsavel_id] if responsavel_id else [])
    por_responsavel = conn.execute(f'''
        SELECT usuarios.id, usuarios.nome, COUNT(demandas.id) AS qtd
        FROM usuarios
        LEFT JOIN demandas ON demandas.responsavel_id = usuarios.id
                          AND {SQL_ABERTA}{extras_join}
        {filtro_usuario}
        GROUP BY usuarios.id
        ORDER BY qtd DESC, usuarios.nome
    ''', params_resp).fetchall()

    tempo = conn.execute(f'''
        SELECT SUM(dias * peso) / SUM(peso) AS ponderada,
               AVG(dias) AS simples,
               COUNT(*) AS base
        FROM (
            SELECT julianday(demandas.data_conclusao) - julianday(demandas.data_criacao) AS dias,
                   CASE demandas.prioridade WHEN 'Alta' THEN ? ELSE 1 END AS peso
            FROM demandas
            {onde("demandas.status = 'Concluída'", 'demandas.data_conclusao IS NOT NULL')}
        )
    ''', [PESO_CRITICA] + params).fetchone()

    linhas = conn.execute(
        f'SELECT demandas.data_criacao, demandas.data_conclusao, demandas.status FROM demandas {onde()}',
        params,
    ).fetchall()

    criticas_lista = [
        {
            'id': c['id'], 'titulo': c['titulo'], 'status': c['status'],
            'responsavel': c['responsavel_nome'],
            'prazo': datetime.strptime(c['prazo'], '%Y-%m-%d') if c['prazo'] else None,
            'atrasada': bool(c['prazo'] and c['prazo'] < hoje),
        }
        for c in criticas
    ]

    return {
        'criticas_atrasadas': [c for c in criticas_lista if c['atrasada']],
        'kpis': kpis,
        'por_status': por_status,
        'por_prioridade': por_prioridade,
        'maior_status': max([x['qtd'] for x in por_status], default=0),
        'maior_prioridade': max([x['qtd'] for x in por_prioridade], default=0),
        'criticas': criticas,
        'criticas_lista': criticas_lista,
        'por_responsavel': por_responsavel,
        'maior_carga': max([p['qtd'] for p in por_responsavel], default=0),
        'tempo_ponderado': round(tempo['ponderada'], 1) if tempo['ponderada'] is not None else None,
        'tempo_simples': round(tempo['simples'], 1) if tempo['simples'] is not None else None,
        'tempo_base': tempo['base'],
        'peso_critica': PESO_CRITICA,
        'grafico_tempo': _svg_evolucao(_serie_temporal(linhas)),
        'hoje': hoje,
    }


@app.route('/painel')
def painel():
    """Painel de KPIs e gráficos, com filtros combinados (período,
    responsável, prioridade e status). Com ?parcial=1 devolve só o bloco de
    dados, que o JavaScript troca na tela sem recarregar a página."""
    condicoes, params, filtros = _filtros_comuns(request.args)
    responsavel_id = int(filtros['responsavel_id']) if 'responsavel_id' in filtros else None

    conn = get_db()
    dados = calcular_painel(conn, condicoes, params, responsavel_id)
    lista_usuarios = listar_usuarios(conn)
    conn.close()

    contexto = dict(
        dados,
        filtros=filtros,
        usuarios=lista_usuarios,
        prioridades=PRIORIDADES,
        status_opcoes=STATUS_OPCOES,
        atualizado_em=datetime.now().strftime('%H:%M:%S'),
    )
    if request.args.get('parcial'):
        return render_template('_painel_conteudo.html', **contexto)
    return render_template('painel.html', **contexto)


MESES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def _descrever_periodo(de, ate):
    """'Jan–Mar 2025' quando o período fecha meses inteiros; senão datas."""
    d1 = datetime.strptime(de, '%Y-%m-%d').date() if de else None
    d2 = datetime.strptime(ate, '%Y-%m-%d').date() if ate else None
    if d1 and d2:
        if d1.day == 1 and (d2 + timedelta(days=1)).day == 1 and d1 <= d2:
            if d1.year == d2.year:
                if d1.month == d2.month:
                    return f'{MESES[d1.month - 1]} {d1.year}'
                return f'{MESES[d1.month - 1]}–{MESES[d2.month - 1]} {d1.year}'
            return f'{MESES[d1.month - 1]}/{d1.year}–{MESES[d2.month - 1]}/{d2.year}'
        return f'{d1.strftime("%d/%m/%Y")} a {d2.strftime("%d/%m/%Y")}'
    if d1:
        return f'a partir de {d1.strftime("%d/%m/%Y")}'
    if d2:
        return f'até {d2.strftime("%d/%m/%Y")}'
    return ''


def descrever_filtros(filtros, usuarios):
    """Texto do rodapé do relatório: 'Prioridade Alta · Jan–Mar 2025'."""
    partes = []
    if filtros.get('visao') == VISAO_CRITICAS_ATRASADAS:
        partes.append('Críticas atrasadas')
    if 'prioridade' in filtros:
        partes.append(f"Prioridade {filtros['prioridade']}")
    if 'status' in filtros:
        partes.append(f"Status {filtros['status']}")
    if 'responsavel_id' in filtros:
        nomes = {str(u['id']): u['nome'] for u in usuarios}
        partes.append(f"Responsável {nomes.get(filtros['responsavel_id'], '?')}")
    periodo = _descrever_periodo(filtros.get('de'), filtros.get('ate'))
    if periodo:
        partes.append(periodo)
    return ' · '.join(partes) if partes else 'nenhum filtro (todas as demandas)'


def listar_demandas_filtradas(conn, condicoes, params):
    where_sql = ('WHERE ' + ' AND '.join(condicoes)) if condicoes else ''
    linhas = conn.execute(f'''
        SELECT demandas.id, demandas.titulo, demandas.prioridade, demandas.status,
               demandas.data_criacao, demandas.prazo, demandas.data_conclusao,
               solicitantes.nome AS solicitante_nome,
               responsaveis.nome AS responsavel_nome
        FROM demandas
        JOIN usuarios AS solicitantes ON solicitantes.id = demandas.solicitante_id
        JOIN usuarios AS responsaveis ON responsaveis.id = demandas.responsavel_id
        {where_sql}
        ORDER BY {ORDEM_STATUS_SQL}, {ORDEM_PRIORIDADE_SQL}, demandas.id
    ''', params).fetchall()

    hoje = hoje_iso()
    lista = []
    for l in linhas:
        lista.append({
            'id': l['id'],
            'titulo': l['titulo'],
            'solicitante': l['solicitante_nome'],
            'responsavel': l['responsavel_nome'],
            'prioridade': l['prioridade'],
            'status': l['status'],
            'criacao': _parse_data(l['data_criacao']),
            'prazo': datetime.strptime(l['prazo'], '%Y-%m-%d') if l['prazo'] else None,
            'conclusao': _parse_data(l['data_conclusao']),
            'atrasada': bool(l['status'] in ('Aberta', 'Em andamento') and l['prazo'] and l['prazo'] < hoje),
        })
    return lista


def montar_relatorio(args):
    """Monta o relatório com os MESMOS filtros do painel: o que sai no
    PDF/Excel/CSV é exatamente o que está na tela."""
    condicoes, params, filtros = _filtros_comuns(args)
    responsavel_id = int(filtros['responsavel_id']) if 'responsavel_id' in filtros else None

    conn = get_db()
    dados = calcular_painel(conn, condicoes, params, responsavel_id)
    demandas = listar_demandas_filtradas(conn, condicoes, params)
    usuarios_lista = listar_usuarios(conn)
    conn.close()

    return {
        'empresa': NOME_EMPRESA,
        'titulo': ('Relatório de Demandas Críticas Atrasadas'
                   if filtros.get('visao') == VISAO_CRITICAS_ATRASADAS
                   else 'Relatório de Demandas'),
        'gerado_em': datetime.now(),
        'filtros_texto': descrever_filtros(filtros, usuarios_lista),
        'dados': dados,
        'demandas': demandas,
    }


@app.route('/exportar/<formato>')
def exportar(formato):
    """Baixa o relatório em PDF, Excel (xlsx) ou CSV, respeitando os
    filtros da URL (os mesmos do painel)."""
    if formato not in exportacao.FORMATOS:
        abort(404)

    relatorio = montar_relatorio(request.args)
    conteudo = exportacao.GERADORES[formato](relatorio)
    mimetype, extensao = exportacao.FORMATOS[formato]
    nome = f"relatorio-demandas-{relatorio['gerado_em'].strftime('%Y%m%d-%H%M%S')}.{extensao}"
    return send_file(io.BytesIO(conteudo), mimetype=mimetype, as_attachment=True, download_name=nome)


@app.route('/usuarios', methods=['GET', 'POST'])
def usuarios():
    conn = get_db()

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()

        if not nome:
            flash('Informe o nome do usuário.')
        else:
            try:
                conn.execute('INSERT INTO usuarios (nome) VALUES (?)', (nome,))
                conn.commit()
                flash('Usuário cadastrado!')
            except sqlite3.IntegrityError:
                flash('Já existe um usuário com esse nome.')

    lista = listar_usuarios(conn)
    conn.close()
    return render_template('usuarios.html', usuarios=lista)


@app.route('/usuarios/deletar/<int:id>', methods=['POST'])
def deletar_usuario(id):
    conn = get_db()
    usuario = conn.execute('SELECT id FROM usuarios WHERE id = ?', (id,)).fetchone()

    if usuario is None:
        conn.close()
        flash('Usuário não encontrado.')
        return redirect(url_for('usuarios'))

    total_demandas = conn.execute(
        'SELECT COUNT(*) AS total FROM demandas WHERE solicitante_id = ? OR responsavel_id = ?',
        (id, id),
    ).fetchone()['total']

    if total_demandas > 0:
        conn.close()
        flash(
            f'Não é possível excluir: esse usuário ainda está vinculado a {total_demandas} '
            f'demanda(s) (como solicitante ou responsável). Edite ou apague essas demandas primeiro.'
        )
        return redirect(url_for('usuarios'))

    conn.execute('DELETE FROM usuarios WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Usuário excluído!')
    return redirect(url_for('usuarios'))


def _validar_demanda(conn, titulo, descricao, solicitante_id, responsavel_id, prioridade, status, prazo=''):
    erros = []
    if prazo:
        try:
            datetime.strptime(prazo, '%Y-%m-%d')
        except ValueError:
            erros.append('Prazo inválido.')
    if not titulo or not descricao or not solicitante_id or not responsavel_id:
        erros.append('Preencha todos os campos obrigatórios.')
    if prioridade not in PRIORIDADES:
        erros.append('Prioridade inválida. Escolha Alta, Média ou Baixa.')
    if status not in STATUS_OPCOES:
        erros.append('Status inválido.')

    if solicitante_id:
        if conn.execute('SELECT id FROM usuarios WHERE id = ?', (solicitante_id,)).fetchone() is None:
            erros.append('Selecione um solicitante cadastrado.')

    if responsavel_id:
        if conn.execute('SELECT id FROM usuarios WHERE id = ?', (responsavel_id,)).fetchone() is None:
            erros.append('Selecione um responsável cadastrado.')

    return erros


@app.route('/nova_demanda', methods=['GET', 'POST'])
def nova_demanda():
    conn = get_db()

    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        solicitante_id = request.form.get('solicitante_id', '').strip()
        responsavel_id = request.form.get('responsavel_id', '').strip()
        prioridade = request.form.get('prioridade', 'Média').strip()
        status = request.form.get('status', 'Aberta').strip()
        prazo = request.form.get('prazo', '').strip()

        erros = _validar_demanda(conn, titulo, descricao, solicitante_id, responsavel_id, prioridade, status, prazo)

        if erros:
            for erro in erros:
                flash(erro)
            lista_usuarios = listar_usuarios(conn)
            conn.close()
            # Devolve pro formulário exatamente o que a pessoa já tinha
            # escolhido, em vez de resetar tudo pro valor padrão.
            return render_template(
                'nova_demanda.html',
                prioridades=PRIORIDADES,
                status_opcoes=STATUS_OPCOES,
                usuarios=lista_usuarios,
                titulo=titulo,
                descricao=descricao,
                solicitante_id=solicitante_id,
                responsavel_id=responsavel_id,
                prioridade_selecionada=prioridade,
                status_selecionado=status,
                prazo=prazo,
            ), 400

        conn.execute(
            'INSERT INTO demandas (titulo, descricao, solicitante_id, responsavel_id, data_criacao, '
            'prioridade, status, prazo, data_conclusao) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                titulo, descricao, solicitante_id, responsavel_id,
                agora_str(), prioridade, status, prazo or None,
                agora_str() if status == 'Concluída' else None,
            ),
        )
        conn.commit()
        conn.close()

        flash('Salvo!')
        return redirect(url_for('index'))

    lista_usuarios = listar_usuarios(conn)
    conn.close()
    return render_template('nova_demanda.html', prioridades=PRIORIDADES, status_opcoes=STATUS_OPCOES, usuarios=lista_usuarios)


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar(id):
    conn = get_db()

    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        solicitante_id = request.form.get('solicitante_id', '').strip()
        responsavel_id = request.form.get('responsavel_id', '').strip()
        prioridade = request.form.get('prioridade', 'Média').strip()
        status = request.form.get('status', 'Aberta').strip()
        prazo = request.form.get('prazo', '').strip()

        erros = _validar_demanda(conn, titulo, descricao, solicitante_id, responsavel_id, prioridade, status, prazo)

        if erros:
            for erro in erros:
                flash(erro)
            original = conn.execute('SELECT data_criacao FROM demandas WHERE id = ?', (id,)).fetchone()
            lista_usuarios = listar_usuarios(conn)
            conn.close()
            # Devolve exatamente o que a pessoa digitou (não o que estava
            # salvo no banco antes), só a data de criação (não editável)
            # continua vindo do banco.
            demanda_exibir = {
                'id': id,
                'titulo': titulo,
                'descricao': descricao,
                'solicitante_id': int(solicitante_id) if solicitante_id.isdigit() else None,
                'responsavel_id': int(responsavel_id) if responsavel_id.isdigit() else None,
                'data_criacao': original['data_criacao'] if original else '',
                'prioridade': prioridade,
                'status': status,
                'prazo': prazo,
            }
            return render_template(
                'editar.html',
                demanda=demanda_exibir,
                prioridades=PRIORIDADES,
                status_opcoes=STATUS_OPCOES,
                usuarios=lista_usuarios,
            ), 400

        # data_conclusao: marca o momento em que a demanda vira "Concluída",
        # mantém se já estava concluída e limpa se for reaberta.
        atual = conn.execute('SELECT status, data_conclusao FROM demandas WHERE id = ?', (id,)).fetchone()
        if status != 'Concluída':
            data_conclusao = None
        elif atual is not None and atual['status'] == 'Concluída' and atual['data_conclusao']:
            data_conclusao = atual['data_conclusao']
        else:
            data_conclusao = agora_str()

        conn.execute(
            'UPDATE demandas SET titulo = ?, descricao = ?, solicitante_id = ?, '
            'responsavel_id = ?, prioridade = ?, status = ?, prazo = ?, data_conclusao = ? WHERE id = ?',
            (titulo, descricao, solicitante_id, responsavel_id, prioridade, status,
             prazo or None, data_conclusao, id),
        )
        conn.commit()
        conn.close()
        flash('Demanda atualizada!')
        return redirect(url_for('index'))

    demanda = conn.execute('SELECT * FROM demandas WHERE id = ?', (id,)).fetchone()
    lista_usuarios = listar_usuarios(conn)
    conn.close()

    if demanda is None:
        flash('Demanda não encontrada.')
        return redirect(url_for('index'))

    return render_template('editar.html', demanda=demanda, prioridades=PRIORIDADES, status_opcoes=STATUS_OPCOES, usuarios=lista_usuarios)


@app.route('/deletar/<int:id>', methods=['POST'])
def deletar(id):
    conn = get_db()
    demanda = conn.execute('SELECT id FROM demandas WHERE id = ?', (id,)).fetchone()

    if demanda is None:
        conn.close()
        flash('Demanda não encontrada.')
        return redirect(url_for('index'))

    conn.execute('DELETE FROM comentarios WHERE demanda_id = ?', (id,))
    conn.execute('DELETE FROM demandas WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Deletado!')
    return redirect(url_for('index'))


@app.route('/buscar')
def buscar():
    # Mantida como redirect para "/": links antigos e a busca do
    # cabeçalho continuam funcionando.
    termo = request.args.get('q', '')
    return redirect(url_for('index', q=termo))


@app.route('/detalhes/<int:id>')
def detalhes(id):
    conn = get_db()
    demanda = conn.execute('''
        SELECT demandas.id, demandas.titulo, demandas.descricao,
               demandas.solicitante_id, demandas.responsavel_id,
               demandas.data_criacao, demandas.prioridade, demandas.status,
               demandas.prazo, demandas.data_conclusao,
               solicitantes.nome AS solicitante_nome,
               responsaveis.nome AS responsavel_nome
        FROM demandas
        JOIN usuarios AS solicitantes ON solicitantes.id = demandas.solicitante_id
        JOIN usuarios AS responsaveis ON responsaveis.id = demandas.responsavel_id
        WHERE demandas.id = ?
    ''', (id,)).fetchone()

    if demanda is None:
        conn.close()
        flash('Demanda não encontrada.')
        return redirect(url_for('index'))

    comentarios = conn.execute(
        'SELECT * FROM comentarios WHERE demanda_id = ? ORDER BY data',
        (id,),
    ).fetchall()
    conn.close()

    return render_template('detalhes.html', demanda=demanda, comentarios=comentarios, hoje=hoje_iso())


@app.route('/adicionar_comentario/<int:demanda_id>', methods=['POST'])
def adicionar_comentario(demanda_id):
    comentario = request.form.get('comentario', '').strip()
    autor = request.form.get('autor', '').strip()

    if not comentario or not autor:
        flash('Informe autor e comentário.')
        return redirect(url_for('detalhes', id=demanda_id))

    conn = get_db()
    demanda = conn.execute('SELECT id FROM demandas WHERE id = ?', (demanda_id,)).fetchone()

    if demanda is None:
        conn.close()
        flash('Demanda não encontrada.')
        return redirect(url_for('index'))

    conn.execute(
        'INSERT INTO comentarios (demanda_id, comentario, autor, data) VALUES (?, ?, ?, ?)',
        (demanda_id, comentario, autor, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
    )
    conn.commit()
    conn.close()

    return redirect(url_for('detalhes', id=demanda_id))


if __name__ == '__main__':
    migrar_banco()
    app.run(debug=True, host='127.0.0.1')
