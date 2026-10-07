"""Central configuration for AirAuth.

Every magic number lives here. Nothing in security.py or server.py
should hardcode thresholds, weights, or sizes.
"""

# --- Enrollment -----------------------------------------------------------
ENROLL_PASSES: int = 3          # passes fused into one master template
TARGET_POINTS: int = 64         # resampled trajectory length
DBA_ITERATIONS: int = 6         # DTW Barycenter Averaging refinement rounds

# --- Matching -------------------------------------------------------------
DTW_BAND: int = 14              # Sakoe-Chiba constraint band width
FUSION_W_SHAPE: float = 0.70    # score-level fusion weights (must sum to 1)
FUSION_W_BEHAVIOR: float = 0.30
BEHAVIOR_SCALE: float = 15.0    # scales cosine distance into DTW range

# Decision threshold on the fused cost. Calibrate with backend/eval.py
# against real genuine/impostor attempts instead of guessing.
THRESHOLD: float = 16.5

# --- Input validation -----------------------------------------------------
MIN_POINTS: int = 8             # hard floor for feature extraction
MIN_KINEMATICS: int = 6        # hard floor for behavioral profile
UI_MIN_POINTS: int = 12         # frontend "long enough" gate before capture
