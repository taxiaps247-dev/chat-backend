from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.firebase_config import get_firestore_client, init_firebase, verify_firebase_token
from app.websocket_manager import ConnectionManager
from app.chat_service import (
    get_user_profile,
    save_message,
    get_user_chats,
    get_chat_messages,
    serialize_message_data,
)

app = FastAPI(title="TaxiApp Chat Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:4300",
        "https://taxiapp247.com",
        "https://www.taxiapp247.com",
        "https://taxi-app-247.web.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_firebase()
manager = ConnectionManager()


@app.get("/")
def root():
    return {"message": "Chat backend funcionando"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/me")
def get_me(token: str):
    try:
        print("DEBUG /me -> token recibido")
        decoded = verify_firebase_token(token)
        print("DEBUG /me -> token decodificado:", decoded)

        uid = decoded["uid"]
        profile = get_user_profile(uid)
        print("DEBUG /me -> uid:", uid)
        print("DEBUG /me -> profile:", profile)

        if not profile:
            raise HTTPException(
                status_code=404,
                detail="Perfil no encontrado en UsersAdministration ni Users",
            )

        return {
            "uid": uid,
            "profile": serialize_message_data(profile),
        }
    except HTTPException:
        raise
    except Exception as e:
        print("DEBUG /me ERROR:", repr(e))
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/chats")
def chats(token: str):
    try:
        decoded = verify_firebase_token(token)
        uid = decoded["uid"]

        profile = get_user_profile(uid)
        if not profile:
            raise HTTPException(
                status_code=404,
                detail="Perfil no encontrado en UsersAdministration ni Users",
            )

        return {
            "items": get_user_chats(uid)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/chats/{chat_id}/messages")
def chat_messages(chat_id: str, token: str, limit: int = 50):
    try:
        decoded = verify_firebase_token(token)
        uid = decoded["uid"]

        profile = get_user_profile(uid)
        if not profile:
            raise HTTPException(
                status_code=404,
                detail="Perfil no encontrado en UsersAdministration ni Users",
            )

        user_chats = get_user_chats(uid)
        allowed_chat_ids = {item["chatId"] for item in user_chats}

        if chat_id not in allowed_chat_ids:
            return {"items": []}

        return {
            "items": get_chat_messages(chat_id, limit=limit)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, token: str = Query(...)):
    user_id = None

    try:
        decoded = verify_firebase_token(token)
        user_id = decoded["uid"]

        profile = get_user_profile(user_id)
        if not profile:
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "message": "Perfil no encontrado en UsersAdministration ni Users",
            })
            await websocket.close()
            return

        await manager.connect(user_id, websocket)

        await websocket.send_json({
            "type": "connected",
            "uid": user_id,
            "profile": serialize_message_data(profile),
        })

        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")

            if event_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if event_type == "message":
                receiver_id = str(data.get("receiverId", "")).strip()
                text = str(data.get("text", "")).strip()

                if not receiver_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "receiverId es requerido",
                    })
                    continue

                if receiver_id == user_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No puedes enviarte mensajes a ti mismo",
                    })
                    continue

                if not text:
                    await websocket.send_json({
                        "type": "error",
                        "message": "text es requerido",
                    })
                    continue

                receiver_profile = get_user_profile(receiver_id)
                if not receiver_profile:
                    await websocket.send_json({
                        "type": "error",
                        "message": "El usuario destino no existe",
                    })
                    continue

                saved_message = save_message(
                    sender_id=user_id,
                    receiver_id=receiver_id,
                    text=text,
                )

                payload = {
                    "type": "message",
                    "data": saved_message,
                }

                await manager.send_to_user(user_id, payload)
                await manager.send_to_user(receiver_id, payload)

    except WebSocketDisconnect:
        if user_id:
            manager.disconnect(user_id)
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        finally:
            if user_id:
                manager.disconnect(user_id)
            await websocket.close()

@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, token: str):
    try:
        decoded = verify_firebase_token(token)
        uid = decoded["uid"]

        profile = get_user_profile(uid)
        if not profile or profile.get("collection") != "UsersAdministration":
            raise HTTPException(status_code=403, detail="Solo administrador puede cerrar conversaciones")

        db = get_firestore_client()
        chat_ref = db.collection("chats").document(chat_id)
        chat_doc = chat_ref.get()

        if not chat_doc.exists:
            return {"ok": True, "message": "La conversación ya no existe"}

        data = chat_doc.to_dict() or {}
        participants = data.get("participants", [])

        if uid not in participants:
            raise HTTPException(status_code=403, detail="No tienes acceso a esta conversación")

        messages_ref = chat_ref.collection("messages")
        docs = list(messages_ref.stream())

        batch = db.batch()
        count = 0

        for doc_snap in docs:
            batch.delete(doc_snap.reference)
            count += 1

            if count % 400 == 0:
                batch.commit()
                batch = db.batch()

        batch.delete(chat_ref)
        batch.commit()

        return {
            "ok": True,
            "chatId": chat_id,
            "participants": participants,
            "message": "Conversación eliminada correctamente"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))