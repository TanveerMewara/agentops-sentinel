"""Validate an exported business-rules report; exit 1 when its gate fails."""
import argparse
import json
import re
from pathlib import Path


def gate_passes(report):
    if report.get("evaluator_version") not in ('business_rules_v1', 'agent_rules_v2', 'agent_rules_v3', 'agent_rules_v4', 'agent_rules_v5'):
        raise ValueError("Unsupported evaluator version.")
    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Report has no cases.")
    passed = 0
    seen = set()
    for case in cases:
        if case["case_key"] in seen:
            raise ValueError("Duplicate case key.")
        seen.add(case["case_key"])
        checks = case["checks"]
        if not checks:
            raise ValueError("Case has no checks.")
        checks_pass = []
        for check in checks:
            private_rules = ('output_equals', 'output_schema', 'required_trace_spans',
                'ordered_trace_spans', 'forbidden_trace_spans', 'external_reported_status',
                'max_external_duration_ms', 'max_reported_external_tokens',
                'reported_model_usage_complete', 'max_external_spans', 'max_failed_trace_spans')
            if check['rule']=='semantic_judge':
                if (report['evaluator_version']!='agent_rules_v5' or check['expected'] is not True or
                    type(check['actual']) is not bool or not re.fullmatch(r'[0-9a-f]{64}',check.get('definition_hash','')) or
                    not re.fullmatch(r'[0-9a-f]{64}',check.get('judge_config_hash','')) or
                    not isinstance(check.get('score'),(int,float)) or not 0<=check['score']<=1 or
                    not isinstance(check.get('score_stddev'),(int,float)) or check['score_stddev']<0 or
                    not isinstance(check.get('repetitions'),int) or not 1<=check['repetitions']<=5):
                    raise ValueError('Invalid semantic judge representation.')
            if check['rule'] in private_rules:
                allowed = ('agent_rules_v3', 'agent_rules_v4', 'agent_rules_v5') if check['rule'].startswith('output_') else ('agent_rules_v4','agent_rules_v5')
                if (report['evaluator_version'] not in allowed or
                    check['expected'] is not True or type(check['actual']) is not bool or
                    not re.fullmatch(r'[0-9a-f]{64}', check.get('definition_hash', ''))):
                    raise ValueError('Invalid output check representation.')
            value = check["actual"] <= check["expected"] if check["rule"].startswith("max_") else check["actual"] == check["expected"]
            if check["passed"] is not value:
                raise ValueError("Check result contradicts its facts.")
            checks_pass.append(value)
        case_passes = all(checks_pass)
        if case["passed"] is not case_passes:
            raise ValueError("Case result contradicts its checks.")
        passed += case_passes
    total_weight = sum(float(case.get('weight',1.0)) for case in cases)
    if total_weight <= 0:
        raise ValueError('Invalid case weights.')
    rate = sum(float(case.get('weight',1.0)) for case in cases if case['passed']) / total_weight
    if report["total_cases"] != len(cases) or report["passed_cases"] != passed or report["pass_rate"] != rate:
        raise ValueError("Report totals contradict its cases.")
    threshold = report["gate"]["min_pass_rate"]
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("Invalid gate threshold.")
    result = rate >= threshold
    if report["gate"]["passed"] is not result:
        raise ValueError("Gate result contradicts its threshold.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        passed = gate_passes(json.loads(args.report.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("Invalid evaluation report:", type(error).__name__)
        return 2
    print("Evaluation gate:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
