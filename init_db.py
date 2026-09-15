import sqlite3
import os

DB_PATH = 'demandas.db'

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute('PRAGMA foreign_keys = ON')

cursor.execute('''
CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE
)
''')

cursor.execute('''
CREATE TABLE demandas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descricao TEXT NOT NULL,
    solicitante_id INTEGER NOT NULL,
    data_criacao TEXT NOT NULL,
    prioridade TEXT NOT NULL DEFAULT 'Média' CHECK(prioridade IN ('Alta', 'Média', 'Baixa')),
    FOREIGN KEY (solicitante_id) REFERENCES usuarios(id)
)
''')

cursor.execute('''
CREATE TABLE comentarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demanda_id INTEGER NOT NULL,
    comentario TEXT NOT NULL,
    autor TEXT NOT NULL,
    data TEXT NOT NULL,
    FOREIGN KEY (demanda_id) REFERENCES demandas(id) ON DELETE CASCADE
)
''')

cursor.execute('CREATE INDEX idx_demandas_prioridade ON demandas(prioridade)')
cursor.execute('CREATE INDEX idx_demandas_solicitante ON demandas(solicitante_id)')

usuarios = ['João Silva', 'Maria Santos', 'Pedro Costa', 'Carlos Mendes', 'Ana Lima']
for nome in usuarios:
    cursor.execute('INSERT INTO usuarios (nome) VALUES (?)', (nome,))

# id 1=João Silva, 2=Maria Santos, 3=Pedro Costa, 4=Carlos Mendes, 5=Ana Lima
cursor.execute(
    "INSERT INTO demandas (id, titulo, descricao, solicitante_id, data_criacao, prioridade) "
    "VALUES (1, 'Corrigir bug no login', 'Usuários não conseguem fazer login', 1, '2024-01-15 10:30:00', 'Alta')"
)
cursor.execute(
    "INSERT INTO demandas (id, titulo, descricao, solicitante_id, data_criacao, prioridade) "
    "VALUES (2, 'Implementar relatório de vendas', 'Precisamos de um relatório mensal', 2, '2024-01-16 14:20:00', 'Média')"
)
cursor.execute(
    "INSERT INTO demandas (id, titulo, descricao, solicitante_id, data_criacao, prioridade) "
    "VALUES (3, 'Melhorar performance', 'Sistema está lento', 3, '2024-01-17 09:15:00', 'Alta')"
)
cursor.execute(
    "INSERT INTO demandas (id, titulo, descricao, solicitante_id, data_criacao, prioridade) "
    "VALUES (4, 'Atualizar documentação', 'Manual do sistema desatualizado', 4, '2024-01-17 16:45:00', 'Baixa')"
)
cursor.execute(
    # Sem informar a coluna prioridade de proposito: demonstra que o
    # DEFAULT 'Média' do banco entra em acao sozinho.
    "INSERT INTO demandas (id, titulo, descricao, solicitante_id, data_criacao) "
    "VALUES (5, 'Adicionar filtros', 'Usuários querem filtrar demandas', 5, '2024-01-18 11:00:00')"
)

cursor.execute(
    "INSERT INTO comentarios (demanda_id, comentario, autor, data) VALUES (1, 'Vou investigar esse bug', 'Tech Team', '2024-01-15 11:00:00')"
)
cursor.execute(
    "INSERT INTO comentarios (demanda_id, comentario, autor, data) VALUES (1, 'Bug corrigido na branch develop', 'Desenvolvedor', '2024-01-15 16:30:00')"
)
cursor.execute(
    "INSERT INTO comentarios (demanda_id, comentario, autor, data) VALUES (2, 'Precisamos definir o layout do relatório', 'PO', '2024-01-16 09:00:00')"
)

conn.commit()
conn.close()

print('Banco de dados criado com sucesso!')
