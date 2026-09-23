"""Agent loop turn cap: deck builds need more turns than the SDK default."""
import os
import unittest
from unittest.mock import patch

from app.server import agent_max_turns


class MaxTurnsTests(unittest.TestCase):
    def test_default_covers_multi_step_builds(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(agent_max_turns(), 30)

    def test_env_override_is_honored(self):
        with patch.dict(os.environ, {"CHATKIT_MAX_TURNS": "40"}):
            self.assertEqual(agent_max_turns(), 40)

    def test_invalid_and_nonpositive_values_fall_back_safely(self):
        with patch.dict(os.environ, {"CHATKIT_MAX_TURNS": "lots"}):
            self.assertEqual(agent_max_turns(), 30)
        with patch.dict(os.environ, {"CHATKIT_MAX_TURNS": "0"}):
            self.assertEqual(agent_max_turns(), 1)


if __name__ == "__main__":
    unittest.main()
