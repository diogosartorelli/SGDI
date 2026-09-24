from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
import os

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


PRIORIDADES = ['Alta', 'Média', 'Baixa']
STATUS_OPCOES = ['Aberta', 'Em andamento', 'Concluída']
PAGINA_TAMANHO = 8


def get_db():
    conn = sqlite3.connect('demandas.db')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


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
                "CHECK(status IN ('Aberta', 'Em andamento', 'Concluída'))"
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
        ELSE 4
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


@app.route('/')
def index():
    termo_busca = request.args.get('q', '').strip()
    prioridade = request.args.get('prioridade', '').strip()
    status = request.args.get('status', '').strip()
    responsavel_filtro = request.args.get('responsavel_id', '').strip()

    try:
        pagina = int(request.args.get('pagina', 1))
    except ValueError:
        pagina = 1
    if pagina < 1:
        pagina = 1

    condicoes = []
    params = []
    filtros_ativos = {}

    if termo_busca:
        like = f'%{termo_busca}%'
        condicoes.append(
            '(demandas.titulo LIKE ? OR demandas.descricao LIKE ? '
            'OR solicitantes.nome LIKE ? OR responsaveis.nome LIKE ?)'
        )
        params.extend([like, like, like, like])
        filtros_ativos['q'] = termo_busca

    # Valores inválidos de prioridade/status/responsável são ignorados no
    # filtro, sem quebrar a tela.
    if prioridade in PRIORIDADES:
        condicoes.append('demandas.prioridade = ?')
        params.append(prioridade)
        filtros_ativos['prioridade'] = prioridade

    if status in STATUS_OPCOES:
        condicoes.append('demandas.status = ?')
        params.append(status)
        filtros_ativos['status'] = status

    if responsavel_filtro.isdigit():
        condicoes.append('demandas.responsavel_id = ?')
        params.append(int(responsavel_filtro))
        filtros_ativos['responsavel_id'] = responsavel_filtro

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
    )


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


def _validar_demanda(conn, titulo, descricao, solicitante_id, responsavel_id, prioridade, status):
    erros = []
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

        erros = _validar_demanda(conn, titulo, descricao, solicitante_id, responsavel_id, prioridade, status)

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
            ), 400

        conn.execute(
            'INSERT INTO demandas (titulo, descricao, solicitante_id, responsavel_id, data_criacao, prioridade, status) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (
                titulo, descricao, solicitante_id, responsavel_id,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'), prioridade, status,
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

        erros = _validar_demanda(conn, titulo, descricao, solicitante_id, responsavel_id, prioridade, status)

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
            }
            return render_template(
                'editar.html',
                demanda=demanda_exibir,
                prioridades=PRIORIDADES,
                status_opcoes=STATUS_OPCOES,
                usuarios=lista_usuarios,
            ), 400

        conn.execute(
            'UPDATE demandas SET titulo = ?, descricao = ?, solicitante_id = ?, '
            'responsavel_id = ?, prioridade = ?, status = ? WHERE id = ?',
            (titulo, descricao, solicitante_id, responsavel_id, prioridade, status, id),
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

    return render_template('detalhes.html', demanda=demanda, comentarios=comentarios)


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
