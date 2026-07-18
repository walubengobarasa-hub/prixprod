import joblib
from pathlib import Path

model_path = Path("../models/epl/epl_outcome_calibrated_model.pkl")
model = joblib.load(model_path)

print("MODEL TYPE:", type(model))
print("CLASSES:", getattr(model, "classes_", None))

if hasattr(model, "calibrated_classifiers_"):
    print("HAS calibrated_classifiers_:", True)
    print("COUNT:", len(model.calibrated_classifiers_))

if hasattr(model, "estimator"):
    print("ESTIMATOR TYPE:", type(model.estimator))
    print("ESTIMATOR CLASSES:", getattr(model.estimator, "classes_", None))

if hasattr(model, "base_estimator"):
    print("BASE ESTIMATOR TYPE:", type(model.base_estimator))
    print("BASE ESTIMATOR CLASSES:", getattr(model.base_estimator, "classes_", None))