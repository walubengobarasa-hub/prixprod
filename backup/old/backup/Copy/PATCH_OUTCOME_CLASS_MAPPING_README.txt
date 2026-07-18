PrixPredictor FastAPI outcome class mapping patch

What changed:
- app/predictor.py now maps numeric outcome model classes:
  0 -> AWAY_WIN
  1 -> DRAW
  2 -> HOME_WIN

Why:
- The EPL calibrated outcome model exposes classes_ as [0, 1, 2].
- The previous API expected string classes such as HOME_WIN/DRAW/AWAY_WIN.
- This caused match_outcome and double_chance probabilities to become 0.0.

After deploying:
1. Restart uvicorn.
2. Run python helper.py again.
3. match_outcome and double_chance probabilities should be non-zero.
