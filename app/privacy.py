from typing import Dict, Tuple
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine

# Indian PAN and GST formats aren't in Presidio's default recognizer set —
# these are custom, high-precision regex recognizers layered on top of Presidio's
# built-in NER (PERSON, PHONE_NUMBER, EMAIL_ADDRESS).
_PAN_PATTERN = Pattern(name="pan_pattern", regex=r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b", score=0.9)
_GST_PATTERN = Pattern(name="gst_pattern", regex=r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}\d[Z]{1}[A-Z\d]{1}\b", score=0.9)
_ACCOUNT_PATTERN = Pattern(name="account_pattern", regex=r"\b\d{9,18}\b", score=0.6)

_pan_recognizer = PatternRecognizer(supported_entity="IN_PAN", patterns=[_PAN_PATTERN])
_gst_recognizer = PatternRecognizer(supported_entity="IN_GST", patterns=[_GST_PATTERN])
_account_recognizer = PatternRecognizer(
    supported_entity="BANK_ACCOUNT", patterns=[_ACCOUNT_PATTERN],
    context=["account", "a/c", "acc", "bank"],
)

_analyzer = AnalyzerEngine()
_analyzer.registry.add_recognizer(_pan_recognizer)
_analyzer.registry.add_recognizer(_gst_recognizer)
_analyzer.registry.add_recognizer(_account_recognizer)

_anonymizer = AnonymizerEngine()

_ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "IN_PAN", "IN_GST", "BANK_ACCOUNT"]


def redact_text(text: str) -> Tuple[str, Dict[str, int]]:
    """Returns (redacted_text, entity_count_summary). Never returns raw PII spans —
    only a count per entity type, safe to persist in audit logs."""
    if not text or not text.strip():
        return text, {}

    results = _analyzer.analyze(text=text, language="en", entities=_ENTITIES)
    anonymized = _anonymizer.anonymize(text=text, analyzer_results=results)

    summary: Dict[str, int] = {}
    for r in results:
        summary[r.entity_type] = summary.get(r.entity_type, 0) + 1

    return anonymized.text, summary