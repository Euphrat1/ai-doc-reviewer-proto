## Техническое задание: PII Masking Service (HTTP) v0.1

### 1. Цель
Отдельный локальный HTTP-сервис для маскирования PII в текстах перед отправкой во внешние LLM.
Сервис должен быть разработан так, чтобы его “ядро” можно было легко использовать как Python-библиотеку.

### 2. Общее описание
Сервис принимает `text` и возвращает:
- `masked_text`: текст с масками `<TYPE_N>` (N — сквозной номер в рамках запроса/job’а)
- `replacements`: соответствия `{mask,type,original}` (локальные чувствительные данные)
- `warnings`, `stats`, `trace_id`

Сервис поддерживает несколько способов маскирования (`method_id`), выбираемых через API.

Интеграция с основным приложением:
- основной клиент (UI) использует `GET /health` для проверки доступности сервиса;
- основной клиент использует `GET /methods` для построения UI выбора метода/модели и для получения `input_limits.max_chars` (чтобы выбирать sync vs async).

### 3. Контракты данных

#### 3.1 Типы масок (минимум)
- `PERSON`
- `PHONE`
- `EMAIL`
- `COMPANY`

#### 3.2 Формат `replacements`
`replacements` — массив объектов:
- `mask` (string) — например `<PERSON_1>`
- `type` (string) — тип маски (см. 3.1)
- `original` (string) — исходное значение

#### 3.3 Формат ответа маскирования (основной)
Успешный ответ:
- `masked_text` (string)
- `replacements` (array, см. 3.2)
- `warnings` (array of string, может быть пустым)
- `stats` (object):
  - обязательные: `elapsed_ms`, `replacements_count`, `method_id`
  - опциональные: `input_chars`, `output_chars`, `chunks_total`, `chunks_done`, `model_id`
- `trace_id` (string)

#### 3.4 Формат ошибки (единый)
Единый формат (sync/async):
- `error.code` (string): машинный код
- `error.message` (string): описание
- `error.details` (object, optional): структурированные детали
- `trace_id` (string)

### 4. API
#### 4.1 Health
`GET /health`

Возвращает: `status`, `version`, `api_version`, `uptime` (минимально).

Требования:
- `version` — semver сервиса (например `0.1.0`)
- `api_version` — версия протокола API (integer). Для v0.1: `api_version=1`

#### 4.2 Получить список методов маскирования
`GET /methods`

Возвращает список методов (минимальные поля):
- `id` (string) — стабильный идентификатор
- `name` (string)
- `description` (string)
- `supports_async` (bool)
- `pii_types` (array of string)
- `input_limits` (object): например `{ "max_chars": 200000 }`

Для `method_id = local_llm` дополнительно:
- `models_supported` (array of string) — список локальных моделей, которые сервис “видит/проверил” и рекомендует для выбора (первый элемент списка используется по умолчанию).

Примечание: `options_schema` отсутствует в v0.1 (feature на будущее).

#### 4.3 Маскирование (sync)
`POST /mask`

Тело запроса:
- `method_id` (string): из `/methods`
- `text` (string)
- `options` (object, optional; в v0.1 может быть `{}`)
- `trace_id` (string, optional; если не передан — генерируется)

- `method_id` — выбранный метод из `/methods`
- `options` — объект опций (в v0.1 допускается пустой; конкретные опции документируются в описании метода)
- `trace_id` — если не передан, сервис генерирует сам

Ответ: как в разделе 3.3.

#### 4.4 Маскирование (async) для больших текстов
`POST /mask_async`

Тело запроса: как `/mask`.

Ответ: `{ job_id, trace_id }`

`GET /jobs/{job_id}`

Ответ:
- `job_id` (string)
- `status` (`queued|running|completed|failed`)
- `progress` (object, optional): `{done,total,stage}`
- `result` (object|null): при `completed` содержит ответ 3.3
- `error` (object|null): при `failed` содержит ошибку 3.4
- `trace_id` (string)

Когда `status=completed`, `result` содержит объект из 3.3.
Когда `status=failed`, `error` содержит объект из 3.4.

#### 4.5 Ошибки и ограничения
HTTP/error.code: 400→`invalid_method_id|invalid_options|model_not_found`, 413→`payload_too_large`, 503→`backend_unavailable`, 504→`backend_timeout`; если `text` > `input_limits.max_chars` для sync — использовать `/mask_async`.

### 5. Методы маскирования (MVP)

#### 5.1 `method_id = local_llm` (обязательный)
Цель: маскирование сложных PII через локальную LLM (LM Studio).

Требования:
- строгий JSON-ответ (LLM должна возвращать `masked_text` + `replacements`)
- chunking для больших текстов (спецификация: `chunking_pii.md`)
- стабильность масок в рамках одного запроса/job’а (повторы → одинаковая маска)
- промпт для локальной LLM должен соответствовать шаблону из `promts_pii.md`

**Выбор модели:**
- `options.model_id` (string, optional): идентификатор локальной модели (например: `llama-3.2-3b-instruct`).
- Если `options.model_id` не передан — сервис использует модель по умолчанию: **первый элемент** `models_supported`, возвращаемого в `/methods`.
- Если `options.model_id` передан, но его нет в `models_supported` — сервис **всё равно пытается** выполнить запрос с указанной моделью; ошибку возвращает только если локальный LLM backend не смог обработать запрос с этим `model_id`.
- Использованная модель должна попадать в `stats` как `model_id`.

**Опции (необязательные):**
- `timeout_seconds` (integer) — таймаут запроса к локальному LLM backend; если не передан, используется значение по умолчанию сервиса.
- `chunk_chars` (integer) — размер чанка при chunking (в символах); если не передан, используется значение по умолчанию сервиса.
- `overlap_chars` (integer) — перекрытие чанков (в символах); если не передан, используется значение по умолчанию сервиса.
- `max_output_tokens` (integer) — лимит генерации ответа локальной LLM; если не передан, используется значение по умолчанию сервиса.

#### 5.2 Опциональные методы (не обязательны в v0.1)
Возможные `method_id`: `lib` (Presidio), `ner_basic` (spaCy), `nlp_basic` (GLiNER), `regex_basic` (regex).


### 7. Требования к разработке “конвертируемости в библиотеку”
Внутренняя логика маскирования должна быть реализована в “ядре” (core-модуле) без зависимости от HTTP.
HTTP-слой — тонкая обёртка над core.

### 8. Future / backlog (не делать в v0.1)
options_schema в /methods (самоописание опций для UI)
Streaming результата
Возврат только replacements/spans без masked_text
Restore (обратная подстановка) как отдельная функция/endpoint