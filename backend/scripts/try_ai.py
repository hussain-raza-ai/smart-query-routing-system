"""
Quick manual check of the AI engine.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.try_ai

It classifies the sample queries from the project proposal, shows what the
keyword fallback would decide for the same text, and prints one reply draft
and one FAQ answer. Useful during development and in the project demo.
"""
import time

from app.services.ai_service import (
    _classify_by_keywords,  # used here only to show what the fallback would decide
    answer_faq,
    classify_query,
    clean_query_text,
    draft_reply,
    extract_course_code,
)

# Example queries from the project proposal (section 5.1) and the category we expect.
SAMPLES = [
    ("My result is wrong", "Result"),
    ("I need my fee challan", "Fee"),
    ("What is on the midterm of CS201?", "Course"),
    ("My attendance shows absent in CS101", "Attendance"),
    ("I need my degree verification", "Degree"),
    ("Lab computers are not working", "IT"),
    ("Scholarship application help", "Fee"),
    ("I have a problem, please help", "General"),
]

PAUSE_SECONDS = 13  # the free tier allows 5 requests per minute


def main() -> None:
    print(f"{'Query':38} {'Expected':11} {'AI':11} {'Conf':>5}  {'Method':8} {'Keywords':11} {'Course':7}")
    print("-" * 100)

    correct = 0
    for text, expected in SAMPLES:
        ai = classify_query(text)
        cleaned = clean_query_text(text)
        fallback = _classify_by_keywords(cleaned, extract_course_code(cleaned))

        is_correct = ai.category == expected
        correct += is_correct
        print(f"{text[:38]:38} {expected:11} {ai.category:11} {ai.confidence:5.2f}  "
              f"{ai.method:8} {fallback.category:11} {ai.course_code or '-':7} "
              f"{'OK' if is_correct else 'MISS'}")
        time.sleep(PAUSE_SECONDS)

    print(f"\nAI accuracy on samples: {correct}/{len(SAMPLES)}  (SDD target: about 80%)")

    print("\n--- Reply draft example ---")
    print(draft_reply("My result is wrong, I got 45 marks but expected around 80.",
                      "Result", "Ali Khan", "Examination Department"))
    time.sleep(PAUSE_SECONDS)

    print("\n--- FAQ example ---")
    print(answer_faq("Who handles fee challans?"))


if __name__ == "__main__":
    main()