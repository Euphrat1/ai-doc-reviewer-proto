from __future__ import annotations

from typing import Any

import streamlit as st

from app_core.corpus import (
    build_full_corpus_text,
    build_prompt_corpus,
    build_qa_block,
    estimate_total_prompt_tokens,
)
from app_core.llm import (
    create_lm_studio_client,
    create_openrouter_client,
    generate_trace_id,
    run_final_analysis,
    run_pii_masking,
    run_primary_analysis,
)
from app_core.parsers import parse_attachment, parse_files_from_folder
from app_core.prompts import load_prompt_templates, render_user_template
from app_core.reporting import build_report_json


st.set_page_config(page_title="AI Doc Reviewer MVP", layout="wide")


def main() -> None:
    templates = load_prompt_templates()
    _init_session_state()

    st.title("AI Doc Reviewer MVP")
    st.caption("Локальный Streamlit MVP: Full Corpus -> Prompt Corpus -> PII -> OpenRouter -> Q/A -> Final")

    settings = render_sidebar()
    render_materials_section(settings)

    if st.session_state.files:
        render_masking_section(templates, settings)
        render_analysis_section(templates, settings)
        render_export_section(settings)

    render_log_section()


def render_sidebar() -> dict[str, Any]:
    st.sidebar.header("Настройки")

    api_key = st.sidebar.text_input("OpenRouter API key", type="password")
    openrouter_model = st.sidebar.text_input("OpenRouter model", value="openai/gpt-4o-")
    timeout_seconds = st.sidebar.number_input("Timeout (seconds)", min_value=10, value=90, step=5)

    st.sidebar.subheader("Папка с материалами")
    folder_path = st.sidebar.text_input("Путь к папке", value=st.session_state.folder_path)
    if st.sidebar.button("Обзор"):
        selected = _browse_folder()
        if selected:
            folder_path = selected
            st.session_state.folder_path = selected
            st.rerun()
    st.session_state.folder_path = folder_path

    st.sidebar.subheader("LM Studio")
    lm_studio_url = st.sidebar.text_input("LM Studio base URL", value="http://127.0.0.1:1234")
    lm_studio_api_key = st.sidebar.text_input("LM Studio API key", value="lm-studio", type="password")
    lm_studio_model = st.sidebar.text_input("LM Studio model", value="mistral-7b-instruct-v0.3")

    st.sidebar.subheader("Оценка токенов и лимиты")
    chars_per_token = st.sidebar.number_input(
        "Chars per token (estimate)",
        min_value=2.0,
        max_value=4.0,
        step=0.1,
        value=3.0,
    )
    prompt_budget_tokens = st.sidebar.number_input("Prompt budget tokens", min_value=1000, value=70000, step=1000)
    max_output_tokens = st.sidebar.number_input("Max output tokens", min_value=256, value=4000, step=256)
    max_structure_tokens_per_file = st.sidebar.number_input(
        "Max structure tokens per file",
        min_value=100,
        value=1000,
        step=100,
    )
    max_evidence_tokens_per_file = st.sidebar.number_input(
        "Max evidence tokens per file",
        min_value=100,
        value=5000,
        step=100,
    )
    max_pdf_pages_in_evidence = st.sidebar.number_input(
        "Max PDF pages in evidence",
        min_value=1,
        value=12,
        step=1,
    )
    max_files_with_evidence = st.sidebar.number_input(
        "Max files with evidence",
        min_value=1,
        value=10,
        step=1,
    )

    return {
        "api_key": api_key,
        "openrouter_model": openrouter_model,
        "timeout_seconds": int(timeout_seconds),
        "folder_path": folder_path,
        "lm_studio_url": lm_studio_url,
        "lm_studio_api_key": lm_studio_api_key,
        "lm_studio_model": lm_studio_model,
        "chars_per_token": float(chars_per_token),
        "prompt_budget_tokens": int(prompt_budget_tokens),
        "max_output_tokens": int(max_output_tokens),
        "max_structure_tokens_per_file": int(max_structure_tokens_per_file),
        "max_evidence_tokens_per_file": int(max_evidence_tokens_per_file),
        "max_pdf_pages_in_evidence": int(max_pdf_pages_in_evidence),
        "max_files_with_evidence": int(max_files_with_evidence),
    }


