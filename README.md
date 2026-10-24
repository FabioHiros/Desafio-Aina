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
| 2 | **Camadas `api → service → repository` reconhecíveis.** | Pastas `app/api`, `app/services`, `app/repositories`. Rotas não contêm regra de negócio. |
| 3 | **Sem `terms_accepted=true` não inicia protocolo nem jornada.** | Erro tipado `missing_consent` → HTTP 403. |
| 4 | **Telefone é PII.** Persistir `patient_id` + `phone_hash` (SHA-256 com salt via env). | Telefone em claro só no cadastro (`patients`); **nunca** em eventos, logs ou respostas de erro. |
| 5 | **Eventos sem PII.** `properties` não pode ter telefone, nome nem data de nascimento. | Guard no `append()` do event store + teste dedicado. Texto livre (objetivo, tarefas) também não entra em eventos. |
| 6 | **Event store append-only.** | Repositório só expõe `append` e consultas; eventos são modelos `frozen`; triggers no SQLite bloqueiam `UPDATE`/`DELETE`. |
| 7 | **Protocolo data-driven.** Perguntas só no JSON; nada de `if template_id == ...`. | Interpretador genérico de regras de skip. |
| 8 | **Skip PHQ-2 exato:** após item 2, se `item1 + item2 < 3` → `end_block`, concluído, `ended_by_skip=true`, score = soma parcial. | Sem fórmulas clínicas inventadas, só a soma. |
| 9 | **Jornada só nasce após protocolo concluído.** | A jornada é criada automaticamente na mesma transação que conclui o protocolo; não existe endpoint para criá-la. No banco, `journeys.session_id` é obrigatório e único. |
| 10 | **Elegibilidade declarativa + cooldown de 72h.** | Regras em JSON; relógio injetável para testar o tempo. |
| 11 | **Sem segredos ou dados reais no repositório.** | `.env.example` com valores fictícios; `.env` e `*.db` no `.gitignore`. |
| 12 | **Testes rodam localmente sem credenciais de nuvem.** | `pytest` puro; cada teste usa um banco SQLite temporário e isolado. |

---

## Como rodar

```bash
# requisitos: uv (baixa o Python 3.12 automaticamente)
uv sync                                  # cria .venv com Python 3.12 e instala deps (inclusive dev)
cp .env.example .env                     # define os salts e a URL do banco
uv run uvicorn app.main:app --reload     # API em http://localhost:8000
uv run pytest                            # suíte de testes
```

Documentação interativa: `http://localhost:8000/docs`

### Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `PHONE_HASH_SALT` | sim | Salt do SHA-256 do telefone. Nunca commitar o valor real. |
| `EVENT_HASH_SALT` | sim | Salt do `patient_id_hash` dos eventos. Diferente do salt do telefone: o vazamento de um não expõe o outro. |
| `DATABASE_URL` | não | URL SQLAlchemy do banco. Padrão: `sqlite:///journey_core.db`. O schema é criado na inicialização. |

---

## Arquitetura

```
HTTP ─► api/ (rotas + schemas Pydantic)
           │   só valida entrada/saída e traduz erros de domínio em HTTP
           ▼
        services/ (regras de negócio)
           │   consentimento · motor de protocolo · jornada · elegibilidade
           │   toda transição relevante ─► event_store.append()
           ▼
        repositories/ (SQLAlchemy 2)
           ▼
        journey_core.db
```

```
journey-core/
├── app/
│   ├── main.py                    # create_app(): só monta o app e registra routers/handlers
│   ├── core/
│   │   ├── config.py              # settings (salts e banco via env)
│   │   ├── clock.py               # relógio injetável (testes de cooldown)
│   │   └── security.py            # hash_phone(), hash_patient_id()
│   ├── exceptions/
│   │   ├── errors.py              # AppError + erros tipados (sem dependência de HTTP)
│   │   └── handlers.py            # mapeia erro → status HTTP + payload padronizado
│   ├── api/                       # rotas + schemas.py (contratos Pydantic v2)
│   ├── domain/                    # models.py (entidades)
│   ├── services/                  # patient, protocol_engine, journey, event_store, eligibility
│   └── repositories/
│       ├── database.py            # engine (FKs ligadas no SQLite), sessões e init_db()
│       ├── orm.py                 # modelos SQLAlchemy: fonte única do schema
│       ├── patient_repository.py
│       ├── protocol_session_repository.py
│       ├── journey_repository.py
│       └── event_repository.py    # só append() e consultas
├── templates/
│   ├── phq9.json                  # perguntas + regras de skip (dados, não código)
│   └── journey_tasks.json         # tarefas placeholder da jornada
├── rules/followup.json            # regras de elegibilidade (dados, não código)
└── tests/
    └── conftest.py                # banco temporário por teste + relógio falso
```

