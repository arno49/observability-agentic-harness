"""Celery tasks for AI explanation generation."""
import logging

import anthropic
from celery import shared_task
from django.conf import settings

from apps.questions.models import Answer, Question

from .models import Explanation, PersonalizedExplanation
from .prompts import (
    EXPLANATION_SYSTEM,
    EXPLANATION_TEMPLATE,
    PERSONALIZED_EXPLANATION_TEMPLATE,
)

logger = logging.getLogger(__name__)

# Pricing per token (Claude 3.5 Sonnet) — used for logging estimates only.
COST_PER_INPUT_TOKEN = 0.003 / 1000
COST_PER_OUTPUT_TOKEN = 0.015 / 1000


def _call_claude(system: str, user_message: str) -> tuple[str, str, dict]:
    """Call the Anthropic API and return (content, model_used, usage_dict).

    Includes the ``anthropic-no-log`` header so user-specific prompts are
    never stored on Anthropic's servers.  Uses a configurable timeout.

    Raises:
        ValueError: If ANTHROPIC_API_KEY is not configured.
        anthropic.APIError: On any Anthropic API error.
    """
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not configured. Cannot generate AI explanations."
        )

    timeout = getattr(settings, "ANTHROPIC_TIMEOUT", 30)
    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=float(timeout),
        default_headers={"anthropic-no-log": "true"},
    )
    model = settings.ANTHROPIC_MODEL

    message = client.messages.create(
        model=model,
        max_tokens=settings.ANTHROPIC_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    return message.content[0].text, model, usage


def _estimate_cost(usage: dict) -> float:
    """Return estimated USD cost from a usage dict."""
    return (
        usage["input_tokens"] * COST_PER_INPUT_TOKEN
        + usage["output_tokens"] * COST_PER_OUTPUT_TOKEN
    )


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(anthropic.RateLimitError,),
    retry_backoff=True,
    retry_backoff_max=120,
)
def generate_explanation(self, question_id: int):
    """Generate and cache a general explanation for a question."""
    try:
        question = Question.objects.prefetch_related("answers").get(pk=question_id)
    except Question.DoesNotExist:
        logger.error("Question %s not found", question_id)
        return

    # Skip if already cached
    if Explanation.objects.filter(question=question).exists():
        return

    correct = question.answers.filter(is_correct=True).first()
    others = question.answers.filter(is_correct=False)

    prompt = EXPLANATION_TEMPLATE.format(
        stem=question.stem,
        correct_answer=correct.text if correct else "N/A",
        other_answers="\n".join(f"- {a.text}" for a in others),
    )

    try:
        content, model_used, usage = _call_claude(EXPLANATION_SYSTEM, prompt)
        Explanation.objects.create(
            question=question,
            content=content,
            model_used=model_used,
        )
        cost = _estimate_cost(usage)
        logger.info(
            "Generated explanation for Q%s (%d in / %d out tokens, ~$%.4f)",
            question_id,
            usage["input_tokens"],
            usage["output_tokens"],
            cost,
        )
    except anthropic.RateLimitError:
        # Handled by autoretry_for + retry_backoff above; re-raise so Celery
        # applies exponential backoff automatically.
        raise
    except anthropic.APIError as exc:
        logger.warning("Anthropic API error for Q%s: %s", question_id, exc)
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("Unexpected error generating explanation for Q%s", question_id)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(anthropic.RateLimitError,),
    retry_backoff=True,
    retry_backoff_max=120,
)
def generate_personalized_explanation(self, question_id: int, wrong_answer_id: int):
    """Generate explanation personalized to a specific wrong answer."""
    try:
        question = Question.objects.prefetch_related("answers").get(pk=question_id)
        wrong_answer = Answer.objects.get(pk=wrong_answer_id)
    except (Question.DoesNotExist, Answer.DoesNotExist):
        logger.error("Question %s or Answer %s not found", question_id, wrong_answer_id)
        return

    # Skip if already cached
    if PersonalizedExplanation.objects.filter(
        question=question, wrong_answer=wrong_answer
    ).exists():
        return

    correct = question.answers.filter(is_correct=True).first()

    prompt = PERSONALIZED_EXPLANATION_TEMPLATE.format(
        stem=question.stem,
        wrong_answer=wrong_answer.text,
        correct_answer=correct.text if correct else "N/A",
    )

    try:
        content, model_used, usage = _call_claude(EXPLANATION_SYSTEM, prompt)
        PersonalizedExplanation.objects.create(
            question=question,
            wrong_answer=wrong_answer,
            content=content,
            model_used=model_used,
        )
        cost = _estimate_cost(usage)
        logger.info(
            "Generated personalized explanation for Q%s / A%s (%d in / %d out, ~$%.4f)",
            question_id,
            wrong_answer_id,
            usage["input_tokens"],
            usage["output_tokens"],
            cost,
        )
    except anthropic.RateLimitError:
        raise
    except anthropic.APIError as exc:
        logger.warning("Anthropic API error for Q%s/A%s: %s", question_id, wrong_answer_id, exc)
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception(
            "Unexpected error generating personalized explanation for Q%s/A%s",
            question_id, wrong_answer_id,
        )
        raise self.retry(exc=exc)