def render_materials_section(settings: dict[str, Any]) -> None:
    st.header("Материалы")

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("Загрузить материалы", type="primary"):
            load_materials(settings)
    with col2:
        st.write("Поддерживаемые форматы MVP: `.txt`, `.md`, `.csv`, `.xlsx`, `.xml`, `.pdf`.")

    if not st.session_state.files:
        st.info("Сначала укажите путь к папке и загрузите материалы.")
        return

    st.success(f"Загружено файлов: {len(st.session_state.files)}")

    corpus_metrics = st.columns(3)
    corpus_metrics[0].metric("Full Corpus tokens est", st.session_state.prompt_result.tokens_full_corpus_est)
    corpus_metrics[1].metric("Prompt Corpus tokens est", st.session_state.prompt_result.tokens_prompt_corpus_est)
    corpus_metrics[2].metric("Compression policy", st.session_state.prompt_result.compression_policy_step)

    st.subheader("Файлы")
    table_data = []
    for file_result in st.session_state.files:
        table_data.append(
            {
                "file": file_result.relative_path,
                "type": file_result.file_type,
                "parse": file_result.parse_status,
                "tokens_total_full_est": file_result.tokens_total_full_est,
            }
        )
    st.dataframe(table_data, use_container_width=True)

    if st.session_state.prompt_result.compression_summary:
        st.subheader("Что было сжато")
        for item in st.session_state.prompt_result.compression_summary:
            st.write(f"- {item}")

    tabs = st.tabs(["Full Corpus", "Prompt Corpus"])
    with tabs[0]:
        st.text_area(
            "Full Corpus preview",
            st.session_state.full_corpus_text,
            height=350,
            disabled=True,
            label_visibility="collapsed",
        )
    with tabs[1]:
        st.text_area(
            "Prompt Corpus preview",
            current_prompt_corpus_text(),
            height=350,
            disabled=True,
            label_visibility="collapsed",
        )


def render_masking_section(templates: dict[str, str], settings: dict[str, Any]) -> None:
    st.header("PII маскировка")

    # PII masking templates were removed from specs/promts.md when PII was moved to a service.
    # Keep the app runnable even if these templates are absent.
    if not templates.get("pii_system") or not templates.get("pii_user"):
        st.info("PII-маскирование вынесено в отдельный сервис. В этом MVP UI для LM Studio-маскирования отключён.")
        return

    prompt_corpus_text = st.session_state.prompt_result.prompt_corpus_text
    pii_user_prompt = render_user_template(templates["pii_user"], text_to_mask=prompt_corpus_text)
    pii_prompt_tokens = estimate_total_prompt_tokens(
        system_prompt=templates["pii_system"],
        user_prompt=pii_user_prompt,
        chars_per_token=settings["chars_per_token"],
    )
    st.caption(f"PII prompt tokens est: {pii_prompt_tokens}")

    with st.expander("Предпросмотр PII промпта"):
        st.text_area("SYSTEM", templates["pii_system"], height=220, disabled=True)
        st.text_area("USER", pii_user_prompt, height=220, disabled=True)

    if st.button("Скрыть личные данные"):
        try:
            trace_id = generate_trace_id()
            client = create_lm_studio_client(settings["lm_studio_url"], settings["lm_studio_api_key"])
            with st.spinner("LM Studio маскирует данные..."):
                result = run_pii_masking(
                    client=client,
                    model=settings["lm_studio_model"],
                    system_prompt=templates["pii_system"],
                    user_prompt=pii_user_prompt,
                    trace_id=trace_id,
                    timeout_seconds=settings["timeout_seconds"],
                    max_output_tokens=settings["max_output_tokens"],
                    request_logs=st.session_state.request_logs,
                    tokens_prompt_total_est=pii_prompt_tokens,
                )
            st.session_state.pii_mask_result = result
            st.session_state.last_trace_id = trace_id
            st.success("PII-маскировка завершена.")
        except Exception as exc:
            st.error(f"Ошибка маскировки: {exc}")

    if st.session_state.pii_mask_result is not None:
        st.text_area(
            "Masked Prompt Corpus",
            st.session_state.pii_mask_result.masked_text,
            height=280,
            disabled=True,
        )
        st.caption(
            f"Локально сохранено replacements: {len(st.session_state.pii_mask_result.replacements)}. "
            "Во внешние API они не отправляются."
        )


