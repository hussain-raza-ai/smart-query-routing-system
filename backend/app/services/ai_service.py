"""
AI engine (FR-03, FR-05): classifies queries, drafts replies and answers FAQs.

Classification pipeline (SDD section 8.2):
    1. Gemini classifies the query.
    2. If Gemini is unsure (confidence below AI_CONFIDENCE_THRESHOLD) or fails,
       Claude classifies it again, provided a Claude key is configured.
    3. If no AI provider answers, a keyword matcher takes over.
    4. If the keywords find nothing either, the query is flagged for manual review.

The rest of the backend never talks to an AI provider directly; it only uses
classify_query(), draft_reply() and answer_faq() from this module.
"""
import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.constants import Category, RouteMethod
from app.services import ai_prompts

logger = logging.getLogger(__name__)

AI_TIMEOUT_SECONDS = 20
MAX_QUERY_CHARS = 2000
KEYWORD_CONFIDENCE = 0.50  # a keyword match is only a guess, so it is never reported as confident


# --- Result types ------------------------------------------------------------

class _ModelClassification(BaseModel):
    """The structured answer we ask the language model to return."""

    category: Literal["Fee", "Result", "Course", "Attendance", "Degree", "IT", "General"]
    intent: str = Field(description="What the student needs, in 3 to 6 words")
    confidence: float = Field(description="How sure the classification is, from 0 to 1")


@dataclass
class ClassificationResult:
    category: str
    intent: str
    confidence: float
    method: str                        # which pipeline step decided (see RouteMethod)
    course_code: Optional[str] = None  # e.g. "CS619" if the student mentioned one
    needs_review: bool = False         # True when nothing could classify the query


# --- Providers ---------------------------------------------------------------

def _gemini(temperature: float) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=temperature,
        timeout=AI_TIMEOUT_SECONDS,
        max_retries=1,
    )


def _claude(temperature: float) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.CLAUDE_MODEL,
        api_key=settings.ANTHROPIC_API_KEY,
        temperature=temperature,
        timeout=AI_TIMEOUT_SECONDS,
        max_retries=1,
    )


def _gemini_enabled() -> bool:
    return bool(settings.GEMINI_API_KEY)


def _claude_enabled() -> bool:
    return bool(settings.ANTHROPIC_API_KEY and settings.CLAUDE_MODEL)


def _text_providers():
    """Providers for free-text tasks (drafts, FAQ), in order of preference."""
    providers = []
    if _gemini_enabled():
        providers.append(("Gemini", _gemini))
    if _claude_enabled():
        providers.append(("Claude", _claude))
    return providers


# --- Text preparation --------------------------------------------------------

_COURSE_CODE = re.compile(r"\b([A-Za-z]{2,4})\s?-?(\d{3})\b")


def clean_query_text(text: str) -> str:
    """
    Prepare raw query text for the model (SDD 8.2 preprocessing): drop quoted
    email history and signatures, collapse whitespace and cap the length.
    """
    kept = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(">"):  # quoted text from an earlier email
            continue
        if line == "--" or re.match(r"^On .+ wrote:$", line):  # signature or reply header
            break
        kept.append(line)
    cleaned = re.sub(r"\s+", " ", " ".join(kept)).strip()
    return cleaned[:MAX_QUERY_CHARS]


def extract_course_code(text: str) -> Optional[str]:
    """Find a course code such as 'CS619' or 'cs 619' in the text."""
    match = _COURSE_CODE.search(text)
    return f"{match.group(1)}{match.group(2)}".upper() if match else None


# --- Classification ----------------------------------------------------------

_CLASSIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ai_prompts.CLASSIFICATION_SYSTEM),
    ("human", ai_prompts.CLASSIFICATION_USER),
])


def _ask_model(provider_name: str, build_model, text: str) -> Optional[_ModelClassification]:
    """Ask one provider to classify the text. Returns None if the call fails."""
    chain = _CLASSIFY_PROMPT | build_model(temperature=0).with_structured_output(_ModelClassification)
    try:
        answer = chain.invoke({"query": text})
    except Exception as exc:  # network error, quota limit or unparsable output
        logger.warning("%s classification failed: %s", provider_name, exc)
        return None
    if answer is None:
        return None
    answer.confidence = min(max(answer.confidence, 0.0), 1.0)
    return answer


