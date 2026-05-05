Установить
Python 3.11+
Git
(опционально) Tesseract OCR, если нужен OCR
2) Клонировать проект
git clone https://github.com/<you>/<repo>.git
cd <repo>
3) Создать venv и поставить зависимости
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
4) Запуск приложения
streamlit run app.py
5) (Если используете PII сервис)
Запустить PII Masking Service отдельно
В приложении указать PII_SERVICE_URL (в сайдбаре)
