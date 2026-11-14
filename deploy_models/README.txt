Place trained v0.6.4 scikit-learn 1.6.1 folders in models/<model_folder>/.
This delivered ZIP deliberately does not contain the binary model artifacts.
Do not commit or push until all six folders are added and the manifest is generated:
python scripts/prepare_github_models.py --write
Models are stored with Git LFS via .gitattributes.
