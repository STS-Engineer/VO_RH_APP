# config.py

import os

class Config:
    # Informations de connexion
    DB_HOST = "avcpgsqlflexsrvr.postgres.database.azure.com"
    DB_PORT = 5432
    DB_LOGIN = "sqladmin"
    DB_PASSWORD = "P@$$w0rd123"
    DB_DATABASE = "STS_BI_Core"
    
    # Mode SSL : 'require' est le mode recommandé pour Azure.
    # Changez à 'disable' si vous avez une erreur de connexion, pour débogage seulement.
    SSL_MODE = 'require' 

    # Clé secrète pour les sessions Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'votre_cle_secrete_tres_tres_securisee'