### Persistência (SQLite)

- **SQLAlchemy 2 (ORM tipado com `Mapped[]`).** Os modelos em `orm.py` são a fonte única do schema. `init_db()` roda `create_all` na inicialização (idempotente). O que o ORM não expressa (triggers append-only de `events`) é anexado como `DDL` no evento `after_create` da tabela.
- **Sem migrations por enquanto:** o schema nasce junto com o banco; não há dados de produção para evoluir. Constraints já têm nomes determinísticos (`naming_convention`), o que deixa o caminho pronto para adotar Alembic depois.
- **Uma sessão por requisição**, entregue às rotas via `Depends`. A engine liga `PRAGMA foreign_keys = ON` em cada conexão (o SQLite vem com FKs desligadas).
- **Transações explícitas nos services** com `session.begin()`: estado e eventos de uma operação são gravados juntos ou nada é gravado. O commit acontece antes da resposta, então o cliente nunca recebe 201 de algo não persistido.

#### Tabelas

| Tabela | Conteúdo |
|---|---|
| `patients` | `patient_id`, `phone`, `phone_hash` (único), `name`, `birth_date`, `sex` (`F`/`M`/`O`), `terms_accepted`, `terms_accepted_at`. Único lugar com PII. |
| `protocol_sessions` | `session_id`, `patient_id`, `template_id`, `objetivo` (anotado no início), `status`, `score`, `ended_by_skip`, datas |
| `protocol_answers` | uma linha por resposta; PK `(session_id, question_id)` |
| `journeys` | `journey_id`, `patient_id`, `session_id` (obrigatório e único), `objetivo` (copiado da sessão), `status` |
| `journey_tasks` | **uma linha por tarefa**: `task_id`, `journey_id`, `position`, `titulo`, `status`, `completed_at` |
| `events` | envelope do evento; `properties` como JSON; **sem** colunas de PII e **sem** FK para `patients` (só o hash liga a trilha ao paciente) |

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
| Uma jornada ativa por paciente | índice único parcial `WHERE status = 'em_andamento'` |
| Sem resposta duplicada | PK `(session_id, question_id)` |
| Estados consistentes | `CHECK`s (sessão concluída tem score e data; termos aceitos têm data) |
| Telefone não duplicado | `phone_hash UNIQUE` |
| Só os 8 eventos da taxonomia | `CHECK (event_name IN (...))` |

- **Tarefas como linhas, não JSON:** cada tarefa tem id próprio (usado no `PATCH`), status e data; concluir uma é um `UPDATE` simples e a regra `has_active_task` é um `SELECT` indexado. Na API as tarefas voltam como lista dentro da jornada.
- **Testes:** cada teste recebe um arquivo SQLite novo em `tmp_path`, com o schema criado por `init_db()`, o mesmo caminho da aplicação. Não usamos `:memory:` porque cada conexão abriria um banco vazio diferente.
- **Datas sempre em UTC:** o tipo `UTCDateTime` recusa datetime sem timezone, grava em UTC e devolve com timezone. O SQLite não guarda fuso; sem isso, a comparação do cooldown ficaria ambígua.

### Tratamento de erros

Exceções ficam em um módulo próprio, `app/exceptions/`, e o `main.py` apenas chama `register_exception_handlers(app)`.

- **`errors.py`:** hierarquia de erros de domínio, sem saber nada de HTTP. Cada erro tem um `code` estável.

  ```python
  class AppError(Exception):
      code: str = "internal_error"

  class ConsentRequiredError(AppError):        code = "missing_consent"
  class NotFoundError(AppError):               code = "not_found"
  class PatientAlreadyExistsError(AppError):   code = "patient_already_exists"
  class InvalidAnswerError(AppError):          code = "invalid_answer"
  class SessionClosedError(AppError):          code = "session_closed"
  class ProtocolInProgressError(AppError):     code = "protocol_in_progress"
  class JourneyAlreadyActiveError(AppError):   code = "journey_already_active"
  ```