def classify_query(raw_text: str) -> ClassificationResult:
    """Run the classification pipeline described at the top of this module."""
    text = clean_query_text(raw_text)
    course_code = extract_course_code(text)

    def result(answer: _ModelClassification, method: str) -> ClassificationResult:
        return ClassificationResult(
            category=answer.category,
            intent=answer.intent,
            confidence=round(answer.confidence, 2),
            method=method,
            course_code=course_code,
        )

    gemini_answer = _ask_model("Gemini", _gemini, text) if _gemini_enabled() else None
    if gemini_answer and gemini_answer.confidence >= settings.AI_CONFIDENCE_THRESHOLD:
        return result(gemini_answer, RouteMethod.GEMINI)

    claude_answer = _ask_model("Claude", _claude, text) if _claude_enabled() else None
    if claude_answer:
        return result(claude_answer, RouteMethod.CLAUDE)

    if gemini_answer:
        # Gemini was unsure but nothing better is available: keep its best guess.
        return result(gemini_answer, RouteMethod.GEMINI)

    return _classify_by_keywords(text, course_code)


# Checked in this order; on a tie the earlier category wins,
# so the more specific categories come first.
_KEYWORDS = {
    Category.ATTENDANCE: ["attendance", "absent"],
    Category.FEE: ["fee", "fees", "challan", "voucher", "instalment", "installment",
                   "dues", "fines", "scholarship"],
    Category.RESULT: ["result", "results", "grade", "grades", "marks", "gpa", "cgpa",
                      "recheck", "rechecking", "dmc", "exam", "datesheet", "date sheet"],
    Category.DEGREE: ["degree", "transcript", "enrolment", "enrollment", "admission",
                      "freeze", "verification"],
    Category.IT: ["lms", "password", "login", "portal", "email", "wifi", "internet", "lab"],
    Category.COURSE: ["course", "lecture", "lectures", "assignment", "quiz", "syllabus",
                      "midterm", "handouts"],
}


def _classify_by_keywords(text: str, course_code: Optional[str]) -> ClassificationResult:
    """Last-resort classifier, used only when no AI provider is reachable."""
    lowered = text.lower()
    scores = {
        category: sum(1 for word in words if re.search(rf"\b{re.escape(word)}\b", lowered))
        for category, words in _KEYWORDS.items()
    }
    best_category, best_score = max(scores.items(), key=lambda item: item[1])

    if best_score == 0 and course_code:
        best_category, best_score = Category.COURSE, 1  # a course code alone points to the instructor

    if best_score == 0:
        return ClassificationResult(
            category=Category.GENERAL,
            intent="Needs manual review",
            confidence=0.0,
            method=RouteMethod.KEYWORD,
            course_code=course_code,
            needs_review=True,
        )
    return ClassificationResult(
        category=best_category,
        intent=f"{best_category} request",
        confidence=KEYWORD_CONFIDENCE,
        method=RouteMethod.KEYWORD,
        course_code=course_code,
    )


# --- Reply drafting ----------------------------------------------------------

_DRAFT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ai_prompts.REPLY_DRAFT_SYSTEM),
    ("human", ai_prompts.REPLY_DRAFT_USER),
])


def draft_reply(raw_text: str, category: str, student_name: str, department_name: str) -> str:
    """
    Write a first draft for staff to review (FR-05). It is never sent automatically.
    Falls back to a neutral template if no AI provider is available.
    """
    values = {
        "query": clean_query_text(raw_text),
        "category": category,
        "student_name": student_name,
        "department_name": department_name,
    }
    for provider_name, build_model in _text_providers():
        try:
            draft = (_DRAFT_PROMPT | build_model(temperature=0.3) | StrOutputParser()).invoke(values)
            if draft.strip():
                return draft.strip()
        except Exception as exc:
            logger.warning("%s reply draft failed: %s", provider_name, exc)

    return (
        f"Dear {student_name},\n\n"
        f"Thank you for contacting us. Your query has been received by the {department_name} "
        f"and is being reviewed. We will get back to you as soon as possible.\n\n"
        f"Regards,\n{department_name}"
    )


# --- FAQ assistant -----------------------------------------------------------

_FAQ_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ai_prompts.FAQ_SYSTEM),
    ("human", "{question}"),
])

_FAQ_FALLBACK = (
    "I can't answer that right now. Please submit your question as a query "
    "from the dashboard and the right department will reply."
)


def answer_faq(question: str) -> str:
    """Answer a general question using only the facts in ai_prompts.FAQ_KNOWLEDGE."""
    values = {"question": clean_query_text(question), "knowledge": ai_prompts.FAQ_KNOWLEDGE}
    for provider_name, build_model in _text_providers():
        try:
            answer = (_FAQ_PROMPT | build_model(temperature=0.2) | StrOutputParser()).invoke(values)
            if answer.strip():
                return answer.strip()
        except Exception as exc:
            logger.warning("%s FAQ answer failed: %s", provider_name, exc)
    return _FAQ_FALLBACK