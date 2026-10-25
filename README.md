# journey-core

Núcleo determinístico de uma jornada de saúde da AINA: **consentimento**, **protocolo clínico data-driven** (PHQ-9 com skip logic PHQ-2), **jornada com tarefas**, **event store append-only sem PII** e **motor de elegibilidade de follow-up**.

> API FastAPI (Python 3.12) · Pydantic v2 · pytest · SQLAlchemy 2 · SQLite.
> Sem chatbot, sem WhatsApp, sem LLM: toda decisão aqui é regra determinística e auditável.

---

## Regras inegociáveis do desafio

Antes de qualquer linha de código, estas são as regras que o revisor vai checar:

| # | Regra | Como garantimos |
|---|---|---|
| 1 | **Sem IA decidindo.** Nada de LLM/heurística no lugar de regra. | Só regras explícitas em JSON + código puro. O objetivo é apenas anotado via API; as tarefas são placeholders configuráveis. |
| 2 | **Camadas `api → service → repository` reconhecíveis.** | `app/api/routes` → `app/services` → `app/repositories`, com `app/models` (domínio) e `app/schemas` (HTTP) separados. Rotas não contêm regra de negócio, e `tests/test_architecture.py` falha se uma camada importar na direção errada. |
| 3 | **Sem `terms_accepted=true` não inicia protocolo nem jornada.** | Erro tipado `missing_consent` → HTTP 403. |
| 4 | **Telefone é PII.** Persistir `patient_id` + `phone_hash` (SHA-256 com salt via env). | Telefone em claro só no cadastro (`patients`); **nunca** em eventos, logs ou respostas de erro. |
| 5 | **Eventos sem PII.** `properties` não pode ter telefone, nome nem data de nascimento. | Guard no `append()` do event store + teste dedicado. Texto livre (objetivo, tarefas) também não entra em eventos. |
| 6 | **Event store append-only.** | Repositório só expõe `append` e consultas; eventos são modelos `frozen`; triggers no SQLite bloqueiam `UPDATE`/`DELETE`. |
| 7 | **Protocolo data-driven.** Perguntas só no JSON; nada de `if template_id == ...`. | Interpretador genérico de regras de skip. |
| 8 | **Skip PHQ-2 exato:** após item 2, se `item1 + item2 < 3` → `end_block`, concluído, `ended_by_skip=true`, score = soma parcial. | Sem fórmulas clínicas inventadas, só a soma. |
| 9 | **Jornada só nasce após protocolo concluído.** | A jornada é criada automaticamente na mesma transação que conclui o protocolo; não existe endpoint para criá-la. No banco, `journeys.session_id` é obrigatório e único. |
| 10 | **Elegibilidade declarativa + cooldown de 72h.** | Regras em `rules/followup.json`, validadas na inicialização; motivos de recusa tipados; relógio injetável para testar o tempo; avaliações simultâneas serializadas (nunca dois follow-ups). |
| 11 | **Sem segredos ou dados reais no repositório.** | `.env.example` com valores fictícios; `.env` e `*.db` no `.gitignore`. |
| 12 | **Testes rodam localmente sem credenciais de nuvem.** | `pytest` puro; cada teste usa um banco SQLite temporário e isolado. |

---

## Como rodar

```bash
# requisitos: uv (baixa o Python 3.12 automaticamente)
uv sync                                  # cria .venv com Python 3.12 e instala deps (inclusive dev)
cp .env.example .env                     # define os salts e a URL do banco
uv run uvicorn --factory app.main:create_app --reload   # API em http://localhost:8000
uv run pytest                            # suíte de testes
```

Qualidade (rodam limpos):

```bash
uv run ruff check . && uv run ruff format --check .   # lint + formatação
uv run mypy app tests                                  # tipagem estrita
```

Documentação interativa: `http://localhost:8000/docs`

### Com Docker (opcional)

```bash
cp .env.example .env          # os salts vêm do .env; não entram na imagem
docker compose up --build     # API em http://localhost:8000
```

A imagem tem só as dependências de runtime (versões do `uv.lock`), roda com usuário sem privilégios e grava o SQLite no volume `journey-data`, então os dados sobrevivem a reinícios do container. `docker compose down -v` apaga o volume e recomeça com o banco vazio. Os testes rodam fora do container (`uv run pytest`).

### Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `PHONE_HASH_SALT` | sim | Chave do HMAC-SHA256 do telefone (mín. 16 caracteres). Nunca commitar o valor real. |
| `EVENT_HASH_SALT` | sim | Chave do HMAC-SHA256 do `patient_id_hash` (mín. 16). **Precisa ser diferente** do salt do telefone; a aplicação recusa subir se forem iguais. |
| `DATABASE_URL` | não | URL SQLAlchemy do banco. Padrão: `sqlite:///journey_core.db`. O schema é criado na inicialização. |
| `LOG_LEVEL` | não | Padrão: `INFO`. |
| `TEMPLATES_DIR` | não | Diretório dos templates. Padrão: `templates/` do projeto. |
| `FOLLOWUP_RULES_PATH` | não | Arquivo de regras de follow-up. Padrão: `rules/followup.json` do projeto. |

### Dependências

