"""AI explanation views.

POST /api/v1/ai/explain/ — synchronous endpoint with caching and rate limiting.
GET  /api/v1/ai/explain/{question_id}/ — legacy async endpoint (Celery).
"""
import logging

import anthropic
from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.questions.models import Answer, Question

from .models import AIUsageLog, Explanation, PersonalizedExplanation
from .prompts import (
    EXPLANATION_TEMPLATE,
    PERSONALIZED_EXPLANATION_TEMPLATE,
    get_explanation_system,
)
from .serializers import ExplanationSerializer, PersonalizedExplanationSerializer
from .tasks import generate_explanation, generate_personalized_explanation

logger = logging.getLogger(__name__)

# Singleton Anthropic client — reuses connection pool across requests
_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if _anthropic_client is None and api_key:
        _anthropic_client = anthropic.Anthropic(
            api_key=api_key,
            timeout=30.0,
            default_headers={"anthropic-no-log": "true"},
        )
    return _anthropic_client

# Rate limits (per user per day)
FREE_TIER_AI_LIMIT = 10
PAID_TIER_AI_LIMIT = 50


def _ai_usage_cache_key(user) -> str:
    return f"ai_usage:{user.pk}:{timezone.now().strftime('%Y%m%d')}"


def _get_daily_ai_usage(user) -> int:
    """Current AI usage today: the atomic Redis counter, seeded from the DB log.

    The Redis counter is authoritative for limit enforcement (it includes
    in-flight reservations); the DB count is a floor that survives cache flushes.
    """
    from django.core.cache import cache

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    db_count = AIUsageLog.objects.filter(user=user, created_at__gte=today_start).count()
    cached = cache.get(_ai_usage_cache_key(user)) or 0
    return max(int(cached), db_count)


def _reserve_ai_slot(user, limit) -> bool:
    """Atomically reserve one AI call slot for today.

    Uses Redis INCR so concurrent requests cannot all pass the limit check.
    Returns False (and rolls back the increment) when the limit is exhausted.
    """
    from django.core.cache import cache

    key = _ai_usage_cache_key(user)
    # Seed the counter from the DB so a cache flush doesn't reset the limit.
    if cache.get(key) is None:
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        db_count = AIUsageLog.objects.filter(user=user, created_at__gte=today_start).count()
        cache.add(key, db_count, timeout=90000)  # 25h — survives the day boundary
    try:
        count = cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=90000)
        count = 1
    if count > limit:
        cache.decr(key)
        return False
    return True


def _release_ai_slot(user) -> None:
    """Return a reserved slot after a failed API call."""
    from django.core.cache import cache

    try:
        cache.decr(_ai_usage_cache_key(user))
    except ValueError:
        pass


def _get_ai_limit(user) -> int:
    """Return the daily AI call limit based on user's subscription tier."""
    from apps.subscriptions.services.usage_tracker import UsageTracker

    tracker = UsageTracker()
    plan = tracker.get_user_plan(user)
    if plan == "free":
        return FREE_TIER_AI_LIMIT
    return PAID_TIER_AI_LIMIT