- **`handlers.py`:** a única camada que traduz erro → HTTP, por uma tabela explícita:

  | Erro | HTTP |
  |---|---|
  | `ConsentRequiredError` | 403 |
  | `NotFoundError` | 404 |
  | `PatientAlreadyExistsError` | 409 |
  | `InvalidAnswerError` | 422 |
  | `SessionClosedError` | 409 |
  | `ProtocolInProgressError` | 409 |
  | `JourneyAlreadyActiveError` | 409 |
  | `RequestValidationError` (FastAPI) | 422, **sem ecoar o `input`** |
  | `Exception` não tratada | 500 genérico, log sem corpo da requisição |

- **Payload padronizado** para todo erro:

  ```json
  { "error": { "code": "missing_consent", "message": "Paciente não aceitou os termos." } }
  ```

- **Proteção de PII:** o handler padrão do FastAPI para 422 devolve o valor enviado (ex.: o telefone). O handler customizado remove `input` dos detalhes, e o handler genérico nunca loga o body.

---

## Domínio

### Paciente e consentimento
- `POST /patients` → `phone`, `name`, `birth_date`, `sex` (`F` | `M` | `O`), `terms_accepted`.
- Persiste `patient_id` (UUID interno) e `phone_hash = SHA-256(PHONE_HASH_SALT + phone)`. O `phone_hash` impede cadastro duplicado (409) sem precisar comparar telefones em claro.
- Emite `patient_created` e, se aceito, `terms_accepted`.
- `POST /patients/{id}/terms` permite aceitar os termos depois do cadastro (emite `terms_accepted`).
- Iniciar protocolo/jornada sem consentimento → **403** `missing_consent`.

### Motor de protocolo
Template em JSON é a **única fonte** das perguntas:

```json
{
  "template_id": "phq9",
  "scale": [0, 1, 2, 3],
  "questions": [{ "id": "q1", "text": "Pouco interesse ou prazer em fazer as coisas" }],
  "rules": [
    { "after": "q2", "when": { "sum": ["q1", "q2"], "op": "lt", "value": 3 }, "action": "end_block" }
  ]
}
```

Fluxo por resposta:
1. Valida a resposta contra a escala do template.
2. Avalia as regras cujo `after` é a pergunta respondida.
3. `end_block` → conclui com `ended_by_skip=true` e score parcial.
4. Senão → devolve a próxima pergunta, ou conclui ao fim das perguntas.

Escala PHQ-9: `0` Nenhuma vez · `1` Vários dias · `2` Mais da metade dos dias · `3` Quase todos os dias.

**Dono da sessão:** `protocol_sessions.patient_id` (FK para `patients`), gravado ao iniciar e nunca alterado. A rota de respostas segue o enunciado (`/protocol-sessions/{id}/answers`, sem o paciente na URL): o service carrega a sessão e obtém o paciente dela, usado na jornada e nos eventos. Sem autenticação (fora do escopo), quem conhece um `session_id` pode respondê-lo; o risco é baixo porque os ids são UUIDs aleatórios, e em produção a API ficaria atrás de autenticação entre serviços.

### Jornada
Segue o enunciado: **quando o protocolo conclui, a jornada é criada**, na mesma transação que grava `protocol_completed` e `journey_created`.

- **Objetivo:** texto livre, apenas anotado via API ao iniciar o protocolo e copiado para a jornada:
  ```
  POST /patients/{id}/protocols
  { "template_id": "phq9", "objetivo": "Perder 5kg em 3 meses" }
  ```
  `objetivo` com 1–500 caracteres; fora disso → 422.
- **Tarefas:** placeholders lidos de `templates/journey_tasks.json`. A escolha de quais tarefas levam a um objetivo é responsabilidade do agente conversacional e não faz parte do desafio (confirmado com o recrutador); o arquivo só deixa os dados da jornada realistas.
- Iniciar um protocolo é recusado com 409 se o paciente já tem uma sessão em andamento (`protocol_in_progress`) ou uma jornada em andamento (`journey_already_active`). Assim, a conclusão de um protocolo nunca conflita com outra jornada.
- Status: `em_andamento` → `concluida` quando todas as tarefas são concluídas.
- `PATCH /journeys/{id}/tasks/{task_id}` conclui uma tarefa → `task_completed`.
- **LGPD:** o objetivo é texto livre e pode conter dado de saúde (dado sensível). Fica só nas tabelas de sessão e jornada; eventos levam apenas ids e contagens (`journey_id`, `task_count`).

