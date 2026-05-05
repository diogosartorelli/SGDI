# 📊 Observabilidade com Prometheus, Loki e Grafana

> **Para quem é este guia?**
> Este documento foi escrito para alunos que estão aprendendo sobre monitoramento de aplicações. Você não precisa saber tudo de antemão — a ideia é que este guia seja sua referência enquanto explora o projeto.

---

## 📌 Índice

1. [O que é Observabilidade?](#o-que-é-observabilidade)
2. [Os Três Pilares](#os-três-pilares)
3. [Arquitetura do Projeto](#arquitetura-do-projeto)
4. [Prometheus — Métricas](#prometheus--métricas)
5. [Loki — Logs](#loki--logs)
6. [Promtail — Coletor de Logs](#promtail--coletor-de-logs)
7. [Grafana — Visualização](#grafana--visualização)
8. [Como Tudo Se Conecta](#como-tudo-se-conecta)
9. [Consultando Logs com LogQL](#consultando-logs-com-logql)
10. [Consultando Métricas com PromQL](#consultando-métricas-com-promql)
11. [Criando Métricas Personalizadas](#criando-métricas-personalizadas)
12. [Rodando o Projeto](#rodando-o-projeto)
13. [Acessando as Ferramentas](#acessando-as-ferramentas)
14. [Exercícios Sugeridos](#exercícios-sugeridos)

---

## 🔍 O que é Observabilidade?

**Observabilidade** é a capacidade de entender o que está acontecendo **dentro** de um sistema a partir do que ele produz **para fora** — sem precisar modificar o código ou adivinhar.

Pense assim: você tem uma aplicação Flask rodando. Como saber se ela está saudável? Como descobrir por que ela ficou lenta às 14h? Como saber quantas requisições falharam hoje?

Sem observabilidade, você depende de:
- Reclamações de usuários
- Logs soltos que ninguém lê
- "Acho que deve estar funcionando"

Com observabilidade, você tem:
- Dashboards mostrando o estado do sistema em tempo real
- Alertas automáticos quando algo vai mal
- Capacidade de investigar problemas **no passado** (não só agora)

> 💡 **Analogia**: Observabilidade é como o painel do carro. Você não abre o motor toda vez que quer saber se está tudo bem — você olha o velocímetro, o nível de combustível, a temperatura do motor. Esses **indicadores** te dão visibilidade do sistema.

---

## 🏛️ Os Três Pilares

A observabilidade moderna é construída sobre três pilares:

| Pilar | O que é | Ferramenta neste projeto |
|-------|---------|--------------------------|
| **Métricas** | Números que variam ao longo do tempo (ex: quantas requisições por segundo) | Prometheus |
| **Logs** | Registros textuais de eventos que aconteceram | Loki |
| **Rastreamentos (Traces)** | O caminho completo de uma requisição pelo sistema | *(não implementado neste projeto)* |

```
┌─────────────────────────────────────────────────┐
│                  OBSERVABILIDADE                 │
│                                                 │
│   📊 Métricas    📄 Logs    🔗 Traces           │
│   "Quantos?"    "O quê?"   "Por onde?"          │
│   Prometheus     Loki      Jaeger/Zipkin         │
└─────────────────────────────────────────────────┘
```

> ⚠️ **Nota importante**: Métricas dizem **o que** está errado (ex: taxa de erro aumentou). Logs dizem **por que** está errado (ex: "NullPointerException na linha 42"). Você precisa dos dois para investigar problemas de verdade.

---

## 🏗️ Arquitetura do Projeto

Este projeto é uma aplicação Flask de gerenciamento de demandas com toda a stack de observabilidade configurada via Docker Compose:

```
┌─────────────────────────────────────────────────────────────────┐
│                        DOCKER COMPOSE                           │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  flask-api   │    │  prometheus  │    │    grafana   │      │
│  │  :5000       │◄───│  :9090       │◄───│    :3000     │      │
│  │              │    │              │    │              │      │
│  │ /metrics     │    │ scrape a     │    │ consulta     │      │
│  │ expõe dados  │    │ cada 5s      │    │ prometheus   │      │
│  └──────┬───────┘    └──────────────┘    │ e loki       │      │
│         │                                └──────┬───────┘      │
│         │ stdout/stderr                         │              │
│         ▼                                       │              │
│  ┌──────────────┐    ┌──────────────┐           │              │
│  │   promtail   │───►│     loki     │───────────┘              │
│  │  coleta logs │    │  :3100       │                          │
│  │  dos contrs  │    │  armazena    │                          │
│  └──────────────┘    └──────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📈 Prometheus — Métricas

### O que é?

**Prometheus** é um banco de dados de séries temporais (time-series database) especializado em métricas. Ele funciona no modelo **pull**: em vez de a aplicação empurrar dados para ele, o Prometheus vai até a aplicação e **busca** as métricas periodicamente.

### Como funciona?

1. Sua aplicação Flask expõe um endpoint `/metrics`
2. O Prometheus acessa esse endpoint a cada **5 segundos** (configurado no `prometheus.yml`)
3. Ele guarda esses números com um timestamp
4. Você consulta esses dados com a linguagem **PromQL**

### Configuração no projeto

**`prometheus.yml`** — diz ao Prometheus onde buscar métricas:

```yaml
global:
  scrape_interval: 5s      # coleta a cada 5 segundos

scrape_configs:
  - job_name: "flask-api"
    metrics_path: "/metrics"  # endpoint da aplicação
    static_configs:
      - targets: ["flask-api:5000"]  # endereço do container
```

### Como a aplicação Flask expõe métricas?

No `app.py`, usamos a biblioteca `prometheus_flask_exporter`:

```python
from prometheus_flask_exporter import PrometheusMetrics

app = Flask(__name__)
metrics = PrometheusMetrics(app, path='/metrics')
```

Isso cria automaticamente métricas como:
- `flask_http_request_total` — total de requisições por rota e status HTTP
- `flask_http_request_duration_seconds` — tempo de resposta por rota
- `flask_http_request_exceptions_total` — exceções ocorridas

### Tipos de métricas no Prometheus

| Tipo | Descrição | Exemplo |
|------|-----------|---------|
| **Counter** | Só sobe, nunca desce. Conta eventos. | Total de requisições |
| **Gauge** | Pode subir e descer. Estado atual. | Uso de memória, conexões abertas |
| **Histogram** | Distribui valores em buckets. | Tempo de resposta (p50, p90, p99) |
| **Summary** | Similar ao histogram, mas calcula percentis no cliente. | Latência calculada pela app |

> 💡 **Regra prática**: Use **Counter** para "quantas vezes X aconteceu". Use **Gauge** para "qual é o valor de X agora". Use **Histogram** para "quanto tempo X levou".

---

## 📄 Loki — Logs

### O que é?

**Loki** é um sistema de agregação de logs criado pela Grafana Labs. Ele foi projetado para ser simples e econômico: em vez de indexar o **conteúdo** dos logs (como o Elasticsearch faz), ele indexa apenas os **labels** (metadados).

### A filosofia do Loki

```
Elasticsearch:  indexa TUDO → pesquisa rápida → caro e pesado
      Loki:  indexa só labels → pesquisa eficiente → leve e barato
```

Isso significa que no Loki você:
- Filtra primeiro pelos **labels** (ex: qual container? qual ambiente?)
- Depois filtra pelo **conteúdo** do texto dentro desses logs

### Configuração no projeto

**`loki-config.yml`** — configuração básica:

```yaml
auth_enabled: false    # sem autenticação (desenvolvimento)

server:
  http_listen_port: 3100

common:
  path_prefix: /tmp/loki
  storage:
    filesystem:
      chunks_directory: /tmp/loki/chunks  # onde os logs ficam salvos
```

### O que são Labels no Loki?

Labels são **metadados** que identificam de onde vem um log. Pense neles como tags.

No nosso projeto, o Promtail adiciona automaticamente:
- `container` → nome do container Docker (ex: `flask-api`)
- `stream` → `stdout` ou `stderr`

Você filtra logs por label antes de qualquer outra coisa.

---

## 🚚 Promtail — Coletor de Logs

### O que é?

**Promtail** é o agente responsável por **coletar logs** dos containers Docker e enviá-los ao Loki. Ele é o intermediário entre sua aplicação e o Loki.

### Como funciona?

```
Container Flask → gera logs no stdout
       ↓
   Promtail (ouve o Docker socket)
       ↓
   Adiciona labels (container=flask-api, stream=stdout)
       ↓
   Envia para Loki via HTTP
```

### Configuração no projeto

**`promtail-config.yml`**:

```yaml
clients:
  - url: http://loki:3100/loki/api/v1/push  # envia para o Loki

scrape_configs:
  - job_name: docker-logs
    docker_sd_configs:
      - host: unix:///var/run/docker.sock  # ouve o Docker
        refresh_interval: 5s

    relabel_configs:
      # pega o nome do container e usa como label
      - source_labels: ["__meta_docker_container_name"]
        regex: "/(.*)"
        target_label: "container"
```

> 💡 **Dica**: O Promtail monta o socket do Docker (`/var/run/docker.sock`) para conseguir descobrir automaticamente quais containers estão rodando. É por isso que no `docker-compose.yml` tem esse volume:
> ```yaml
> - /var/run/docker.sock:/var/run/docker.sock:ro
> ```

---

## 📊 Grafana — Visualização

### O que é?

**Grafana** é a ferramenta de visualização que conecta tudo. Ele não armazena dados — ele consulta o Prometheus e o Loki e transforma esses dados em gráficos, tabelas e dashboards.

### Datasources

No Grafana, você configura **datasources** (fontes de dados). No nosso projeto:

`grafana/provisioning/datasources/datasources.yml` provisiona automaticamente:
- **Prometheus** em `http://prometheus:9090`
- **Loki** em `http://loki:3100`

### Dashboards

Dashboards são coleções de painéis (gráficos, tabelas, alertas). O projeto tem um dashboard pré-configurado em `grafana/dashboards/`.

> 💡 **Dica para alunos**: Ao abrir o Grafana, vá em **Dashboards** no menu lateral. O dashboard do projeto já está lá pronto para você explorar.

---

## 🔗 Como Tudo Se Conecta

Aqui está o fluxo completo de ponta a ponta:

### Fluxo de Métricas

```
1. Usuário acessa /nova_demanda
           ↓
2. Flask processa e responde
           ↓
3. prometheus_flask_exporter registra:
   - +1 requisição em flask_http_request_total{endpoint="/nova_demanda", status="200"}
   - tempo de resposta em flask_http_request_duration_seconds
           ↓
4. Prometheus scrape /metrics a cada 5s e salva esses números
           ↓
5. Grafana consulta Prometheus com PromQL e exibe no dashboard
```

### Fluxo de Logs

```
1. app.py executa: logger.info("Nova demanda criada por João: Correção de bug")
           ↓
2. Python escreve no stdout do container:
   "2024-01-15 14:30:00 INFO app=flask message=Nova demanda criada por João: Correção de bug"
           ↓
3. Promtail detecta nova linha no log do container flask-api
           ↓
4. Promtail adiciona labels: {container="flask-api", stream="stdout"}
           ↓
5. Promtail envia para Loki via HTTP POST
           ↓
6. Loki armazena o log com os labels e timestamp
           ↓
7. Grafana consulta Loki com LogQL e exibe os logs
```

---

## 🔎 Consultando Logs com LogQL

**LogQL** é a linguagem de consulta do Loki. A sintaxe básica é:

```
{seletor_de_labels} | filtros_de_texto
```

### Seletores de Labels

Sempre começa com `{}` com os labels que você quer filtrar:

```logql
# todos os logs do container flask-api
{container="flask-api"}

# logs de stderr de qualquer container
{stream="stderr"}

# logs de um container específico no stream stdout
{container="flask-api", stream="stdout"}
```

### Filtros de Texto

Depois do seletor, você pode filtrar pelo conteúdo:

```logql
# logs que contêm a palavra "ERROR"
{container="flask-api"} |= "ERROR"

# logs que NÃO contêm "DEBUG"
{container="flask-api"} != "DEBUG"

# logs que batem com expressão regular
{container="flask-api"} |~ "demanda.*criada"

# logs que NÃO batem com regex
{container="flask-api"} !~ "GET /metrics"
```

### Exemplos Práticos com este Projeto

```logql
# Ver todos os logs da aplicação Flask
{container="flask-api"}

# Ver apenas erros da aplicação
{container="flask-api"} |= "ERROR"

# Ver logs de criação de demandas
{container="flask-api"} |= "Nova demanda criada"

# Ver logs dos últimos 5 minutos com a palavra "demanda"
{container="flask-api"} |= "demanda"

# Ver logs de todos os containers exceto o promtail
{container!="promtail"}

# Filtrar por múltiplas palavras (AND implícito)
{container="flask-api"} |= "INFO" |= "Acessou"
```

### Parsers de Log

Se o log tem estrutura, você pode extrair campos:

```logql
# Nosso log tem formato: "2024-01-15 14:30:00 INFO app=flask message=..."
# Podemos extrair com o parser de padrão logfmt-like
{container="flask-api"} | pattern "<_> <level> app=<app> message=<msg>"

# Filtrar após extrair o campo
{container="flask-api"} | pattern "<_> <level> app=<app> message=<msg>" | level="ERROR"
```

### Métricas a partir de Logs (LogQL Avançado)

```logql
# Contar quantos logs de erro por minuto
count_over_time({container="flask-api"} |= "ERROR" [1m])

# Taxa de logs por segundo
rate({container="flask-api"}[1m])

# Contar acessos à página inicial por hora
count_over_time({container="flask-api"} |= "Acessou a página inicial" [1h])
```

> ⚠️ **Atenção**: No Grafana, ao criar um painel de Loki, você escolhe entre **Logs** (para ver linhas de log) e **Metrics** (para gráficos a partir de `count_over_time`, `rate`, etc.).

---

## 📐 Consultando Métricas com PromQL

**PromQL** é a linguagem de consulta do Prometheus.

### Consultas Básicas

```promql
# Ver a métrica bruta (valor atual)
flask_http_request_total

# Filtrar por label
flask_http_request_total{endpoint="/"}

# Filtrar por múltiplos labels
flask_http_request_total{endpoint="/nova_demanda", http_status="200"}

# Regex nos labels
flask_http_request_total{endpoint=~"/detalhes/.*"}
```

### Funções Essenciais

```promql
# Taxa de requisições por segundo (nos últimos 5 minutos)
rate(flask_http_request_total[5m])

# Total de requisições nos últimos 1 minuto
increase(flask_http_request_total[1m])

# Taxa de erros (status 5xx)
rate(flask_http_request_total{http_status=~"5.."}[5m])

# Percentual de erros
rate(flask_http_request_total{http_status=~"5.."}[5m])
/
rate(flask_http_request_total[5m])
* 100

# Latência média de resposta
rate(flask_http_request_duration_seconds_sum[5m])
/
rate(flask_http_request_duration_seconds_count[5m])

# Percentil 95 de latência (p95)
histogram_quantile(0.95, rate(flask_http_request_duration_seconds_bucket[5m]))
```

### Agregações

```promql
# Total de requisições por endpoint
sum by (endpoint) (flask_http_request_total)

# Taxa de erro por endpoint
sum by (endpoint) (rate(flask_http_request_total{http_status=~"5.."}[5m]))

# Endpoint mais lento (p99)
histogram_quantile(0.99,
  sum by (endpoint, le) (
    rate(flask_http_request_duration_seconds_bucket[5m])
  )
)
```

---

## 🛠️ Criando Métricas Personalizadas

As métricas geradas automaticamente pela biblioteca são ótimas, mas às vezes você precisa de métricas específicas do seu negócio. Por exemplo: "quantas demandas foram criadas hoje?" ou "quantos comentários foram adicionados?".

### Passo 1 — Importar os tipos do Prometheus Client

```python
from prometheus_client import Counter, Gauge, Histogram
from prometheus_flask_exporter import PrometheusMetrics
```

### Passo 2 — Definir as métricas

Defina as métricas **fora das rotas** (uma vez, no escopo global):

```python
app = Flask(__name__)
metrics = PrometheusMetrics(app, path='/metrics')

# Conta quantas demandas foram criadas (Counter: só sobe)
demandas_criadas_total = Counter(
    'demandas_criadas_total',          # nome da métrica
    'Total de demandas criadas',       # descrição
    ['solicitante']                    # labels (dimensões)
)

# Conta comentários adicionados
comentarios_total = Counter(
    'comentarios_adicionados_total',
    'Total de comentários adicionados'
)

# Quantas demandas existem agora (Gauge: sobe e desce)
demandas_abertas = Gauge(
    'demandas_abertas_atual',
    'Número atual de demandas abertas'
)

# Histograma do tamanho do título das demandas
titulo_tamanho = Histogram(
    'demanda_titulo_caracteres',
    'Tamanho em caracteres do título das demandas',
    buckets=[10, 20, 50, 100, 200]    # define os buckets
)
```

### Passo 3 — Usar as métricas nas rotas

```python
@app.route('/nova_demanda', methods=['GET', 'POST'])
def nova_demanda():
    if request.method == 'POST':
        titulo = request.form['titulo']
        descricao = request.form['descricao']
        solicitante = request.form['solicitante']

        conn = sqlite3.connect('demandas.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO demandas (titulo, descricao, solicitante, data_criacao) VALUES (?, ?, ?, ?)",
            (titulo, descricao, solicitante, datetime.now())
        )
        conn.commit()
        conn.close()

        # Incrementa o contador de demandas criadas, separado por solicitante
        demandas_criadas_total.labels(solicitante=solicitante).inc()

        # Registra o tamanho do título no histograma
        titulo_tamanho.observe(len(titulo))

        logger.info(f"Nova demanda criada por {solicitante}: {titulo}")
        flash('Salvo!')
        return redirect('/')

    return render_template('nova_demanda.html')


@app.route('/deletar/<id>')
def deletar(id):
    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()
    cursor.execute(f'DELETE FROM demandas WHERE id={id}')
    conn.commit()
    conn.close()

    # Decrementa o gauge de demandas abertas
    demandas_abertas.dec()

    flash('Deletado!')
    return redirect('/')


@app.route('/adicionar_comentario/<demanda_id>', methods=['POST'])
def adicionar_comentario(demanda_id):
    comentario = request.form['comentario']
    autor = request.form['autor']

    conn = sqlite3.connect('demandas.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO comentarios (demanda_id, comentario, autor, data) VALUES (?, ?, ?, ?)",
        (demanda_id, comentario, autor, datetime.now())
    )
    conn.commit()
    conn.close()

    # Incrementa o contador de comentários
    comentarios_total.inc()

    return redirect(f'/detalhes/{demanda_id}')
```

### Passo 4 — Verificar no Prometheus

Após criar demandas, acesse `http://localhost:9090` e consulte:

```promql
# Total de demandas criadas
demandas_criadas_total

# Demandas criadas por solicitante
demandas_criadas_total{solicitante="João"}

# Taxa de criação de demandas por minuto
rate(demandas_criadas_total[1m]) * 60

# Tamanho médio dos títulos
histogram_quantile(0.5, rate(demanda_titulo_caracteres_bucket[5m]))
```

### Passo 5 — Criar um painel no Grafana

1. Acesse `http://localhost:3000`
2. Clique em **"+"** → **New Dashboard**
3. Clique em **Add panel**
4. Selecione o datasource **Prometheus**
5. Digite a query PromQL
6. Escolha o tipo de visualização (Time series, Stat, Gauge, etc.)
7. Salve o dashboard

---

## 🚀 Rodando o Projeto

### Pré-requisitos

- Docker instalado
- Docker Compose instalado

### Comandos

```bash
# Subir todos os serviços em background
docker compose up -d

# Ver os logs de todos os containers
docker compose logs -f

# Ver logs de um container específico
docker compose logs -f flask-api

# Parar todos os serviços
docker compose down

# Parar e remover volumes (cuidado: apaga dados do Grafana)
docker compose down -v
```

> ⏳ **Aguarde alguns segundos** após o `up` para que todos os containers inicializem. O Grafana pode demorar um pouco mais.

---

## 🌐 Acessando as Ferramentas

| Ferramenta | URL | Usuário | Senha |
|-----------|-----|---------|-------|
| **Flask App** | http://localhost:5000 | — | — |
| **Prometheus** | http://localhost:9090 | — | — |
| **Loki** | http://localhost:3100 | — | — |
| **Grafana** | http://localhost:3000 | admin | admin |

### Dicas de navegação

**Prometheus:**
- Vá em **Graph** para executar queries PromQL
- Vá em **Status → Targets** para ver se o Flask está sendo coletado (deve aparecer `UP`)

**Grafana:**
- **Explore** (ícone de bússola) → escolha Loki ou Prometheus → escreva sua query
- **Dashboards** → veja os dashboards pré-configurados
- **Alerting** → configure alertas (avançado)

---

## 💡 Exercícios Sugeridos

### Nível Básico
1. Acesse o Grafana e abra o dashboard do projeto. Identifique cada painel e o que ele mostra.
2. No Prometheus (`/graph`), busque `flask_http_request_total` e explore as métricas automáticas.
3. No Grafana (Explore → Loki), faça uma query para ver os logs do container `flask-api`.

### Nível Intermediário
4. Crie uma demanda na aplicação e veja no Prometheus como o contador de requisições subiu.
5. Escreva uma query LogQL que filtre apenas os logs de criação de nova demanda.
6. Escreva uma query PromQL que mostre a taxa de requisições por segundo nos últimos 5 minutos.

### Nível Avançado
7. Adicione uma métrica personalizada `Counter` que conta quantas buscas (`/buscar`) foram feitas.
8. Crie um painel no Grafana que mostre essa métrica ao longo do tempo.
9. Adicione um **label** à sua métrica para separar por termo buscado.
10. Crie um alerta no Grafana que dispare quando a taxa de erro (status 5xx) ultrapassar 10%.

---

## 📚 Referências

- [Documentação do Prometheus](https://prometheus.io/docs/)
- [Documentação do Loki](https://grafana.com/docs/loki/latest/)
- [LogQL Cheat Sheet](https://grafana.com/docs/loki/latest/query/)
- [PromQL Tutorial](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana Docs](https://grafana.com/docs/grafana/latest/)
- [prometheus-flask-exporter](https://github.com/rycus86/prometheus_flask_exporter)

---

> 📝 **Dúvidas?** Abra uma issue no repositório ou pergunte ao professor durante a aula.