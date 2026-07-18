EPL artifacts prepared for PrixPredictor FastAPI.

Fixes applied:
1. feature_columns.json replaced with the actual feature list from model_metadata_v04.json.
2. model_config.json model filenames updated to match the artifact filenames in this folder.

Place the contents of this epl/ folder into:
models/epl/

Important runtime note:
These pickles were created with scikit-learn 1.6.1. Use scikit-learn==1.6.1 in the FastAPI environment for safest loading.