def render_analysis_section(templates: dict[str, str], settings: dict[str, Any]) -> None:
    st.header("Анализ")
    task_text = st.text_area("Задание", value=st.session_state.task_text, height=120)
    st.session_state.task_text = task_text

    if not task_text.strip():
        st.info("Введите задание для анализа.")
        return

    context_text = current_prompt_corpus_text()
    analyze_user_prompt = render_user_template(
        templates["universal_user"],
        task_text=task_text,
        prompt_corpus_text=context_text,
    )
    analyze_prompt_tokens = estimate_total_prompt_tokens(
        system_prompt=templates["universal_system"],
        user_prompt=analyze_user_prompt,
        chars_per_token=settings["chars_per_token"],
    )

    st.caption(f"Total prompt tokens est before analyze: {analyze_prompt_tokens}")
    with st.expander("Предпросмотр промпта анализа"):
        st.text_area("SYSTEM", templates["universal_system"], height=220, disabled=True)
        st.text_area("USER", analyze_user_prompt, height=260, disabled=True)

    if st.button("Анализировать", type="primary"):
        if not settings["api_key"]:
            st.error("Укажите OpenRouter API key.")
        else:
            try:
                trace_id = generate_trace_id()
                client = create_openrouter_client(settings["api_key"])
                with st.spinner("OpenRouter выполняет первичный анализ..."):
                    result = run_primary_analysis(
                        client=client,
                        model=settings["openrouter_model"],
                        system_prompt=templates["universal_system"],
                        user_prompt=analyze_user_prompt,
                        trace_id=trace_id,
                        timeout_seconds=settings["timeout_seconds"],
                        max_output_tokens=settings["max_output_tokens"],
                        request_logs=st.session_state.request_logs,
                        tokens_prompt_total_est=analyze_prompt_tokens,
                        compression_applied=bool(st.session_state.prompt_result.compression_summary),
                    )
                st.session_state.primary_result = result
                st.session_state.final_result = None
                st.session_state.last_trace_id = trace_id
            except Exception as exc:
                st.error(f"Ошибка OpenRouter: {exc}")

    if st.session_state.primary_result is None:
        return

    primary_result = st.session_state.primary_result
    st.subheader("Первичный результат")
    metrics = st.columns(3)
    metrics[0].metric("Confidence", primary_result.confidence)
    metrics[1].metric(
        "Expected confidence after answers",
        primary_result.expected_confidence_after_answers or "n/a",
    )
    metrics[2].metric("Questions", len(primary_result.questions))
    st.write(primary_result.answer)

    if primary_result.question_impact:
        with st.expander("Question impact details"):
            st.json(primary_result.question_impact)

    if primary_result.questions:
        st.subheader("Уточняющие вопросы")
        answers: list[str] = []
        attachment_texts: list[list[tuple[str, str]]] = []
        for index, question in enumerate(primary_result.questions):
            st.markdown(f"**Вопрос {index + 1}:** {question}")
            answer = st.text_area(
                f"Ответ {index + 1}",
                value=st.session_state.question_answers[index] if index < len(st.session_state.question_answers) else "",
                key=f"answer_{index}",
                height=100,
            )
            answers.append(answer)
            uploads = st.file_uploader(
                f"Файл к вопросу {index + 1}",
                accept_multiple_files=False,
                key=f"upload_{index}",
                type=["txt", "md", "csv", "xlsx", "xml", "pdf"],
            )
            parsed_attachments: list[tuple[str, str]] = []
            for upload in ([uploads] if uploads is not None else []):
                parsed = parse_attachment(upload.name, upload.getvalue(), settings["chars_per_token"])
                parsed_attachments.append((upload.name, parsed.to_full_corpus_block()))
            attachment_texts.append(parsed_attachments)

        st.session_state.question_answers = answers

        qa_block_text = build_qa_block(primary_result.questions, answers, attachment_texts)
        final_user_prompt = render_user_template(
            templates["final_user"],
            task_text=task_text,
            prompt_corpus_text=context_text,
            qa_block_text=qa_block_text,
        )
        final_prompt_tokens = estimate_total_prompt_tokens(
            system_prompt=templates["final_system"],
            user_prompt=final_user_prompt,
            chars_per_token=settings["chars_per_token"],
        )
        st.caption(f"Final prompt tokens est: {final_prompt_tokens}")

        with st.expander("Предпросмотр финального промпта"):
            st.text_area("SYSTEM", templates["final_system"], height=180, disabled=True, key="final_system_preview")
            st.text_area("USER", final_user_prompt, height=300, disabled=True, key="final_user_preview")

        if st.button("Отправить уточнения"):
            if not settings["api_key"]:
                st.error("Укажите OpenRouter API key.")
            else:
                try:
                    trace_id = generate_trace_id()
                    client = create_openrouter_client(settings["api_key"])
                    with st.spinner("OpenRouter выполняет финальный анализ..."):
                        final_result = run_final_analysis(
                            client=client,
                            model=settings["openrouter_model"],
                            system_prompt=templates["final_system"],
                            user_prompt=final_user_prompt,
                            trace_id=trace_id,
                            timeout_seconds=settings["timeout_seconds"],
                            max_output_tokens=settings["max_output_tokens"],
                            request_logs=st.session_state.request_logs,
                            tokens_prompt_total_est=final_prompt_tokens,
                            compression_applied=bool(st.session_state.prompt_result.compression_summary),
                        )
                    st.session_state.final_result = final_result
                    st.session_state.last_trace_id = trace_id
                    st.session_state.question_answer_payload = [
                        {
                            "question": question,
                            "answer": answer,
                            "attachments": [
                                {"name": filename, "content": content}
                                for filename, content in attachments
                            ],
                        }
                        for question, answer, attachments in zip(
                            primary_result.questions,
                            answers,
                            attachment_texts,
                            strict=False,
                        )
                    ]
                except Exception as exc:
                    st.error(f"Ошибка финального анализа: {exc}")

    if st.session_state.final_result is not None:
        st.subheader("Финальный результат")
        st.metric("Final confidence", st.session_state.final_result.confidence)
        st.write(st.session_state.final_result.answer)


