"""Offline routing regressions and prompt-presence checks, NOT learning efficacy.

Synthetic sessions must never be reported as real learner history. B checks the
teaching contract only: no automatic concept selector is implemented or implied.
"""
from copy import deepcopy
from pathlib import Path

from session import new_session

ROOT = Path(__file__).resolve().parents[1]


def test_a_repeated_independent_transfer_returns_without_mutation():
    s = new_session('active_learning')
    s.data['task'] = 'evaluate a synthetic pricing hypothesis'
    s.set_current_question('research.pricing', 'explain cashflows', 'L2')
    s.record_answer('correct')
    for q in ['different settlement convention', 'different financing constraint']:
        s.set_current_question('research.pricing', q, 'L2', True)
        s.record_answer('correct')
    before = deepcopy(s.data)
    advice = s.teaching_guidance()
    assert advice['independent_transfers'] == 2
    assert advice['marginal_value'] == 'diminishing'
    assert advice['action'] == 'return_to_original_task'
    assert s.data == before
    assert s.closure_decision().grade == 3


def test_b_next_concept_contract_uses_coverage_dependencies_not_chat_recency():
    skill = (ROOT / 'SKILL.md').read_text()
    section = skill.split('## 下一 Concept 的增量价值检查', 1)[1].split('\n## ', 1)[0]
    for marker in ['strategy roadmap gap', 'search --track', 'TargetLevel',
                   'Prerequisites', 'SourceRefs', 'Source Library', 'Anki',
                   '覆盖', '全局 search', '不扩 Roadmap', 'no_evidence',
                   '不代表不会', '不再默认加一道换数字题', '不是要求先刷满两题']:
        assert marker in section
    prompt = (ROOT / 'prompts/question_generation.md').read_text()
    assert '下一 Concept 的增量价值检查' in prompt
    assert '不把最近聊天细节当默认主线' in prompt


def test_c_observed_prerequisite_gap_repairs_then_returns_to_research():
    s = new_session('active_learning')
    task = 'synthetic cross-venue pricing anomaly: test executable net return'
    s.data.update(task=task, bottleneck='funding cashflow sign')
    s.set_current_question('research.funding', 'cashflow sign in venue A', 'L2')
    s.record_answer('wrong')
    assert s.teaching_guidance()['action'] == 'minimal_prerequisite_repair'
    s.advance_attempt(1)
    s.record_answer('correct')
    assert s.teaching_guidance()['action'] == 'fresh_independent_transfer'
    s.set_current_question('research.funding', 'new settlement rule at venue B', 'L2', True)
    s.record_answer('correct')
    advice = s.teaching_guidance()
    assert advice['action'] == 'return_to_original_task'
    assert advice['task'] == task
    assert s.closure_decision().grade == 1


def test_external_view_evaluation_is_allowed_with_provenance():
    prompt = (ROOT / 'prompts/question_generation.md').read_text()
    assert '刷到博主推文' in prompt
    assert '并不禁止' in prompt
    assert '教学虚构明确标识' in prompt
    assert '真实来源注明 URL/as-of' in prompt
