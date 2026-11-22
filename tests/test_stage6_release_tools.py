import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


capacity=load('capacity_check',Path('scripts/capacity_check.py'))
service=load('local_service',Path('scripts/local_service.py'))
release=load('stage6_release_check',Path('scripts/release_check.py'))


class Stage6ReleaseToolTests(unittest.TestCase):
    def test_percentile_uses_bounded_nearest_rank(self):
        self.assertEqual(capacity.percentile([.4,.1,.3,.2],.5),.2)
        self.assertEqual(capacity.percentile([.4,.1,.3,.2],.95),.4)

    def test_service_health_fails_closed(self):
        class Failing:
            def open(self,*args,**kwargs): raise OSError('fixture')
        original=service.OPENER; service.OPENER=Failing()
        try: self.assertFalse(service.health('http://127.0.0.1:1/health'))
        finally: service.OPENER=original

    def test_full_release_requires_stage6_evidence(self):
        # Frontend stages need installed dashboard packages (absent in backend CI);
        # this test only checks backend stage coverage and ordering.
        with mock.patch.object(release,'frontend_commands',return_value=[]):
            names=[name for name,_,_ in release.plan('full')]
        for expected in ('install_readiness','security_lab','failure_lab','capacity',
                         'native_service','pilot_startup','backup_restore'):
            self.assertIn(expected,names)
        self.assertLess(names.index('capacity'),names.index('pilot_startup'))


if __name__=='__main__': unittest.main()
