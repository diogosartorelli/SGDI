"""Camada de logs de auditoria do SGDI.

Objetivo: registrar de forma centralizada, segura e padronizada as ações
importantes feitas no sistema (quem fez, quando, de onde, o quê e em qual
registro), para permitir auditorias, análise de incidentes e rastreamento de
alterações.

Princípios:
- Padronizado: toda ação tem um código fixo (ver ACOES) e o mesmo formato de
  registro (data/hora, usuário, IP, ação, entidade, descrição e detalhes em JSON).
- Seguro: a tabela é "somente inclusão". Triggers do SQLite bloqueiam UPDATE e
  DELETE, então um log gravado não pode ser alterado nem apagado pela aplicação.
- Consistente: o log é gravado na MESMA transação da mudança. Se a mudança
  falhar, o log não existe; se o log falhar, a mudança é desfeita.
- Histórico preservado: o nome do usuário é copiado para o log (não é chave
  estrangeira), então o registro continua legível mesmo se o usuário for excluído.

Este módulo não depende do Flask: quem chama informa o contexto (usuário, IP).
"""
import json
from datetime import datetime

# código da ação -> (rótulo mostrado na tela, tom da etiqueta)
ACOES = {
    'demanda.criada':        ('Demanda criada', 'verde'),
    'demanda.editada':       ('Demanda editada', 'azul'),
    'demanda.excluida':      ('Demanda excluída', 'vermelho'),
    'comentario.adicionado': ('Comentário adicionado', 'amarelo'),
    'usuario.criado':        ('Usuário criado', 'verde'),
    'usuario.excluido':      ('Usuário excluído', 'vermelho'),
    'relatorio.exportado':   ('Relatório exportado', 'mudo'),
    'auditoria.exportada':   ('Logs exportados', 'mudo'),
    'sessao.identificada':   ('Usuário identificado', 'mudo'),
    'sessao.encerrada':      ('Identificação encerrada', 'mudo'),
    'sistema.iniciado':      ('Registro do sistema', 'mudo'),
}

USUARIO_PADRAO = 'Não identificado'

SQL_ESTRUTURA = '''
CREATE TABLE IF NOT EXISTS logs_auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL,
    usuario_id INTEGER,
    usuario_nome TEXT NOT NULL DEFAULT 'Não identificado',
    ip TEXT,
    agente TEXT,
    acao TEXT NOT NULL,
    entidade TEXT,
    entidade_id INTEGER,
    descricao TEXT NOT NULL,
    detalhes TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_data ON logs_auditoria(data_hora);
CREATE INDEX IF NOT EXISTS idx_logs_acao ON logs_auditoria(acao);
CREATE INDEX IF NOT EXISTS idx_logs_entidade ON logs_auditoria(entidade, entidade_id);
CREATE INDEX IF NOT EXISTS idx_logs_usuario ON logs_auditoria(usuario_nome);
CREATE TRIGGER IF NOT EXISTS logs_auditoria_sem_update
BEFORE UPDATE ON logs_auditoria
BEGIN
    SELECT RAISE(ABORT, 'Logs de auditoria são imutáveis: UPDATE não permitido.');
END;
CREATE TRIGGER IF NOT EXISTS logs_auditoria_sem_delete
BEFORE DELETE ON logs_auditoria
BEGIN
    SELECT RAISE(ABORT, 'Logs de auditoria são imutáveis: DELETE não permitido.');
END;
'''


def criar_estrutura(conn):
    """Cria a tabela de logs (e índices/triggers) se ainda não existir.
    Devolve True se acabou de criar, False se já existia."""
    existia = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'logs_auditoria'"
    ).fetchone() is not None
    conn.executescript(SQL_ESTRUTURA)
    return not existia


def agora():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def registrar(conn, acao, descricao, *, entidade=None, entidade_id=None,
              detalhes=None, contexto=None):
    """Grava um evento. NÃO faz commit: quem chama confirma junto com a mudança.

    contexto: dict opcional com usuario_id, usuario_nome, ip, agente.
    detalhes: dict serializável em JSON (dados completos do evento).
    """
    if acao not in ACOES:
        raise ValueError(f'Ação de auditoria desconhecida: {acao}')
    contexto = contexto or {}
    cursor = conn.execute(
        'INSERT INTO logs_auditoria (data_hora, usuario_id, usuario_nome, ip, agente, '
        'acao, entidade, entidade_id, descricao, detalhes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            agora(),
            contexto.get('usuario_id'),
            contexto.get('usuario_nome') or USUARIO_PADRAO,
            (contexto.get('ip') or '')[:64] or None,
            (contexto.get('agente') or '')[:200] or None,
            acao,
            entidade,
            entidade_id,
            descricao,
            json.dumps(detalhes, ensure_ascii=False, default=str) if detalhes else None,
        ),
    )
    return cursor.lastrowid


# ---------------------------------------------------------------- alterações

ROTULOS_DEMANDA = {
    'titulo': 'Título',
    'descricao': 'Descrição',
    'solicitante': 'Solicitante',
    'responsavel': 'Responsável',
    'prioridade': 'Prioridade',
    'status': 'Status',
    'prazo': 'Prazo',
}