Além da stack pedida (Python 3.12, FastAPI, pytest, uv, SQLite), cada biblioteca está aqui por um motivo:

| Biblioteca | Grupo | Por quê |
|---|---|---|
| `fastapi` | runtime | Stack do enunciado. |
| `pydantic` | runtime | Pedido pelo enunciado (v2): schemas da API, templates, regras de follow-up e allow-list das properties dos eventos. |
| `pydantic-settings` | runtime | Lê e valida a configuração do ambiente/`.env` (salts com tamanho mínimo e diferentes entre si). A aplicação falha ao subir com configuração inválida, em vez de falhar no meio de uma requisição. |
| `sqlalchemy` | runtime | ORM tipado sobre o SQLite: schema declarado em um lugar só, constraints e índices parciais, transações explícitas pela Unit of Work. Ver [Persistência (SQLite)](#persistência-sqlite). |
| `uvicorn` | runtime | Servidor ASGI para rodar o FastAPI. |
| `pytest` | dev | Stack do enunciado. |
| `httpx` | dev | Exigido pelo `TestClient` do FastAPI nos testes de API. |
| `ruff` | dev | Lint e formatação em uma ferramenta (inclui regras de segurança `S`, ex.: proíbe `assert` no código da aplicação). |
| `mypy` | dev | Checagem estática em modo `strict`, garantindo os type hints pedidos no enunciado. |

---

## Arquitetura

Camadas clássicas, uma pasta por papel e um arquivo por assunto dentro de cada uma:

```
HTTP ─► api/routes/        rotas finas: validam entrada (schemas/) e chamam um service
           │
           ▼
        services/          regras de negócio; toda transição relevante grava um evento
           │
           ▼
        repositories/      interfaces.py (o que os services enxergam) + implementações SQLAlchemy;
                           recebem e devolvem models/ (nunca linhas do ORM)
           │
           ▼
        journey_core.db

models/   domínio (dataclasses e eventos), sem banco nem HTTP — usado por todas as camadas
schemas/  contratos HTTP (Pydantic), separados do domínio
core/     base técnica: config, banco, segurança, relógio, logging, erros
```

```
journey-core/
├── app/
│   ├── main.py                    # create_app(): monta dependências, rotas e handlers
│   ├── core/
│   │   ├── config.py              # settings validados (salts, banco, templates e regras via env)
│   │   ├── database.py            # engine, sessões, Base ORM, UTCDateTime
│   │   ├── security.py            # Hasher: HMAC-SHA256 do telefone e do patient_id
│   │   ├── clock.py               # Clock (interface) + SystemClock
│   │   ├── logging.py             # logs JSON com request_id e mascaramento de PII
│   │   ├── errors.py              # categorias de erro + erros de cada assunto (sem HTTP)
│   │   └── ids.py                 # new_id() (UUID4)
│   ├── models/
│   │   ├── patient.py             # Patient, NewPatient, Sex
│   │   ├── protocol.py            # ProtocolTemplate + motor genérico de skip; ProtocolSession, Answer
│   │   ├── journey.py             # Journey, Task
│   │   ├── followup.py            # regras de elegibilidade (puras), motivos tipados, Eligible | Skipped
│   │   └── events.py              # EventName, Event, DomainEvent + os eventos (allow-list)
│   ├── schemas/
│   │   ├── patient.py             # PatientCreate (normaliza telefone), PatientOut (sem PII)
│   │   ├── protocol.py            # ProtocolStart, AnswerIn (inteiro estrito), ProtocolSessionOut
│   │   ├── journey.py             # JourneyOut, TaskUpdate
│   │   ├── followup.py            # FollowupEvaluate, FollowupDecisionOut
│   │   ├── event.py               # EventOut
│   │   └── common.py              # ErrorResponse, HealthOut
│   ├── repositories/
│   │   ├── interfaces.py          # UnitOfWork (expõe os repositórios), repositórios, TemplateCatalog
│   │   ├── patient.py             # SqlAlchemyPatientRepository
│   │   ├── event.py               # SqlAlchemyEventRepository (só append e consultas)
│   │   ├── protocol_session.py    # SqlAlchemyProtocolSessionRepository
│   │   ├── journey.py             # SqlAlchemyJourneyRepository (uma linha por tarefa)
│   │   ├── templates.py           # FileTemplateCatalog: lê e valida templates/ na inicialização
│   │   ├── rules.py               # lê e valida rules/followup.json na inicialização
│   │   ├── unit_of_work.py        # SqlAlchemyUnitOfWork: uma sessão por `with`, commit explícito
│   │   └── tables.py              # schema completo (todas as tabelas, constraints, triggers) + init_db()
│   ├── services/
│   │   ├── patient.py             # PatientService: cadastro, consulta, aceite dos termos
│   │   ├── protocol.py            # ProtocolService: início, respostas idempotentes, conclusão + jornada
│   │   ├── journey.py             # JourneyService: consulta e conclusão de tarefas
│   │   ├── followup.py            # FollowupService: fatos → regras → evento, numa transação
│   │   └── event_store.py         # EventStore: única porta da trilha, calcula o hash, bloqueia PII
│   └── api/
│       ├── routes/                # health, patients, protocols, journeys, followups, events
│       ├── dependencies.py        # injeção de dependência: escolhe as implementações das interfaces
│       ├── errors.py              # erro → HTTP, formato padrão, sem eco de input
│       └── middleware.py          # request_id + log de requisição
├── templates/
│   ├── protocols/phq9.json        # perguntas, escala e regras de skip (dados, não código)
│   └── journey_tasks.json         # tarefas placeholder da jornada
├── rules/followup.json            # regras de elegibilidade, em ordem, com o cooldown (dados, não código)
├── tests/                         # um arquivo por assunto; fakes.py (em memória), concurrency.py (threads)
├── Dockerfile                     # imagem de runtime (sem dependências de dev), usuário sem privilégios
└── compose.yaml                   # sobe a API com o .env e um volume para o SQLite
```

### Padrões

| Padrão | Onde | Por quê |
|---|---|---|
| **Camadas com direção única** | `api → services → repositories → models` | Cada camada só conhece as de baixo; `tests/test_architecture.py` verifica os imports. |
| **Composition root** | `create_app(settings, clock)` | Único lugar que escolhe implementações concretas. Testes passam settings e relógio falso, sem globais nem monkeypatch. |
| **Injeção de dependência** | `api/dependencies.py` | Cada requisição recebe sua sessão e os repositórios/services que a compartilham. |
| **Interfaces de persistência** | `repositories/interfaces.py` | Services dependem só das interfaces (`Protocol`); as implementações SQLAlchemy são escolhidas em `api/dependencies.py`. Regras de negócio são testadas com implementações em memória (`tests/fakes.py`), sem banco. |
| **Repository + modelos de domínio** | `repositories/` → `models/` | Repositórios devolvem dataclasses imutáveis, nunca linhas do ORM. |
| **Unit of Work** | `repositories/interfaces.py` | Única porta da persistência: os repositórios só existem dentro de um `with uow:`, então estado e eventos de uma operação estão sempre na mesma transação. Nada é gravado sem `uow.commit()`. Detalhes em **Transações e concorrência**. |
| **Eventos com allow-list** | `models/events.py` | Cada evento declara exatamente suas properties (`extra="forbid"`); o nome vem do tipo, então não há como gravar `protocol_completed` com o payload errado. |
| **Contratos HTTP separados** | `schemas/` | `PatientOut` não tem campo de telefone: vazar na resposta é impossível por construção. |
| **Relógio injetável** | interface `Clock` em `core/clock.py` | Nenhum código chama `datetime.now()`; o cooldown de 72h é testado avançando o relógio. |

### Proteção de PII (defesa em profundidade)

| Camada | Proteção |
|---|---|
| Hash | HMAC-SHA256 (forma padrão de "SHA-256 com segredo"), chaves separadas por finalidade. Telefone normalizado (só dígitos) antes do hash. |
| Respostas | Schemas de saída sem PII; 422 sem eco do `input`; 500 genérico. |
| Eventos | Allow-list por evento + bloqueio de chaves proibidas (`phone`, `name`, `birth_date`, `objetivo`...) no `EventStore`. |
| Domínio | Campos de PII com `repr=False`: não aparecem em logs ou tracebacks se um objeto for logado. |
| Banco | `hide_parameters=True`: erros do SQLAlchemy não incluem os valores do INSERT. |
| Logs | Nunca logamos corpo ou query string; ainda assim, sequências longas de dígitos e datas são mascaradas no formatter. Access log do uvicorn desligado (o middleware o substitui com `request_id`). |

### Operação

- **Logs estruturados** (uma linha JSON por evento) com `request_id`, propagado do header `X-Request-ID` (validado) ou gerado, e devolvido na resposta.
- **`GET /health`** verifica o banco (`SELECT 1`): 200 `ok` ou 503 `degraded`.
- **Configuração validada na inicialização:** salts ausentes, curtos ou iguais impedem a aplicação de subir.
- **Qualidade:** `ruff` (lint + format), `mypy --strict`, testes sem rede nem credenciais.

### Persistência (SQLite)

- **SQLAlchemy 2 (ORM tipado com `Mapped[]`).** O schema inteiro está em `repositories/tables.py`, fonte única lida de cima a baixo. `init_db()` roda `create_all` na inicialização (idempotente). O que o ORM não expressa (triggers append-only de `events`) é anexado como `DDL` no evento `after_create` da tabela.
- **Sem migrations por enquanto:** o schema nasce junto com o banco; não há dados de produção para evoluir. Constraints já têm nomes determinísticos (`naming_convention`), o que deixa o caminho pronto para adotar Alembic depois.
- **Conexão SQLite configurada na engine:** `PRAGMA foreign_keys = ON` (o SQLite vem com FKs desligadas), `journal_mode = WAL` (leitores não bloqueiam o escritor) e `BEGIN IMMEDIATE` em toda transação (ver abaixo).

#### Transações e concorrência

O Unit of Work é a única forma de acessar os repositórios:

```python
with self._uow as uow:                      # abre sessão e transação
    if uow.patients.exists_by_phone_hash(h):
        raise PatientAlreadyExistsError     # sai sem commit → rollback
    uow.patients.add(patient)
    self._event_store.append(uow, patient_id, PatientCreated())   # o evento exige o uow aberto
    uow.commit()                            # único ponto em que algo é gravado
```

- **Atomicidade por construção:** os repositórios são criados pelo próprio Unit of Work sobre a mesma sessão, e `EventStore.append` recebe o `uow`. Não existe caminho para gravar um evento fora da transação da mudança que ele descreve.
- **Commit explícito, falha segura:** sair do bloco sem `commit()` (exceção ou esquecimento) desfaz tudo. O commit acontece antes da resposta, então o cliente nunca recebe 201 de algo não persistido.
- **Uma unidade de trabalho por requisição**, criada em `api/dependencies.py`. Sessões nunca são compartilhadas entre threads. Abrir um `with` dentro de outro na mesma instância falha na hora (não é reentrante).

**Condições de corrida "verifica, depois grava".** Várias regras leem antes de escrever; duas requisições simultâneas podem passar pela verificação antes de qualquer uma gravar:

| Regra | Proteção |
|---|---|
| Telefone não duplicado | `phone_hash UNIQUE`: a segunda inserção vira 409 |
| Uma sessão de protocolo em andamento | índice único parcial `WHERE status = 'em_andamento'` |
| Uma jornada em andamento | índice único parcial `WHERE status = 'em_andamento'` |
| Cooldown de 72h (janela de tempo, sem constraint possível) | **`BEGIN IMMEDIATE`**: a transação pega o lock de escrita no início, então verificação e escrita rodam serializadas |

`BEGIN IMMEDIATE` também evita o erro `database is locked` do SQLite: com o *busy timeout* de 5s, a segunda escrita espera a primeira em vez de falhar.

**Verificado em teste** (`tests/test_unit_of_work.py`): 10 threads fazem "se não existe evento recente, grava um" ao mesmo tempo. Com `BEGIN IMMEDIATE`, sempre 1 evento. Sem ele (testado desligando o recurso), de 3 a 10 eventos, ou seja, a mesma mensagem de follow-up enviada várias vezes. Outro teste cadastra o mesmo telefone em 10 threads: 1 cadastro, 9 respostas 409, nenhum erro 500.

**Em produção (Postgres):** o equivalente é travar a linha do paciente (`SELECT ... FOR UPDATE`) no início de cada operação, o que serializa só as operações do mesmo paciente, sem bloquear os demais.

#### Tabelas

| Tabela | Conteúdo |
|---|---|
| `patients` | `patient_id`, `phone`, `phone_hash` (único), `name`, `birth_date`, `sex` (`F`/`M`/`O`), `terms_accepted`, `terms_accepted_at`. Único lugar com PII. |
| `protocol_sessions` | `session_id`, `patient_id`, `template_id`, `objetivo` (anotado no início), `status`, `score`, `ended_by_skip`, datas |
| `protocol_answers` | uma linha por resposta; PK `(session_id, question_id)` |
| `journeys` | `journey_id`, `patient_id`, `session_id` (obrigatório e único), `objetivo` (copiado da sessão), `status` |
| `journey_tasks` | **uma linha por tarefa**: `task_id`, `journey_id`, `position`, `titulo`, `status`, `completed_at` |
| `events` | `position` (sequência global, ordena a trilha mesmo com timestamps iguais), envelope do evento, `properties` como JSON; **sem** colunas de PII e **sem** FK para `patients` (só o hash liga a trilha ao paciente) |

```
patients 1──* protocol_sessions 1──* protocol_answers
    │               │
    │               └──1 journeys 1──* journey_tasks
    └───────────────────────┘
events ··· (ligada apenas por patient_id_hash)
```

#### Regras garantidas pelo próprio banco

Segunda linha de defesa: os services validam primeiro, o banco garante mesmo se houver bug.

| Regra | Como |
|---|---|
| Eventos imutáveis | triggers bloqueiam `UPDATE`/`DELETE` em `events` |
| Jornada só a partir de protocolo | `journeys.session_id NOT NULL UNIQUE` + FK |
| Uma sessão de protocolo e uma jornada em andamento por paciente | índices únicos parciais `WHERE status = 'em_andamento'` |
| Sem resposta duplicada | PK `(session_id, question_id)` |
| Estados consistentes | `CHECK`s (sessão concluída tem score e data; termos aceitos têm data) |
| Telefone não duplicado | `phone_hash UNIQUE` |
| Só os eventos da taxonomia | `CHECK (event_name IN (...))` |

- **Tarefas como linhas, não JSON:** cada tarefa tem id próprio (usado no `PATCH`), status e data; concluir uma é um `UPDATE` simples e a regra `has_active_task` é um `SELECT` indexado. Na API as tarefas voltam como lista dentro da jornada.
- **Testes:** cada teste recebe um arquivo SQLite novo em `tmp_path`, com o schema criado por `init_db()`, o mesmo caminho da aplicação. Não usamos `:memory:` porque cada conexão abriria um banco vazio diferente.
- **Datas sempre em UTC:** o tipo `UTCDateTime` recusa datetime sem timezone, grava em UTC e devolve com timezone. O SQLite não guarda fuso; sem isso, a comparação do cooldown ficaria ambígua.

### Tratamento de erros

- **`core/errors.py`**: categorias de erro e os erros de cada assunto, sem nada de HTTP. Cada erro tem `code` estável e mensagem fixa (nunca inclui dados do paciente):

  ```python
  class PatientNotFoundError(NotFoundError):
      code = "patient_not_found"
      message = "Paciente não encontrado."
  ```

- **`api/errors.py`** é a única camada que traduz erro → HTTP, **por categoria**: um erro novo só precisa herdar da categoria certa.

  | Categoria | HTTP | Erros |
  |---|---|---|
  | `NotFoundError` | 404 | `patient_not_found`, `template_not_found`, `protocol_session_not_found`, `journey_not_found`, `task_not_found` |
  | `PermissionDeniedError` | 403 | `missing_consent` |
  | `ConflictError` | 409 | `patient_already_exists`, `answer_already_recorded`, `unexpected_question`, `session_closed`, `protocol_in_progress`, `journey_already_active` |
  | `BusinessRuleViolationError` | 422 | `invalid_answer` |
  | `RequestValidationError` (FastAPI) | 422 | `validation_error`, **sem ecoar o `input`** |
  | `HTTPException` (rota inexistente, método errado) | 404/405 | mesmo formato |
  | `Exception` não tratada | 500 | genérico, log sem corpo da requisição |

- **Payload padronizado** para todo erro:

  ```json
  { "error": { "code": "missing_consent", "message": "Paciente não aceitou os termos." } }
  ```

- **Proteção de PII:** o handler padrão do FastAPI para 422 devolve o valor enviado (ex.: o telefone). O handler customizado remove `input` dos detalhes, e o handler genérico nunca loga o body.

---

## Domínio

### Paciente e consentimento
- `POST /patients` → `phone`, `name`, `birth_date`, `sex` (`F` | `M` | `O`), `terms_accepted`.
- Persiste `patient_id` (UUID interno) e `phone_hash = HMAC-SHA256(PHONE_HASH_SALT, telefone normalizado)`. Formatações diferentes do mesmo número (`+55 (11) 98765-4321`, `5511987654321`) geram o mesmo hash. O `phone_hash` impede cadastro duplicado (409) sem precisar comparar telefones em claro.
- Emite `patient_created` e, se aceito, `terms_accepted`.
- `POST /patients/{id}/terms` permite aceitar os termos depois do cadastro (emite `terms_accepted`).
- Iniciar protocolo/jornada sem consentimento → **403** `missing_consent`.

### Motor de protocolo
Templates em JSON (`templates/protocols/<template_id>.json`) são a **única fonte** das perguntas, da escala e das regras de skip:

```json
{
  "template_id": "phq9",
  "name": "PHQ-9",
  "instructions": "Nas últimas duas semanas, com que frequência você foi incomodado por…",
  "scale": [{ "value": 0, "label": "Nenhuma vez" }, "..."],
  "questions": [{ "id": "q1", "text": "Pouco interesse ou prazer em fazer as coisas" }, "..."],
  "rules": [
    { "after": "q2", "when": { "sum": ["q1", "q2"], "op": "lt", "value": 3 }, "action": "end_block" }
  ]
}
```

- **Motor genérico** (`ProtocolTemplate.evaluate()` em `models/protocol.py`): percorre as perguntas em ordem e, após cada pergunta respondida, aplica as regras ligadas a ela. Comparações: `lt`, `lte`, `gt`, `gte`, `eq` sobre a soma das perguntas listadas. Templates têm um único bloco, então `end_block` conclui o protocolo com a soma parcial. Nenhum `if template_id == ...`; um template novo é só um arquivo novo (há teste com um template fictício).
- **Validado na inicialização:** pergunta inexistente numa regra, regra que soma uma pergunta posterior, ids ou valores de escala repetidos, `template_id` diferente do nome do arquivo: a aplicação não sobe.
- **Score:** só a soma das respostas dadas. Nenhuma fórmula clínica além disso.

Escala PHQ-9: `0` Nenhuma vez · `1` Vários dias · `2` Mais da metade dos dias · `3` Quase todos os dias.

#### Respostas idempotentes

O cliente sempre diz qual pergunta está respondendo: `{"question_id": "q2", "value": 1}`. Assim, uma resposta reenviada (retry do agente, webhook duplicado do WhatsApp, toque duplo do paciente) nunca é gravada como resposta da pergunta seguinte, o que deslocaria todas as respostas sem nenhum erro aparente.

| Requisição | Resposta |
|---|---|
| pergunta pendente | **200**: grava; devolve a próxima pergunta ou o resultado |
| reenvio idêntico de uma resposta já gravada | **200** com o mesmo conteúdo da primeira vez; nada é gravado |
| outro valor para uma pergunta já respondida | **409** `answer_already_recorded` (respostas gravadas não mudam) |
| pergunta diferente da pendente | **409** `unexpected_question`, com a pergunta esperada na mensagem |
| nova resposta com a sessão concluída | **409** `session_closed` |
| valor fora da escala | **422** `invalid_answer` |
| valor que não é inteiro (`"2"`, `1.5`, `true`) | **422** `validation_error` |

Isso vale também para requisições **simultâneas**: 10 threads enviando a mesma resposta ao mesmo tempo recebem todas 200 e a resposta é gravada uma vez (`tests/test_protocol_concurrency.py`). Sem `BEGIN IMMEDIATE`, parte delas recebia 409.

`GET /protocol-sessions/{id}` devolve o estado atual, para o agente retomar após uma falha de comunicação.

**Dono da sessão:** `protocol_sessions.patient_id` (FK para `patients`), gravado ao iniciar e nunca alterado. A rota de respostas segue o enunciado (`/protocol-sessions/{id}/answers`, sem o paciente na URL): o service carrega a sessão e obtém o paciente dela, usado na jornada e nos eventos. Sem autenticação (fora do escopo), quem conhece um `session_id` pode respondê-lo; o risco é baixo porque os ids são UUIDs aleatórios, e em produção a API ficaria atrás de autenticação entre serviços.

### Jornada
Segue o enunciado: **quando o protocolo conclui (por skip ou pelo fim), a jornada é criada** na mesma transação: sessão concluída, `protocol_completed`, jornada e `journey_created` são gravados juntos, ou nada é gravado (há teste que força falha na jornada e confirma que a sessão continua em andamento).

- **Objetivo:** texto livre, apenas anotado via API ao iniciar o protocolo e copiado para a jornada:
  ```
  POST /patients/{id}/protocols
  { "template_id": "phq9", "objetivo": "Perder 5kg em 3 meses" }
  ```
  `objetivo` com 1–500 caracteres; fora disso → 422.
- **Tarefas:** placeholders lidos de `templates/journey_tasks.json`. A escolha de quais tarefas levam a um objetivo é responsabilidade do agente conversacional e não faz parte do desafio (confirmado com o recrutador); o arquivo só deixa os dados da jornada realistas.
- A resposta que conclui o protocolo já traz o `journey_id`; `GET /patients/{id}/journey` devolve a jornada em andamento (ou a mais recente), e 404 enquanto nenhum protocolo foi concluído.
- `PATCH /journeys/{id}/tasks/{task_id}` com `{"status": "concluida"}` conclui a tarefa → `task_completed`. Idempotente. Ao concluir a última tarefa, a jornada passa a `concluida` → `journey_completed`, na mesma transação. Tarefas concluídas não reabrem.
- Iniciar um protocolo é recusado com 409 se o paciente já tem uma sessão em andamento (`protocol_in_progress`) ou uma jornada em andamento (`journey_already_active`). Assim, a conclusão de um protocolo nunca conflita com outra jornada.
- **LGPD:** o objetivo é texto livre e pode conter dado de saúde (dado sensível). Fica só nas tabelas de sessão e jornada; eventos levam apenas ids e contagens (`journey_id`, `task_count`). Há teste lendo a tabela `events` direto.

### Event store
Envelope mínimo (imutável):

```
event_id · occurred_at · event_name · patient_id_hash · properties
```

- **`patient_id_hash = HMAC-SHA256(EVENT_HASH_SALT, patient_id)`**, calculado em um único lugar: dentro do `EventStore`. Os services passam o `patient_id`; nenhum deles manipula o hash.
- **Por que hash do `patient_id` e não o `phone_hash`:** o `patient_id` é um UUID aleatório, então o hash não revela nada mesmo se o salt vazar (telefones são um espaço pequeno e seriam descobertos por força bruta); e a trilha não quebra se o paciente trocar de telefone.
- **Por que hashear:** pseudonimização (LGPD). A trilha é feita para sair do sistema operacional (ex.: analytics); lá é possível acompanhar um paciente pelo hash, mas não chegar ao cadastro sem o salt. Dentro do journey-core o ganho é pequeno, mas o contrato já nasce pronto para exportação.

| event_name | Quando |
|---|---|
| `patient_created` | Cadastro do paciente |
| `terms_accepted` | Aceite dos termos |
| `protocol_started` | Início da sessão de protocolo |
| `protocol_completed` | Fim do protocolo (inclusive por skip) |
| `journey_created` | Jornada criada após o protocolo |
| `task_completed` | Tarefa concluída |
| `journey_completed` | Jornada concluída (última tarefa concluída) — extensão da taxonomia mínima, pois o enunciado pede evento para toda transição relevante |
| `followup_eligible` | Motor aprovou o disparo |
| `followup_skipped` | Motor recusou o disparo (com `reason` tipado) |

`GET /events?patient_id=...` recebe o id interno (conforme o enunciado), calcula o hash e filtra por ele. É um endpoint operacional/interno: em produção ficaria atrás de autenticação entre serviços (fora do escopo). A resposta traz o envelope como persistido, sem `patient_id` nem PII. Id com formato inválido → 422; id sem eventos → lista vazia (não confirmamos se um id existe).

### Elegibilidade de follow-up
`POST /followups/evaluate` com `{"patient_id": "..."}` aplica as regras declarativas de `rules/followup.json`, **em ordem**; a primeira que falha define o motivo:

```json
{
  "template_key": "checkin_adesao",
  "rules": [
    { "check": "terms_accepted", "reason": "missing_consent", "description": "Paciente precisa ter aceitado os termos" },
    { "check": "protocol_completed", "reason": "no_completed_protocol", "description": "Ao menos um protocolo concluído" },
    { "check": "journey_active", "reason": "no_active_journey", "description": "Jornada em andamento" },
    { "check": "has_active_task", "reason": "no_active_task", "description": "Ao menos uma tarefa em andamento" },
    { "check": "cooldown", "reason": "cooldown", "params": { "hours": 72 }, "description": "No máximo um follow-up elegível a cada 72h" }
  ]
}
```

| Resposta (sempre 200) | Evento gravado |
|---|---|
| `{"eligible": true, "template_key": "checkin_adesao", "reason": null}` | `followup_eligible` com `template_key` |
| `{"eligible": false, "template_key": null, "reason": "cooldown"}` | `followup_skipped` com `reason` |

- **Declarativo, mas fechado:** cada `check` aponta para uma verificação conhecida pelo código, e `reason` só aceita os motivos tipados (`missing_consent`, `no_completed_protocol`, `no_active_journey`, `no_active_task`, `cooldown`). Mudar a ordem, remover uma regra ou alterar a janela do cooldown é editar o JSON; um `check` ou `reason` desconhecido impede a aplicação de subir.
- **Avaliação pura:** o service lê numa transação um retrato dos fatos (consentimento, protocolo concluído, jornada atual, último `followup_eligible`) e as regras decidem sem acessar o banco (`models/followup.py`), o que deixa cada regra testável isoladamente.
- **Cooldown:** conta a partir do último `followup_eligible` do paciente (pelo `patient_id_hash`), não da última avaliação; avaliações recusadas não reiniciam a janela. Exatamente 72h depois, já é elegível.
- **Concorrência:** decisão e evento são gravados na mesma transação, e `BEGIN IMMEDIATE` serializa avaliações simultâneas. 10 avaliações ao mesmo tempo resultam em 1 elegível e 9 `cooldown`; sem `BEGIN IMMEDIATE`, o teste falhou em 3 de 5 execuções (mais de um elegível, ou seja, mensagens duplicadas para o paciente).
- **`no_active_task` e conclusão automática:** como a jornada é concluída junto com a última tarefa, uma jornada sem tarefas em andamento já não está em andamento, e a regra anterior (`no_active_journey`) responde primeiro. A regra `has_active_task` continua no arquivo, como pede o enunciado, e protege o caso caso a regra de conclusão automática mude; é testada isoladamente.
- **Sob demanda:** a avaliação roda quando `POST /followups/evaluate` é chamado. Disparo automático ao concluir tarefa (permitido pelo enunciado) ficou como evolução.
- Nenhuma mensagem é enviada; só a decisão e o evento.

---

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/patients` | Cria paciente |
| `POST` | `/patients/{id}/terms` | Aceita os termos após o cadastro |
| `GET` | `/patients/{id}` | Consulta o paciente (sem PII) |
| `POST` | `/patients/{id}/protocols` | Inicia sessão a partir de `template_id` e anota o `objetivo`; devolve a 1ª pergunta |
| `POST` | `/protocol-sessions/{id}/answers` | `{question_id, value}`; devolve a próxima pergunta ou o resultado (com o `journey_id`) |
| `GET` | `/protocol-sessions/{id}` | Estado atual da sessão (retomar após falha) |
| `GET` | `/patients/{id}/journey` | Jornada em andamento (ou a mais recente) |
| `PATCH` | `/journeys/{id}/tasks/{task_id}` | `{"status": "concluida"}`: conclui a tarefa |
| `POST` | `/followups/evaluate` | `{patient_id}`; devolve `{eligible, template_key, reason}` e grava o evento |
| `GET` | `/events?patient_id=...` | Trilha de eventos do paciente (por id interno) |
| `GET` | `/health` | Verifica o banco |

---

## Testes

Obrigatórios:
- [x] Skip PHQ-2: `q1+q2 < 3` encerra com `ended_by_skip=true` e score parcial (`tests/test_protocols_api.py`, `tests/test_protocol_template.py`).
- [x] Sem skip: `q1+q2 ≥ 3` segue até a 9ª pergunta.
- [x] Recusa sem termos: iniciar protocolo sem consentimento → 403 `missing_consent`.
- [x] PII ausente: num fluxo completo que gera todos os tipos de evento, nenhum evento (na API e direto na tabela) contém telefone, nome, data de nascimento, `phone_hash` ou o `patient_id` em claro; os logs da aplicação, tracebacks incluídos, não contêm telefone, nome, data de nascimento nem `phone_hash` (`tests/test_pii.py`).
- [x] Cooldown 72h: 1ª avaliação elegível, 2ª `cooldown`, 71h59 depois ainda `cooldown`, exatamente 72h depois elegível de novo (`tests/test_followups_api.py`, `tests/test_followup_service.py`).
- [x] Jornada só após protocolo: 404 antes e durante a sessão; existe logo após a resposta que conclui o protocolo (`tests/test_journeys_api.py`).

Extras:
- [x] Template fictício diferente funciona sem mudar código (prova do motor genérico); templates inválidos impedem a aplicação de subir (`tests/test_template_catalog.py`).
- [x] Respostas: reenvio idêntico → mesma resposta; mudar resposta, fora de ordem, sessão concluída → 409; fora da escala ou não inteiro → 422.
- [x] Respostas e inícios simultâneos (`tests/test_protocol_concurrency.py`): mesma resposta enviada 10 vezes ao mesmo tempo é gravada uma vez e todas recebem 200; uma jornada e uma sessão por paciente.
- [x] Jornada criada na mesma transação da conclusão: falha na jornada desfaz a conclusão (`tests/test_protocol_service.py`).
- [x] Tarefas: concluir emite `task_completed`, é idempotente, e a última conclui a jornada (`journey_completed`).
- [x] Follow-up: cada motivo de recusa a partir do fluxo real, primeira regra que falha define o motivo, ordem e janela configuráveis, regras inválidas impedem a aplicação de subir (`tests/test_followup_rules.py`, `tests/test_followup_rules_file.py`).
- [x] Follow-up simultâneo: 10 avaliações ao mesmo tempo → 1 elegível e 9 `cooldown` (`tests/test_protocol_concurrency.py`).
- [x] Erro de validação (422) não ecoa o telefone; 409 e 500 também não; logs sem PII (`tests/test_pii.py`).
- [x] Objetivo não aparece em nenhum evento (API e tabela).
- [x] Iniciar protocolo com sessão ou jornada em andamento → 409.
- [x] Cadastro e termos (`tests/test_patients.py`): sem PII na resposta, telefone duplicado com outra formatação → 409, validações → 422, aceite posterior idempotente.
- [x] Event store (`tests/test_event_store.py`): hash do id, allow-list, bloqueio de PII, ordem de gravação, isolamento por paciente, janela de tempo, rollback junto com a operação.
- [x] Segurança e operação (`tests/test_security.py`, `tests/test_app.py`): HMAC, salts validados, mascaramento de logs, health, request id, formato de erro padrão.
- [x] Regras do paciente sem banco (`tests/test_patient_service.py`): cadastro, duplicidade, falha no meio da operação desfaz cadastro e eventos, aceite posterior e idempotente, usando o Unit of Work em memória (com rollback de verdade).
- [x] Unit of Work e concorrência (`tests/test_unit_of_work.py`): nada é gravado sem commit, repositórios indisponíveis fora do `with`, não reentrante, cadastro simultâneo do mesmo telefone, verificação + escrita simultâneas serializadas.
- [x] Arquitetura (`tests/test_architecture.py`): nenhuma camada importa na direção errada; services só enxergam `repositories/interfaces.py`.
- [x] Banco (`tests/test_persistence.py`): `init_db` idempotente, eventos imutáveis, jornada exige sessão, uma jornada ativa, sem resposta duplicada, datas em UTC, transação com rollback.


---

## O que ficou de fora

- **Autenticação e autorização** (fora do escopo pelo enunciado). Os endpoints são internos, chamados pelo agente; quem conhece um `session_id` ou `journey_id` pode operá-lo. Os ids são UUIDs aleatórios, o que reduz o risco, mas não substitui autenticação.
- **Disparo automático do follow-up ao concluir tarefa** (o enunciado aceita os dois). A avaliação é sob demanda; o disparo automático é a primeira evolução abaixo.
- **Envio de mensagens:** só a decisão e o evento, como pedido.
- **Correção de respostas:** respostas gravadas não mudam, por desenho (auditoria e score). Uma correção seria uma funcionalidade explícita, provavelmente uma nova sessão.
- **Templates com mais de um bloco:** o motor tem um único bloco por template, e `end_block` conclui o protocolo. Suficiente para o PHQ-9/PHQ-2.
- **Migrations versionadas:** o schema nasce com o banco (`create_all`); não há dados para migrar.
- **Exclusão e retenção de dados (LGPD):** não há endpoint para apagar ou anonimizar um paciente.
- **Paginação em `GET /events`** e rate limiting.
- **Integrações reais** (Firestore, BigQuery, WhatsApp, Vertex AI), fora do escopo pelo enunciado.

## O que eu faria no 4º dia

Em ordem de prioridade:

1. **Disparo automático do follow-up ao concluir tarefa**, com um *outbox* transacional: a decisão `followup_eligible` grava, na mesma transação, um item para o serviço de envio consumir. Garante que nenhum follow-up aprovado se perca e que nenhum seja enviado sem estar registrado.
2. **Autenticação entre serviços** (API key ou mTLS) e um id de cliente por requisição nos logs.
3. **LGPD:** anonimização do paciente (apagar telefone, nome e data de nascimento de `patients`, mantendo a trilha pseudonimizada), política de retenção, e uma tabela de contatos com **consentimento por finalidade** (ex.: opt-in de marketing separado do consentimento de cuidado).
4. **Postgres em produção**, trocando `BEGIN IMMEDIATE` (lock global do SQLite) por lock da linha do paciente (`SELECT ... FOR UPDATE`), que serializa só operações do mesmo paciente; e **migrations com Alembic**.
5. **Versionamento de templates e regras:** gravar na sessão a versão do template usada, para que mudar o JSON não altere a interpretação de sessões antigas; templates com múltiplos blocos; GAD-7.
6. **Exportação da trilha** para analytics (BigQuery) via outbox, usando o `patient_id_hash` como chave pseudônima.
7. **Operação:** CI (GitHub Actions com `ruff`, `mypy` e `pytest`), métricas por endpoint e paginação de `GET /events`.