### Event store
Envelope mínimo (imutável):

```
event_id · occurred_at · event_name · patient_id_hash · properties
```

- **`patient_id_hash = SHA-256(EVENT_HASH_SALT + patient_id)`**, calculado em um único lugar: dentro do `EventStore`. Os services passam o `patient_id`; nenhum deles manipula o hash.
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
| `followup_eligible` | Motor aprovou o disparo |
| `followup_skipped` | Motor recusou o disparo (com `reason` tipado) |

`GET /events?patient_id=...` recebe o id interno (conforme o enunciado), calcula o hash e filtra por ele. É um endpoint operacional/interno: em produção ficaria atrás de autenticação entre serviços (fora do escopo). A resposta traz o envelope como persistido, sem `patient_id` nem PII. Id com formato inválido → 422; id sem eventos → lista vazia (não confirmamos se um id existe).

### Elegibilidade de follow-up
Regras declarativas avaliadas em ordem; a primeira que falha define o `reason`:

```json
{
  "template_key": "checkin_adesao",
  "rules": [
    { "check": "terms_accepted", "reason": "missing_consent", "description": "Paciente precisa ter aceitado os termos" },
    { "check": "protocol_completed", "reason": "no_completed_protocol", "description": "Ao menos um protocolo concluído" },
    { "check": "journey_active", "reason": "no_active_journey", "description": "Jornada em andamento" },
    { "check": "has_active_task", "reason": "no_active_task", "description": "Ao menos uma tarefa em andamento" },
    { "check": "cooldown", "reason": "cooldown", "params": { "hours": 72 }, "description": "No máximo um follow-up a cada 72h" }
  ]
}
```

- Cada `check` aponta para uma função em um registry no código; `description` documenta a regra no próprio arquivo (JSON não aceita comentários).
- O arquivo é validado com Pydantic ao carregar; `check` desconhecido falha na inicialização, não em runtime.
- O cooldown consulta o event store (`followup_eligible` do mesmo `patient_id_hash` depois de `agora - 72h`), com `agora` vindo do relógio injetável.
- Elegível → `followup_eligible` com `template_key`.
- Não elegível → `followup_skipped` com `reason`.
- Nenhuma mensagem é enviada; só a decisão e o evento.