def comparar(antes, depois, rotulos=ROTULOS_DEMANDA):
    """Lista o que mudou entre dois dicts: [{'campo', 'rotulo', 'de', 'para'}]."""
    mudancas = []
    for campo, rotulo in rotulos.items():
        a, d = antes.get(campo), depois.get(campo)
        if (a or '') != (d or ''):
            mudancas.append({'campo': campo, 'rotulo': rotulo, 'de': a, 'para': d})
    return mudancas


def _legivel(campo, valor, limite=50):
    if valor in (None, ''):
        return '—'
    texto = str(valor)
    if campo == 'prazo':
        try:
            return datetime.strptime(texto, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            return texto
    return texto if len(texto) <= limite else texto[:limite - 1] + '…'


def descrever_mudancas(mudancas):
    """'Status: Aberta → Concluída; Prazo: — → 12/10/2026'"""
    return '; '.join(
        f"{m['rotulo']}: {_legivel(m['campo'], m['de'])} → {_legivel(m['campo'], m['para'])}"
        for m in mudancas
    )


# ------------------------------------------------------------------ consulta

def filtros_da_consulta(args):
    """Converte os parâmetros da URL em (condições SQL, parâmetros, filtros ativos)."""
    condicoes, params, ativos = [], [], {}

    for chave, operador, sufixo in (('de', '>=', ' 00:00:00'), ('ate', '<=', ' 23:59:59')):
        valor = (args.get(chave) or '').strip()
        if valor:
            try:
                datetime.strptime(valor, '%Y-%m-%d')
            except ValueError:
                continue
            condicoes.append(f'data_hora {operador} ?')
            params.append(valor + sufixo)
            ativos[chave] = valor

    usuario = (args.get('usuario') or '').strip()
    if usuario:
        condicoes.append('usuario_nome = ?')
        params.append(usuario)
        ativos['usuario'] = usuario

    acao = (args.get('acao') or '').strip()
    if acao in ACOES:
        condicoes.append('acao = ?')
        params.append(acao)
        ativos['acao'] = acao

    entidade = (args.get('entidade') or '').strip()
    if entidade:
        condicoes.append('entidade = ?')
        params.append(entidade)
        ativos['entidade'] = entidade
        entidade_id = (args.get('entidade_id') or '').strip()
        if entidade_id.isdigit():
            condicoes.append('entidade_id = ?')
            params.append(int(entidade_id))
            ativos['entidade_id'] = entidade_id

    termo = (args.get('q') or '').strip()
    if termo:
        condicoes.append('(descricao LIKE ? OR usuario_nome LIKE ? OR ip LIKE ?)')
        params.extend([f'%{termo}%'] * 3)
        ativos['q'] = termo

    return condicoes, params, ativos


def consultar(conn, condicoes, params, pagina=1, tamanho=15):
    """Página de logs (mais recentes primeiro) + total."""
    where = ('WHERE ' + ' AND '.join(condicoes)) if condicoes else ''
    total = conn.execute(f'SELECT COUNT(*) AS n FROM logs_auditoria {where}', params).fetchone()['n']
    paginas = max(1, (total + tamanho - 1) // tamanho)
    pagina = min(max(1, pagina), paginas)
    linhas = conn.execute(
        f'SELECT * FROM logs_auditoria {where} ORDER BY id DESC LIMIT ? OFFSET ?',
        params + [tamanho, (pagina - 1) * tamanho],
    ).fetchall()
    return {'linhas': [_preparar(l) for l in linhas], 'total': total, 'pagina': pagina, 'paginas': paginas}


def todos(conn, condicoes, params):
    """Todos os logs que passam nos filtros (para exportação), em ordem cronológica."""
    where = ('WHERE ' + ' AND '.join(condicoes)) if condicoes else ''
    return [_preparar(l) for l in conn.execute(
        f'SELECT * FROM logs_auditoria {where} ORDER BY id', params).fetchall()]


def _preparar(linha):
    registro = dict(linha)
    try:
        registro['detalhes'] = json.loads(registro['detalhes']) if registro['detalhes'] else None
    except ValueError:
        registro['detalhes'] = None
    rotulo, tom = ACOES.get(registro['acao'], (registro['acao'], 'mudo'))
    registro['acao_rotulo'] = rotulo
    registro['acao_tom'] = tom
    return registro


def historico_da_entidade(conn, entidade, entidade_id, limite=30):
    """Eventos de um registro específico (ex.: demanda 3), mais recentes primeiro."""
    linhas = conn.execute(
        'SELECT * FROM logs_auditoria WHERE entidade = ? AND entidade_id = ? ORDER BY id DESC LIMIT ?',
        (entidade, entidade_id, limite),
    ).fetchall()
    return [_preparar(l) for l in linhas]


def usuarios_nos_logs(conn):
    return [r[0] for r in conn.execute(
        'SELECT DISTINCT usuario_nome FROM logs_auditoria ORDER BY usuario_nome').fetchall()]