def render_export_section(settings: dict[str, Any]) -> None:
    st.header("Экспорт отчёта")
    if st.session_state.primary_result is None:
        st.info("Отчёт станет доступен после первичного анализа.")
        return

    report_json = build_report_json(
        trace_id=st.session_state.last_trace_id or generate_trace_id(),
        model=settings["openrouter_model"],
        task_text=st.session_state.task_text,
        prompt_result=st.session_state.prompt_result,
        primary_result=st.session_state.primary_result,
        final_result=st.session_state.final_result,
        question_answers=st.session_state.question_answer_payload,
        request_logs=st.session_state.request_logs,
        pii_mask_result=st.session_state.pii_mask_result,
    )
    st.download_button(
        "Сохранить отчёт (.json)",
        data=report_json.encode("utf-8"),
        file_name="analysis_report.json",
        mime="application/json",
    )
    with st.expander("Preview report JSON"):
        st.text_area("report", report_json, height=260, disabled=True, label_visibility="collapsed")


def render_log_section() -> None:
    st.header("Журнал запросов")
    if not st.session_state.request_logs:
        st.info("Пока запросов не было.")
        return
    st.json([entry.to_dict() for entry in st.session_state.request_logs[-10:]])


def load_materials(settings: dict[str, Any]) -> None:
    if not settings["folder_path"].strip():
        st.error("Укажите путь к папке.")
        return

    try:
        files = parse_files_from_folder(settings["folder_path"], settings["chars_per_token"])
    except Exception as exc:
        st.error(f"Не удалось загрузить материалы: {exc}")
        return

    if not files:
        st.warning("Подходящие файлы в папке не найдены.")
        return

    prompt_result = build_prompt_corpus(
        files,
        chars_per_token=settings["chars_per_token"],
        prompt_budget_tokens=settings["prompt_budget_tokens"],
        max_structure_tokens_per_file=settings["max_structure_tokens_per_file"],
        max_evidence_tokens_per_file=settings["max_evidence_tokens_per_file"],
        max_pdf_pages_in_evidence=settings["max_pdf_pages_in_evidence"],
        max_files_with_evidence=settings["max_files_with_evidence"],
    )
    st.session_state.files = files
    st.session_state.full_corpus_text = build_full_corpus_text(files)
    st.session_state.prompt_result = prompt_result
    st.session_state.pii_mask_result = None
    st.session_state.primary_result = None
    st.session_state.final_result = None
    st.session_state.question_answers = []
    st.session_state.question_answer_payload = []


def current_prompt_corpus_text() -> str:
    if st.session_state.pii_mask_result is not None and st.session_state.pii_mask_result.masked_text:
        return st.session_state.pii_mask_result.masked_text
    if st.session_state.prompt_result is None:
        return ""
    return st.session_state.prompt_result.prompt_corpus_text


def _browse_folder() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        selected = filedialog.askdirectory()
        root.destroy()
        return selected or None
    except Exception:
        return None


def _init_session_state() -> None:
    st.session_state.setdefault("folder_path", "")
    st.session_state.setdefault("files", [])
    st.session_state.setdefault("full_corpus_text", "")
    st.session_state.setdefault("prompt_result", None)
    st.session_state.setdefault("pii_mask_result", None)
    st.session_state.setdefault("primary_result", None)
    st.session_state.setdefault("final_result", None)
    st.session_state.setdefault("question_answers", [])
    st.session_state.setdefault("question_answer_payload", [])
    st.session_state.setdefault("request_logs", [])
    st.session_state.setdefault("task_text", "")
    st.session_state.setdefault("last_trace_id", "")


if __name__ == "__main__":
    main()
