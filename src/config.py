"""AnkiTutor central configuration.

Single place for paths, Anki identifiers, session policy and mastery levels.
Every other module imports from here so there is exactly one source of truth
for "where things live" and "what the rules are".
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
SKILL_ROOT = Path(__file__).resolve().parent.parent

LIBRARY_DIR = Path(os.environ.get("ANKITUTOR_LIBRARY", SKILL_ROOT / "library"))
SOURCES_DIR = LIBRARY_DIR / "sources"
PARSED_DIR = LIBRARY_DIR / "parsed"
MANIFESTS_DIR = LIBRARY_DIR / "manifests"
INDEX_DIR = LIBRARY_DIR / "index"

STATE_DIR = Path(os.environ.get("ANKITUTOR_STATE", SKILL_ROOT / "state"))
ACTIVE_SESSION_PATH = STATE_DIR / "active_session.json"
EVENTS_LOG_PATH = Path(os.environ.get("ANKITUTOR_EVENTS_LOG", STATE_DIR / "events.jsonl"))

# --------------------------------------------------------------------------
# Anki / AnkiConnect
# --------------------------------------------------------------------------
ANKI_URL = os.environ.get("ANKICONNECT_URL", "http://127.0.0.1:8765")
ANKI_API_KEY = os.environ.get("ANKICONNECT_API_KEY") or None
ANKI_VERSION = 6

DECK = "AnkiTutor::Concepts"
MODEL = "AdaptiveConcept"
MANAGED_TAG = "managed::anki_tutor"

# Field order matters: it is the order AnkiConnect uses to create the model.
FIELDS = [
    "ConceptID",
    "Title",
    "CoreKnowledge",
    "LearningObjective",
    "Level",
    "Prerequisites",
    "CommonErrors",
    "SourceRefs",
    "SourceHash",
    "Status",
    "TutorInstruction",
    "Version",
    "UpdatedAt",
]

REQUIRED_FIELDS = [
    "ConceptID",
    "Title",
    "CoreKnowledge",
    "LearningObjective",
    "Level",
    "Status",
    "Version",
    "UpdatedAt",
]

CARD_TEMPLATES = [
    {
        "Name": "Concept",
        "Front": (
            "[Concept Review] {{Title}}\n"
            "请不看资料，用自己的话回忆 {{CoreKnowledge}}，并举一个例子。"
        ),
        "Back": (
            "核心：{{CoreKnowledge}}<br>\n"
            "目标层级：{{Level}}<br>\n"
            "来源：{{SourceRefs}}"
        ),
    }
]

MODEL_CSS = ".card { font-family: -apple-system, 'PingFang SC', sans-serif; font-size: 18px; }"

# --------------------------------------------------------------------------
# Concept status / mastery
# --------------------------------------------------------------------------
STATUS_ACTIVE = "active"
STATUS_RETIRED = "retired"
STATUS_MERGED = "merged"
VALID_STATUS = {STATUS_ACTIVE, STATUS_RETIRED, STATUS_MERGED}

LEVELS = ["L0", "L1", "L2", "L3"]
LEVEL_DEFINITION = {
    "L0": "Recognition — 看到选项能识别",
    "L1": "Recall — 无选项能独立回忆",
    "L2": "Application — 陌生情境能应用",
    "L3": "Construction — 能从零设计、审计、解释系统",
}

ERROR_TYPES = [
    "knowledge_gap",
    "concept_confusion",
    "incomplete_model",
    "execution_gap",
    "careless_error",
    "overconfidence",
]

ERROR_INTERVENTION = {
    "knowledge_gap": "短教学 + 分步检索",
    "concept_confusion": "对比 + 最小反例",
    "incomplete_model": "指出缺失环节 + 补全",
    "execution_gap": "从零构造/操作题",
    "careless_error": "要求复核，不长讲",
    "overconfidence": "高优先级重教 + 新情境复测；可写入 CommonErrors",
}

# Ease values, mapped to Anki's answerCards scale.
EASE_AGAIN, EASE_HARD, EASE_GOOD, EASE_EASY = 1, 2, 3, 4
EASE_NAMES = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}

# --------------------------------------------------------------------------
# Session policy (doc §9.1)
# --------------------------------------------------------------------------
SESSION_POLICY = {
    "target_concepts": 3,
    "normal_questions": (4, 6),
    "max_questions": 8,
    "target_duration_min": (10, 15),
    "hard_cap_duration_min": 20,
    "mastered": 1,
    "uncertain": 2,
    "misconception": (2, 3),
    "deep_misconception_limit": 1,
}

MODES = ["active_learning", "passive_review", "quick_quiz"]
SESSION_STATUSES = [
    "asking",
    "waiting_answer",
    "answer_received",
    "diagnosing",
    "verifying_transfer",
    "graded",
    "paused",
    "closed",
]


def ensure_dirs() -> None:
    """Create library/state directories if missing (idempotent)."""
    for d in (SOURCES_DIR, PARSED_DIR, MANIFESTS_DIR, INDEX_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
