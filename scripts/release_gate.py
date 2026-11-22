"""Validate an immutable Stage 4 release-gate report and exit nonzero on failure."""
import argparse,json
from pathlib import Path


def gate_passes(report):
    checks=report.get('checks')
    if not isinstance(checks,dict) or set(checks)!={'mean_pass_rate','pass_rate_stability','held_out','calibration','regression'}:
        raise ValueError('Invalid release checks.')
    if any(type(value) is not bool for value in checks.values()): raise ValueError('Release checks must be boolean.')
    analysis=report.get('candidate_analysis',{})
    if not isinstance(analysis.get('experiment_count'),int) or analysis['experiment_count']<2: raise ValueError('Repeated experiments are required.')
    expected=all(checks.values())
    if report.get('passed') is not expected: raise ValueError('Release decision contradicts checks.')
    return expected


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('report',type=Path); args=parser.parse_args()
    try: passed=gate_passes(json.loads(args.report.read_text(encoding='utf-8')))
    except (ValueError,KeyError,TypeError,OSError) as error:
        print('Invalid release gate:',type(error).__name__); return 2
    print('Release gate:','PASS' if passed else 'FAIL'); return 0 if passed else 1


if __name__=='__main__': raise SystemExit(main())
