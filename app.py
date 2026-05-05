from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime
from prometheus_flask_exporter import PrometheusMetrics
import logging
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from prometheus_client import Counter

app = Flask(__name__)
app.secret_key = '123456'
metrics = PrometheusMetrics(app, path='/metrics')

requests_por_endpoint = Counter(
    'api_requests_por_endpoint_total',
    'Total de requests por endpoint e método',
    ['method', 'endpoint']
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s app=flask message=%(message)s'
)

logger = logging.getLogger(__name__)

resource = Resource(attributes={
    "service.name": "flask-api"
})

trace.set_tracer_provider(TracerProvider(resource=resource))

otlp_exporter = OTLPSpanExporter(
    endpoint="http://tempo:4317",
    insecure=True
)

trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

tracer = trace.get_tracer(__name__)

FlaskInstrumentor().instrument_app(app)

def get_db():
    conn = sqlite3.connect('demandas.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.after_request
def contar_requests(response):
    endpoint = request.path
    method = request.method

    requests_por_endpoint.labels(
        method=method,
        endpoint=endpoint
    ).inc()

    return response

@app.route('/')
def index():
    logger.info("Acessou a página inicial")
    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()
    demandas = cursor.execute('SELECT * FROM demandas').fetchall()
    conn.close()
    return render_template('index.html', demandas=demandas)


# @app.route('/nova_demanda', methods=['GET', 'POST'])
# def nova_demanda():
#     if request.method == 'POST':
#         titulo = request.form['titulo']
#         descricao = request.form['descricao']
#         solicitante = request.form['solicitante']
#
#
#         conn = sqlite3.connect('demandas.db')
#         cursor = conn.cursor()
#
#         cursor.execute(
#             f"INSERT INTO demandas (titulo, descricao, solicitante, data_criacao) VALUES ('{titulo}', '{descricao}', '{solicitante}', '{datetime.now()}')")
#         conn.commit()
#         conn.close()
#         logger.info(f"Nova demanda criada por {solicitante}: {titulo}")
#
#         flash('Salvo!')
#         return redirect('/')
#
#     return render_template('nova_demanda.html')
@app.route('/nova_demanda', methods=['GET', 'POST'])
def nova_demanda():
    with tracer.start_as_current_span("nova_demanda") as span:
        span.set_attribute("http.route", "/nova_demanda")
        span.set_attribute("http.method", request.method)

        if request.method == 'POST':
            titulo = request.form['titulo']
            descricao = request.form['descricao']
            solicitante = request.form['solicitante']

            span.set_attribute("demanda.titulo", titulo)
            span.set_attribute("demanda.solicitante", solicitante)

            try:
                conn = sqlite3.connect('demandas.db')
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO demandas 
                    (titulo, descricao, solicitante, data_criacao) 
                    VALUES (?, ?, ?, ?)
                    """,
                    (titulo, descricao, solicitante, datetime.now())
                )

                conn.commit()
                conn.close()

                span.set_attribute("status", "success")
                logger.info(f"Nova demanda criada por {solicitante}: {titulo}")

                flash('Salvo!')
                return redirect('/')

            except Exception as e:
                span.set_attribute("status", "error")
                span.record_exception(e)
                logger.error(f"Erro ao criar demanda: {e}")
                raise

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