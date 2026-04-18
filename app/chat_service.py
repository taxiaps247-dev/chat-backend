from datetime import datetime, timezone
from app.firebase_config import get_firestore_client

db = get_firestore_client()


def serialize_value(value):
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}

    if isinstance(value, list):
        return [serialize_value(item) for item in value]

    return value


def serialize_message_data(data: dict):
    return {k: serialize_value(v) for k, v in data.items()}


def build_chat_id(uid1: str, uid2: str) -> str:
    return "_".join(sorted([uid1, uid2]))


def get_user_profile(uid: str):
    admin_doc = db.collection("UsersAdministration").document(uid).get()
    if admin_doc.exists:
        data = admin_doc.to_dict()
        return {
            "uid": uid,
            "collection": "UsersAdministration",
            "name": data.get("name", data.get("correo", "Administrador")),
            "email": data.get("correo", ""),
            "phone": data.get("phone", ""),
            "avatar": data.get("avatar", ""),
            "role": data.get("role", "administrador"),
            "isOnline": data.get("estado", False),
            "isDriver": False,
            "fcmToken": data.get("fcmToken", ""),
            "activado": data.get("activado", False),
        }

    user_doc = db.collection("Users").document(uid).get()
    if user_doc.exists:
        data = user_doc.to_dict()
        return {
            "uid": uid,
            "collection": "Users",
            "name": data.get("name", ""),
            "email": data.get("email", ""),
            "phone": data.get("phone", ""),
            "avatar": data.get("avatar", ""),
            "role": data.get("role", ""),
            "isOnline": data.get("isOnline", False),
            "isDriver": data.get("isDriver", False),
            "fcmToken": data.get("fcmToken", ""),
            "activado": data.get("estado", False),
        }

    return None


def ensure_chat_exists(uid1: str, uid2: str):
    chat_id = build_chat_id(uid1, uid2)
    chat_ref = db.collection("chats").document(chat_id)
    chat_doc = chat_ref.get()

    sender_profile = get_user_profile(uid1)
    receiver_profile = get_user_profile(uid2)

    if not chat_doc.exists:
        chat_ref.set({
            "chatId": chat_id,
            "participants": sorted([uid1, uid2]),
            "participantRoles": sorted([
                sender_profile.get("role", "") if sender_profile else "",
                receiver_profile.get("role", "") if receiver_profile else "",
            ]),
            "participantProfiles": {
                uid1: sender_profile or {},
                uid2: receiver_profile or {},
            },
            "lastMessage": "",
            "lastMessageAt": datetime.now(timezone.utc),
            "lastSenderId": "",
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        })
    else:
        # Mantiene el chat fresco si cambian perfiles/roles
        chat_ref.set({
            "participants": sorted([uid1, uid2]),
            "participantRoles": sorted([
                sender_profile.get("role", "") if sender_profile else "",
                receiver_profile.get("role", "") if receiver_profile else "",
            ]),
            "participantProfiles": {
                uid1: sender_profile or {},
                uid2: receiver_profile or {},
            },
            "updatedAt": datetime.now(timezone.utc),
        }, merge=True)

    return chat_id


def save_message(sender_id: str, receiver_id: str, text: str):
    text = text.strip()
    if not text:
        raise ValueError("El mensaje no puede ir vacío")

    sender_profile = get_user_profile(sender_id)
    receiver_profile = get_user_profile(receiver_id)

    if not sender_profile:
        raise ValueError("El remitente no existe")
    if not receiver_profile:
        raise ValueError("El destinatario no existe")

    chat_id = ensure_chat_exists(sender_id, receiver_id)
    chat_ref = db.collection("chats").document(chat_id)
    messages_ref = chat_ref.collection("messages")

    now = datetime.now(timezone.utc)

    message_data = {
        "chatId": chat_id,
        "senderId": sender_id,
        "receiverId": receiver_id,
        "senderRole": sender_profile.get("role", ""),
        "receiverRole": receiver_profile.get("role", ""),
        "senderName": sender_profile.get("name", ""),
        "senderAvatar": sender_profile.get("avatar", ""),
        "receiverName": receiver_profile.get("name", ""),
        "receiverAvatar": receiver_profile.get("avatar", ""),
        "senderCollection": sender_profile.get("collection", ""),
        "receiverCollection": receiver_profile.get("collection", ""),
        "text": text,
        "type": "text",
        "read": False,
        "delivered": True,
        "createdAt": now,
    }

    message_ref = messages_ref.document()
    message_ref.set(message_data)

    chat_ref.set({
        "chatId": chat_id,
        "participants": sorted([sender_id, receiver_id]),
        "participantRoles": sorted([
            sender_profile.get("role", ""),
            receiver_profile.get("role", ""),
        ]),
        "participantProfiles": {
            sender_id: sender_profile,
            receiver_id: receiver_profile,
        },
        "lastMessage": text,
        "lastMessageAt": now,
        "lastSenderId": sender_id,
        "updatedAt": now,
    }, merge=True)

    response_data = {
        "messageId": message_ref.id,
        **message_data,
    }

    return serialize_message_data(response_data)


def get_chat_messages(chat_id: str, limit: int = 50):
    messages_ref = (
        db.collection("chats")
        .document(chat_id)
        .collection("messages")
        .order_by("createdAt")
        .limit(limit)
    )

    docs = messages_ref.stream()
    results = []

    for doc in docs:
        item = doc.to_dict()
        item["messageId"] = doc.id
        results.append(serialize_message_data(item))

    return results


def get_user_chats(uid: str):
    chats_ref = db.collection("chats").where("participants", "array_contains", uid).stream()

    results = []

    for doc in chats_ref:
        data = doc.to_dict()
        data["chatId"] = doc.id
        results.append(serialize_message_data(data))

    def sort_key(item):
        updated_at = item.get("updatedAt")
        if isinstance(updated_at, str):
          return updated_at
        return ""

    results.sort(key=sort_key, reverse=True)
    return results