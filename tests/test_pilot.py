"""The local launcher must isolate frontend secrets and preserve busy services."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

scripts = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location("pilot", scripts / "pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)
demo_spec = importlib.util.spec_from_file_location("pilot_demo", scripts / "pilot_demo.py")
pilot_demo = importlib.util.module_from_spec(demo_spec)
demo_spec.loader.exec_module(pilot_demo)


class PilotTests(unittest.TestCase):
    def test_frontend_does_not_inherit_backend_secrets(self):
        with patch.dict(os.environ, {"PATH": "synthetic-path", "TEMP": "synthetic-temp",
            "SENTINEL_AUTH_PEPPER": "private", "SENTINEL_WORKER_API_KEY": "private",
            "SENTINEL_CREDENTIAL_ENCRYPTION_KEY": "private", "OPENAI_API_KEY": "private",
            "PGPASSWORD": "private", "DATABASE_URL": "private"}, clear=True):
            environment = pilot.frontend_environment("node")
        self.assertEqual(set(environment), {"PATH", "TEMP", "NODE_ENV"})
        self.assertNotIn("private", str(environment))

    def test_duplicate_ports_fail_before_starting_components(self):
        with self.assertRaisesRegex(RuntimeError, "different port"):
            pilot.check_ports([3000, 3000, 8000])

    def test_demo_replays_the_frozen_model_alias(self):
        class Client:
            def request(self,path,body=None):
                if path=='/v1/tools' and body is None: return []
                if path.startswith('/v1/agents/') and '/tools/' in path: return {}
                if path=='/v1/properties': return {'property':{'property_id':'property'}}
                if path=='/v1/tools' or body and body.get('name')=='book_viewing': return {'tool_id':'tool'}
                raise AssertionError(path)
            def register_agent(self,*args): return {'agent_id':'agent'}
            def create_version(self,*args,**kwargs):
                self.model_alias=kwargs['model_alias']; return {'agent_version_id':'version'}
        client=Client(); pilot_demo.configure_demo(client)
        self.assertEqual(client.model_alias,'deterministic_estateflow')