---

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/patients` | Cria paciente |
| `POST` | `/patients/{id}/terms` | Aceita os termos após o cadastro |
| `POST` | `/patients/{id}/protocols` | Inicia sessão a partir de `template_id` e anota o `objetivo` |
| `POST` | `/protocol-sessions/{id}/answers` | Envia resposta; retorna próxima pergunta ou resultado (com a jornada criada) |
| `GET` | `/patients/{id}/journey` | Consulta a jornada ativa |
| `PATCH` | `/journeys/{id}/tasks/{task_id}` | Marca tarefa como concluída |
| `POST` | `/followups/evaluate` | Avalia elegibilidade de follow-up |
| `GET` | `/events?patient_id=...` | Trilha de eventos do paciente (por id interno) |

---

## Testes

Obrigatórios:
- [ ] Skip PHQ-2: `q1+q2 < 3` encerra com `ended_by_skip=true` e score parcial.
- [ ] Sem skip: `q1+q2 ≥ 3` segue até a 9ª pergunta.
- [ ] Recusa sem termos: iniciar protocolo sem consentimento → 403.
- [ ] PII ausente: nenhum evento serializado contém telefone, nome ou data de nascimento.
- [ ] Cooldown 72h: 1ª avaliação elegível, 2ª `cooldown`, após +73h elegível de novo.
- [ ] Jornada só após protocolo: não existe durante a sessão; existe logo após a resposta que conclui o protocolo (por skip ou pelo fim).

Extras:
- [ ] Template fictício diferente funciona sem mudar código (prova do motor genérico).
- [ ] Resposta fora da escala é rejeitada.
- [ ] Resposta após sessão concluída é rejeitada.
- [ ] Erro de validação (422) não ecoa o telefone.
- [ ] Objetivo não aparece em nenhum evento.
- [ ] Iniciar protocolo com sessão ou jornada em andamento → 409.
- [x] Banco (`tests/test_database.py`): `init_db` idempotente, eventos imutáveis, jornada exige sessão, uma jornada ativa, sem resposta duplicada, datas em UTC, transação com rollback.


---

## Roteiro de revisão (~15 min)

1. Subir a API seguindo **Como rodar**.
2. Criar paciente → iniciar o PHQ com um objetivo (`{ "template_id": "phq9", "objetivo": "Perder 5kg em 3 meses" }`) → responder até skip ou fim → ver a jornada criada.
3. Avaliar follow-up duas vezes → observar `cooldown` na segunda.
4. `GET /events?patient_id=...` → confirmar ausência de PII.

---

## Plano de execução (3 dias)

| Dia | Foco | Resultado visível |
|---|---|---|
| 1 | Schema, paciente/consentimento, event store, testes de PII | Cadastro + trilha de eventos sem telefone |
| 2 | Motor de protocolo, skip logic, jornada | PHQ-9 via JSON; skip testado |
| 3 | Elegibilidade, cooldown, README, polimento | Regras declarativas e casos de borda |

---

## Fora de escopo

- WhatsApp / Meta Cloud API, Vertex AI, LangGraph, Langfuse.
- Lógica de "quais tarefas levam a um objetivo": responsabilidade do agente conversacional; aqui as tarefas são placeholders.
- Dashboard, BigQuery, autenticação de usuário final, deploy em GCP.
- Interface gráfica.
- Fórmulas clínicas inventadas (bem-estar composto, "nível de confiança" etc.).

---

## Decisões de desenho

> _Preencher durante a implementação: o que foi decidido e por quê._

- **Erros de domínio desacoplados de HTTP:** services lançam `AppError`; só `exceptions/handlers.py` conhece status codes. Facilita testar services sem FastAPI e garante um formato único de erro.
- **SQLite em vez de dicts em memória:** os dados sobrevivem a reinícios (o revisor pode reiniciar a API no meio do roteiro), e regras críticas são garantidas também pelo banco (constraints e triggers). Continua sem credenciais de nuvem.
- **SQLAlchemy em vez de SQL puro:** padrão de mercado, modelos tipados e trocar de banco (ex.: Postgres) vira mudança de `DATABASE_URL` + revisão das partes específicas do SQLite (triggers, índice parcial). A camada de repositório continua isolando a persistência caso o destino seja Firestore.
- **Sem Alembic no escopo do desafio:** sem dados para migrar, `create_all` basta e mantém o setup do revisor em um passo a menos.
- **Jornada criada automaticamente ao fim do protocolo, como no enunciado:** o objetivo é anotado ao iniciar a sessão e as tarefas são placeholders configuráveis. Não há endpoint para criar jornada, então "jornada só após protocolo" vale por construção, e o banco reforça (`session_id` obrigatório e único).
- **`patient_id_hash` a partir do `patient_id`, com salt próprio:** pseudonimiza a trilha sem depender de PII e sem quebrar se o telefone mudar.
- **Texto livre fora dos eventos:** o objetivo pode conter dado de saúde; eventos levam só ids e contagens.
- **Regras em JSON (não YAML):** mesmo formato dos templates, sem dependência extra (`json` é stdlib) e sem a tipagem implícita do YAML (`no` → `False`). O campo `description` substitui os comentários.
- **Relógio injetável:** permite testar o cooldown de 72h sem depender do tempo real.
- **Guard de PII no event store:** a regra de "sem PII" é imposta por código, não só por convenção.
- **Primeira regra que falha define o `reason`:** comportamento previsível e auditável.

## O que ficou de fora

> _Preencher na entrega._

## O que eu faria no 4º dia

> _Preencher na entrega._ Ideias:
> - Migrations versionadas com Alembic (`render_as_batch` por causa do SQLite).
> - Tabela de contatos com **consentimento por finalidade** (ex.: opt-in de marketing separado do consentimento de cuidado, exigido pela LGPD) e suporte a mais de um telefone por paciente.
> - Arquivamento de jornadas concluídas se o volume de `journey_tasks` crescer.
> - Repositório Firestore atrás da mesma interface, Docker Compose, mais templates (GAD-7), versionamento de templates e regras.
