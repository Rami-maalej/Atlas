"""Final integration sanity check."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.jarvis_general as gen
import core.jarvis_memory as mem

print("CORE+MEMORY+GENERAL OK")
mem.record_episode("Who won the Nobel?", "test episode")
mem.update_last_episode("Answer test")
print("episodes:", mem.recent_episodes(1))
print("recall:", mem.format_episode_recall("Nobel")[:150].replace("\n", " | "))
print("gen:", gen.is_general_question("what is the capital of Tunisia"))
