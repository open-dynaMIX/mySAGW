import csv
import io
import logging

from django.db import transaction
from django.db.models.signals import post_save

from caluma.caluma_core.events import on
from caluma.caluma_form import models as caluma_form_models

from ..settings import settings

logger = logging.getLogger(__name__)


@on(post_save, sender=caluma_form_models.AnswerDocument, raise_exception=True)
@transaction.atomic
def update_table_summary(instance, *args, **kwargs):
    question = instance.answer.question
    main_document = instance.answer.document

    summary_question = question.meta.get("summary-question")
    summary_mode = question.meta.get("summary-mode")

    if not summary_question and not summary_mode:
        # no summary requested
        return

    msg = f"Updating table summary: tq={instance.answer.question_id}"
    logger.debug(msg)

    if not summary_question or not summary_mode:
        msg = f"Updating table summary: missing info in TQ meta: sq={summary_question},sm={summary_mode}"
        logger.warning(msg)
        return

    msg = f"Updating table summary: sq={summary_question} sm={summary_mode}"
    logger.debug(msg)

    summary_answer, _ = caluma_form_models.Answer.objects.get_or_create(
        document=main_document, question_id=summary_question
    )

    summary_modes = {"csv": _make_csv_summary}

    summary_func = summary_modes.get(summary_mode)
    if not summary_func:
        msg = f'Updating table summary: summary mode "{summary_mode}" does not exist. Must be one of {settings.TABLE_SUMMARY_MODES}'
        logger.warning(msg)
        return

    summary_answer.value = summary_func(instance.answer)
    summary_answer.save()


@on(post_save, sender=caluma_form_models.Answer, raise_exception=True)
@transaction.atomic
def update_table_summary_from_row(instance, *args, **kwargs):
    ad = caluma_form_models.AnswerDocument.objects.filter(
        document=instance.document
    ).first()
    if not ad:
        return

    # AnswerDocument available, we're in a table
    # Trigger by just saving the AnswerDocument
    ad.save()


def _make_csv_summary(table_answer):
    def get_lines(answer_docs, row_questions):
        for ad in answer_docs:
            result = {}
            for question in row_questions:
                try:
                    answer = ad.document.answers.get(question=question).value
                except caluma_form_models.Answer.DoesNotExist:
                    answer = ""
                result[question.slug] = answer
            yield result

    msg = f"Making CSV summary for {table_answer.question}"
    logger.debug(msg)
    answer_docs = caluma_form_models.AnswerDocument.objects.filter(
        answer=table_answer
    ).order_by("-sort")
    row_questions = _sorted_form_questions(table_answer.question.row_form)

    with io.StringIO() as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=[q.slug for q in row_questions],
            delimiter=";",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        for line in get_lines(answer_docs, row_questions):
            writer.writerow(line)

        result = csvfile.getvalue()
    msg = f"Making CSV summary for {table_answer.question}: result={result}"
    logger.debug(msg)
    return result


def _sorted_form_questions(form):
    fqs = caluma_form_models.FormQuestion.objects.filter(form=form).order_by("-sort")
    return [fq.question for fq in fqs]
