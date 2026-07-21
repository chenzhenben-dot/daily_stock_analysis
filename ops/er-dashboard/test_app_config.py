"""Offline configuration tests for the ER dashboard server.

These tests only validate that ``ER_*`` environment variables override the
historical production defaults in ``app.py`` and ``trigger.py``. They never
touch the network, the trigger pipeline, or any production data. Run them
with::

    python3 -m unittest test_app_config -v
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

APP_PATH = Path(__file__).resolve().with_name("app.py")
TRIGGER_PATH = Path(__file__).resolve().with_name("trigger.py")


def _load_module(name, path, env):
    """Load a module from disk with the supplied env vars and return it."""
    saved = {key: os.environ.get(key) for key in env}
    sys.modules.pop(name, None)
    try:
        for key, value in env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        spec = importlib.util.spec_from_file_location(name, str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for key, previous in saved.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def _load_app(env):
    return _load_module("er_app_under_test", APP_PATH, env)


def _load_trigger(env):
    return _load_module("er_trigger_under_test", TRIGGER_PATH, env)


class ErAppConfigTests(unittest.TestCase):
    def test_production_defaults_match_historical_layout(self):
        module = _load_app({})
        self.assertEqual(module.DASH_DIR, "/opt/er-dashboards")
        self.assertEqual(module.PORT, 8080)
        self.assertEqual(module.HOST, "0.0.0.0")
        self.assertEqual(module.LOG_FILE, "/opt/er-dashboard/logs/access.log")
        self.assertEqual(module.JOB_LOG_FILE, "/opt/er-dashboard/logs/jobs.log")
        self.assertEqual(module.TRIGGER_SCRIPT, "/opt/er-dashboard/trigger.py")
        self.assertEqual(module.TRIGGER_CWD, "/opt/er-dashboard")
        self.assertEqual(module.ER_JOB_TIMEOUT_SECONDS, 1800)

    def test_env_overrides_take_effect(self):
        module = _load_app({
            "ER_DASHBOARD_DIR": "/tmp/orbstack/dashboards",
            "ER_PORT": "18080",
            "ER_HOST": "127.0.0.1",
            "ER_LOG_FILE": "/tmp/orbstack/logs/access.log",
            "ER_JOB_LOG_FILE": "/tmp/orbstack/logs/jobs.log",
            "ER_TRIGGER_SCRIPT": "/tmp/orbstack/trigger.py",
            "ER_TRIGGER_CWD": "/tmp/orbstack",
            "ER_JOB_TIMEOUT_SECONDS": "120",
            "ER_DSA_URL": "http://127.0.0.1:18088/",
        })
        self.assertEqual(module.DASH_DIR, "/tmp/orbstack/dashboards")
        self.assertEqual(module.PORT, 18080)
        self.assertEqual(module.HOST, "127.0.0.1")
        self.assertEqual(module.LOG_FILE, "/tmp/orbstack/logs/access.log")
        self.assertEqual(module.JOB_LOG_FILE, "/tmp/orbstack/logs/jobs.log")
        self.assertEqual(module.TRIGGER_SCRIPT, "/tmp/orbstack/trigger.py")
        self.assertEqual(module.TRIGGER_CWD, "/tmp/orbstack")
        self.assertEqual(module.ER_JOB_TIMEOUT_SECONDS, 120)
        self.assertEqual(module.DSA_URL, "http://127.0.0.1:18088/")


class ErTriggerConfigTests(unittest.TestCase):
    def test_production_defaults_match_historical_layout(self):
        module = _load_trigger({})
        self.assertEqual(module.DSA_ENV_PATH, "/opt/dsa/.env")
        self.assertEqual(module.DASH_DIR, "/opt/er-dashboards")
        self.assertEqual(
            str(module.SERVER_SKILL_DIR),
            "/opt/er-dashboard/equity-research",
        )

    def test_env_overrides_take_effect(self):
        module = _load_trigger({
            "ER_ENV_PATH": "/opt/er-dashboard/.env.local",
            "ER_DASHBOARD_DIR": "/tmp/orbstack/dashboards",
            "ER_SKILL_DIR": "/tmp/orbstack/equity-research",
        })
        self.assertEqual(module.DSA_ENV_PATH, "/opt/er-dashboard/.env.local")
        self.assertEqual(module.DASH_DIR, "/tmp/orbstack/dashboards")
        self.assertEqual(
            str(module.SERVER_SKILL_DIR),
            "/tmp/orbstack/equity-research",
        )


if __name__ == "__main__":
    unittest.main()