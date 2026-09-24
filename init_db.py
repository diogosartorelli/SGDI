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
    responsavel_id INTEGER NOT NULL,
    data_criacao TEXT NOT NULL,
    prioridade TEXT NOT NULL DEFAULT 'Média' CHECK(prioridade IN ('Alta', 'Média', 'Baixa')),
    status TEXT NOT NULL DEFAULT 'Aberta' CHECK(status IN ('Aberta', 'Em andamento', 'Concluída')),
    FOREIGN KEY (solicitante_id) REFERENCES usuarios(id),
    FOREIGN KEY (responsavel_id) REFERENCES usuarios(id)
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
cursor.execute('CREATE INDEX idx_demandas_responsavel ON demandas(responsavel_id)')
cursor.execute('CREATE INDEX idx_demandas_status ON demandas(status)')

usuarios = ['João Silva', 'Maria Santos', 'Pedro Costa', 'Carlos Mendes', 'Ana Lima']
for nome in usuarios:
    cursor.execute('INSERT INTO usuarios (nome) VALUES (?)', (nome,))

# id 1=João Silva, 2=Maria Santos, 3=Pedro Costa, 4=Carlos Mendes, 5=Ana Lima
# (titulo, descricao, solicitante_id, responsavel_id, data_criacao, prioridade, status)
demandas_exemplo = [
    ('Corrigir bug no login', 'Usuários não conseguem fazer login', 1, 2, '2024-01-15 10:30:00', 'Alta', 'Em andamento'),
    ('Implementar relatório de vendas', 'Precisamos de um relatório mensal', 2, 4, '2024-01-16 14:20:00', 'Média', 'Aberta'),
    ('Melhorar performance', 'Sistema está lento', 3, 1, '2024-01-17 09:15:00', 'Alta', 'Aberta'),
    ('Atualizar documentação', 'Manual do sistema desatualizado', 4, 5, '2024-01-17 16:45:00', 'Baixa', 'Concluída'),
    ('Adicionar filtros', 'Usuários querem filtrar demandas', 5, 3, '2024-01-18 11:00:00', 'Média', 'Concluída'),
    ('Corrigir layout mobile', 'Tela quebra no celular', 1, 1, '2024-01-19 08:30:00', 'Alta', 'Aberta'),
    ('Integrar e-mail', 'Enviar notificação por e-mail ao criar demanda', 2, 3, '2024-01-19 13:10:00', 'Média', 'Aberta'),
    ('Exportar dados em CSV', 'Cliente quer baixar os dados', 2, 4, '2024-01-20 13:10:00', 'Baixa', 'Aberta'),
    ('Revisar textos do sistema', 'Alguns textos estão com erro de português', 3, 2, '2024-01-21 15:40:00', 'Baixa', 'Em andamento'),
    ('Configurar backup automático', 'Evitar perda de dados', 4, 1, '2024-01-22 09:00:00', 'Alta', 'Em andamento'),
    ('Padronizar botões da tela', 'Botões com tamanhos diferentes', 5, 5, '2024-01-23 10:20:00', 'Média', 'Aberta'),
    ('Adicionar campo de telefone', 'Cadastro de usuário sem telefone', 1, 2, '2024-01-24 14:00:00', 'Média', 'Concluída'),
    ('Investigar lentidão no relatório', 'Relatório mensal demora pra carregar', 2, 4, '2024-01-25 17:30:00', 'Alta', 'Aberta'),
]

for titulo, descricao, solicitante_id, responsavel_id, data_criacao, prioridade, status in demandas_exemplo:
    cursor.execute(
        'INSERT INTO demandas (titulo, descricao, solicitante_id, responsavel_id, data_criacao, prioridade, status) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (titulo, descricao, solicitante_id, responsavel_id, data_criacao, prioridade, status),
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
