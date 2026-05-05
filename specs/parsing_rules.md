## Parsing rules (STRUCTURE + EVIDENCE)

Этот документ содержит детали парсинга материалов в корпус для LLM (Full Corpus), используемый в `specs/Tech_Req.md` (раздел `F1.2`).

### Общий формат блока файла
Каждый файл добавляется в корпус блоком:
- `FILE: <relative_path> | TYPE: <ext> | SIZE: <bytes> | PARSE: ok|warn|fail`
- `STRUCTURE: ...`
- `EVIDENCE: ...`

### Минимальные правила по типам
- `.txt`, `.md`:
  - STRUCTURE: оглавление (если применимо)
  - EVIDENCE: текст (абзацы/списки сохранять)
- `.csv`, `.xlsx`:
  - STRUCTURE: листы (xlsx), размерность, колонки, типы, доля пустых
  - EVIDENCE: первые N строк + N примеров (крайние/нетипичные)
- `.xml`:
  - STRUCTURE: корень, частые элементы, важные атрибуты
  - EVIDENCE: текстовые узлы/атрибуты без “шума”
- `.bpmn`:
  - STRUCTURE: participants/lanes/tasks/events/gateways/flows
  - EVIDENCE: трасса процесса шагами
- `.drawio`:
  - STRUCTURE: страницы, узлы, связи
  - EVIDENCE: labels + edge-list без координат/стилей
- `.png`, `.jpg`:
  - без OCR: превью+метаданные в UI; в корпус — только метаданные в STRUCTURE
  - с OCR: EVIDENCE включает `OCR_TEXT` (если OCR включён)
- `.pdf`:
  - STRUCTURE: страницы/оглавление
  - EVIDENCE: `PDF_TEXT` по страницам; OCR fallback при недостатке текста (если OCR включён)

### Примечания
- Парсинг формирует **Full Corpus** (вариант B). Сжатие выполняется при сборке Prompt Corpus (см. `F1.3`).

