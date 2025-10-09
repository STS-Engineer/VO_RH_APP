# config.py

import os

class Config:
    # Informations de connexion
    DB_HOST = "avo-adb-002.postgres.database.azure.com"
    DB_PORT = 5432
    DB_LOGIN = "administrationSTS"
    DB_PASSWORD = "St$@0987"
    DB_DATABASE = "Test1_DL"
    
    # Mode SSL : 'require' est le mode recommandé pour Azure.
    # Changez à 'disable' si vous avez une erreur de connexion, pour débogage seulement.
    SSL_MODE = 'require' 

    # Clé secrète pour les sessions Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'votre_cle_secrete_tres_tres_securisee'