class ExplainView(APIView):
    """POST /api/v1/ai/explain/

    Body: {"question_id": int, "selected_answer_id": int}

    Returns an AI-generated explanation covering:
      - Why the selected answer is wrong
      - Why the correct answer is right
      - A teaching moment / key concept

    Features:
      - Caching: same question+answer pair never calls the API twice.
      - Rate limiting: 50 calls/day for paid users, 10 for free tier.
      - Fallback: if API key missing or call fails, returns the static explanation.
      - Timeout: 30-second timeout on API calls.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        question_id = request.data.get("question_id")
        selected_answer_id = request.data.get("selected_answer_id")

        # --- Validate inputs ---
        if not question_id:
            return Response(
                {"error": "question_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            question = Question.objects.select_related(
                "subdomain__domain__certification"
            ).prefetch_related("answers").get(
                pk=question_id, is_active=True
            )
        except Question.DoesNotExist:
            return Response(
                {"error": "Question not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check certification access
        from apps.subscriptions.services.usage_tracker import UsageTracker
        if not UsageTracker().has_certification_access(
            request.user, question.subdomain.domain.certification_id
        ):
            return Response(
                {"error": "You don't have access to this certification."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Require that the user has answered this question (prevents scraping correct answers)
        from apps.exams.models import ExamResponse
        if not ExamResponse.objects.filter(
            session__user=request.user, question=question
        ).exists():
            return Response(
                {"error": "You must answer this question before viewing the explanation."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # If selected_answer_id provided, validate it
        selected_answer = None
        if selected_answer_id:
            try:
                selected_answer = Answer.objects.get(
                    pk=selected_answer_id, question=question
                )
            except Answer.DoesNotExist:
                return Response(
                    {"error": "Invalid answer for this question."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        correct_answer = question.answers.filter(is_correct=True).first()

        # --- Compute usage once for the entire request ---
        daily_usage = _get_daily_ai_usage(request.user)
        daily_limit = _get_ai_limit(request.user)

        # --- Rate limit check (before cache to prevent cache-based bypass) ---
        if daily_usage >= daily_limit:
            return Response({
                "source": "static",
                "question_id": question.id,
                "is_correct": selected_answer.is_correct if selected_answer else None,
                "explanation": question.explanation or "No explanation available.",
                "correct_answer_id": correct_answer.id if correct_answer else None,
                "correct_answer_text": correct_answer.text if correct_answer else None,
                "rate_limited": True,
                "daily_usage": daily_usage,
                "daily_limit": daily_limit,
            })

        # --- Check cache ---
        if selected_answer and not selected_answer.is_correct:
            cached = PersonalizedExplanation.objects.filter(
                question=question, wrong_answer=selected_answer
            ).first()
            if cached:
                return Response({
                    "source": "cached",
                    "question_id": question.id,
                    "is_correct": False,
                    "explanation": cached.content,
                    "correct_answer_id": correct_answer.id if correct_answer else None,
                    "correct_answer_text": correct_answer.text if correct_answer else None,
                    "daily_usage": daily_usage,
                    "daily_limit": daily_limit,
                })
        else:
            cached = Explanation.objects.filter(question=question).first()
            if cached:
                return Response({
                    "source": "cached",
                    "question_id": question.id,
                    "is_correct": selected_answer.is_correct if selected_answer else None,
                    "explanation": cached.content,
                    "correct_answer_id": correct_answer.id if correct_answer else None,
                    "correct_answer_text": correct_answer.text if correct_answer else None,
                    "daily_usage": daily_usage,
                    "daily_limit": daily_limit,
                })

        # --- Check API key ---
        api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not configured; returning static explanation.")
            return Response({
                "source": "static",
                "question_id": question.id,
                "is_correct": selected_answer.is_correct if selected_answer else None,
                "explanation": question.explanation or "No explanation available.",
                "correct_answer_id": correct_answer.id if correct_answer else None,
                "correct_answer_text": correct_answer.text if correct_answer else None,
            })

        # --- Atomically reserve a usage slot before spending API dollars ---
        # (concurrent requests each take their own slot; no TOCTOU race)
        if not _reserve_ai_slot(request.user, daily_limit):
            return Response({
                "source": "static",
                "question_id": question.id,
                "is_correct": selected_answer.is_correct if selected_answer else None,
                "explanation": question.explanation or "No explanation available.",
                "correct_answer_id": correct_answer.id if correct_answer else None,
                "correct_answer_text": correct_answer.text if correct_answer else None,
                "rate_limited": True,
                "daily_usage": daily_limit,
                "daily_limit": daily_limit,
            })

        # --- Call Claude API synchronously with 30s timeout ---
        try:
            client = _get_anthropic_client()
            if client is None:
                raise RuntimeError("Anthropic client could not be initialized")

            is_wrong_answer = selected_answer and not selected_answer.is_correct
            other_answers = question.answers.filter(is_correct=False)

            # Derive certification context for the prompt
            cert_name = question.subdomain.domain.certification.name
            domain_name = question.subdomain.domain.name

            if is_wrong_answer:
                prompt = PERSONALIZED_EXPLANATION_TEMPLATE.format(
                    stem=question.stem,
                    wrong_answer=selected_answer.text,
                    correct_answer=correct_answer.text if correct_answer else "N/A",
                    certification_name=cert_name,
                    domain_name=domain_name,
                )
            else:
                prompt = EXPLANATION_TEMPLATE.format(
                    stem=question.stem,
                    correct_answer=correct_answer.text if correct_answer else "N/A",
                    other_answers="\n".join(f"- {a.text}" for a in other_answers),
                    certification_name=cert_name,
                    domain_name=domain_name,
                )

            model = getattr(settings, "ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
            max_tokens = getattr(settings, "ANTHROPIC_MAX_TOKENS", 1024)

            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=get_explanation_system(cert_name),
                messages=[{"role": "user", "content": prompt}],
            )

            ai_content = message.content[0].text

            # --- Cache the result ---
            if is_wrong_answer:
                PersonalizedExplanation.objects.get_or_create(
                    question=question,
                    wrong_answer=selected_answer,
                    defaults={
                        "content": ai_content,
                        "model_used": model,
                    },
                )
            else:
                Explanation.objects.get_or_create(
                    question=question,
                    defaults={
                        "content": ai_content,
                        "model_used": model,
                    },
                )

            # --- Log usage ---
            AIUsageLog.objects.create(
                user=request.user,
                question=question,
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                model_used=model,
            )

            return Response({
                "source": "ai",
                "question_id": question.id,
                "is_correct": selected_answer.is_correct if selected_answer else None,
                "explanation": ai_content,
                "correct_answer_id": correct_answer.id if correct_answer else None,
                "correct_answer_text": correct_answer.text if correct_answer else None,
                "daily_usage": daily_usage + 1,
                "daily_limit": daily_limit,
                "disclaimer": "This explanation was generated by AI and may contain errors. Always verify with official study materials.",
            })

        except Exception as exc:
            logger.exception(
                "AI explanation failed for Q%s (user %s): %s",
                question_id, request.user.pk, exc,
            )
            # Failed call shouldn't consume the user's daily slot
            _release_ai_slot(request.user)
            # Fallback to static explanation on any API failure
            return Response({
                "source": "static",
                "question_id": question.id,
                "is_correct": selected_answer.is_correct if selected_answer else None,
                "explanation": question.explanation or "No explanation available.",
                "correct_answer_id": correct_answer.id if correct_answer else None,
                "correct_answer_text": correct_answer.text if correct_answer else None,
                "error": "AI service temporarily unavailable.",
            })


class ExplanationView(APIView):
    """GET /api/v1/ai/explain/{question_id}/
    Legacy async endpoint — returns cached explanation or triggers Celery generation.

    Query params:
        wrong_answer_id -- if provided, returns personalized explanation.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, question_id):
        # Validate question exists
        try:
            question = Question.objects.select_related(
                "subdomain__domain"
            ).get(pk=question_id, is_active=True)
        except Question.DoesNotExist:
            return Response(
                {"error": "Question not found.", "code": "question_not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Same gates as the POST endpoint — without these, this legacy path
        # allowed unlimited Celery->Anthropic dispatch for any question ID.
        from apps.subscriptions.services.usage_tracker import UsageTracker
        if not UsageTracker().has_certification_access(
            request.user, question.subdomain.domain.certification_id
        ):
            return Response(
                {"error": "You don't have access to this certification.", "code": "no_access"},
                status=status.HTTP_403_FORBIDDEN,
            )

        from apps.exams.models import ExamResponse
        if not ExamResponse.objects.filter(
            session__user=request.user, question=question
        ).exists():
            return Response(
                {"error": "You must answer this question before viewing the explanation.",
                 "code": "not_answered"},
                status=status.HTTP_403_FORBIDDEN,
            )

        self._user = request.user
        wrong_answer_id = request.query_params.get("wrong_answer_id")

        if wrong_answer_id:
            try:
                wrong_answer_id = int(wrong_answer_id)
            except (ValueError, TypeError):
                return Response(
                    {"error": "wrong_answer_id must be a valid integer.", "code": "invalid_param"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return self._get_personalized(question_id, wrong_answer_id)
        return self._get_general(question_id)

    def _dispatch_guarded(self, task, *args):
        """Reserve a daily AI slot, then dispatch the Celery generation task.

        Generation costs real API dollars, so it counts against the same
        per-user daily limit as the synchronous endpoint.
        """
        if not settings.ANTHROPIC_API_KEY:
            return Response(
                {"error": "AI explanations are not available at this time.", "code": "ai_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not _reserve_ai_slot(self._user, _get_ai_limit(self._user)):
            return Response(
                {"error": "Daily AI explanation limit reached.", "code": "rate_limited"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        task.delay(*args)
        return Response(
            {"status": "generating", "message": "Explanation is being generated. Please retry shortly."},
            status=status.HTTP_202_ACCEPTED,
        )

    def _get_general(self, question_id):
        try:
            explanation = Explanation.objects.select_related("question").get(
                question_id=question_id
            )
            return Response(ExplanationSerializer(explanation).data)
        except Explanation.DoesNotExist:
            return self._dispatch_guarded(generate_explanation, question_id)

    def _get_personalized(self, question_id, wrong_answer_id):
        try:
            explanation = PersonalizedExplanation.objects.select_related(
                "question", "wrong_answer"
            ).get(
                question_id=question_id, wrong_answer_id=wrong_answer_id
            )
            return Response(PersonalizedExplanationSerializer(explanation).data)
        except PersonalizedExplanation.DoesNotExist:
            return self._dispatch_guarded(
                generate_personalized_explanation, question_id, wrong_answer_id
            )
