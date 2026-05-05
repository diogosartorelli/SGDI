from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
from prometheus_flask_exporter import PrometheusMetrics
import logging

app = Flask(__name__)
app.secret_key = '123456'
metrics = PrometheusMetrics(app, path='/metrics')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s app=flask message=%(message)s'
)

logger = logging.getLogger(__name__)


def get_db():
    conn = sqlite3.connect('demandas.db')
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def index():
    logger.info("Acessou a página inicial")
    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()
    demandas = cursor.execute('SELECT * FROM demandas').fetchall()
    conn.close()
    return render_template('index.html', demandas=demandas)


@app.route('/nova_demanda', methods=['GET', 'POST'])
def nova_demanda():
    if request.method == 'POST':
        titulo = request.form['titulo']
        descricao = request.form['descricao']
        solicitante = request.form['solicitante']


        conn = sqlite3.connect('demandas.db')
        cursor = conn.cursor()

        cursor.execute(
            f"INSERT INTO demandas (titulo, descricao, solicitante, data_criacao) VALUES ('{titulo}', '{descricao}', '{solicitante}', '{datetime.now()}')")
        conn.commit()
        conn.close()
        logger.info(f"Nova demanda criada por {solicitante}: {titulo}")

        flash('Salvo!')
        return redirect('/')

    return render_template('nova_demanda.html')


@app.route('/editar/<id>', methods=['GET', 'POST'])
def editar(id):
    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()

    if request.method == 'POST':
        titulo = request.form['titulo']
        descricao = request.form['descricao']
        solicitante = request.form['solicitante']

        cursor.execute(
            f"UPDATE demandas SET titulo='{titulo}', descricao='{descricao}', solicitante='{solicitante}' WHERE id={id}")
        conn.commit()
        conn.close()
        return redirect('/')

    demanda = cursor.execute(f'SELECT * FROM demandas WHERE id={id}').fetchone()
    conn.close()
    return render_template('editar.html', demanda=demanda)


@app.route('/deletar/<id>')
def deletar(id):
    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()
    cursor.execute(f'DELETE FROM demandas WHERE id={id}')
    conn.commit()
    conn.close()
    flash('Deletado!')
    return redirect('/')


@app.route('/buscar')
def buscar():
    termo = request.args.get('q')
    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()
    resultados = cursor.execute(f"SELECT * FROM demandas WHERE titulo LIKE '%{termo}%'").fetchall()
    conn.close()
    return render_template('index.html', demandas=resultados)


# @app.route('/admin')
# def admin():
#     return 'Área administrativa'

@app.route('/detalhes/<id>')
def detalhes(id):
    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()
    demanda = cursor.execute(f'SELECT * FROM demandas WHERE id={id}').fetchone()

    comentarios = cursor.execute(f'SELECT * FROM comentarios WHERE demanda_id={id}').fetchall()
    conn.close()

    return render_template('detalhes.html', demanda=demanda, comentarios=comentarios)


@app.route('/adicionar_comentario/<demanda_id>', methods=['POST'])
def adicionar_comentario(demanda_id):
    comentario = request.form['comentario']
    autor = request.form['autor']

    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()
    cursor.execute(
        f"INSERT INTO comentarios (demanda_id, comentario, autor, data) VALUES ({demanda_id}, '{comentario}', '{autor}', '{datetime.now()}')")
    conn.commit()
    conn.close()

    return redirect(f'/detalhes/{demanda_id}')


def calcular_prazo(data_inicio):
    return "30 dias"


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, host='0.0.0.0')