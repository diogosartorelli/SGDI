from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-in-production')

PRIORIDADES = ['Alta', 'Média', 'Baixa']


def get_db():
    conn = sqlite3.connect('demandas.db')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def migrar_banco():
    """Garante que bancos criados antes desta sprint ganhem a coluna
    'prioridade' sem perder as demandas já cadastradas (ADR-01, decisão 7)."""
    try:
        conn = get_db()
        colunas = [col[1] for col in conn.execute('PRAGMA table_info(demandas)').fetchall()]
        if 'prioridade' not in colunas:
            conn.execute(
                "ALTER TABLE demandas ADD COLUMN prioridade TEXT DEFAULT 'Média' "
                "CHECK(prioridade IN ('Alta', 'Média', 'Baixa'))"
            )
            conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        # Banco/tabela ainda não existe: rode "python init_db.py" primeiro.
        pass


@app.route('/')
def index():
    termo_busca = request.args.get('q', '').strip()
    prioridade = request.args.get('prioridade', '').strip()

    query = 'SELECT * FROM demandas WHERE 1=1'
    params = []

    if termo_busca:
        like = f'%{termo_busca}%'
        query += ' AND (titulo LIKE ? OR descricao LIKE ? OR solicitante LIKE ?)'
        params.extend([like, like, like])

    # Valor inválido de prioridade é ignorado no filtro, sem quebrar a tela
    # (critério de aceite da ADR-01).
    if prioridade in PRIORIDADES:
        query += ' AND prioridade = ?'
        params.append(prioridade)

    query += '''
        ORDER BY
            CASE prioridade
                WHEN 'Alta' THEN 1
                WHEN 'Média' THEN 2
                WHEN 'Baixa' THEN 3
                ELSE 4
            END,
            id
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


@app.route('/nova_demanda', methods=['GET', 'POST'])
def nova_demanda():
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        solicitante = request.form.get('solicitante', '').strip()
        prioridade = request.form.get('prioridade', 'Média').strip()

        erros = []
        if not titulo or not descricao or not solicitante:
            erros.append('Preencha todos os campos obrigatórios.')
        if prioridade not in PRIORIDADES:
            erros.append('Prioridade inválida. Escolha Alta, Média ou Baixa.')

        if erros:
            for erro in erros:
                flash(erro)
            return render_template(
                'nova_demanda.html',
                prioridades=PRIORIDADES,
                titulo=titulo,
                descricao=descricao,
                solicitante=solicitante,
            ), 400

        conn = get_db()
        conn.execute(
            'INSERT INTO demandas (titulo, descricao, solicitante, data_criacao, prioridade) '
            'VALUES (?, ?, ?, ?, ?)',
            (titulo, descricao, solicitante, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), prioridade),
        )
        conn.commit()
        conn.close()

        flash('Salvo!')
        return redirect(url_for('index'))

    return render_template('nova_demanda.html', prioridades=PRIORIDADES)


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar(id):
    conn = get_db()

    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        solicitante = request.form.get('solicitante', '').strip()
        prioridade = request.form.get('prioridade', 'Média').strip()

        erros = []
        if not titulo or not descricao or not solicitante:
            erros.append('Preencha todos os campos obrigatórios.')
        if prioridade not in PRIORIDADES:
            erros.append('Prioridade inválida. Escolha Alta, Média ou Baixa.')

        if erros:
            for erro in erros:
                flash(erro)
            demanda = conn.execute('SELECT * FROM demandas WHERE id = ?', (id,)).fetchone()
            conn.close()
            return render_template('editar.html', demanda=demanda, prioridades=PRIORIDADES), 400

        conn.execute(
            'UPDATE demandas SET titulo = ?, descricao = ?, solicitante = ?, prioridade = ? WHERE id = ?',
            (titulo, descricao, solicitante, prioridade, id),
        )
        conn.commit()
        conn.close()
        flash('Demanda atualizada!')
        return redirect(url_for('index'))

    demanda = conn.execute('SELECT * FROM demandas WHERE id = ?', (id,)).fetchone()
    conn.close()

    if demanda is None:
        flash('Demanda não encontrada.')
        return redirect(url_for('index'))

    return render_template('editar.html', demanda=demanda, prioridades=PRIORIDADES)


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
    # cabeçalho continuam funcionando (ADR-01, decisão 5).
    termo = request.args.get('q', '')
    return redirect(url_for('index', q=termo))


@app.route('/detalhes/<int:id>')
def detalhes(id):
    conn = get_db()
    demanda = conn.execute('SELECT * FROM demandas WHERE id = ?', (id,)).fetchone()

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