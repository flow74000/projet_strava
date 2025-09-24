import time
from datetime import datetime

print("--- SCRIPT DE TEST DU WORKER DÉMARRÉ ---")

count = 0
while True:
    count += 1
    print(f"[{datetime.now()}] Cycle de test numéro {count}. Le worker est en vie.")
    
    # On fait une pause d'une minute pour le test
    time.sleep(60)