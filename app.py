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


def get_db():
    conn = sqlite3.connect('demandas.db')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def migrar_banco():
    """Evolui bancos criados antes desta mudança sem perder dados:
    - garante a coluna 'prioridade' (com CHECK) se ainda não existir;
    - transforma o campo livre 'solicitante' (texto) em vínculo com a
      tabela 'usuarios' via 'solicitante_id', preservando os nomes já
      cadastrados como usuários."""
    try:
        conn = get_db()
        colunas = [col[1] for col in conn.execute('PRAGMA table_info(demandas)').fetchall()]

        if 'prioridade' not in colunas:
            conn.execute(
                "ALTER TABLE demandas ADD COLUMN prioridade TEXT DEFAULT 'Média' "
                "CHECK(prioridade IN ('Alta', 'Média', 'Baixa'))"
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

        conn.execute('CREATE INDEX IF NOT EXISTS idx_demandas_prioridade ON demandas(prioridade)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_demandas_solicitante ON demandas(solicitante_id)')
        conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        # Banco/tabela ainda não existe: rode "python init_db.py" primeiro.
        pass


def listar_usuarios(conn):
    return conn.execute('SELECT * FROM usuarios ORDER BY nome').fetchall()


@app.route('/')
def index():
    termo_busca = request.args.get('q', '').strip()
    prioridade = request.args.get('prioridade', '').strip()

    query = '''
        SELECT demandas.id, demandas.titulo, demandas.descricao,
               demandas.solicitante_id, demandas.data_criacao, demandas.prioridade,
               usuarios.nome AS solicitante_nome
        FROM demandas
        JOIN usuarios ON usuarios.id = demandas.solicitante_id
        WHERE 1=1
    '''
    params = []

    if termo_busca:
        like = f'%{termo_busca}%'
        query += ' AND (demandas.titulo LIKE ? OR demandas.descricao LIKE ? OR usuarios.nome LIKE ?)'
        params.extend([like, like, like])

    # Valor inválido de prioridade é ignorado no filtro, sem quebrar a tela.
    if prioridade in PRIORIDADES:
        query += ' AND demandas.prioridade = ?'
        params.append(prioridade)

    query += '''
        ORDER BY
            CASE demandas.prioridade
                WHEN 'Alta' THEN 1
                WHEN 'Média' THEN 2
                WHEN 'Baixa' THEN 3
                ELSE 4
            END,
            demandas.id
    '''

    conn = get_db()
    demandas = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        'index.html',
        demandas=demandas,
        termo_busca=termo_busca,
        prioridade_selecionada=prioridade,
        prioridades=PRIORIDADES,
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
        'SELECT COUNT(*) AS total FROM demandas WHERE solicitante_id = ?', (id,)
    ).fetchone()['total']

    if total_demandas > 0:
        conn.close()
        flash(
            f'Não é possível excluir: esse usuário ainda tem {total_demandas} '
            f'demanda(s) vinculada(s). Edite ou apague essas demandas primeiro.'
        )
        return redirect(url_for('usuarios'))

    conn.execute('DELETE FROM usuarios WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Usuário excluído!')
    return redirect(url_for('usuarios'))


@app.route('/nova_demanda', methods=['GET', 'POST'])
def nova_demanda():
    conn = get_db()

    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        solicitante_id = request.form.get('solicitante_id', '').strip()
        prioridade = request.form.get('prioridade', 'Média').strip()

        erros = []
        if not titulo or not descricao or not solicitante_id:
            erros.append('Preencha todos os campos obrigatórios.')
        if prioridade not in PRIORIDADES:
            erros.append('Prioridade inválida. Escolha Alta, Média ou Baixa.')

        usuario_valido = None
        if solicitante_id:
            usuario_valido = conn.execute('SELECT id FROM usuarios WHERE id = ?', (solicitante_id,)).fetchone()
            if usuario_valido is None:
                erros.append('Selecione um solicitante cadastrado.')

        if erros:
            for erro in erros:
                flash(erro)
            lista_usuarios = listar_usuarios(conn)
            conn.close()
            return render_template(
                'nova_demanda.html',
                prioridades=PRIORIDADES,
                usuarios=lista_usuarios,
                titulo=titulo,
                descricao=descricao,
                solicitante_id=solicitante_id,
            ), 400

        conn.execute(
            'INSERT INTO demandas (titulo, descricao, solicitante_id, data_criacao, prioridade) '
            'VALUES (?, ?, ?, ?, ?)',
            (titulo, descricao, solicitante_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), prioridade),
        )
        conn.commit()
        conn.close()

        flash('Salvo!')
        return redirect(url_for('index'))

    lista_usuarios = listar_usuarios(conn)
    conn.close()
    return render_template('nova_demanda.html', prioridades=PRIORIDADES, usuarios=lista_usuarios)


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar(id):
    conn = get_db()

    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        solicitante_id = request.form.get('solicitante_id', '').strip()
        prioridade = request.form.get('prioridade', 'Média').strip()

        erros = []
        if not titulo or not descricao or not solicitante_id:
            erros.append('Preencha todos os campos obrigatórios.')
        if prioridade not in PRIORIDADES:
            erros.append('Prioridade inválida. Escolha Alta, Média ou Baixa.')

        if solicitante_id:
            usuario_valido = conn.execute('SELECT id FROM usuarios WHERE id = ?', (solicitante_id,)).fetchone()
            if usuario_valido is None:
                erros.append('Selecione um solicitante cadastrado.')

        if erros:
            for erro in erros:
                flash(erro)
            demanda = conn.execute('SELECT * FROM demandas WHERE id = ?', (id,)).fetchone()
            lista_usuarios = listar_usuarios(conn)
            conn.close()
            return render_template(
                'editar.html', demanda=demanda, prioridades=PRIORIDADES, usuarios=lista_usuarios
            ), 400

        conn.execute(
            'UPDATE demandas SET titulo = ?, descricao = ?, solicitante_id = ?, prioridade = ? WHERE id = ?',
            (titulo, descricao, solicitante_id, prioridade, id),
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

    return render_template('editar.html', demanda=demanda, prioridades=PRIORIDADES, usuarios=lista_usuarios)


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
               demandas.solicitante_id, demandas.data_criacao, demandas.prioridade,
               usuarios.nome AS solicitante_nome
        FROM demandas
        JOIN usuarios ON usuarios.id = demandas.solicitante_id
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
