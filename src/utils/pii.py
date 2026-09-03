import hashlib

def hash_phone_number(phone: str) -> str:
    """Hash a phone number using SHA-256 for PII protection in logs."""
    if not phone:
        return ""
    # Strip any common formatting before hashing just in case, though whatsapp usually gives pure numbers
    clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")
    return hashlib.sha256(clean_phone.encode('utf-8')).hexdigest()
