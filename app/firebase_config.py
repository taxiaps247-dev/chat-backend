import os
import json
import firebase_admin
from firebase_admin import credentials, auth, firestore

_db = None


def init_firebase():
    global _db

    if not firebase_admin._apps:
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

        if cred_json:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
            print("DEBUG Firebase project_id:", cred_dict.get("project_id"))
        else:
            cred_path = os.getenv("FIREBASE_CREDENTIALS", "./firebase-service-account.json")
            cred = credentials.Certificate(cred_path)
            print("DEBUG Firebase credentials path:", cred_path)

        firebase_admin.initialize_app(cred)

    _db = firestore.client()


def get_firestore_client():
    if _db is None:
        init_firebase()
    return _db


def verify_firebase_token(token: str):
    decoded = auth.verify_id_token(token)
    print("DEBUG verify token uid:", decoded.get("uid"))
    print("DEBUG verify token aud:", decoded.get("aud"))
    print("DEBUG verify token iss:", decoded.get("iss"))
    return decoded