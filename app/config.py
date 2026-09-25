import math
import os

# A configurable example target; a settings UI is deferred.
PROTEIN_GOAL_GRAMS = float(os.environ.get("FITLOG_PROTEIN_GOAL_G", "150"))
if not math.isfinite(PROTEIN_GOAL_GRAMS) or not 0 < PROTEIN_GOAL_GRAMS <= 1000:
    raise ValueError("FITLOG_PROTEIN_GOAL_G must be greater than 0 and at most 1000.")
