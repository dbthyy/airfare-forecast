# 1. Preprocess
python preprocess.py --input data/raw/merged_new.csv --output data/cleaned_new.csv

# 2. Predict (không train lại)
python predictor.py --predict --data data/cleaned_new.csv

# 3. Start server (dùng model.pkl cũ, predict cho user)
python api_server.py